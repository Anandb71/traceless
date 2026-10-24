"""Attacker B (offline): GeoCLIP GPS retrieval on the laptop.

Two variants share one model:
- `geoclip`     : sees the whole frame (3 square views, probabilities averaged).
- `geoclip-adaptive`: the offline adaptive attacker. It is TOLD which pixels
  the defense edited, ignores close-ups that are mostly edited, and zooms
  into a 3x3 grid of the remaining untouched detail (12 views).
"""

from __future__ import annotations

import time

import numpy as np
from PIL import Image

from ..geo import Distribution, haversine_km
from ..schemas import AttackResult, Hypothesis
from .base import AttackContext, Attacker, finalize
from .geoclip_model import GeoCLIPModel, tile_boxes, views


class GeoCLIPAttacker(Attacker):
    id = "geoclip"
    name = "GeoCLIP (offline)"
    family = "retrieval"
    offline = True
    mode = "tri"

    def __init__(self, mode: str | None = None):
        if mode:
            self.mode = mode

    def view_weights(self, img: Image.Image, ctx: AttackContext) -> np.ndarray | None:
        return None

    def probs(self, img: Image.Image, ctx: AttackContext | None = None) -> np.ndarray:
        m = GeoCLIPModel.get()
        crops = views(img, self.mode)
        feats = m.embed(crops)
        p = m.probs_from_feats(feats)  # (V, N)
        w = self.view_weights(img, ctx) if ctx is not None else None
        if w is None:
            w = np.ones(len(crops))
        w = w / w.sum()
        return (p * w[:, None]).sum(0)

    def attack(self, img: Image.Image, ctx: AttackContext) -> AttackResult:
        t0 = time.time()
        try:
            probs = self.probs(img, ctx)
        except Exception as e:  # never take the demo down
            return self.failed(ctx, f"{type(e).__name__}: {e}", t0=t0)
        return self.result_from_probs(probs, ctx, latency_ms=int((time.time() - t0) * 1000))

    def result_from_probs(self, probs: np.ndarray, ctx: AttackContext, latency_ms: int = 0) -> AttackResult:
        m = GeoCLIPModel.get()
        masses = m.cell_masses(probs)
        order = np.argsort(-masses)
        cum = np.cumsum(masses[order])
        keep = order[: int(np.searchsorted(cum, 0.995)) + 1][:40_000]
        dist = Distribution({str(m.cell_ids[i]): float(masses[i]) for i in keep})
        res = self._result(
            image_variant=ctx.variant,
            hypotheses=top_hypotheses(m.gallery, probs),
            latency_ms=latency_ms,
            calls=1,
        )
        return finalize(res, dist, ctx, credible_area_km2=m.credible_area(probs, 0.9), sort=False)


class GeoCLIPAdaptiveAttacker(GeoCLIPAttacker):
    id = "geoclip-adaptive"
    name = "GeoCLIP adaptive (offline)"
    adaptive = True
    mode = "zoom"
    max_edited_frac = 0.25

    def view_weights(self, img: Image.Image, ctx: AttackContext) -> np.ndarray | None:
        boxes = tile_boxes(img.size[0], img.size[1], self.mode)
        if ctx.edit_mask is None or not ctx.edit_mask.any():
            return np.ones(len(boxes))
        w = []
        for x0, y0, x1, y1 in boxes:
            frac = float(ctx.edit_mask[y0:y1, x0:x1].mean()) if (x1 > x0 and y1 > y0) else 1.0
            w.append(1.0 if frac <= self.max_edited_frac else 0.0)
        w = np.array(w)
        return w if w.sum() > 0 else np.ones(len(boxes))


def top_hypotheses(gallery: np.ndarray, probs: np.ndarray, k: int = 5, sep_km: float = 100.0) -> list[Hypothesis]:
    """Top-k gallery points, spatially de-duplicated (>= sep_km apart).

    Probability reported = mass of all gallery points within sep_km of the
    pick (so the list reads as "regions", not single points)."""
    idx = np.argsort(-probs)[:2000]
    picks: list[int] = []
    for i in idx:
        if all(haversine_km(gallery[i, 0], gallery[i, 1], gallery[j, 0], gallery[j, 1]) >= sep_km for j in picks):
            picks.append(int(i))
            if len(picks) == k:
                break
    out = []
    for i in picks:
        d = haversine_km(gallery[i, 0], gallery[i, 1], gallery[:, 0], gallery[:, 1])
        out.append(
            Hypothesis(
                lat=float(gallery[i, 0]),
                lon=float(gallery[i, 1]),
                probability=round(float(probs[d < sep_km].sum()), 5),
                radius_km=sep_km,
            )
        )
    # keep GeoCLIP's own top-1 (argmax point) first, as in its paper's eval
    return out
