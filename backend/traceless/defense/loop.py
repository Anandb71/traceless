"""The defense loop: erase -> re-attack with every attacker -> escalate.

Round 1  erase every clue that measurably helped (ablation gain) plus the
         always-erase types (text, phones, plates, flags, landmarks) and
         soften every reflection.
Round 2  erase the remaining erasable candidates, in contribution order.
Round 3+ leak search: occlude a grid of tiles on the *current* image, erase
         the tiles whose removal pushes GeoCLIP furthest away.
Stop when every attacker misses by more than the radius, or after K rounds,
or when the pixel budget is spent. If the target isn't reached, we say so.
The person is never touched (eyes softened only).
"""

from __future__ import annotations

import concurrent.futures as cf
import math
import os
from dataclasses import dataclass

import numpy as np

from ..ablation import AblationOutput, ViewCache, apply_fix
from ..attackers.base import AttackContext, Attacker
from ..attackers.geoclip_attacker import GeoCLIPAttacker
from ..clues.find import ClueCandidate, ClueSet
from ..geo import fmt_area
from ..metrics import quality
from ..schemas import AttackResult, DefenseAction, DefensePlan, DefenseRound
from .inpaint import dilate, inpaint, portrait_blur

ALWAYS = {"text", "phone", "plate", "flag", "landmark", "reflection"}
PIXEL_BUDGET = 0.35  # never repaint more than 35% of the photo
MIN_GAIN = 0.05  # log10 area gain that counts as "measurably helped"
# Portrait-mode background blur is opt-in: it is natural-looking but changes most
# pixels (measured: 83% changed, LPIPS 0.61 on a bench photo) — not "least destructive".
ALLOW_PORTRAIT_BLUR = os.environ.get("TRACELESS_PORTRAIT_BLUR", "0") == "1"


@dataclass
class DefenseOutput:
    protected: np.ndarray
    edit_mask: np.ndarray
    plan: DefensePlan
    final_attacks: list[AttackResult]


def attack_all(img_arr: np.ndarray, attackers: list[Attacker], ctx: AttackContext) -> list[AttackResult]:
    """Offline attackers run sequentially (CPU-bound); cloud ones in threads alongside."""
    from PIL import Image

    img = Image.fromarray(img_arr)
    remote = [a for a in attackers if not a.offline]
    local = [a for a in attackers if a.offline]
    ex = cf.ThreadPoolExecutor(max(1, len(remote)))
    futs = {a.id: ex.submit(a.attack, img, ctx) for a in remote}
    out = {a.id: a.attack(img, ctx) for a in local}
    for aid, f in futs.items():
        try:
            out[aid] = f.result(timeout=ctx.timeout_s + 5)
        except Exception as e:  # timeout or crash: never sink the demo
            a = next(x for x in remote if x.id == aid)
            out[aid] = a.failed(ctx, f"{type(e).__name__}: {e}", status="timeout")
    ex.shutdown(wait=False, cancel_futures=True)
    return [out[a.id] for a in attackers]


def beyond(results: list[AttackResult]) -> bool:
    """True when every attacker that produced a guess misses by > radius."""
    scored = [r for r in results if r.status == "ok" and r.within_radius is not None]
    return all(not r.within_radius for r in scored)


def verdict(results: list[AttackResult], radius_km: float, reached: bool) -> str:
    names = [r.attacker_name for r in results if r.status == "ok"]
    who = ", ".join(names) if names else "no attacker"
    if reached:
        return f"Not placeable within {radius_km:g} km by the attackers we tested: {who}."
    close = [r for r in results if r.status == "ok" and r.within_radius]
    worst = min(close, key=lambda r: r.distance_km or 0) if close else None
    tail = f" {worst.attacker_name} still lands {worst.distance_km:.0f} km away." if worst and worst.distance_km is not None else ""
    return f"Target not reached: within {radius_km:g} km for {len(close)} of {len(names)} attackers.{tail}"


def run_defense(
    arr: np.ndarray,
    clues: ClueSet,
    abl: AblationOutput,
    attackers: list[Attacker],
    ctx: AttackContext,
    radius_km: float = 25.0,
    max_rounds: int = 4,
    on_progress=None,
) -> DefenseOutput:
    H, W = arr.shape[:2]
    plan = DefensePlan(radius_km=radius_km, max_rounds=max_rounds)
    plan.protected = [_box(f.box, W, H) for f in clues.faces]
    contrib = abl.contributions
    cur = arr.copy()
    edit = np.zeros((H, W), bool)
    done: set[str] = set()
    results: list[AttackResult] = []

    def gain(c: ClueCandidate) -> float:
        ct = contrib.get(c.clue.id)
        if ct is None:
            return 0.0
        moved = 0.0
        if ct.error_with_km and ct.error_without_km:
            moved = math.log10(max(ct.error_without_km, 1) / max(ct.error_with_km, 1))
        return ct.gain + 0.5 * moved

    erasable = [c for c in clues.candidates if c.fix != "none" and c.mask.any()]
    erasable.sort(key=gain, reverse=True)

    for rnd in range(1, max_rounds + 1):
        if rnd == 1:
            batch = [c for c in erasable if c.clue.type in ALWAYS or gain(c) >= MIN_GAIN]
        else:
            batch = [c for c in erasable if c.clue.id not in done]
        ids: list[str] = []
        for c in batch:
            if edit.mean() + c.mask.mean() > PIXEL_BUDGET and c.fix == "inpaint":
                continue
            before = cur
            cur = apply_fix(cur, c)
            changed = np.any(cur != before, axis=-1)
            edit |= changed | c.mask
            done.add(c.clue.id)
            ids.append(c.clue.id)
            plan.actions.append(DefenseAction(
                clue_id=c.clue.id, fix=c.fix, round=rnd, pixels=int(changed.sum()),
                reason=_reason(c, contrib.get(c.clue.id)),
            ))
        # Attacker C still pins the street? Its verified inlier keypoints say exactly
        # which pixels it matched: erase the densest clusters of them (measured, not guessed).
        street_hit = next((r for r in results if r.attacker_id == "street" and r.within_radius), None)
        if rnd >= 2 and street_hit is not None and street_hit.street_matches:
            m = street_anchor_mask(street_hit.street_matches[0].keypoint_pairs, H, W, clues.person_mask | edit,
                                   budget=PIXEL_BUDGET - edit.mean())
            if m is not None:
                before = cur
                cur, _ = inpaint(cur, m)
                changed = np.any(cur != before, axis=-1)
                edit |= changed | m
                ids.append(f"street{rnd}")
                plan.actions.append(DefenseAction(
                    clue_id=f"street{rnd}", fix="inpaint", round=rnd, pixels=int(changed.sum()),
                    reason="Street matcher anchor: erased the areas holding most of its verified keypoint matches.",
                ))
        if rnd >= 2 and not ids:
            has_person = clues.person_mask.mean() > 0.03
            if rnd == max_rounds and has_person and ALLOW_PORTRAIT_BLUR:
                before = cur
                cur = portrait_blur(cur, clues.person_mask)
                changed = np.any(cur != before, axis=-1)
                edit |= changed
                ids.append(f"portrait{rnd}")
                plan.actions.append(DefenseAction(
                    clue_id=f"portrait{rnd}", fix="blur", round=rnd, pixels=int(changed.sum()),
                    reason="Portrait-mode background blur: the person stays pixel-identical, the background detail goes.",
                ))
            else:
                tiles = leak_search(cur, clues.person_mask | edit, ctx, budget=PIXEL_BUDGET - edit.mean())
                for k, m in enumerate(tiles):
                    before = cur
                    cur, _ = inpaint(cur, m)
                    changed = np.any(cur != before, axis=-1)
                    edit |= changed | m
                    tid = f"leak{rnd}.{k + 1}"
                    ids.append(tid)
                    plan.actions.append(DefenseAction(
                        clue_id=tid, fix="inpaint", round=rnd, pixels=int(changed.sum()),
                        reason="Leak search: erasing this area pushed GeoCLIP furthest away.",
                    ))
        if not ids and rnd > 1:
            break
        # Truth rule 6: the person is never altered (eyes excepted) — hard restore.
        cur[clues.person_mask] = arr[clues.person_mask]
        if on_progress:
            on_progress("defense", rnd / max_rounds * 0.5)
        actx = AttackContext(truth=ctx.truth, radius_km=radius_km, variant=f"protected:r{rnd}",
                             edit_mask=edit, precise_regions=ctx.precise_regions, timeout_s=ctx.timeout_s)
        results = attack_all(cur, attackers, actx)
        q = quality(arr, cur, edit, clues.person_mask)
        ok = beyond(results)
        plan.rounds.append(DefenseRound(round=rnd, clue_ids=ids, attacks=results, all_beyond_radius=ok, quality=q))
        if on_progress:
            on_progress("defense", rnd / max_rounds)
        if ok:
            break
    plan.reached_target = bool(plan.rounds and plan.rounds[-1].all_beyond_radius)
    plan.verdict = verdict(results, radius_km, plan.reached_target)
    return DefenseOutput(cur, edit, plan, results)


def street_anchor_mask(pairs: list[list[float]], H: int, W: int, forbidden: np.ndarray, budget: float,
                       grid: int = 8, cover: float = 0.7) -> np.ndarray | None:
    """Grid cells holding the most query-side inlier keypoints, until `cover` of them are masked."""
    if not pairs or budget <= 0.02:
        return None
    q = np.array(pairs)[:, :2]
    gx = np.clip((q[:, 0] * grid).astype(int), 0, grid - 1)
    gy = np.clip((q[:, 1] * grid).astype(int), 0, grid - 1)
    counts = np.zeros((grid, grid), int)
    np.add.at(counts, (gy, gx), 1)
    order = np.dstack(np.unravel_index(np.argsort(-counts.ravel()), counts.shape))[0]
    m = np.zeros((H, W), bool)
    got = 0
    for cy, cx in order:
        if counts[cy, cx] == 0 or got >= cover * len(q):
            break
        cell = np.zeros((H, W), bool)
        cell[cy * H // grid:(cy + 1) * H // grid, cx * W // grid:(cx + 1) * W // grid] = True
        cell &= ~forbidden
        if (m | cell).mean() > budget:
            break
        m |= cell
        got += counts[cy, cx]
    return m if m.any() else None


def leak_search(arr: np.ndarray, forbidden: np.ndarray, ctx: AttackContext, budget: float, grid: int = 6, take: int = 3) -> list[np.ndarray]:
    """Occlusion search: which remaining tile, erased, moves GeoCLIP the most?"""
    if budget <= 0.02:
        return []
    H, W = arr.shape[:2]
    atk = GeoCLIPAttacker()
    cache = ViewCache(atk, arr)
    base = atk.result_from_probs(cache.base_probs(), ctx)
    scored = []
    for gy in range(grid):
        for gx in range(grid):
            m = np.zeros((H, W), bool)
            m[gy * H // grid:(gy + 1) * H // grid, gx * W // grid:(gx + 1) * W // grid] = True
            m &= ~dilate(forbidden, 4)
            if m.mean() < 0.2 / (grid * grid) or m.mean() > budget:
                continue
            e, _ = inpaint(arr, m, max_side=256)
            r = atk.result_from_probs(cache.probs_for(e, np.any(e != arr, axis=-1)), ctx)
            d0, d1 = base.distance_km or 0.0, r.distance_km or 0.0
            a0, a1 = base.credible_area_km2 or 1, r.credible_area_km2 or 1
            scored.append((math.log10(max(d1, 1) / max(d0, 1)) + math.log10(a1 / a0), m))
    scored.sort(key=lambda t: -t[0])
    out, used = [], 0.0
    for s, m in scored[:take]:
        if s <= 0 or used + m.mean() > budget:
            continue
        out.append(m)
        used += m.mean()
    return out


def _reason(c: ClueCandidate, ct) -> str:
    verb = {"inpaint": "Erased", "blur": "Blurred", "soften": "Softened"}.get(c.fix, "Fixed")
    if c.clue.possible_only:
        return f"{verb} as a labeled precaution (possible clue)."
    if ct is not None and ct.gain > 0:
        return (f"{verb}: alone it shrank the search area from {fmt_area(ct.area_without_km2)} "
                f"to {fmt_area(ct.area_with_km2)}.")
    return f"{verb}: {c.clue.type.replace('_', ' ')} is a known giveaway."


def _box(b, W, H):
    from ..schemas import Box

    return Box.from_px(*b, W, H)
