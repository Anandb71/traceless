"""Rehearsal: 5 different photos in a row against ONE running server, no restarts.

Mixes the three real entry paths (phone QR upload, drag-and-drop upload, SIM fixture),
then checks for each run: stage done, card numbers present, face untouched, phone
download page + file (metadata-free), and that a PANIC take can be recorded.

    python scripts/rehearse.py --base http://localhost:8001
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

PLAN = [
    ("abergavenny-book-shop", "phone"),  # the prepared outdoor photo
    ("indoor-sunny-apartment", "sim"),  # already-hard-to-place path
    ("madrid-jamon-shopfront", "upload"),  # inside street coverage -> "The match"
    ("tyumen-portrait", "phone"),  # no GPS, a face to protect
    ("cincinnati-main-st", "sim"),  # famous scene: honest "target not reached"
]


def start(c: httpx.Client, base: str, fid: str, how: str, man: dict) -> str:
    f = ROOT / "fixtures" / man[fid]["file"]
    if how == "sim":
        return c.post(f"{base}/api/sessions/fixture/{fid}").json()["id"]
    if how == "upload":
        return c.post(f"{base}/api/sessions", files={"file": (f.name, f.read_bytes(), "image/jpeg")}).json()["id"]
    slot = c.post(f"{base}/api/slots").json()  # phone: QR slot -> /u/<token> form post
    page = c.get(f"{base}/u/{slot['token']}")
    assert page.status_code == 200 and "Check my photo" in page.text
    r = c.post(f"{base}/u/{slot['token']}", files={"file": (f.name, f.read_bytes(), "image/jpeg")})
    assert r.status_code == 200 and "Watch the big screen" in r.text
    for _ in range(20):
        sid = c.get(f"{base}/api/slots/{slot['token']}").json()["session"]
        if sid:
            return sid
        time.sleep(0.5)
    raise RuntimeError("slot never got a session")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    args = ap.parse_args()
    base = args.base
    man = {m["id"]: m for m in json.loads((ROOT / "fixtures" / "manifest.json").read_text(encoding="utf-8"))}
    from PIL import Image

    rows, ok_all = [], True
    with httpx.Client(timeout=60) as c:
        h = c.get(f"{base}/api/health").json()
        assert h["ready"], "models not ready"
        for fid, how in PLAN:
            t0 = time.time()
            sid = start(c, base, fid, how, man)
            while True:
                st = c.get(f"{base}/api/s/{sid}").json()
                if st["stage"] in ("done", "error"):
                    break
                if time.time() - t0 > 300:
                    st["stage"] = "TIMEOUT"
                    break
                time.sleep(1)
            wall = time.time() - t0
            problems = []
            if st["stage"] != "done":
                problems.append(f"stage={st['stage']} {st.get('error')}")
            street = next((a for a in st.get("attacks", []) if a["attacker_id"] == "street"), None)
            thr = (st.get("street_coverage") or {}).get("match_threshold") or 10**9
            matched = bool(street and street.get("street_matches") and street["street_matches"][0]["inliers"] >= thr)
            if st["stage"] == "done" and not st.get("already_safe"):
                card = st.get("card") or {}
                for k in ("before_km", "after_km", "pct_pixels_changed", "verdict"):
                    if card.get(k) is None:
                        problems.append(f"card.{k} missing")
                if card.get("face_pixels_changed"):
                    problems.append(f"face changed {card['face_pixels_changed']} px")
                dl = st["protected"]["download"]
                if c.get(f"{base}{dl}").status_code != 200:
                    problems.append("download page failed")
                img = c.get(f"{base}{dl}/traceless.jpg")
                im = Image.open(io.BytesIO(img.content))
                if img.status_code != 200 or im.getexif() or im.info.get("exif"):
                    problems.append("downloaded file has metadata or failed")
            if st["stage"] == "done":
                if c.post(f"{base}/api/s/{sid}/take", params={"name": f"rehearsal-{fid}"}).status_code != 200:
                    problems.append("take not recorded")
            card = st.get("card") or {}
            row = {
                "photo": fid, "path": how, "stage": st["stage"], "wall_s": round(wall, 1),
                "timings": st.get("timings"), "already_safe": st.get("already_safe"),
                "street_match": matched, "had_gps": (st.get("exif") or {}).get("has_gps"),
                "truth": (st.get("truth") or {}).get("source"),
                "before_km": card.get("before_km"), "after_km": card.get("after_km"),
                "reached": card.get("reached_target"), "pct_changed": card.get("pct_pixels_changed"),
                "problems": problems,
            }
            ok_all &= not problems
            rows.append(row)
            print(json.dumps(row), flush=True)
            c.delete(f"{base}/api/s/{sid}")  # truth rule 7: delete after the session
        takes = c.get(f"{base}/api/takes").json()
        panic = all(c.get(f"{base}/api/takes/{t}").status_code == 200 for t in takes)
    out = ROOT / "bench" / "results" / "rehearsal.json"
    out.write_text(json.dumps({"date": time.strftime("%Y-%m-%d %H:%M"), "base": base, "runs": rows,
                               "panic_takes_ok": panic, "n_takes": len(takes), "all_ok": ok_all}, indent=1),
                   encoding="utf-8")
    print(f"ALL_OK={ok_all} panic_takes_ok={panic} takes={len(takes)}")
    sys.exit(0 if ok_all and panic else 1)


if __name__ == "__main__":
    main()
