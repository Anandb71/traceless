"""Attacker interface + shared result finalization."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from ..geo import Distribution, gazetteer, haversine_km
from ..schemas import AttackResult, Hypothesis, Truth


@dataclass
class AttackContext:
    truth: Truth | None = None
    radius_km: float = 25.0
    variant: str = "original"
    # bool HxW mask of pixels the defense edited (adaptive attackers may use it)
    edit_mask: np.ndarray | None = None
    precise_regions: bool = False  # projector privacy mode off / public landmark
    timeout_s: float = 25.0
    extra: dict = field(default_factory=dict)


class Attacker:
    id: str = "base"
    name: str = "Attacker"
    family: str = "retrieval"
    offline: bool = True
    adaptive: bool = False

    def available(self) -> bool:
        return True

    def attack(self, img: Image.Image, ctx: AttackContext) -> AttackResult:  # pragma: no cover
        raise NotImplementedError

    def _result(self, **kw) -> AttackResult:
        return AttackResult(
            attacker_id=self.id,
            attacker_name=self.name,
            family=self.family,  # type: ignore[arg-type]
            offline=self.offline,
            adaptive=self.adaptive,
            **kw,
        )

    def failed(self, ctx: AttackContext, error: str, status: str = "failed", t0: float | None = None) -> AttackResult:
        return self._result(
            image_variant=ctx.variant,
            status=status,  # type: ignore[arg-type]
            error=error[:300],
            latency_ms=int((time.time() - t0) * 1000) if t0 else 0,
        )


def finalize(
    res: AttackResult,
    dist: Distribution,
    ctx: AttackContext,
    credible_area_km2: float | None = None,
    sort: bool = True,
) -> AttackResult:
    """Fill credible area, display cells, top-1 distance and region labels."""
    res.credible_area_km2 = (
        credible_area_km2 if credible_area_km2 is not None else dist.credible_area_km2(0.9)
    )
    res.h3_res, res.distribution = dist.display()
    if res.hypotheses:
        if sort:
            res.hypotheses.sort(key=lambda h: h.probability, reverse=True)
        res.top = res.hypotheses[0]
    elif dist.cells:
        m = dist.mode()
        res.top = Hypothesis(lat=m[0], lon=m[1], probability=max(dist.cells.values()))
    gaz = gazetteer()
    for h in res.hypotheses[:5]:
        h.region = gaz.region_label(h.lat, h.lon, precise=ctx.precise_regions)
    if res.top is not None:
        if res.top.region is None:
            res.top.region = gaz.region_label(res.top.lat, res.top.lon, precise=ctx.precise_regions)
        if ctx.truth is not None:
            res.distance_km = round(
                haversine_km(ctx.truth.lat, ctx.truth.lon, res.top.lat, res.top.lon), 2
            )
            res.within_radius = res.distance_km <= ctx.radius_km
    return res
