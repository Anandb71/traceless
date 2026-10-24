"""Attacker C (offline): street-level pinpoint by visual place recognition.

1. Retrieval: EigenPlaces (Berton et al., ICCV 2023; ResNet-50 + GeM, 2048-d)
   global descriptors; exact cosine top-k over the reference set (numpy).
2. Re-ranking: SuperPoint keypoints + LightGlue matching (Lindenberger et al.,
   ICCV 2023), verified by a RANSAC fundamental matrix (OpenCV USAC-MAGSAC).
3. The best-verified reference photo's GPS is the pinpoint — but only if its
   inlier count clears the measured threshold (bench/street_threshold.py).

Truth rule (UPGRADE.md): street-level claims only inside the downloaded
coverage. The reference set *is* the coverage; outside it this attacker can
only say "no street match", never guess.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from torch import nn

from ..geo import WEIGHTS_DIR, Distribution
from ..schemas import AttackResult, Hypothesis, LatLon, RationaleStep, StreetCoverage, StreetMatch
from .base import AttackContext, Attacker, finalize

STREET_DIR = WEIGHTS_DIR / "street"
EIGEN_URL = "https://github.com/gmberton/EigenPlaces/releases/download/v1.0/ResNet50_2048_eigenplaces.pth"
THRESH_FILE = Path(__file__).resolve().parents[1] / "data" / "street_threshold.json"
DEFAULT_THRESHOLD = 60  # used only until bench/street_threshold.py has measured one
TOP_K = 12
MAX_PAIRS = 300
IMNET_MEAN = torch.tensor([0.485, 0.456, 0.406]).view(3, 1, 1)
IMNET_STD = torch.tensor([0.229, 0.224, 0.225]).view(3, 1, 1)


# --------------------------------------------------------------------------- #
# EigenPlaces, vendored (MIT, gmberton/EigenPlaces): ResNet-50 trunk + GeM + FC
# --------------------------------------------------------------------------- #


class _GeM(nn.Module):
    def __init__(self, p: float = 3.0, eps: float = 1e-6):
        super().__init__()
        self.p = nn.Parameter(torch.ones(1) * p)
        self.eps = eps

    def forward(self, x):
        return F.avg_pool2d(x.clamp(min=self.eps).pow(self.p), (x.size(-2), x.size(-1))).pow(1.0 / self.p)


class _L2(nn.Module):
    def forward(self, x):
        return F.normalize(x, p=2.0, dim=1)


class _Flatten(nn.Module):
    def forward(self, x):
        return x[:, :, 0, 0]


class EigenPlaces(nn.Module):
    def __init__(self, dim: int = 2048):
        super().__init__()
        import torchvision

        r = torchvision.models.resnet50()
        self.backbone = nn.Sequential(*list(r.children())[:-2])
        self.aggregation = nn.Sequential(_L2(), _GeM(), _Flatten(), nn.Linear(2048, dim), _L2())

    def forward(self, x):
        return self.aggregation(self.backbone(x))


# --------------------------------------------------------------------------- #
# Models + index
# --------------------------------------------------------------------------- #


class StreetModels:
    _inst: "StreetModels | None" = None
    _lock = threading.Lock()

    @classmethod
    def get(cls) -> "StreetModels":
        with cls._lock:
            if cls._inst is None:
                cls._inst = cls()
            return cls._inst

    def __init__(self) -> None:
        from lightglue import LightGlue, SuperPoint

        from .geoclip_model import pick_device

        self.device = pick_device()
        self.lock = threading.Lock()
        sd = torch.hub.load_state_dict_from_url(EIGEN_URL, map_location="cpu")
        net = EigenPlaces()
        net.load_state_dict(sd)
        self.eigen = net.eval().to(self.device)
        self.sp = SuperPoint(max_num_keypoints=1024).eval().to(self.device)
        self.lg = LightGlue(features="superpoint").eval().to(self.device)

    @torch.no_grad()
    def describe(self, imgs: list[Image.Image], side: int = 512) -> np.ndarray:
        out = []
        with self.lock:
            for im in imgs:
                im = im.convert("RGB")
                s = side / max(im.size)
                im = im.resize((max(32, round(im.width * s)), max(32, round(im.height * s))), Image.BILINEAR)
                t = torch.from_numpy(np.asarray(im, dtype=np.float32) / 255.0).permute(2, 0, 1)
                t = ((t - IMNET_MEAN) / IMNET_STD).unsqueeze(0).to(self.device)
                out.append(self.eigen(t)[0].float().cpu().numpy())
        return np.stack(out).astype(np.float32)

    @torch.no_grad()
    def keypoints(self, im: Image.Image, side: int = 1024) -> dict:
        im = im.convert("RGB")
        s = min(1.0, side / max(im.size))
        w, h = max(16, round(im.width * s)), max(16, round(im.height * s))
        t = torch.from_numpy(np.asarray(im.resize((w, h), Image.BILINEAR), dtype=np.float32) / 255.0)
        t = t.permute(2, 0, 1)[None].to(self.device)
        with self.lock:
            f = self.sp.extract(t)
        f["size_wh"] = (w, h)
        return f

    @torch.no_grad()
    def match(self, fq: dict, fr: dict) -> tuple[np.ndarray, int]:
        """Return (pairs [[qx,qy,rx,ry] normalized], RANSAC inlier count)."""
        with self.lock:
            m = self.lg({"image0": {k: v for k, v in fq.items() if k != "size_wh"},
                         "image1": {k: v for k, v in fr.items() if k != "size_wh"}})
        idx = m["matches"][0].cpu().numpy()
        if len(idx) < 8:
            return np.zeros((0, 4), np.float32), 0
        kq = fq["keypoints"][0].cpu().numpy()[idx[:, 0]]
        kr = fr["keypoints"][0].cpu().numpy()[idx[:, 1]]
        _, mask = cv2.findFundamentalMat(kq, kr, cv2.USAC_MAGSAC, 1.5, 0.999, 10000)
        if mask is None:
            return np.zeros((0, 4), np.float32), 0
        inl = mask.ravel().astype(bool)
        (wq, hq), (wr, hr) = fq["size_wh"], fr["size_wh"]
        pairs = np.concatenate([kq[inl] / [wq, hq], kr[inl] / [wr, hr]], axis=1).astype(np.float32)
        return pairs, int(inl.sum())


@dataclass
class StreetIndex:
    name: str
    root: Path
    desc: np.ndarray  # (N, 2048) float32, L2-normalized
    ids: list[str]
    lat: np.ndarray
    lon: np.ndarray
    compass: list[float | None]
    files: list[str]
    attribution: list[str]
    source: str
    center: tuple[float, float]
    radius_km: float

    @classmethod
    def load(cls, name: str | None = None) -> "StreetIndex | None":
        if not STREET_DIR.exists():
            return None
        names = [name] if name else sorted(p.name for p in STREET_DIR.iterdir() if (p / "index.npz").exists())
        if not names or not (STREET_DIR / names[0] / "index.npz").exists():
            return None
        root = STREET_DIR / names[0]
        z = np.load(root / "index.npz", allow_pickle=False)
        meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))
        return cls(
            name=names[0], root=root, desc=z["desc"].astype(np.float32),
            ids=[m["id"] for m in meta["images"]], lat=np.array([m["lat"] for m in meta["images"]]),
            lon=np.array([m["lon"] for m in meta["images"]]),
            compass=[m.get("compass") for m in meta["images"]], files=[m["file"] for m in meta["images"]],
            attribution=[m.get("attribution", "") for m in meta["images"]], source=meta["source"],
            center=(meta["center"]["lat"], meta["center"]["lon"]), radius_km=meta["radius_km"],
        )


_INDEX: StreetIndex | None = None
_INDEX_LOADED = False


def street_index() -> StreetIndex | None:
    global _INDEX, _INDEX_LOADED
    if not _INDEX_LOADED:
        _INDEX = StreetIndex.load()
        _INDEX_LOADED = True
    return _INDEX


def match_threshold() -> int:
    try:
        return int(json.loads(THRESH_FILE.read_text(encoding="utf-8"))["inlier_threshold"])
    except Exception:
        return DEFAULT_THRESHOLD


def coverage() -> StreetCoverage:
    ix = street_index()
    if ix is None:
        return StreetCoverage(available=False, note="no street reference set downloaded")
    return StreetCoverage(
        available=True, source=ix.source, n_images=len(ix.ids), radius_km=ix.radius_km,
        center=LatLon(lat=ix.center[0], lon=ix.center[1]), match_threshold=match_threshold(),
        note=f"{len(ix.ids)} geotagged street photos within {ix.radius_km:g} km",
    )


# --------------------------------------------------------------------------- #
# The attacker
# --------------------------------------------------------------------------- #


class StreetAttacker(Attacker):
    id = "street"
    name = "Street matcher (offline)"
    family = "street"
    offline = True

    def available(self) -> bool:
        return street_index() is not None

    def attack(self, img: Image.Image, ctx: AttackContext) -> AttackResult:
        t0 = time.time()
        ix = street_index()
        if ix is None:
            return self.failed(ctx, "no street coverage downloaded", status="skipped", t0=t0)
        try:
            matches = self.candidates(img, ix)
        except Exception as e:
            return self.failed(ctx, f"{type(e).__name__}: {e}", t0=t0)
        thr = match_threshold()
        res = self._result(image_variant=ctx.variant, street_matches=matches[:3],
                           latency_ms=int((time.time() - t0) * 1000))
        best = matches[0] if matches else None
        if best is None or best.inliers < thr:
            got = best.inliers if best else 0
            res.error = f"no street-level match (best {got} inliers < {thr} needed)"
            res.rationale_steps = [RationaleStep(text=f"Compared against {len(ix.ids)} street photos; best had {got} verified keypoint matches — below the {thr} needed to claim a match.")]
            for m in res.street_matches:
                m.keypoint_pairs = []  # no lines for non-matches
            return res
        res.hypotheses = [Hypothesis(lat=best.lat, lon=best.lon, probability=1.0, radius_km=0.05,
                                     reasoning=f"{best.inliers} verified keypoint matches with a street photo")]
        res.rationale_steps = [
            RationaleStep(text=f"Searched {len(ix.ids)} street photos within {ix.radius_km:g} km by appearance."),
            RationaleStep(text=f"Best candidate shares {best.inliers} geometrically verified keypoints (threshold {thr})."),
            RationaleStep(text="Its GPS tag is the pinpoint."),
        ]
        dist = Distribution.from_hypotheses(res.hypotheses, samples=4000)
        return finalize(res, dist, ctx)

    def candidates(self, img: Image.Image, ix: StreetIndex) -> list[StreetMatch]:
        sm = StreetModels.get()
        q = sm.describe([img])[0]
        sims = ix.desc @ q
        top = np.argsort(-sims)[:TOP_K]
        fq = sm.keypoints(img)
        out = []
        for i in top:
            ref = Image.open(ix.root / "img" / ix.files[i])
            pairs, n = sm.match(fq, sm.keypoints(ref))
            if len(pairs) > MAX_PAIRS:
                sel = np.linspace(0, len(pairs) - 1, MAX_PAIRS).astype(int)
                pairs = pairs[sel]
            out.append(StreetMatch(
                image_id=ix.ids[i], lat=float(ix.lat[i]), lon=float(ix.lon[i]), compass=ix.compass[i],
                retrieval_score=round(float(sims[i]), 4), inliers=n,
                url=f"/street/{ix.name}/img/{ix.files[i]}", source=ix.source,  # type: ignore[arg-type]
                attribution=ix.attribution[i], keypoint_pairs=np.round(pairs, 4).tolist(),
            ))
        out.sort(key=lambda m: (-m.inliers, -m.retrieval_score))
        return out
