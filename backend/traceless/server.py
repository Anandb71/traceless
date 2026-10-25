"""TRACELESS API + phone pages + static web app.

Run:  backend/.venv/Scripts/python -m traceless.server   (or `make dev`)
"""

from __future__ import annotations

import html
import io
import json
import os
import secrets
import shutil
import socket
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / "backend" / ".env")

import uvicorn  # noqa: E402
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from .geo import gazetteer  # noqa: E402
from .pipeline import SESSIONS_DIR, TAKES_DIR, Session  # noqa: E402
from .schemas import Truth  # noqa: E402

PORT = int(os.environ.get("TRACELESS_PORT", "8000"))
FIXTURES = ROOT / "fixtures"
TAKES = TAKES_DIR
WEB_DIST = ROOT / "web" / "dist"
BENCH_RESULTS = ROOT / "bench" / "results"
MAX_UPLOAD = 40 * 1024 * 1024

@asynccontextmanager
async def lifespan(_app):
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    threading.Thread(target=warm, daemon=True).start()
    yield


app = FastAPI(title="TRACELESS", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SESSIONS: dict[str, Session] = {}
SLOTS: dict[str, dict] = {}  # upload token -> {"session": id|None, "created": t}
READY = {"ready": False, "steps": {}, "error": None}


# --------------------------------------------------------------------------- #
# Warm-up: load every model before the demo starts
# --------------------------------------------------------------------------- #


def warm():
    t0 = time.time()
    try:
        from PIL import Image

        from .attackers.geoclip_model import GeoCLIPModel
        from .attackers.reader import name_index
        from .clues.dense import segment
        from .clues.faces import detect_faces
        from .clues.ocr import read_text
        from .defense.inpaint import inpaint, lama
        from .metrics import _lpips

        for name, fn in [
            ("gazetteer", gazetteer), ("reader", name_index), ("geoclip", GeoCLIPModel.get),
            ("lama", lama), ("lpips", _lpips), ("street", _warm_street), ("depth", _warm_depth),
        ]:
            t = time.time()
            fn()
            READY["steps"][name] = round(time.time() - t, 1)
        import numpy as np

        img = Image.new("RGB", (640, 480), (120, 140, 160))
        t = time.time()
        read_text(img)
        segment(img)
        detect_faces(img)
        m = np.zeros((480, 640), bool)
        m[100:200, 100:300] = True
        inpaint(np.asarray(img), m)
        READY["steps"]["first-pass"] = round(time.time() - t, 1)
        READY["ready"] = True
        READY["seconds"] = round(time.time() - t0, 1)
    except Exception as e:  # pragma: no cover
        READY["error"] = f"{type(e).__name__}: {e}"


def _warm_depth():
    from PIL import Image

    from .depth import _pipe

    _pipe()(Image.new("RGB", (64, 48)))


def _warm_street():
    from .attackers.street import StreetModels, street_index

    if street_index() is not None:
        StreetModels.get()


def lan_ip() -> str:
    if os.environ.get("TRACELESS_HOST"):
        return os.environ["TRACELESS_HOST"]
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))  # no packet is sent
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def base_url() -> str:
    return f"http://{lan_ip()}:{PORT}"


# --------------------------------------------------------------------------- #
# Health / config
# --------------------------------------------------------------------------- #


@app.get("/api/health")
def health():
    from .attackers.cloud import CloudAttacker, providers

    return {
        **READY,
        "cloud": CloudAttacker().available(),
        "cloud_providers": [p for p, _ in providers()],
        "offline": os.environ.get("TRACELESS_OFFLINE", "0") == "1",
        "base_url": base_url(),
        "sessions": len(SESSIONS),
    }


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #


def _start(sess: Session) -> Session:
    SESSIONS[sess.id] = sess
    threading.Thread(target=sess.run, daemon=True).start()
    return sess


def _truth_from(lat, lon, landmark=False) -> Truth | None:
    if lat in (None, "") or lon in (None, ""):
        return None
    return Truth(lat=float(lat), lon=float(lon), source="owner", public_landmark=bool(landmark))


@app.post("/api/sessions")
async def create_session(
    file: UploadFile = File(...),
    lat: str | None = Form(None),
    lon: str | None = Form(None),
    radius_km: float = Form(25.0),
):
    data = await file.read()
    if not data or len(data) > MAX_UPLOAD:
        raise HTTPException(400, "empty or too large")
    sess = _start(Session(data, file.filename or "photo.jpg", truth=_truth_from(lat, lon), radius_km=radius_km))
    return {"id": sess.id}


def manifest() -> list[dict]:
    return json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))


@app.get("/api/fixtures")
def fixtures():
    return [
        {k: x[k] for k in ("id", "title", "place", "category", "indoor", "public_landmark", "license", "author")}
        | {"url": f"/fixtures/{x['file']}"}
        for x in manifest()
    ]


@app.post("/api/sessions/fixture/{fid}")
def fixture_session(fid: str, radius_km: float = 25.0):
    x = next((m for m in manifest() if m["id"] == fid), None)
    if x is None:
        raise HTTPException(404, "no such fixture")
    data = (FIXTURES / x["file"]).read_bytes()
    truth = Truth(lat=x["lat"], lon=x["lon"], source="fixture", public_landmark=x.get("public_landmark", False))
    sess = _start(Session(data, x["file"], truth=truth, radius_km=radius_km, source="sim", fixture_id=fid))
    return {"id": sess.id}


def _sess(sid: str) -> Session:
    s = SESSIONS.get(sid)
    if s is None:
        raise HTTPException(404, "session not found")
    return s


@app.get("/api/s/{sid}")
def session_state(sid: str):
    return _sess(sid).snapshot()


@app.get("/api/s/{sid}/file/{name}")
def session_file(sid: str, name: str):
    s = _sess(sid)
    if name not in {"original.jpg", "protected.jpg", "mask.png", "all_erased.jpg", "depth.png"} and not (
        name.startswith("tap_") and name.endswith(".jpg") and name[4:-4].isdigit()
    ):
        raise HTTPException(404)
    p = s.dir / name
    if not p.exists():
        raise HTTPException(404, "not ready")
    return FileResponse(p, headers={"Cache-Control": "no-store"})


@app.post("/api/s/{sid}/tap/{clue_id}")
def tap(sid: str, clue_id: str):
    """TAP_REMOVE: erase one clue, re-attack with offline GeoCLIP (measured, not estimated)."""
    s = _sess(sid)
    try:
        return s.tap(clue_id)
    except KeyError:
        raise HTTPException(404, "no such clue") from None
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e


@app.delete("/api/s/{sid}")
def delete_session(sid: str):
    s = SESSIONS.pop(sid, None)
    if s:
        s.delete()
    return {"deleted": bool(s)}


@app.post("/api/wipe")
def wipe():
    """Truth rule 7: delete everything after the session."""
    n = len(SESSIONS)
    for s in list(SESSIONS.values()):
        s.delete()
    SESSIONS.clear()
    SLOTS.clear()
    shutil.rmtree(SESSIONS_DIR, ignore_errors=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    return {"wiped_sessions": n}


@app.get("/api/places")
def places(q: str):
    return [
        {"name": p.name, "admin1": p.admin1, "country": p.country, "lat": p.lat, "lon": p.lon}
        for p in gazetteer().search(q)
    ]


# --------------------------------------------------------------------------- #
# Phone transfer: QR upload slot -> phone page -> session; QR download back
# --------------------------------------------------------------------------- #


@app.post("/api/slots")
def new_slot():
    tok = secrets.token_urlsafe(12)
    SLOTS[tok] = {"session": None, "created": time.time()}
    url = f"{base_url()}/u/{tok}"
    return {"token": tok, "url": url, "qr": f"/api/qr?data={url}"}


@app.get("/api/slots/{tok}")
def slot(tok: str):
    if tok not in SLOTS:
        raise HTTPException(404)
    return SLOTS[tok]


@app.get("/api/qr")
def qr(data: str):
    import segno

    buf = io.BytesIO()
    segno.make(data, error="m").save(buf, kind="svg", scale=8, border=2, dark="#0b0f17", light="#ffffff")
    return Response(buf.getvalue(), media_type="image/svg+xml")


PHONE_CSS = """
body{margin:0;font:16px/1.4 system-ui,-apple-system,sans-serif;background:#07090f;color:#e8edf7;
display:flex;min-height:100vh;align-items:center;justify-content:center}
.c{max-width:420px;width:100%;padding:28px}h1{font-size:22px;letter-spacing:.3em;margin:0 0 4px}
p{color:#9aa6bd}label{display:block;margin:18px 0 6px;color:#9aa6bd;font-size:14px}
input{width:100%;box-sizing:border-box;padding:14px;border-radius:12px;border:1px solid #2a3245;
background:#111624;color:#e8edf7;font-size:16px}
button,.b{display:block;width:100%;margin-top:22px;padding:16px;border:0;border-radius:14px;
background:#ff4d6d;color:#fff;font-size:18px;font-weight:600;text-align:center;text-decoration:none}
img{width:100%;border-radius:12px;margin-top:16px}small{color:#6b768c}
"""


@app.get("/u/{tok}", response_class=HTMLResponse)
def phone_upload(tok: str):
    if tok not in SLOTS:
        return HTMLResponse("<h3>This upload link has expired.</h3>", 404)
    return f"""<!doctype html><html><head><meta name=viewport content="width=device-width,initial-scale=1">
<title>TRACELESS</title><style>{PHONE_CSS}</style></head><body><div class=c>
<h1>TRACELESS</h1><p>Send a photo you'd post. It stays on this laptop and is deleted after the demo.</p>
<form method=post action="/u/{html.escape(tok)}" enctype=multipart/form-data>
<label>Photo</label><input type=file name=file accept="image/*" required>
<label>Where was it taken? <small>(private — never shown on screen)</small></label>
<input name=place list=pl placeholder="City (optional)" autocomplete=off oninput="s(this.value)">
<datalist id=pl></datalist><input type=hidden name=lat id=lat><input type=hidden name=lon id=lon>
<button>Check my photo</button></form></div>
<script>let P=[];async function s(q){{if(q.length<2)return;const r=await fetch('/api/places?q='+encodeURIComponent(q));
P=await r.json();document.getElementById('pl').innerHTML=P.map(p=>`<option value="${{p.name}}, ${{p.country}}">`).join('');
const m=P.find(p=>q.startsWith(p.name));if(m){{lat.value=m.lat;lon.value=m.lon}}}}</script></body></html>"""


@app.post("/u/{tok}", response_class=HTMLResponse)
async def phone_upload_post(tok: str, file: UploadFile = File(...), lat: str | None = Form(None), lon: str | None = Form(None)):
    if tok not in SLOTS:
        return HTMLResponse("<h3>This upload link has expired.</h3>", 404)
    data = await file.read()
    if not data or len(data) > MAX_UPLOAD:
        return HTMLResponse("<h3>That file didn't arrive — try again.</h3>", 400)
    sess = _start(Session(data, file.filename or "photo.jpg", truth=_truth_from(lat, lon), source="phone"))
    SLOTS[tok]["session"] = sess.id
    return f"""<!doctype html><html><head><meta name=viewport content="width=device-width,initial-scale=1">
<style>{PHONE_CSS}</style></head><body><div class=c><h1>TRACELESS</h1>
<p>Got it. Watch the big screen.</p><p><small>Your protected photo will come back by QR.</small></p></div></body></html>"""


def _by_token(token: str) -> Session:
    s = next((x for x in SESSIONS.values() if x.token == token), None)
    if s is None or s.protected is None:
        raise HTTPException(404, "not ready")
    return s


@app.get("/d/{token}", response_class=HTMLResponse)
def phone_download(token: str):
    s = _by_token(token)
    card = s.snapshot().get("card") or {}
    line = ""
    if card.get("before_km") is not None and card.get("after_km") is not None:
        line = f"Best AI guess: {card['before_km']:.1f} km → {card['after_km']:.0f} km from where you were."
    return f"""<!doctype html><html><head><meta name=viewport content="width=device-width,initial-scale=1">
<title>Your protected photo</title><style>{PHONE_CSS}</style></head><body><div class=c><h1>TRACELESS</h1>
<p>Safe to post. Location data stripped. {html.escape(line)}</p>
<img src="/d/{token}/traceless.jpg" alt="protected photo">
<a class=b href="/d/{token}/traceless.jpg" download="traceless.jpg">Save photo</a>
<p><small>Long-press the image to save to Photos on iPhone.</small></p></div></body></html>"""


@app.get("/d/{token}/traceless.jpg")
def phone_download_file(token: str):
    s = _by_token(token)
    return FileResponse(s.dir / "protected.jpg", media_type="image/jpeg", filename="traceless.jpg")


# --------------------------------------------------------------------------- #
# Truth / privacy controls (laptop side)
# --------------------------------------------------------------------------- #


@app.post("/api/s/{sid}/privacy")
async def set_privacy(sid: str, req: Request):
    body = await req.json()
    s = _sess(sid)
    s.owner_ok_precise = bool(body.get("precise"))
    with s.lock:
        s.state["privacy"] = {"precise": s.owner_ok_precise or bool((s.state.get("truth") or {}).get("public_landmark"))}
    return s.state["privacy"]


# --------------------------------------------------------------------------- #
# Recorded takes (PANIC key) and benchmark results
# --------------------------------------------------------------------------- #


@app.post("/api/s/{sid}/take")
def save_take(sid: str, name: str | None = None):
    try:
        return {"take": _sess(sid).save_take(name)}
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e


@app.get("/api/takes")
def list_takes():
    if not TAKES.exists():
        return []
    return sorted(p.name for p in TAKES.iterdir() if (p / "state.json").exists())


@app.get("/api/takes/{name}")
def get_take(name: str):
    p = TAKES / name / "state.json"
    if not p.exists():
        raise HTTPException(404)
    st = json.loads(p.read_text(encoding="utf-8"))
    st["take"] = name
    return st


@app.get("/api/bench")
def bench():
    p = BENCH_RESULTS / "latest.json"
    if not p.exists():
        return JSONResponse({"available": False})
    return json.loads(p.read_text(encoding="utf-8")) | {"available": True}


# --------------------------------------------------------------------------- #
# Static
# --------------------------------------------------------------------------- #

app.mount("/fixtures", StaticFiles(directory=FIXTURES), name="fixtures")
STREET = ROOT / "models" / "weights" / "street"
STREET.mkdir(parents=True, exist_ok=True)
app.mount("/street", StaticFiles(directory=STREET), name="street")
TAKES.mkdir(exist_ok=True)
app.mount("/takes", StaticFiles(directory=TAKES), name="takes")
if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = WEB_DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(WEB_DIST / "index.html")


def _free_port(start: int) -> int:
    """A stale socket must never kill the demo: fall back to the next free port."""
    for p in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", p))
                return p
            except OSError:
                continue
    return start


def main():
    global PORT
    port = _free_port(PORT)
    if port != PORT:
        print(f"!! port {PORT} is busy — serving on {port} instead")
    PORT = port
    print(f"TRACELESS → http://localhost:{port}   (phones: {base_url()})", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
