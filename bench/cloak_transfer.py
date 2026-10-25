"""CLOAK transfer: does noise optimized against GeoCLIP fool *other* model families?

Madrid fixture (inside the street coverage): original vs CLOAK (2/255, 4/255),
attacked by the street matcher (EigenPlaces + LightGlue) and The Reader (OCR).
Appends results to bench/results/cloak.json under "transfer" and CLOAK.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "bench"))

from cloak import cloak  # noqa: E402
from traceless.attackers.base import AttackContext  # noqa: E402
from traceless.attackers.reader import ReaderAttacker  # noqa: E402
from traceless.attackers.street import StreetAttacker  # noqa: E402
from traceless.schemas import Truth  # noqa: E402


def main() -> None:
    m = next(x for x in json.loads((ROOT / "fixtures" / "manifest.json").read_text(encoding="utf-8"))
             if x["id"] == "madrid-jamon-shopfront")
    img = Image.open(ROOT / "fixtures" / m["file"]).convert("RGB")
    img.thumbnail((768, 768))
    ctx = AttackContext(truth=Truth(lat=m["lat"], lon=m["lon"], source="fixture"))
    st, rd = StreetAttacker(), ReaderAttacker()
    rows = []
    for label, im in [("original", img), ("cloak 2/255", cloak(img, 2 / 255)), ("cloak 4/255", cloak(img, 4 / 255))]:
        s, r = st.attack(im, ctx), rd.attack(im, ctx)
        best = s.street_matches[0].inliers if s.street_matches else 0
        rows.append({"variant": label, "street_inliers": best, "street_km": s.distance_km, "reader_km": r.distance_km})
        print(rows[-1], flush=True)
    out = ROOT / "bench" / "results"
    data = json.loads((out / "cloak.json").read_text(encoding="utf-8"))
    data = {"geoclip": data if isinstance(data, list) else data.get("geoclip", []), "transfer": rows}
    (out / "cloak.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    md = ["", "Transfer to other model families (Madrid, inside street coverage):", "",
          "| variant | street matcher (inliers / km) | The Reader |", "|---|---|---|"]
    md += [f"| {r['variant']} | {r['street_inliers']} / {r['street_km'] if r['street_km'] is not None else 'no match'} | "
           f"{r['reader_km'] if r['reader_km'] is not None else 'nothing readable'} |" for r in rows]
    with open(out / "CLOAK.md", "a", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
