"""Measure Attacker C's "match" threshold (RANSAC inliers) — UPGRADE.md: pick it by testing.

Two query sets against the street index:
  - in-coverage, leave-one-out: each sampled reference photo queries the index
    with itself removed. A *correct* street claim = best match within 25 m
    (also reported at 100 m; Commons/Mapillary GPS is itself noisy).
  - out-of-coverage negatives: photos taken far outside the coverage (other
    fixtures + Im2GPS3k images > 50 km away). Any claim here is false.

Threshold = smallest inlier count T such that (a) every negative scores < T and
(b) >= 95% of in-coverage claims at >= T are correct within 100 m.
Reports recall@1 within 25 m / 100 m at T. Writes
backend/traceless/data/street_threshold.json (read by attackers/street.py).
"""

from __future__ import annotations

import csv
import json
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from traceless.attackers.street import TOP_K, StreetModels, street_index  # noqa: E402
from traceless.geo import haversine_km  # noqa: E402

OUT = ROOT / "backend" / "traceless" / "data" / "street_threshold.json"


def best_match(sm, ix, img, exclude: int | None = None):
    q = sm.describe([img])[0]
    sims = ix.desc @ q
    if exclude is not None:
        sims[exclude] = -9
    top = np.argsort(-sims)[:TOP_K]
    fq = sm.keypoints(img)
    best = (0, None)
    for i in top:
        _, n = sm.match(fq, sm.keypoints(Image.open(ix.root / "img" / ix.files[i])))
        if n > best[0]:
            best = (n, int(i))
    return best


def main(n_pos: int = 150, n_neg: int = 60) -> None:
    ix = street_index()
    if ix is None:
        raise SystemExit("no street index — run scripts/build_street_index.py first")
    sm = StreetModels.get()
    rng = random.Random(0)
    pos = []
    for i in rng.sample(range(len(ix.ids)), min(n_pos, len(ix.ids))):
        n, j = best_match(sm, ix, Image.open(ix.root / "img" / ix.files[i]), exclude=i)
        d = None if j is None else float(haversine_km(ix.lat[i], ix.lon[i], ix.lat[j], ix.lon[j]) * 1000)
        pos.append({"id": ix.ids[i], "inliers": n, "dist_m": d})
        print(f"pos {len(pos):3d} inliers={n:4d} dist={d if d is None else round(d)} m")
    neg = []
    man = json.loads((ROOT / "fixtures" / "manifest.json").read_text(encoding="utf-8"))
    for m in man:
        if haversine_km(ix.center[0], ix.center[1], m["lat"], m["lon"]) > 50:
            n, _ = best_match(sm, ix, Image.open(ROOT / "fixtures" / m["file"]))
            neg.append({"id": m["id"], "inliers": n})
    imdir = ROOT / "bench" / "data" / "im2gps3k"
    if imdir.exists():
        rows = list(csv.DictReader(open(ROOT / "bench" / "data" / "im2gps3k_places.csv", encoding="utf-8")))
        rng.shuffle(rows)
        for r in rows:
            if len(neg) >= n_neg:
                break
            if haversine_km(ix.center[0], ix.center[1], float(r["LAT"]), float(r["LON"])) < 50 or not (imdir / r["IMG_ID"]).exists():
                continue
            n, _ = best_match(sm, ix, Image.open(imdir / r["IMG_ID"]).convert("RGB"))
            neg.append({"id": r["IMG_ID"], "inliers": n})
    for x in neg:
        print(f"neg {x['id'][:30]:30s} inliers={x['inliers']}")

    max_neg = max([x["inliers"] for x in neg] or [0])
    chosen = None
    for T in range(max_neg + 1, 2000):
        claims = [p for p in pos if p["inliers"] >= T]
        if not claims:
            break
        prec = sum(1 for p in claims if p["dist_m"] is not None and p["dist_m"] <= 100) / len(claims)
        if prec >= 0.95:
            chosen = T
            break
    if chosen is None:
        chosen = max_neg + 1
    claims = [p for p in pos if p["inliers"] >= chosen]
    res = {
        "inlier_threshold": chosen,
        "index": ix.name, "source": ix.source, "n_index": len(ix.ids),
        "n_positive_queries": len(pos), "n_negative_queries": len(neg),
        "max_negative_inliers": max_neg,
        "claims_at_threshold": len(claims),
        "precision_100m": round(sum(1 for p in claims if p["dist_m"] is not None and p["dist_m"] <= 100) / len(claims), 3) if claims else None,
        "recall_at1_25m": round(sum(1 for p in pos if p["inliers"] >= chosen and p["dist_m"] is not None and p["dist_m"] <= 25) / len(pos), 3),
        "recall_at1_100m": round(sum(1 for p in pos if p["inliers"] >= chosen and p["dist_m"] is not None and p["dist_m"] <= 100) / len(pos), 3),
        "criterion": "smallest T above every out-of-coverage negative with >=95% of in-coverage claims within 100 m (leave-one-out)",
        "positives": pos, "negatives": neg,
    }
    OUT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k not in ("positives", "negatives")}, indent=1))


if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:3]))
