"""Inject generated numbers into README.md (truth rule 3: nothing hand-typed).

Replaces the blocks between
  <!-- BENCH:START --> ... <!-- BENCH:END -->      with bench/results/TABLES.md
  <!-- IRIS:START --> ... <!-- IRIS:END -->        with the measured iris threshold table
  <!-- FIXTURES:START --> ... <!-- FIXTURES:END --> with bench/results/fixtures.md (scripts/run_fixtures.py)
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


def block(name: str, body: str, text: str) -> str:
    pat = re.compile(rf"(<!-- {name}:START -->)(.*?)(<!-- {name}:END -->)", re.S)
    return pat.sub(lambda m: f"{m.group(1)}\n{body.strip()}\n{m.group(3)}", text)


def iris_md() -> str:
    p = ROOT / "backend" / "traceless" / "data" / "iris_threshold.json"
    if not p.exists():
        return "_Not measured yet — run `make iris`._"
    d = json.loads(p.read_text(encoding="utf-8"))
    rows = ["| iris diameter | readable (either) | GeoCLIP same place | OCR reads a word |", "|---|---|---|---|"]
    for t in d["table"]:
        rows.append(f"| {t['iris_px']} px | {t['readable_rate'] * 100:.0f}% | {t['geoclip_rate'] * 100:.0f}% | {t['ocr_rate'] * 100:.0f}% |")
    head = (
        f"Measured threshold: **{d['iris_readable_px']} px** iris diameter "
        f"({'found' if d['found'] else 'not reached within tested sizes — never claimed readable'}). "
        f"Criterion: {d['criterion']}. Simulation: {d['simulation']}. Scenes: {len(d['scenes'])} fixtures."
    )
    return head + "\n\n" + "\n".join(rows)


def street_md() -> str:
    p = ROOT / "backend" / "traceless" / "data" / "street_threshold.json"
    if not p.exists():
        return "_Not measured yet — run `bench/street_threshold.py`._"
    d = json.loads(p.read_text(encoding="utf-8"))
    return (
        f"Measured on the `{d['index']}` reference set ({d['n_index']} {d['source']} photos): "
        f"threshold **T = {d['inlier_threshold']} inliers** (max on {d['n_negative_queries']} out-of-coverage "
        f"negatives: {d['max_negative_inliers']}). Leave-one-out on {d['n_positive_queries']} in-coverage "
        f"queries: recall@1 within 25 m **{d['recall_at1_25m'] * 100:.0f}%**, within 100 m "
        f"**{d['recall_at1_100m'] * 100:.0f}%**; precision of claims within 100 m "
        f"{(d['precision_100m'] or 0) * 100:.0f}% ({d['claims_at_threshold']} claims)."
    )


def main() -> None:
    text = README.read_text(encoding="utf-8")
    tables = ROOT / "bench" / "results" / "TABLES.md"
    text = block("BENCH", tables.read_text(encoding="utf-8") if tables.exists() else "_Run `make bench`._", text)
    text = block("IRIS", iris_md(), text)
    text = block("STREET", street_md(), text)
    fx = ROOT / "bench" / "results" / "fixtures.md"
    text = block("FIXTURES", fx.read_text(encoding="utf-8") if fx.exists() else "_Run `python scripts/run_fixtures.py`._", text)
    README.write_text(text, encoding="utf-8")
    print("README updated")


if __name__ == "__main__":
    main()
