"""Faces (protected) and eyes (reflection clues) via OpenCV YuNet.

YuNet (opencv_zoo, MIT) returns a face box and 5 landmarks (eyes, nose,
mouth corners). Iris diameter in pixels is estimated from the inter-ocular
distance: human iris ~11.7 mm / interpupillary distance ~63 mm = 0.186.
Truth rule 2: we only claim an eye reflection is *readable* when the iris is
at least IRIS_READABLE_PX wide — a threshold measured by
bench/iris_threshold.py and recorded in DECISIONS.md.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from ..geo import WEIGHTS_DIR

YUNET = WEIGHTS_DIR / "face_detection_yunet_2023mar.onnx"
IRIS_RATIO = 0.186
_THRESH_FILE = Path(__file__).resolve().parents[1] / "data" / "iris_threshold.json"


def iris_readable_px() -> float:
    """Measured threshold (bench/iris_threshold.py). Conservative default if unmeasured."""
    try:
        return float(json.loads(_THRESH_FILE.read_text(encoding="utf-8"))["iris_readable_px"])
    except Exception:
        return 1e9  # unmeasured -> never claim "readable"


@dataclass
class Face:
    box: tuple[int, int, int, int]  # x0, y0, x1, y1 px
    eyes: list[tuple[float, float]]  # right, left eye centers
    score: float

    @property
    def iod(self) -> float:
        (ax, ay), (bx, by) = self.eyes
        return float(np.hypot(ax - bx, ay - by))

    @property
    def iris_px(self) -> float:
        return IRIS_RATIO * self.iod

    def eye_boxes(self) -> list[tuple[int, int, int, int]]:
        w, h = 0.42 * self.iod, 0.28 * self.iod
        return [
            (int(x - w / 2), int(y - h / 2), int(x + w / 2), int(y + h / 2)) for x, y in self.eyes
        ]


_DET = None
_LOCK = threading.Lock()


def detect_faces(img: Image.Image, min_score: float = 0.7) -> list[Face]:
    global _DET
    arr = cv2.cvtColor(np.asarray(img.convert("RGB")), cv2.COLOR_RGB2BGR)
    h, w = arr.shape[:2]
    # YuNet works best when faces are 10-300 px; run on a capped copy.
    s = min(1.0, 1280 / max(w, h))
    work = cv2.resize(arr, (round(w * s), round(h * s))) if s < 1 else arr
    with _LOCK:
        if _DET is None:
            _DET = cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), min_score, 0.3, 5000)
        _DET.setInputSize((work.shape[1], work.shape[0]))
        _, faces = _DET.detect(work)
    out = []
    for f in faces if faces is not None else []:
        x, y, fw, fh = (f[:4] / s).tolist()
        eyes = [(f[4] / s, f[5] / s), (f[6] / s, f[7] / s)]
        out.append(Face((int(x), int(y), int(x + fw), int(y + fh)), eyes, float(f[14])))
    return out
