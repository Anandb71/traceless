"""OCR (RapidOCR / PP-OCR, ONNX, offline) + text-clue grouping."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

import numpy as np
from PIL import Image

_ENGINE = None
_LOCK = threading.RLock()

PHONE_RE = re.compile(r"(\+?\(?\d[\d\-\s().]{6,}\d)")
PLATE_RE = re.compile(r"^[A-Z0-9][A-Z0-9\- ]{3,8}[A-Z0-9]$")


@dataclass
class TextLine:
    text: str
    score: float
    box: tuple[float, float, float, float]  # x0, y0, x1, y1 in px

    @property
    def h(self) -> float:
        return self.box[3] - self.box[1]


def engine():
    global _ENGINE
    with _LOCK:
        if _ENGINE is None:
            from rapidocr_onnxruntime import RapidOCR

            _ENGINE = RapidOCR()
        return _ENGINE


def read_text(img: Image.Image, max_side: int = 1600, min_score: float = 0.6) -> list[TextLine]:
    w, h = img.size
    s = min(1.0, max_side / max(w, h))
    work = img.resize((round(w * s), round(h * s))) if s < 1 else img
    arr = np.ascontiguousarray(np.asarray(work.convert("RGB"))[:, :, ::-1])  # BGR
    with _LOCK:
        result, _ = engine()(arr)
    lines = []
    for quad, text, score in result or []:
        text = (text or "").strip()
        score = float(score)
        if score < min_score or len(text) < 2:
            continue
        xs = [p[0] / s for p in quad]
        ys = [p[1] / s for p in quad]
        lines.append(TextLine(text, score, (min(xs), min(ys), max(xs), max(ys))))
    return lines


def group_lines(lines: list[TextLine]) -> list[list[TextLine]]:
    """Merge lines that belong to the same sign (touching / stacked)."""
    groups: list[list[TextLine]] = []
    boxes: list[list[float]] = []
    for ln in sorted(lines, key=lambda l: (l.box[1], l.box[0])):
        x0, y0, x1, y1 = ln.box
        pad = 0.4 * ln.h
        placed = False
        for g, b in zip(groups, boxes):
            gh = sum(l.h for l in g) / len(g)
            similar = 0.5 <= ln.h / max(1.0, gh) <= 2.0
            if (
                similar
                and len(g) < 4
                and x0 - pad < b[2] and x1 + pad > b[0] and y0 - pad < b[3] and y1 + pad > b[1]
            ):
                g.append(ln)
                b[0], b[1] = min(b[0], x0), min(b[1], y0)
                b[2], b[3] = max(b[2], x1), max(b[3], y1)
                placed = True
                break
        if not placed:
            groups.append([ln])
            boxes.append([x0, y0, x1, y1])
    return groups


def classify_text(text: str, box_w: float, box_h: float) -> str:
    digits = sum(c.isdigit() for c in text)
    if PHONE_RE.search(text) and digits >= 7:
        return "phone"
    t = text.strip().upper()
    if (
        PLATE_RE.match(t)
        and any(c.isdigit() for c in t)
        and any(c.isalpha() for c in t)
        and 1.8 <= box_w / max(1.0, box_h) <= 6.5
    ):
        return "plate"
    return "text"
