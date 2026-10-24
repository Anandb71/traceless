"""Measure the eye-reflection readability threshold (truth rule 2).

Question: how many pixels wide must an iris be before the scene reflected in
it can be *read* by an attacker?

Simulation (deliberately attacker-favourable, so the threshold is a lower
bound): each outdoor fixture scene is mapped into a disk of diameter D px as a
convex-mirror (fisheye) reflection, blended 65/35 over a synthetic iris
texture, then JPEG-compressed (q=85). The attacker crops the iris and:
  - OCR: reads any >=4-letter word that OCR also reads in the full scene;
  - GeoCLIP: top-1 of the iris crop lands within 25 km of GeoCLIP's top-1 on
    the full scene (i.e. the reflection carries the same location signal).
"Readable" at D = either succeeds on >= 50% of scenes. The threshold is the
smallest D at which that holds, and every D above it also holds.

Writes backend/traceless/data/iris_threshold.json (read by clues/faces.py).
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from traceless.attackers.geoclip_attacker import GeoCLIPAttacker  # noqa: E402
from traceless.attackers.base import AttackContext  # noqa: E402
from traceless.clues.ocr import read_text  # noqa: E402
from traceless.geo import haversine_km  # noqa: E402

SIZES = [8, 12, 16, 24, 32, 48, 64, 96, 128, 192]
OUT = ROOT / "backend" / "traceless" / "data" / "iris_threshold.json"


def fisheye(scene: Image.Image, d: int) -> Image.Image:
    """Convex-mirror look: square crop -> radial compression toward the rim."""
    s = min(scene.size)
    sq = scene.crop(((scene.width - s) // 2, (scene.height - s) // 2, (scene.width + s) // 2, (scene.height + s) // 2))
    n = 512
    src = np.asarray(sq.resize((n, n), Image.LANCZOS)).astype(np.float32)
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    cx = cy = (n - 1) / 2
    dx, dy = (xx - cx) / cx, (yy - cy) / cy
    r = np.sqrt(dx**2 + dy**2)
    rs = np.tan(np.clip(r, 0, 0.999) * 0.9) / np.tan(0.9)  # barrel mapping
    with np.errstate(invalid="ignore", divide="ignore"):
        k = np.where(r > 0, rs / r, 1.0)
    sx = np.clip(cx + dx * k * cx, 0, n - 1).astype(int)
    sy = np.clip(cy + dy * k * cy, 0, n - 1).astype(int)
    out = src[sy, sx]
    out[r > 1] = 0
    return Image.fromarray(out.astype(np.uint8)).resize((d, d), Image.LANCZOS)


def iris_texture(d: int, seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    base = np.zeros((d, d, 3), np.float32)
    yy, xx = np.mgrid[0:d, 0:d]
    r = np.hypot(xx - d / 2, yy - d / 2) / (d / 2)
    ang = np.arctan2(yy - d / 2, xx - d / 2)
    streak = 0.5 + 0.5 * np.sin(ang * 40 + rng.uniform(0, 6))
    col = np.array([90, 60, 35], np.float32)
    base[:] = col * (0.6 + 0.4 * streak[..., None])
    base[r < 0.35] = 10  # pupil
    return Image.fromarray(base.clip(0, 255).astype(np.uint8))


def make_eye(scene: Image.Image, d: int, seed: int) -> Image.Image:
    refl = fisheye(scene, d)
    iris = iris_texture(d, seed)
    eye = Image.blend(iris, refl, 0.65)
    mask = Image.new("L", (d, d), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, d - 1, d - 1), fill=255)
    canvas = Image.new("RGB", (int(d * 1.6), int(d * 1.2)), (225, 215, 205))  # sclera
    canvas.paste(eye, (int(d * 0.3), int(d * 0.1)), mask.filter(ImageFilter.GaussianBlur(max(0.5, d / 60))))
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=85)
    return Image.open(buf).convert("RGB")


def main() -> None:
    man = json.loads((ROOT / "fixtures" / "manifest.json").read_text(encoding="utf-8"))
    scenes = [m for m in man if m["category"] in ("street_text", "landmark", "suburban", "reflective")]
    atk = GeoCLIPAttacker(mode="center")
    ctx = AttackContext()
    rows = []
    for m in scenes:
        scene = Image.open(ROOT / "fixtures" / m["file"]).convert("RGB")
        ref = atk.attack(scene, ctx).top
        words = {w.lower() for l in read_text(scene) for w in l.text.split() if len(w) >= 4 and w.isalpha()}
        for i, d in enumerate(SIZES):
            eye = make_eye(scene, d, seed=i)
            up = eye.resize((max(224, eye.width * 4), max(224, eye.height * 4)), Image.BICUBIC)
            top = atk.attack(up, ctx).top
            geo_ok = bool(ref and top and haversine_km(ref.lat, ref.lon, top.lat, top.lon) <= 25)
            seen = {w.lower() for l in read_text(up) for w in l.text.split() if len(w) >= 4}
            ocr_ok = bool(words & seen)
            rows.append({"scene": m["id"], "iris_px": d, "geoclip_same_place": geo_ok, "ocr_word": ocr_ok})
            print(f"{m['id'][:26]:26s} D={d:4d} geo={geo_ok!s:5s} ocr={ocr_ok}")
    table = []
    for d in SIZES:
        rs = [r for r in rows if r["iris_px"] == d]
        rate = float(np.mean([r["geoclip_same_place"] or r["ocr_word"] for r in rs]))
        table.append({"iris_px": d, "readable_rate": round(rate, 3),
                      "geoclip_rate": round(float(np.mean([r["geoclip_same_place"] for r in rs])), 3),
                      "ocr_rate": round(float(np.mean([r["ocr_word"] for r in rs])), 3)})
    thr = None
    for i, t in enumerate(table):
        if all(x["readable_rate"] >= 0.5 for x in table[i:]):
            thr = t["iris_px"]
            break
    out = {
        "iris_readable_px": thr if thr is not None else SIZES[-1] * 2,
        "found": thr is not None,
        "criterion": "smallest iris diameter where >=50% of scenes are readable (GeoCLIP same place within 25 km, or OCR reads a scene word), holding for every larger size",
        "simulation": "convex-mirror reflection, 65% over synthetic iris, JPEG q85, attacker upsamples 4x (attacker-favourable)",
        "scenes": [m["id"] for m in scenes],
        "table": table,
        "rows": rows,
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(table, indent=1))
    print("threshold:", out["iris_readable_px"], "px")


if __name__ == "__main__":
    main()
