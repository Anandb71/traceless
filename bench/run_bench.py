"""TRACELESS benchmark on Im2GPS3k (`make bench`).

Runs the *exact demo pipeline* (traceless.pipeline.Session — same attackers,
clue finder, ablation, defense loop) on a deterministic subset of Im2GPS3k
(2,997 Flickr photos with known coordinates), and reports, per attacker,
before vs after protection:
  accuracy at 1 / 25 / 200 / 750 / 2500 km, median top-1 error, median 90%
  credible area; plus LPIPS / SSIM / % pixels changed.

Subsets:
  - "random": the first N photos of a fixed seeded shuffle (seed 0).
  - "clue-rich": the first M photos (same shuffle order) where OCR reads >= 2
    confident text lines (score >= 0.8), scanned from the rest of the shuffle.

No cherry-picking: every attempted photo is counted; failures are listed.
"Can't be placed" always means "not within the radius, by these attackers".

Data: bench/data/im2gps3k_places.csv (committed) + images, fetched by
`--download` into bench/data/im2gps3k/ (455 MB zip, gitignored).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import statistics
import sys
import time
import traceback
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("TRACELESS_OFFLINE", "1")  # cloud costs money; opt in with --cloud

DATA = ROOT / "bench" / "data"
IMG_DIR = DATA / "im2gps3k"
CSV = DATA / "im2gps3k_places.csv"
RESULTS = ROOT / "bench" / "results"
THRESH = [1, 25, 200, 750, 2500]
ZIP_PAGE = "http://www.mediafire.com/file/7ht7sn78q27o9we/im2gps3ktest.zip"


def download() -> None:
    import re

    import httpx

    IMG_DIR.mkdir(parents=True, exist_ok=True)
    if any(IMG_DIR.iterdir()):
        print("images already present")
        return
    zpath = DATA / "im2gps3ktest.zip"
    if not zpath.exists():
        page = httpx.get(ZIP_PAGE, follow_redirects=True, timeout=60, headers={"User-Agent": "Mozilla/5.0"}).text
        m = re.search(r"(https?://download\d*\.mediafire\.com/[^\"'\s]+im2gps3ktest\.zip)", page)
        if not m:
            raise SystemExit("could not find the mediafire download link; download manually to " + str(zpath))
        print("downloading", m.group(1))
        with httpx.stream("GET", m.group(1), follow_redirects=True, timeout=600) as r:
            r.raise_for_status()
            with open(zpath, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            name = Path(info.filename).name
            if name.lower().endswith((".jpg", ".jpeg", ".png")):
                (IMG_DIR / name).write_bytes(z.read(info))
    zpath.unlink()
    print("extracted", sum(1 for _ in IMG_DIR.iterdir()), "images")


def load_rows() -> list[dict]:
    with open(CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rng = random.Random(0)
    rng.shuffle(rows)
    return rows


def acc(dists: list[float | None]) -> dict[str, float]:
    n = len(dists)
    return {str(t): round(sum(1 for d in dists if d is not None and d <= t) / n, 4) if n else 0.0 for t in THRESH}


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None


def run_one(path: Path, lat: float, lon: float, radius: float) -> dict:
    from PIL import Image

    from traceless.attackers.base import AttackContext
    from traceless.attackers.geoclip_attacker import GeoCLIPAdaptiveAttacker
    from traceless.pipeline import Session
    from traceless.schemas import Truth

    truth = Truth(lat=lat, lon=lon, source="fixture")
    s = Session(path.read_bytes(), path.name, truth=truth, radius_km=radius, source="bench")
    t0 = time.time()
    try:
        s.run()
        st = s.snapshot()
        if st["stage"] != "done":
            raise RuntimeError(st.get("error") or st["stage"])
        before = {a["attacker_id"]: a for a in st["attacks"] if a["status"] == "ok"}
        # the adaptive attacker's "before" = it attacking the untouched original
        img = Image.fromarray(s.arr)
        ad = GeoCLIPAdaptiveAttacker().attack(img, AttackContext(truth=truth, radius_km=radius))
        before["geoclip-adaptive"] = ad.model_dump()
        if st["already_safe"]:
            after = dict(before)
            q = {"lpips": 0.0, "ssim": 1.0, "pct_pixels_changed": 0.0}
        else:
            last = st["defense"]["rounds"][-1]
            after = {a["attacker_id"]: a for a in last["attacks"] if a["status"] == "ok"}
            q = last["quality"]
        pick = lambda a: {"d": a.get("distance_km"), "area": a.get("credible_area_km2")}  # noqa: E731
        return {
            "ok": True,
            "already_safe": st["already_safe"],
            "n_clues": len(st["clues"]),
            "n_text_clues": sum(1 for c in st["clues"] if c["type"] in ("text", "phone", "plate")),
            "before": {k: pick(v) for k, v in before.items()},
            "after": {k: pick(v) for k, v in after.items()},
            "quality": {k: q.get(k) for k in ("lpips", "ssim", "pct_pixels_changed")},
            "rounds": 0 if st["already_safe"] else len(st["defense"]["rounds"]),
            "reached": None if st["already_safe"] else st["defense"]["reached_target"],
            "seconds": round(time.time() - t0, 1),
        }
    finally:
        s.delete()


NAMES = {
    "geoclip": "GeoCLIP (offline)",
    "geoclip-adaptive": "GeoCLIP adaptive (told what was edited)",
    "reader": "The Reader (OCR sleuth)",
    "cloud": "Cloud VLM",
    "cloud-adaptive": "Cloud VLM, told it was edited",
}


def summarize(label: str, recs: list[dict]) -> dict:
    ok = [r for r in recs if r.get("ok")]
    attackers = {}
    ids = sorted({k for r in ok for k in r["before"]} | {k for r in ok for k in r["after"]})
    for aid in ids:
        if aid == "cloud-adaptive":
            continue
        b = [r["before"].get(aid, {}).get("d") for r in ok]
        a_id = aid if aid != "cloud" else "cloud-adaptive"
        a = [r["after"].get(a_id, r["after"].get(aid, {})).get("d") for r in ok]
        attackers[aid] = {
            "name": NAMES.get(aid, aid) + (" → told it was edited" if aid == "cloud" else ""),
            "before": {"acc": acc(b), "median_km": med(b), "median_area_km2": med([r["before"].get(aid, {}).get("area") for r in ok]), "n": len(b)},
            "after": {"acc": acc(a), "median_km": med(a), "median_area_km2": med([r["after"].get(a_id, {}).get("area") for r in ok]), "n": len(a)},
        }
    defended = [r for r in ok if not r["already_safe"]]
    return {
        "label": label,
        "n": len(ok),
        "attempted": len(recs),
        "already_safe": sum(1 for r in ok if r["already_safe"]),
        "defended": len(defended),
        "reached_target": sum(1 for r in defended if r["reached"]),
        "attackers": attackers,
        "quality": {
            "lpips_mean": round(statistics.mean([r["quality"]["lpips"] for r in defended if r["quality"]["lpips"] is not None]), 4) if defended else None,
            "ssim_mean": round(statistics.mean([r["quality"]["ssim"] for r in defended if r["quality"]["ssim"] is not None]), 4) if defended else None,
            "pct_changed_median": med([r["quality"]["pct_pixels_changed"] for r in defended]),
        },
        "median_seconds": med([r["seconds"] for r in ok]),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--clue-rich", type=int, default=100)
    ap.add_argument("--radius", type=float, default=25.0)
    ap.add_argument("--download", action="store_true")
    ap.add_argument("--cloud", action="store_true", help="include the cloud attacker (costs API credits)")
    args = ap.parse_args()
    if args.cloud:
        os.environ["TRACELESS_OFFLINE"] = "0"
    if args.download or not IMG_DIR.exists() or not any(IMG_DIR.iterdir()):
        download()

    from traceless.clues.ocr import read_text

    rows = [r for r in load_rows() if (IMG_DIR / r["IMG_ID"]).exists()]
    RESULTS.mkdir(parents=True, exist_ok=True)
    per_image = RESULTS / "per_image.jsonl"
    done = {}
    if per_image.exists():  # resumable
        for line in per_image.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done[(r["subset"], r["id"])] = r
    out = open(per_image, "a", encoding="utf-8")

    def process(subset: str, row: dict) -> dict:
        key = (subset, row["IMG_ID"])
        if key in done:
            return done[key]
        try:
            rec = run_one(IMG_DIR / row["IMG_ID"], float(row["LAT"]), float(row["LON"]), args.radius)
        except Exception as e:
            traceback.print_exc()
            rec = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        rec.update(subset=subset, id=row["IMG_ID"])
        out.write(json.dumps(rec) + "\n")
        out.flush()
        done[key] = rec
        return rec

    t0 = time.time()
    rand = []
    for i, row in enumerate(rows[: args.n]):
        rand.append(process("random", row))
        print(f"[random {i + 1}/{args.n}] {row['IMG_ID']} {rand[-1].get('before', {}).get('geoclip', {})} -> {rand[-1].get('after', {}).get('geoclip', {})}  ({time.time() - t0:.0f}s)")
    rich = []
    from PIL import Image

    for row in rows[args.n :]:
        if len(rich) >= args.clue_rich:
            break
        key = ("clue-rich", row["IMG_ID"])
        if key not in done:
            lines = [l for l in read_text(Image.open(IMG_DIR / row["IMG_ID"]).convert("RGB")) if l.score >= 0.8]
            if len(lines) < 2:
                continue
        rich.append(process("clue-rich", row))
        print(f"[clue-rich {len(rich)}/{args.clue_rich}] {row['IMG_ID']}  ({time.time() - t0:.0f}s)")

    res = {
        "dataset": "Im2GPS3k",
        "date": date.today().isoformat(),
        "radius_km": args.radius,
        "thresholds_km": THRESH,
        "command": " ".join(["python bench/run_bench.py"] + sys.argv[1:]),
        "device": _device(),
        "subsets": [summarize(f"Random subset (seed 0, first {args.n})", rand)]
        + ([summarize("Clue-rich subset (>= 2 confident OCR lines)", rich)] if rich else []),
        "failures": [{"id": r["id"], "subset": r["subset"], "error": r.get("error")} for r in rand + rich if not r.get("ok")],
    }
    (RESULTS / "latest.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    (RESULTS / "TABLES.md").write_text(tables_md(res), encoding="utf-8")
    print(tables_md(res))


def _device() -> str:
    import torch

    return torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"


def tables_md(res: dict) -> str:
    def pct(v):
        return f"{v * 100:.1f}%"

    def km(v):
        return "—" if v is None else (f"{v:,.0f} km" if v >= 10 else f"{v:.1f} km")

    lines = [f"_Generated by `{res['command']}` on {res['date']} ({res['device']}). Radius {res['radius_km']:g} km._", ""]
    for s in res["subsets"]:
        lines += [
            f"**{s['label']}** — n = {s['n']} of {s['attempted']} attempted; {s['already_safe']} already hard to place; "
            f"{s['defended']} defended, {s['reached_target']} reached the {res['radius_km']:g} km target. "
            f"LPIPS {s['quality']['lpips_mean']}, SSIM {s['quality']['ssim_mean']}, median pixels changed {s['quality']['pct_changed_median']}%.",
            "",
            "| attacker | " + " | ".join(f"≤{t} km" for t in res["thresholds_km"]) + " | median error | median 90% area |",
            "|---|" + "---|" * (len(res["thresholds_km"]) + 2),
        ]
        for a in s["attackers"].values():
            cells = [f"{pct(a['before']['acc'][str(t)])} → **{pct(a['after']['acc'][str(t)])}**" for t in res["thresholds_km"]]
            area_b, area_a = a["before"]["median_area_km2"], a["after"]["median_area_km2"]
            lines.append(
                f"| {a['name']} | " + " | ".join(cells)
                + f" | {km(a['before']['median_km'])} → **{km(a['after']['median_km'])}**"
                + f" | {'—' if area_b is None else f'{area_b:,.0f}'} → **{'—' if area_a is None else f'{area_a:,.0f}'}** km² |"
            )
        lines.append("")
    if res["failures"]:
        lines.append(f"Failures ({len(res['failures'])}): " + ", ".join(f"{f['id']}" for f in res["failures"][:20]))
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
