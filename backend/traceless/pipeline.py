"""Session orchestrator: one uploaded photo -> the full risk report.

Stages (each published to `state` as soon as it is ready, so the web app can
reveal at the presenter's pace while compute runs ahead):
  exif -> attack -> clues -> ablation/collapse -> defense/re-attack -> card
"""

from __future__ import annotations

import json
import secrets
import shutil
import threading
import time
import traceback
from pathlib import Path

import numpy as np
from PIL import Image

from . import exif as exif_mod
from .ablation import run_ablation
from .attackers.base import AttackContext
from .attackers.cloud import CloudAttacker
from .attackers.geoclip_attacker import GeoCLIPAdaptiveAttacker, GeoCLIPAttacker
from .attackers.reader import ReaderAttacker
from .attackers.street import StreetAttacker, coverage
from .clues.dense import segment
from .clues.faces import detect_faces
from .clues.find import find_clues
from .clues.ocr import read_text
from .defense.loop import beyond, run_defense
from .geo import gazetteer, haversine_km
from .schemas import SCHEMA_VERSION, Truth

ROOT = Path(__file__).resolve().parents[2]
SESSIONS_DIR = ROOT / "sessions"
TAKES_DIR = ROOT / "takes"
HEAVY = threading.Lock()  # one CPU-heavy pipeline at a time


class Session:
    def __init__(self, data: bytes, filename: str = "photo.jpg", truth: Truth | None = None,
                 radius_km: float = 25.0, source: str = "upload", fixture_id: str | None = None):
        self.id = secrets.token_urlsafe(9)
        self.token = secrets.token_urlsafe(16)  # download capability
        self.dir = SESSIONS_DIR / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.raw = data
        self.filename = filename
        self.radius_km = radius_km
        self.owner_truth = truth
        self.owner_ok_precise = False
        self.created = time.time()
        self.lock = threading.Lock()
        self.state: dict = {
            "schema": SCHEMA_VERSION, "id": self.id, "source": source, "fixture_id": fixture_id,
            "stage": "queued", "progress": {}, "timings": {}, "error": None,
            "radius_km": radius_km, "privacy": {"precise": False},
        }
        self.arr: np.ndarray | None = None
        self.protected: np.ndarray | None = None

    # ------------------------------------------------------------------ #
    def set(self, **kw):
        with self.lock:
            self.state.update(kw)

    def progress(self, key: str, frac: float):
        with self.lock:
            self.state["progress"][key] = round(frac, 3)

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.state, default=str))

    def url(self, name: str) -> str:
        return f"/api/s/{self.id}/file/{name}"

    def save_img(self, arr: np.ndarray, name: str):
        exif_mod.save_clean_jpeg(Image.fromarray(arr), self.dir / name)

    # ------------------------------------------------------------------ #
    def run(self):
        try:
            with HEAVY:
                self._run()
        except Exception as e:  # surface, never crash the server
            traceback.print_exc()
            self.set(stage="error", error=f"{type(e).__name__}: {e}")

    def _timed(self, name: str, t0: float):
        with self.lock:
            self.state["timings"][name] = round(time.time() - t0, 2)

    def _run(self):
        T = time.time()
        # ---- clue zero ---------------------------------------------------
        rep = exif_mod.read_exif(self.raw)
        img = exif_mod.load_clean(self.raw)  # pixels only from here on
        self.arr = np.asarray(img)
        self.save_img(self.arr, "original.jpg")
        rep.stripped = not exif_mod.has_any_metadata(self.dir / "original.jpg")
        gaz = gazetteer()
        if rep.gps:
            rep.gps_region = gaz.region_label(rep.gps.lat, rep.gps.lon)
        truth = None
        if rep.gps:
            truth = Truth(lat=rep.gps.lat, lon=rep.gps.lon, source="exif")
        if self.owner_truth is not None:
            truth = self.owner_truth  # owner's private confirmation wins
        precise = bool(truth and truth.public_landmark) or self.owner_ok_precise
        self.set(
            stage="exif", exif=rep.model_dump(), image={"w": img.size[0], "h": img.size[1], "url": self.url("original.jpg")},
            truth=_truth_public(truth, precise), privacy={"precise": precise},
        )
        self._timed("exif", T)

        # ---- Shot 1 depth (visual layer only; never feeds an attacker or a metric) ----
        try:
            from .depth import depth_png

            depth_png(img, self.dir / "depth.png")
            self.set(depth_url=self.url("depth.png"))
        except Exception as e:  # the diorama falls back to the flat photo
            print("depth failed:", e)

        # ---- attack (pixels only) + clue finding ------------------------
        t0 = time.time()
        ctx = AttackContext(truth=truth, radius_km=self.radius_km, variant="original", precise_regions=precise)
        cloud = CloudAttacker()
        geo, reader = GeoCLIPAttacker(), ReaderAttacker()
        import concurrent.futures as cf

        ex = cf.ThreadPoolExecutor(1)
        cloud_f = ex.submit(cloud.attack, img, ctx) if cloud.available() else None
        lines = read_text(img)
        self.progress("attack", 0.2)
        r_geo = geo.attack(img, ctx)
        self.progress("attack", 0.5)
        r_reader = reader.attack(img, ctx, lines=lines)
        street = StreetAttacker()
        r_street = street.attack(img, ctx) if street.available() else None
        self.set(street_coverage=coverage().model_dump())
        if truth is None and r_geo.top is not None:  # proxy answer key, labeled
            truth = Truth(lat=r_geo.top.lat, lon=r_geo.top.lon, source="proxy")
            ctx.truth = truth
            for r in (r_geo, r_reader, r_street):
                _retarget(r, truth, self.radius_km)
            self.set(truth=_truth_public(truth, precise))
        dense = segment(img)
        faces = detect_faces(img)
        self.progress("attack", 0.8)
        r_cloud = None
        if cloud_f is not None:
            try:
                r_cloud = cloud_f.result(timeout=ctx.timeout_s + 5)
            except Exception as e:
                r_cloud = cloud.failed(ctx, f"{type(e).__name__}: {e}", status="timeout")
            _retarget(r_cloud, truth, self.radius_km)
        else:
            r_cloud = cloud.failed(ctx, "no cloud key / offline mode", status="skipped")
        ex.shutdown(wait=False)
        attacks = [r_geo, r_reader, r_cloud] + ([r_street] if r_street is not None else [])
        self.set(stage="attack", attacks=[a.model_dump() for a in attacks])
        self._timed("attack", t0)

        t0 = time.time()
        cs = find_clues(img, dense, lines, faces, extra=r_cloud.clues if r_cloud.status == "ok" else None)
        self.clueset = cs
        self.set(stage="clues", clues=[c.clue.model_dump() for c in cs.candidates],
                 faces=len(faces))
        self._timed("clues", t0)

        # already hard to place? (every attacker misses by > radius)
        already = beyond(attacks) and truth is not None and truth.source != "proxy"
        if truth is not None and truth.source == "proxy":
            # without a real answer key, judge by spread: tiny clouds = placeable
            areas = [a.credible_area_km2 for a in attacks if a.status == "ok" and a.credible_area_km2]
            already = bool(areas) and min(areas) > 50_000
        self.set(already_safe=already)

        # ---- ablation + collapse ------------------------------------------
        t0 = time.time()
        abl = run_ablation(self.arr, cs.candidates, ctx, base=r_geo, on_progress=self.progress)
        for c in cs.candidates:
            c.clue.contribution = abl.contributions.get(c.clue.id)
        # display numbering follows contribution order
        order = {cid: i for i, cid in enumerate(abl.order)}
        cs.candidates.sort(key=lambda c: (order.get(c.clue.id, 99), c.clue.index))
        for i, c in enumerate(cs.candidates, 1):
            c.clue.index = i
        if abl.all_erased is not None:
            self.save_img(abl.all_erased, "all_erased.jpg")
        self.set(
            stage="ablation",
            clues=[c.clue.model_dump() for c in cs.candidates],
            collapse={"attacker_id": "geoclip", "frames": [f.model_dump() for f in abl.frames],
                      "order": abl.order},
        )
        self._timed("ablation", t0)

        if already:
            self.set(stage="done", defense=None)
            self._timed("total", T)
            return

        # ---- defense + re-attack with different AIs ---------------------------
        t0 = time.time()
        re_attackers = [GeoCLIPAttacker(), GeoCLIPAdaptiveAttacker(), ReaderAttacker()]
        if cloud.available():
            re_attackers += [CloudAttacker(adaptive=True)]
        if street.available():
            re_attackers += [StreetAttacker()]
        d = run_defense(self.arr, cs, abl, re_attackers, ctx, radius_km=self.radius_km,
                        on_progress=self.progress)
        self.protected = d.protected
        self.save_img(d.protected, "protected.jpg")
        Image.fromarray((d.edit_mask * 255).astype(np.uint8)).save(self.dir / "mask.png")
        q = d.plan.rounds[-1].quality if d.plan.rounds else None
        self.set(
            stage="defense",
            defense=d.plan.model_dump(),
            protected={"url": self.url("protected.jpg"), "mask_url": self.url("mask.png"),
                       "download": f"/d/{self.token}"},
        )
        self._timed("defense", t0)
        self.set(stage="done", card=_card(attacks, d, q, rep))
        self._timed("total", T)

    # ------------------------------------------------------------------ #
    def delete(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def save_take(self, name: str | None = None) -> str:
        """Record a finished run for the PANIC key (state + images, URLs rewritten)."""
        st = self.snapshot()
        if st.get("stage") != "done":
            raise RuntimeError("session not finished")
        name = name or st.get("fixture_id") or self.id
        d = TAKES_DIR / name
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        for f in ("original.jpg", "protected.jpg", "mask.png", "all_erased.jpg", "depth.png"):
            if (self.dir / f).exists():
                shutil.copy(self.dir / f, d / f)
        blob = json.dumps(st).replace(f"/api/s/{self.id}/file/", f"/takes/{name}/")
        (d / "state.json").write_text(blob, encoding="utf-8")
        return name


def _retarget(r, truth: Truth | None, radius: float):
    if r is None or truth is None or r.top is None:
        return
    r.distance_km = round(haversine_km(truth.lat, truth.lon, r.top.lat, r.top.lon), 2)
    r.within_radius = r.distance_km <= radius


def _truth_public(t: Truth | None, precise: bool) -> dict | None:
    """Projector privacy: the answer key's coordinates only when allowed."""
    if t is None:
        return None
    out = {"source": t.source, "public_landmark": t.public_landmark,
           "region": gazetteer().region_label(t.lat, t.lon, precise=precise)}
    if precise:
        out.update(lat=t.lat, lon=t.lon)
    return out


def _card(before, d, q, rep) -> dict:
    """The screenshot card: every number from this run."""
    def best(rs):
        ok = [r for r in rs if r.status == "ok" and r.distance_km is not None]
        return min(ok, key=lambda r: r.distance_km) if ok else None

    b, a = best(before), best(d.final_attacks)
    area_b = min((r.credible_area_km2 for r in before if r.status == "ok" and r.credible_area_km2), default=None)
    area_a = min((r.credible_area_km2 for r in d.final_attacks if r.status == "ok" and r.credible_area_km2), default=None)
    return {
        "before_km": b.distance_km if b else None,
        "before_by": b.attacker_name if b else None,
        "after_km": a.distance_km if a else None,
        "after_by": a.attacker_name if a else None,
        "area_before_km2": area_b,
        "area_after_km2": area_a,
        "area_growth": (area_a / area_b) if area_a and area_b else None,
        "pct_pixels_changed": q.pct_pixels_changed if q else None,
        "lpips": q.lpips if q else None,
        "ssim": q.ssim if q else None,
        "face_pixels_changed": q.face_pixels_changed if q else None,
        "metadata_stripped": rep.stripped,
        "metadata_fields": len(rep.fields),
        "had_gps": rep.has_gps,
        "reached_target": d.plan.reached_target,
        "radius_km": d.plan.radius_km,
        "verdict": d.plan.verdict,
        "attackers": [r.attacker_name for r in d.final_attacks if r.status == "ok"],
    }
