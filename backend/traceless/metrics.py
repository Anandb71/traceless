"""Image-quality metrics vs the original: LPIPS, SSIM, % pixels changed."""

from __future__ import annotations

import threading

import numpy as np
import torch

from .schemas import Quality

_LP = None
_LOCK = threading.Lock()
CHANGE_THRESH = 2  # a pixel "changed" if any channel moved by > 2/255 (JPEG-noise floor)


def _lpips():
    global _LP
    with _LOCK:
        if _LP is None:
            import lpips

            _LP = lpips.LPIPS(net="squeeze", verbose=False).eval()
        return _LP


def _t(a: np.ndarray) -> torch.Tensor:
    return torch.from_numpy(a).permute(2, 0, 1).float().unsqueeze(0) / 255.0


def quality(orig: np.ndarray, new: np.ndarray, edit_mask: np.ndarray, protected: np.ndarray | None = None, max_side: int = 768) -> Quality:
    diff = np.abs(orig.astype(np.int16) - new.astype(np.int16)).max(-1) > CHANGE_THRESH
    pct_changed = 100.0 * float(diff.mean())
    pct_masked = 100.0 * float(edit_mask.mean())
    face_px = int((diff & protected).sum()) if protected is not None else 0
    # metrics on a downscaled copy (LPIPS/SSIM are scale-sensitive; fixed 768 for comparability)
    import cv2

    h, w = orig.shape[:2]
    s = min(1.0, max_side / max(h, w))
    size = (max(32, round(w * s)), max(32, round(h * s)))
    o = cv2.resize(orig, size, interpolation=cv2.INTER_AREA)
    n = cv2.resize(new, size, interpolation=cv2.INTER_AREA)
    lp = ss = None
    try:
        with torch.no_grad():
            lp = float(_lpips()(_t(o) * 2 - 1, _t(n) * 2 - 1).item())
    except Exception:
        lp = None
    try:
        from pytorch_msssim import ssim

        with torch.no_grad():
            ss = float(ssim(_t(o), _t(n), data_range=1.0, size_average=True).item())
    except Exception:
        ss = None
    return Quality(
        lpips=None if lp is None else round(lp, 4),
        ssim=None if ss is None else round(ss, 4),
        pct_pixels_changed=round(pct_changed, 2),
        pct_pixels_masked=round(pct_masked, 2),
        face_pixels_changed=face_px,
    )
