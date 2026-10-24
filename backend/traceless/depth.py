"""Shot 1: monocular depth for the photo diorama (Depth Anything V2 Small, Apache-2.0).

Produces an 8-bit depth PNG aligned with the photo (near = bright). It is a
*visual* layer: no attacker or metric consumes it, and clue pins are placed at
the depth actually measured at each clue's box.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np
from PIL import Image

from .geo import WEIGHTS_DIR

MODEL_DIR = WEIGHTS_DIR / "depth-anything-v2-small"  # fetched by scripts/fetch_models.py depth
os.environ.setdefault("HF_HUB_OFFLINE", "1")  # never let the hub client touch the network at demo time

_PIPE = None
_LOCK = threading.RLock()  # depth_png holds it while calling _pipe()


def _pipe():
    global _PIPE
    with _LOCK:
        if _PIPE is None:
            import torch
            from transformers import pipeline

            dev = 0 if torch.cuda.is_available() and os.environ.get("TRACELESS_DEVICE", "auto") != "cpu" else -1
            if not (MODEL_DIR / "model.safetensors").exists():
                raise RuntimeError("depth model missing: run scripts/fetch_models.py depth")
            _PIPE = pipeline("depth-estimation", model=str(MODEL_DIR), device=dev)
        return _PIPE


def depth_png(img: Image.Image, out: Path, max_side: int = 640) -> np.ndarray:
    """Write depth PNG (near = 255) and return the normalized depth (0..1, near=1)."""
    im = img.convert("RGB")
    s = min(1.0, max_side / max(im.size))
    small = im.resize((max(16, round(im.width * s)), max(16, round(im.height * s))), Image.BILINEAR)
    with _LOCK:
        d = _pipe()(small)["predicted_depth"]
    d = d.squeeze().float().cpu().numpy()  # relative inverse depth: larger = nearer
    lo, hi = np.percentile(d, 2), np.percentile(d, 98)
    n = np.clip((d - lo) / max(1e-6, hi - lo), 0, 1)
    Image.fromarray((n * 255).astype(np.uint8)).resize(small.size, Image.BILINEAR).save(out)
    return n
