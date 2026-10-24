"""Clue contributions by ablation + the real-data collapse sequence.

Driven by Attacker B (GeoCLIP, offline) for speed — the UI labels this.
- Contribution of clue c: erase ONLY c (with the same eraser the defense
  uses), re-attack, compare 90% credible area and top-1 error.
- Collapse: start from the image with every erasable clue erased, restore
  clues one at a time in contribution order; each frame is a real attack.

Speed trick (exact, not an approximation): GeoCLIP sees the frame through a
few square views; an edit can only change the views it overlaps, so cached
embeddings are reused for the untouched views.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

import numpy as np
import torch
from PIL import Image

from .attackers.base import AttackContext
from .attackers.geoclip_attacker import GeoCLIPAttacker
from .attackers.geoclip_model import GeoCLIPModel, tile_boxes
from .clues.find import ClueCandidate
from .defense.inpaint import blur, feather, inpaint, soften
from .schemas import AttackResult, CollapseFrame, Contribution

COLLAPSE_STEPS = 5
MEASURE_MAX_FRAC = 0.5  # regions larger than this are not ablated (would erase the photo)


def apply_fix(arr: np.ndarray, cand: ClueCandidate, fix: str | None = None, lama_side: int = 512) -> np.ndarray:
    fix = fix or cand.fix
    m = cand.mask
    if not m.any():
        return arr
    if fix == "inpaint":
        return inpaint(arr, m, max_side=lama_side)[0]
    if fix == "blur":
        return blur(arr, m)
    if fix == "soften":
        return soften(arr, m)
    return arr


def measure_fix(c: ClueCandidate) -> str:
    """Eraser used to MEASURE a clue (big regions use inpaint for measurement)."""
    return c.fix if c.fix != "none" else "inpaint"


@dataclass
class ViewCache:
    """GeoCLIP view embeddings for one image, with partial recompute."""

    attacker: GeoCLIPAttacker
    arr: np.ndarray
    feats: torch.Tensor = field(init=False)
    boxes: list = field(init=False)

    def __post_init__(self):
        h, w = self.arr.shape[:2]
        self.boxes = tile_boxes(w, h, self.attacker.mode)
        self.feats = self._embed(self.arr, list(range(len(self.boxes))))

    def _embed(self, arr: np.ndarray, which: list[int]) -> torch.Tensor:
        img = Image.fromarray(arr)
        crops = [img.crop(self.boxes[i]) for i in which]
        return GeoCLIPModel.get().embed(crops)

    def probs_for(self, arr: np.ndarray, changed: np.ndarray) -> np.ndarray:
        """Probs for `arr`, which differs from self.arr only where `changed`."""
        feats = self.feats.clone()
        which = [i for i, (x0, y0, x1, y1) in enumerate(self.boxes) if changed[y0:y1, x0:x1].any()]
        if which:
            feats[which] = self._embed(arr, which)
        p = GeoCLIPModel.get().probs_from_feats(feats)
        return p.mean(0)

    def base_probs(self) -> np.ndarray:
        return GeoCLIPModel.get().probs_from_feats(self.feats).mean(0)


@dataclass
class AblationOutput:
    base: AttackResult
    contributions: dict[str, Contribution]
    erased: dict[str, np.ndarray]  # clue id -> image with only that clue erased
    frames: list[CollapseFrame]
    order: list[str]
    all_erased: np.ndarray | None
    seconds: float


def run_ablation(
    arr: np.ndarray,
    cands: list[ClueCandidate],
    ctx: AttackContext,
    base: AttackResult | None = None,
    on_progress=None,
) -> AblationOutput:
    t0 = time.time()
    atk = GeoCLIPAttacker()
    cache = ViewCache(atk, arr)
    if base is None:
        base = atk.result_from_probs(cache.base_probs(), ctx)
    contributions: dict[str, Contribution] = {}
    erased: dict[str, np.ndarray] = {}
    measurable = [
        c for c in cands
        if c.region_mask is not None and c.region_mask.mean() <= MEASURE_MAX_FRAC and c.mask.any()
        and not c.clue.possible_only  # precautions are softened, not measured
    ]
    for k, c in enumerate(measurable):
        e = apply_fix(arr, c, measure_fix(c), lama_side=384)
        erased[c.clue.id] = e
        changed = np.any(e != arr, axis=-1)
        r = atk.result_from_probs(
            cache.probs_for(e, changed), _ctx(ctx, f"ablate:{c.clue.id}")
        )
        a_with = base.credible_area_km2 or 0.0
        a_wo = r.credible_area_km2 or 0.0
        contributions[c.clue.id] = Contribution(
            attacker_id=atk.id,
            area_with_km2=round(a_with, 1),
            area_without_km2=round(a_wo, 1),
            error_with_km=base.distance_km,
            error_without_km=r.distance_km,
            gain=round(math.log10(max(a_wo, 1.0) / max(a_with, 1.0)), 3),
        )
        if on_progress:
            on_progress("ablation", (k + 1) / max(1, len(measurable)))

    # Score = area gain, tie-broken by how far the guess moves.
    def score(cid: str) -> float:
        ct = contributions[cid]
        moved = 0.0
        if ct.error_with_km is not None and ct.error_without_km is not None:
            moved = math.log10(max(ct.error_without_km, 1.0) / max(ct.error_with_km, 1.0))
        return ct.gain + 0.5 * moved

    order = sorted(contributions, key=score, reverse=True)
    for rank, cid in enumerate(order, 1):
        contributions[cid].rank = rank

    # Collapse: all erased -> restore one at a time (contribution order).
    frames: list[CollapseFrame] = []
    all_erased = None
    if order:
        by_id = {c.clue.id: c for c in cands}
        cur = arr.copy()
        for cid in reversed(order):  # erase least important first, most important last
            cur = apply_fix(cur, by_id[cid], measure_fix(by_id[cid]), lama_side=384)
        all_erased = cur
        changed = np.any(cur != arr, axis=-1)
        r0 = atk.result_from_probs(cache.probs_for(cur, changed), _ctx(ctx, "collapse:0"))
        frames.append(CollapseFrame(step=0, restored_clue_ids=[], attack=r0))
        restored: list[str] = []
        # Restore the top clues one by one; the long tail comes back in one last step.
        steps = [[cid] for cid in order[:COLLAPSE_STEPS]]
        if len(order) > COLLAPSE_STEPS:
            steps.append(order[COLLAPSE_STEPS:])
        for i, group in enumerate(steps, 1):
            for cid in group:
                alpha = feather(by_id[cid].mask | np.any(erased[cid] != arr, axis=-1), 2)[..., None]
                cur = (alpha * arr + (1 - alpha) * cur).astype(np.uint8)
                restored.append(cid)
            if i == len(steps):
                r = base.model_copy(deep=True)  # fully restored == the original attack
                r.image_variant = f"collapse:{i}"
            else:
                changed = np.any(cur != arr, axis=-1)
                r = atk.result_from_probs(cache.probs_for(cur, changed), _ctx(ctx, f"collapse:{i}"))
            frames.append(CollapseFrame(step=i, restored_clue_ids=list(restored), attack=r))
            if on_progress:
                on_progress("collapse", i / len(steps))
    return AblationOutput(base, contributions, erased, frames, order, all_erased, time.time() - t0)


def _ctx(ctx: AttackContext, variant: str) -> AttackContext:
    return AttackContext(
        truth=ctx.truth, radius_km=ctx.radius_km, variant=variant,
        precise_regions=ctx.precise_regions,
    )
