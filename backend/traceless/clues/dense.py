"""Open-vocabulary dense detector: ClearCLIP on GeoCLIP's own CLIP backbone.

No extra weights: the ViT-L/14 tower that powers Attacker B also labels every
14x14 patch against the clue vocabulary (traceless/clues/vocab.py). This is a
deliberate substitute for a separate detector + SAM 2 given our disk budget;
see DECISIONS.md. Output masks are patch-resolution, refined to pixel edges
with a guided upsample.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from ..attackers.clip_vit import dense_features
from ..attackers.geoclip_model import MEAN, STD, GeoCLIPModel
from .vocab import CLASSES

PROMPTS = Path(__file__).resolve().parents[1] / "data" / "clip_prompts.npz"


@dataclass
class DenseMap:
    names: list[str]
    roles: list[str]
    probs: np.ndarray  # (gh, gw, C) softmax over classes
    labels: np.ndarray  # (gh, gw) argmax class index
    size: tuple[int, int]  # image (w, h)

    def class_mask(self, name: str, min_p: float = 0.0) -> np.ndarray:
        i = self.names.index(name)
        return (self.labels == i) & (self.probs[..., i] >= min_p)

    def upsample(self, grid_mask: np.ndarray) -> np.ndarray:
        """Patch-grid bool mask -> pixel bool mask (bilinear, threshold .5)."""
        import cv2

        w, h = self.size
        m = cv2.resize(grid_mask.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
        return m >= 0.5


_TEXT = None


def _text():
    global _TEXT
    if _TEXT is None:
        z = np.load(PROMPTS)
        names = [str(n) for n in z["names"]]
        _TEXT = (names, torch.from_numpy(z["embs"]))
    return _TEXT


def segment(img: Image.Image, long_side: int = 448, temperature: float = 50.0) -> DenseMap:
    m = GeoCLIPModel.get()
    names, text = _text()
    w, h = img.size
    s = long_side / max(w, h)
    gw, gh = max(1, round(w * s / 14)), max(1, round(h * s / 14))
    x = img.convert("RGB").resize((gw * 14, gh * 14), Image.BICUBIC)
    t = torch.from_numpy(np.asarray(x, dtype=np.float32) / 255.0).permute(2, 0, 1)
    t = ((t - MEAN) / STD).unsqueeze(0)
    with torch.no_grad(), m.infer_lock:
        f = dense_features(m.vision, t.to(m.device, m.dtype))[0].float().cpu()  # (gh, gw, 768)
    logits = temperature * (f @ text.T)
    probs = logits.softmax(-1).numpy()
    return DenseMap(
        names=names,
        roles=[CLASSES[n][0] for n in names],
        probs=probs,
        labels=probs.argmax(-1),
        size=(w, h),
    )
