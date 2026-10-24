"""Clue finding: OCR + dense open-vocabulary map + faces/eyes + Attacker A boxes.

Produces ClueCandidates (schema Clue + pixel mask + the fix it would get).
Nothing here claims a clue *matters* — that is measured by ablation
(traceless.ablation). This module only proposes where to look.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

from ..defense.inpaint import dilate, glyph_mask
from ..schemas import Box, Clue
from .dense import DenseMap
from .faces import Face, iris_readable_px
from .ocr import TextLine, classify_text, group_lines
from .vocab import CLASSES, DESCRIPTIONS, LABELS

MAX_CLUES = 9
BIG_FRAC = 0.10  # regions bigger than this are measured but never erased whole
BIG_FRAC_LANDMARK = 0.30  # a landmark may be bigger and still worth erasing

# Prior order for capping candidates before ablation (most likely to matter first).
TYPE_PRIOR = {
    "text": 0, "phone": 0, "plate": 1, "landmark": 1, "flag": 1, "reflection": 2,
    "road_marking": 3, "vehicle": 4, "vegetation": 4, "building": 5, "terrain": 5, "other": 6,
}
PER_CLASS = {"sign": 3, "building": 1, "field": 1, "tree": 2, "water": 1, "sand": 1, "mountain": 1}
MIN_PATCHES = {"sign": 2, "plate": 1, "flag": 2, "landmark": 3, "sunglasses": 1, "window": 3, "vehicle": 3}


@dataclass
class ClueCandidate:
    clue: Clue
    mask: np.ndarray  # bool HxW: pixels the eraser would touch
    fix: str  # inpaint | blur | soften | none
    region_mask: np.ndarray | None = None  # full region (for boxes / ablation of big areas)
    lines: list[TextLine] = field(default_factory=list)


@dataclass
class ClueSet:
    candidates: list[ClueCandidate]
    person_mask: np.ndarray  # protected pixels (people, faces), eyes excluded
    faces: list[Face]

    def by_id(self, cid: str) -> ClueCandidate:
        return next(c for c in self.candidates if c.clue.id == cid)


def _box_from_mask(m: np.ndarray) -> Box:
    H, W = m.shape
    ys, xs = np.where(m)
    return Box.from_px(xs.min(), ys.min(), xs.max() + 1, ys.max() + 1, W, H)


def _truncate(s: str, n: int = 26) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def find_clues(
    img: Image.Image,
    dense: DenseMap,
    lines: list[TextLine],
    faces: list[Face],
    extra: list[Clue] | None = None,
) -> ClueSet:
    arr = np.asarray(img.convert("RGB"))
    H, W = arr.shape[:2]

    # ---- protected: people + faces (eyes handled separately) -------------
    pm = dense.upsample(dense.class_mask("person", 0.3))
    pm = dilate(pm, max(2, int(0.006 * max(H, W))))
    for f in faces:
        x0, y0, x1, y1 = f.box
        mx, my = int(0.15 * (x1 - x0)), int(0.25 * (y1 - y0))
        pm[max(0, y0 - my) : min(H, y1 + my // 2), max(0, x0 - mx) : min(W, x1 + mx)] = True
    eye_mask = np.zeros((H, W), bool)
    for f in faces:
        for ex0, ey0, ex1, ey1 in f.eye_boxes():
            eye_mask[max(0, ey0) : min(H, ey1), max(0, ex0) : min(W, ex1)] = True
    person_mask = pm & ~eye_mask

    cands: list[ClueCandidate] = []

    # ---- text (OCR) -------------------------------------------------------
    for g in group_lines(lines):
        x0, y0 = min(l.box[0] for l in g), min(l.box[1] for l in g)
        x1, y1 = max(l.box[2] for l in g), max(l.box[3] for l in g)
        text = " ".join(l.text for l in g)
        kind = classify_text(text, x1 - x0, y1 - y0)
        gm = np.zeros((H, W), bool)
        for l in g:
            pad = 0.15 * l.h
            gm |= glyph_mask(arr, (int(l.box[0] - pad), int(l.box[1] - pad), int(l.box[2] + pad), int(l.box[3] + pad)))
        region = np.zeros((H, W), bool)
        region[int(y0):int(y1), int(x0):int(x1)] = True
        line_h = np.median([l.h for l in g])
        fix = "blur" if (kind == "plate" or line_h < 0.012 * max(H, W)) else "inpaint"
        label = {"phone": "Phone number", "plate": "Plate", "text": "Sign"}[kind]
        cands.append(
            ClueCandidate(
                clue=Clue(
                    id="", index=0, type=kind, label=f"{label} “{_truncate(text)}”",
                    description=DESCRIPTIONS[kind], box=_box_from_mask(region),
                    sources=["ocr"], confidence=float(np.mean([l.score for l in g])), text=text,
                ),
                mask=(gm if fix == "inpaint" else dilate(region, 3)) & ~person_mask,
                fix=fix, region_mask=region, lines=g,
            )
        )

    # ---- dense open-vocabulary regions -------------------------------------
    for name, (role, _) in CLASSES.items():
        if role in ("person", "background"):
            continue
        grid = dense.class_mask(name, 0.25).astype(np.uint8)
        if grid.sum() == 0:
            continue
        # bridge 1-patch gaps so one object = one clue, then keep the biggest
        bridged = cv2.dilate(grid, np.ones((3, 3), np.uint8))
        n, lab = cv2.connectedComponents(bridged, connectivity=8)
        comps = []
        for i in range(1, n):
            cm = (lab == i) & (grid > 0)
            if cm.sum() >= MIN_PATCHES.get(name, 4):
                comps.append(cm)
        comps.sort(key=lambda c: -c.sum())
        if role == "reflection" and comps:
            comps = [np.logical_or.reduce(comps)]  # all glass = one precaution
        for comp in comps[: PER_CLASS.get(name, 2)]:
            m = dense.upsample(comp)
            if not m.any():
                continue
            frac = m.mean()
            # merge dense "sign" blobs into OCR clues they overlap
            if role == "text":
                hit = next((c for c in cands if "ocr" in c.clue.sources and (c.region_mask & m).sum() > 0.2 * m.sum()), None)
                if hit is not None:
                    if "detector" not in hit.clue.sources:
                        hit.clue.sources.append("detector")
                    continue
            possible = role == "reflection"
            if possible:
                fix = "soften"
            elif frac > (BIG_FRAC_LANDMARK if role in ("landmark", "flag") else BIG_FRAC):
                fix = "none"
            elif role == "text":
                fix = "inpaint"
            else:
                fix = "inpaint"
            conf = float(dense.probs[..., dense.names.index(name)][comp].mean())
            label = LABELS.get(name, name.title())
            if role == "text":
                label = "Sign (unread)"
            if possible:
                label = f"{label} (possible clue)"
            cands.append(
                ClueCandidate(
                    clue=Clue(
                        id="", index=0, type=role, label=label, description=DESCRIPTIONS.get(role, ""),
                        box=_box_from_mask(m), sources=["detector"], confidence=round(conf, 3),
                        possible_only=possible,
                        protected_overlap=bool((m & person_mask).sum() > 0.3 * m.sum()),
                    ),
                    mask=dilate(m, 6) & ~person_mask, fix=fix, region_mask=m,
                )
            )

    # ---- eyes (truth rule 2) -------------------------------------------------
    thr = iris_readable_px()
    for f in faces:
        em = np.zeros((H, W), bool)
        for ex0, ey0, ex1, ey1 in f.eye_boxes():
            em[max(0, ey0) : min(H, ey1), max(0, ex0) : min(W, ex1)] = True
        if not em.any():
            continue
        readable = f.iris_px >= thr
        cands.append(
            ClueCandidate(
                clue=Clue(
                    id="", index=0, type="reflection",
                    label="Eye reflection" if readable else "Eyes (possible reflection)",
                    description=(
                        f"Iris is {f.iris_px:.0f} px wide — above the {thr:.0f} px threshold where a reflection can be read."
                        if readable else
                        f"Iris is {f.iris_px:.0f} px wide — too small to read a reflection; softened as a precaution."
                    ),
                    box=_box_from_mask(em), sources=["reflection"], confidence=f.score,
                    possible_only=not readable, iris_px=round(f.iris_px, 1),
                ),
                mask=em, fix="soften", region_mask=em,
            )
        )

    # ---- Attacker A boxes -----------------------------------------------------
    for c in extra or []:
        x0, y0, x1, y1 = c.box.to_px(W, H)
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        m = np.zeros((H, W), bool)
        m[y0:y1, x0:x1] = True
        hit = next((k for k in cands if k.clue.box.iou(c.box) > 0.3), None)
        if hit is not None:
            if "attacker_a" not in hit.clue.sources:
                hit.clue.sources.append("attacker_a")
            if c.description and len(hit.clue.description) < 90:
                hit.clue.description = c.description
            continue
        frac = m.mean()
        fix = "soften" if c.type == "reflection" else ("none" if frac > BIG_FRAC else "inpaint")
        cc = c.model_copy(update={"sources": ["attacker_a"]})
        cands.append(ClueCandidate(clue=cc, mask=dilate(m, 4) & ~person_mask, fix=fix, region_mask=m))

    # ---- rank, cap, number ------------------------------------------------------
    def prior(c: ClueCandidate) -> tuple:
        return (TYPE_PRIOR.get(c.clue.type, 6), -c.clue.confidence, -c.region_mask.mean())

    cands = [c for c in cands if c.mask.any() or c.fix == "none"]
    cands.sort(key=prior)
    keep = cands[:MAX_CLUES]
    keep += [c for c in cands[MAX_CLUES:] if c.clue.type == "reflection" and "reflection" in c.clue.sources]
    for i, c in enumerate(keep, 1):
        c.clue.id = f"c{i}"
        c.clue.index = i
        c.clue.planned_fix = c.fix  # type: ignore[assignment]
    return ClueSet(candidates=keep, person_mask=person_mask, faces=faces)
