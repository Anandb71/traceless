"""Golden tests: the full offline pipeline on every fixture photo.

Invariants rather than exact numbers (GPU fp16 vs CPU fp32 differ slightly):
- clue zero is stripped; attackers saw pixels only
- the person is never altered (face_pixels_changed == 0 every round)
- the indoor photo takes the "already hard to place" path
- placeable photos get a defense with rounds, a verdict, and a full card
"""

import json
from pathlib import Path

import pytest

from traceless.pipeline import Session
from traceless.schemas import Truth

ROOT = Path(__file__).resolve().parents[2]
MAN = json.loads((ROOT / "fixtures" / "manifest.json").read_text(encoding="utf-8"))


@pytest.mark.golden
@pytest.mark.parametrize("fx", MAN, ids=[m["id"] for m in MAN])
def test_fixture_pipeline(fx):
    data = (ROOT / "fixtures" / fx["file"]).read_bytes()
    truth = Truth(lat=fx["lat"], lon=fx["lon"], source="fixture", public_landmark=fx.get("public_landmark", False))
    s = Session(data, truth=truth, source="sim")
    try:
        s.run()
        st = s.snapshot()
        assert st["stage"] == "done", st.get("error")
        assert st["exif"]["stripped"]
        assert any(a["attacker_id"] == "geoclip" and a["status"] == "ok" for a in st["attacks"])
        assert st["collapse"]["frames"], "collapse animation needs real frames"
        if fx.get("indoor"):
            assert st["already_safe"], "indoor fixture should take the already-safe path"
        if not st["already_safe"]:
            d = st["defense"]
            assert d["rounds"] and d["verdict"]
            for r in d["rounds"]:
                assert r["quality"]["face_pixels_changed"] == 0
            for k in ("before_km", "after_km", "pct_pixels_changed", "verdict"):
                assert st["card"][k] is not None
    finally:
        s.delete()
