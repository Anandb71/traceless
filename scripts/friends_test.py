"""Real people's photos: run the full pipeline on a local folder of CONSENTED photos.

    python scripts/friends_test.py [--dir friends_photos] [--delete]

- The folder is git-ignored and never committed; per-photo results never leave memory.
- Answer key: each photo's own EXIF GPS (photos without GPS are skipped and counted).
- Writes ONLY aggregates to bench/friends.json: how many photos any attacker placed
  within 1 km / 25 km before vs after, and median best-attacker error before/after.
- `--delete` removes the photos after the run (truth rule 7).
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}


def best(attacks) -> float | None:
    ds = [a["distance_km"] for a in attacks if a.get("status") == "ok" and a.get("distance_km") is not None]
    return min(ds) if ds else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "friends_photos"))
    ap.add_argument("--delete", action="store_true", help="delete the photos afterwards")
    args = ap.parse_args()
    folder = Path(args.dir)
    files = sorted(p for p in folder.glob("*") if p.suffix.lower() in EXTS) if folder.exists() else []

    from traceless.exif import read_exif
    from traceless.pipeline import Session

    before, after, skipped, failed = [], [], 0, 0
    for p in files:
        data = p.read_bytes()
        if not read_exif(data).has_gps:
            skipped += 1  # no answer key: we never guess one for real people's photos
            continue
        s = Session(data, p.name, source="friends")
        try:
            s.run()
            st = s.snapshot()
            if st["stage"] != "done":
                failed += 1
                continue
            b = best(st["attacks"])
            a = b if st["already_safe"] else best(st["defense"]["rounds"][-1]["attacks"])
            before.append(b)
            after.append(a)
        finally:
            s.delete()  # no per-photo artefact survives

    def within(xs, km):
        return sum(1 for x in xs if x is not None and x <= km)

    def med(xs):
        xs = [x for x in xs if x is not None]
        return round(statistics.median(xs), 2) if xs else None

    out = {
        "date": time.strftime("%Y-%m-%d %H:%M"),
        "photos_found": len(files),
        "photos_run": len(before),
        "skipped_no_gps": skipped,
        "failed": failed,
        "attackers": "all available (offline: GeoCLIP, GeoCLIP adaptive, The Reader, street matcher; cloud if keyed)",
        "within_1km": {"before": within(before, 1), "after": within(after, 1)},
        "within_25km": {"before": within(before, 25), "after": within(after, 25)},
        "median_best_error_km": {"before": med(before), "after": med(after)},
    }
    dest = ROOT / "bench" / "friends.json"
    dest.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    if args.delete and folder.exists():
        shutil.rmtree(folder)
        print("deleted", folder)


if __name__ == "__main__":
    main()
