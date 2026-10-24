"""GeoCLIP (Vivanco et al., NeurIPS 2023), loaded lean for CPU inference.

- Image backbone: CLIP ViT-L/14 vision tower only (fp16 on disk, fp32 in RAM).
- GeoCLIP image MLP, location encoder and the 100k-coordinate GPS gallery come
  from the `geoclip` pip package (MIT).
- Gallery location features are computed once at startup; a prediction is a
  softmax over the 100k gallery points (exactly GeoCLIP's own `predict`).
- Gallery points are pre-binned into H3 analysis cells, so a full
  distribution + credible area is one np.bincount.
"""

from __future__ import annotations

import math
import os
import threading
import time

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from ..geo import ANALYSIS_RES, WEIGHTS_DIR

CLIP_WEIGHTS = WEIGHTS_DIR / "clip-vit-l14-vision-fp16.safetensors"
def pick_device() -> torch.device:
    want = os.environ.get("TRACELESS_DEVICE", "auto")
    if want == "cpu" or (want == "auto" and not torch.cuda.is_available()):
        return torch.device("cpu")
    return torch.device("cuda")


MEAN = torch.tensor([0.48145466, 0.4578275, 0.40821073]).view(3, 1, 1)
STD = torch.tensor([0.26862954, 0.26130258, 0.27577711]).view(3, 1, 1)


class GeoCLIPModel:
    """Thread-safe singleton-ish wrapper. Use `GeoCLIPModel.get()`."""

    _inst: "GeoCLIPModel | None" = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "GeoCLIPModel":
        with cls._lock:
            if cls._inst is None:
                cls._inst = cls()
            return cls._inst

    def __init__(self, quantize: bool | None = None) -> None:
        from safetensors.torch import load_file

        from .clip_vit import CLIPVision
        from .geoclip_loc import LocationEncoder, geoclip_dir

        t0 = time.time()
        torch.set_num_threads(max(1, (os.cpu_count() or 4) - 2))
        self.infer_lock = threading.Lock()

        sd = {k: v.float() for k, v in load_file(str(CLIP_WEIGHTS)).items()}
        with torch.device("meta"):
            vision = CLIPVision()
        missing, unexpected = vision.load_state_dict(sd, strict=False, assign=True)
        if missing or unexpected:
            raise RuntimeError(f"CLIP weight mismatch: missing={missing} unexpected={unexpected}")
        self.device = pick_device()
        # GPU: fp16 vision tower (cosine vs fp32 checked in tests); CPU: fp32.
        self.dtype = torch.float16 if self.device.type == "cuda" else torch.float32
        self.vision = vision.eval().to(self.device, self.dtype)
        if quantize is None:
            quantize = os.environ.get("TRACELESS_QUANTIZE", "0") == "1"
        if quantize and self.device.type == "cpu":  # int8 dynamic: ~2x faster on CPU; measured drift in DECISIONS.md
            self.vision = torch.ao.quantization.quantize_dynamic(
                self.vision, {torch.nn.Linear}, dtype=torch.qint8
            )
        self.quantized = quantize

        gdir = geoclip_dir()
        self.mlp = torch.nn.Sequential(
            torch.nn.Linear(768, 768), torch.nn.ReLU(), torch.nn.Linear(768, 512)
        )
        self.mlp.load_state_dict(
            torch.load(gdir / "weights" / "image_encoder_mlp_weights.pth", map_location="cpu",
                       weights_only=True)
        )
        self.mlp.eval().to(self.device)
        loc = LocationEncoder()
        loc.load_state_dict(
            torch.load(gdir / "weights" / "location_encoder_weights.pth", map_location="cpu",
                       weights_only=True)
        )
        loc.eval()
        self.logit_scale = float(
            torch.load(gdir / "weights" / "logit_scale_weights.pth", map_location="cpu",
                       weights_only=True).exp()
        )
        gal = np.loadtxt(gdir / "gps_gallery" / "coordinates_100K.csv", delimiter=",",
                         skiprows=1, dtype=np.float32)
        self.gallery = gal  # (N, 2) lat, lon
        with torch.no_grad():
            g = torch.from_numpy(gal)
            self.loc_feats = torch.cat(
                [F.normalize(loc(g[i : i + 10_000]), dim=1) for i in range(0, len(g), 10_000)]
            ).to(self.device)  # (N, 512)

        # Pre-bin the gallery into H3 analysis cells.
        import h3

        cells = [h3.latlng_to_cell(float(a), float(b), ANALYSIS_RES) for a, b in gal]
        uniq, idx = np.unique(np.array(cells), return_inverse=True)
        self.cell_ids = uniq
        self.cell_idx = idx
        self.cell_area = np.array([h3.cell_area(c, unit="km^2") for c in uniq])
        self.load_s = time.time() - t0

    # ------------------------------------------------------------------ #

    @staticmethod
    def to_tensor(img: Image.Image) -> torch.Tensor:
        """CLIP preprocessing for an already-square-ish crop -> (3,224,224)."""
        img = img.convert("RGB")
        w, h = img.size
        s = 224 / min(w, h)
        img = img.resize((max(224, round(w * s)), max(224, round(h * s))), Image.BICUBIC)
        w, h = img.size
        left, top = (w - 224) // 2, (h - 224) // 2
        img = img.crop((left, top, left + 224, top + 224))
        arr = torch.from_numpy(np.asarray(img, dtype=np.float32) / 255.0).permute(2, 0, 1)
        return (arr - MEAN) / STD

    @torch.no_grad()
    def embed(self, crops: list[Image.Image], batch: int = 16) -> torch.Tensor:
        out = []
        with self.infer_lock:
            for i in range(0, len(crops), batch):
                x = torch.stack([self.to_tensor(c) for c in crops[i : i + batch]])
                v = self.vision(x.to(self.device, self.dtype)).float()
                out.append(F.normalize(self.mlp(v), dim=1))
        return torch.cat(out)

    @torch.no_grad()
    def probs_from_feats(self, feats: torch.Tensor) -> np.ndarray:
        logits = self.logit_scale * feats.to(self.device) @ self.loc_feats.T
        return logits.softmax(dim=-1).cpu().numpy().astype(np.float64)

    def cell_masses(self, probs: np.ndarray) -> np.ndarray:
        return np.bincount(self.cell_idx, weights=probs, minlength=len(self.cell_ids))

    def credible_area(self, probs: np.ndarray, level: float = 0.9) -> float:
        m = self.cell_masses(probs)
        order = np.argsort(-m)
        cum = np.cumsum(m[order])
        k = int(np.searchsorted(cum, level - 1e-9)) + 1
        return float(self.cell_area[order[:k]].sum())


def views(img: Image.Image, mode: str = "tri") -> list[Image.Image]:
    """Square crops the attacker looks at.

    center: GeoCLIP's own preprocessing (shortest side, center crop).
    tri:    center + both ends of the long axis -> the whole frame is seen.
    zoom:   tri + a 3x3 grid of half-size close-ups (hunts for small details).
    """
    w, h = img.size
    s = min(w, h)
    out = []
    if mode in ("center", "tri", "zoom"):
        out.append(img.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)))
    if mode in ("tri", "zoom") and abs(w - h) > 0.08 * s:
        if w > h:
            out += [img.crop((0, 0, s, s)), img.crop((w - s, 0, w, s))]
        else:
            out += [img.crop((0, 0, s, s)), img.crop((0, h - s, s, h))]
    if mode == "zoom":
        t = max(112, s // 2)
        for gy in range(3):
            for gx in range(3):
                x0 = round(gx * (w - t) / 2)
                y0 = round(gy * (h - t) / 2)
                out.append(img.crop((x0, y0, x0 + t, y0 + t)))
    return out


def tile_boxes(w: int, h: int, mode: str) -> list[tuple[int, int, int, int]]:
    """Pixel boxes matching `views` order (used to drop edited tiles)."""
    s = min(w, h)
    boxes = [((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)]
    if mode in ("tri", "zoom") and abs(w - h) > 0.08 * s:
        boxes += [(0, 0, s, s), (w - s, 0, w, s)] if w > h else [(0, 0, s, s), (0, h - s, s, h)]
    if mode == "zoom":
        t = max(112, s // 2)
        for gy in range(3):
            for gx in range(3):
                x0 = round(gx * (w - t) / 2)
                y0 = round(gy * (h - t) / 2)
                boxes.append((x0, y0, x0 + t, y0 + t))
    return boxes


def log_area(a: float | None) -> float:
    return math.log10(max(1.0, a or 1.0))
