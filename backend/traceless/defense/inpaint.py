"""Erasers: LaMa (local, offline) + blur + reflection softening.

LaMa ("Resolution-robust Large Mask Inpainting with Fourier Convolutions",
Suvorov et al. 2022), big-lama TorchScript export. We inpaint each region in
its own context crop (mask bbox + generous margin, capped at 512 px) so cost
scales with the clue, not the photo. If LaMa is unavailable or fails, OpenCV
Telea inpainting is the labeled fallback.
"""

from __future__ import annotations

import threading
import time

import cv2
import numpy as np
import torch

from ..geo import WEIGHTS_DIR

LAMA_PATH = WEIGHTS_DIR / "big-lama.pt"
_LAMA = None
_LOCK = threading.Lock()


def lama():
    global _LAMA
    with _LOCK:
        if _LAMA is None and LAMA_PATH.exists():
            from ..attackers.geoclip_model import pick_device

            dev = pick_device()
            # Skip TorchScript's profiling passes: every crop has a new shape, and
            # re-profiling cost ~2 s per new shape vs 0.17 s steady state on GPU.
            torch._C._jit_set_profiling_executor(False)
            m = torch.jit.load(str(LAMA_PATH), map_location=dev)
            m.eval()
            _LAMA = (m, dev)
        return _LAMA


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def feather(mask: np.ndarray, px: int) -> np.ndarray:
    """Soft alpha in [0,1] that is 1 inside the mask and fades over ~px."""
    if px <= 0:
        return mask.astype(np.float32)
    k = px * 2 + 1
    a = cv2.GaussianBlur(mask.astype(np.float32), (k, k), px / 2)
    return np.maximum(a, mask.astype(np.float32))


def dilate(mask: np.ndarray, px: int) -> np.ndarray:
    if px <= 0:
        return mask
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * px + 1, 2 * px + 1))
    return cv2.dilate(mask.astype(np.uint8), k).astype(bool)


def inpaint(img: np.ndarray, mask: np.ndarray, max_side: int = 512, use_lama: bool = True) -> tuple[np.ndarray, str]:
    """img uint8 HxWx3 RGB, mask bool HxW. Returns (new image, engine used)."""
    out = img.copy()
    if not mask.any():
        return out, "none"
    H, W = mask.shape
    # Process connected groups separately so crops stay small.
    n, lab = cv2.connectedComponents(dilate(mask, 12).astype(np.uint8))
    engine = "lama"
    for i in range(1, n):
        region = mask & (lab == i)
        bb = _bbox(region)
        if bb is None:
            continue
        x0, y0, x1, y1 = bb
        bw, bh = x1 - x0, y1 - y0
        m = int(max(bw, bh) * 0.6) + 24  # context margin
        cx0, cy0 = max(0, x0 - m), max(0, y0 - m)
        cx1, cy1 = min(W, x1 + m), min(H, y1 + m)
        crop = out[cy0:cy1, cx0:cx1]
        cmask = region[cy0:cy1, cx0:cx1]
        res, eng = _inpaint_crop(crop, cmask, max_side, use_lama)
        engine = eng if eng != "lama" else engine
        alpha = feather(cmask, 3)[..., None]
        out[cy0:cy1, cx0:cx1] = (alpha * res + (1 - alpha) * crop).astype(np.uint8)
    return out, engine


def _inpaint_crop(crop: np.ndarray, cmask: np.ndarray, max_side: int, use_lama: bool) -> tuple[np.ndarray, str]:
    h, w = cmask.shape
    loaded = lama() if use_lama else None
    if loaded is not None:
        model, dev = loaded
        try:
            s = min(1.0, max_side / max(h, w))
            nh, nw = max(8, int(round(h * s / 8)) * 8), max(8, int(round(w * s / 8)) * 8)
            ci = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA)
            cm = cv2.resize(cmask.astype(np.uint8), (nw, nh), interpolation=cv2.INTER_NEAREST)
            cm = dilate(cm.astype(bool), 2)
            ti = torch.from_numpy(ci).permute(2, 0, 1).float().unsqueeze(0) / 255.0
            tm = torch.from_numpy(cm.astype(np.float32))[None, None]
            with torch.no_grad(), _LOCK:
                r = model(ti.to(dev), tm.to(dev))[0].permute(1, 2, 0).clamp(0, 1).float().cpu().numpy()
            r = (r * 255).astype(np.uint8)
            return cv2.resize(r, (w, h), interpolation=cv2.INTER_CUBIC), "lama"
        except Exception:
            pass
    bgr = cv2.cvtColor(crop, cv2.COLOR_RGB2BGR)
    r = cv2.inpaint(bgr, dilate(cmask, 2).astype(np.uint8) * 255, 7, cv2.INPAINT_TELEA)
    return cv2.cvtColor(r, cv2.COLOR_BGR2RGB), "telea"


def blur(img: np.ndarray, mask: np.ndarray, strength: float = 1.0) -> np.ndarray:
    """Pixelate-free heavy blur for small text and plates (unreadable, still 'a sign')."""
    out = img.copy()
    bb = _bbox(mask)
    if bb is None:
        return out
    x0, y0, x1, y1 = bb
    k = max(9, int(max(x1 - x0, y1 - y0) * 0.35 * strength)) | 1
    pad = k
    H, W = mask.shape
    cx0, cy0, cx1, cy1 = max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)
    crop = out[cy0:cy1, cx0:cx1]
    b = cv2.GaussianBlur(crop, (k, k), 0)
    b = cv2.GaussianBlur(b, (k, k), 0)
    alpha = feather(mask[cy0:cy1, cx0:cx1], 4)[..., None]
    out[cy0:cy1, cx0:cx1] = (alpha * b + (1 - alpha) * crop).astype(np.uint8)
    return out


def soften(img: np.ndarray, mask: np.ndarray, strength: float = 1.0) -> np.ndarray:
    """Soften reflections: kill specular detail, keep colour and shape.

    Blur within the region, then compress local contrast toward the blurred
    mean. Eyes stay eyes; what they mirror becomes unreadable."""
    out = img.copy()
    bb = _bbox(mask)
    if bb is None:
        return out
    x0, y0, x1, y1 = bb
    size = max(x1 - x0, y1 - y0)
    k = max(3, int(size * 0.18 * strength)) | 1
    H, W = mask.shape
    pad = k
    cx0, cy0, cx1, cy1 = max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)
    crop = out[cy0:cy1, cx0:cx1].astype(np.float32)
    b = cv2.GaussianBlur(crop, (k, k), 0)
    mean = cv2.GaussianBlur(crop, (k * 2 + 1, k * 2 + 1), 0)
    soft = 0.55 * b + 0.45 * mean
    alpha = feather(mask[cy0:cy1, cx0:cx1], max(2, k // 3))[..., None]
    out[cy0:cy1, cx0:cx1] = np.clip(alpha * soft + (1 - alpha) * crop, 0, 255).astype(np.uint8)
    return out


def fast_erase(img: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Cheap eraser used only for bulk ablation probes when LaMa is too slow."""
    return inpaint(img, mask, max_side=256, use_lama=True)[0]


if __name__ == "__main__":  # quick timing
    from PIL import Image

    im = np.asarray(Image.open("../fixtures/photos/madrid-jamon-shopfront.jpg").convert("RGB"))
    mk = np.zeros(im.shape[:2], bool)
    mk[200:350, 60:420] = True
    for side in (256, 512):
        t = time.time()
        r, e = inpaint(im, mk, max_side=side)
        print(side, e, round(time.time() - t, 2))
    Image.fromarray(r).save("../.scratch/inpaint_test.jpg")


def glyph_mask(img: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    """Pixels of the lettering inside a text box (not the sign board).

    Otsu split inside the box; the glyph class is the one that touches the
    box border least (the board surrounds the letters). Dilated so anti-
    aliased edges and outlines go too. Returns a full-size bool mask."""
    H, W = img.shape[:2]
    x0, y0, x1, y1 = max(0, box[0]), max(0, box[1]), min(W, box[2]), min(H, box[3])
    out = np.zeros((H, W), bool)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return out
    g = cv2.cvtColor(img[y0:y1, x0:x1], cv2.COLOR_RGB2GRAY)
    _, th = cv2.threshold(g, 0, 1, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    border = np.concatenate([th[0], th[-1], th[:, 0], th[:, -1]])
    glyph = th == (0 if border.mean() > 0.5 else 1)
    frac = glyph.mean()
    if frac < 0.03 or frac > 0.65:  # not a clean split -> take the whole box
        glyph = np.ones_like(glyph, bool)
    px = max(2, int(0.12 * (y1 - y0)))
    out[y0:y1, x0:x1] = glyph
    return dilate(out, px)


def portrait_blur(img: np.ndarray, keep: np.ndarray, strength: float = 1.0) -> np.ndarray:
    """Phone-style 'portrait mode': the person stays pixel-identical, the
    background goes soft. Last-resort escalation when a person is present:
    it removes background architecture/vegetation detail without inventing
    anything, and looks like a normal phone photo."""
    H, W = keep.shape
    sigma = max(3.0, 0.012 * max(H, W) * strength)
    k = int(sigma * 3) | 1
    b = cv2.GaussianBlur(img, (k, k), sigma)
    alpha = feather(dilate(keep, 2), max(3, int(sigma)))[..., None]
    out = (alpha * img + (1 - alpha) * b).astype(np.uint8)
    out[keep] = img[keep]
    return out
