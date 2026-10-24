"""Render the README hero image + GIF from a recorded take (real run data).

Uses headless Chrome against the running server's deep links
(/?take=<name>&step=<step>&frame=<n>). Every frame shows numbers from that
take's recorded run. Usage (server must be running):
    python scripts/make_hero.py --take <fixture_id> [--port 8000]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def chrome() -> str:
    for c in CHROME_CANDIDATES:
        if os.path.exists(c):
            return c
    raise SystemExit("Chrome/Edge not found")


def shot(url: str, out: Path, budget_ms: int, profile: str) -> Image.Image:
    # Own profile dir + own process: never touches the user's browser.
    p = subprocess.run(
        [chrome(), "--headless=new", f"--user-data-dir={profile}", "--use-angle=swiftshader",
         "--enable-unsafe-swiftshader", "--hide-scrollbars", "--window-size=1920,1080",
         f"--virtual-time-budget={budget_ms}", f"--screenshot={out}", url],
        capture_output=True, timeout=120,
    )
    if not out.exists():
        raise RuntimeError(f"screenshot failed for {url}: {p.stderr[-300:]}")
    return Image.open(out).convert("RGB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--take", required=True)
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    base = f"http://localhost:{args.port}/?take={args.take}"
    st = json.loads(urllib.request.urlopen(f"http://localhost:{args.port}/api/takes/{args.take}").read())
    n_frames = len((st.get("collapse") or {}).get("frames") or [])
    DOCS.mkdir(exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="hero_"))
    profile = str(tmp / "profile")
    plan = [("zero", None, 3000, 1600)]
    plan += [("attack", k, 4000, 900 if k < n_frames - 1 else 2200) for k in range(n_frames)]
    plan += [("clues", None, 5000, 2600), ("erase", None, 6000, 2400), ("reattack", None, 5000, 2600), ("safe", None, 5000, 3200)]
    frames, durations = [], []
    try:
        for i, (step, k, budget, dur) in enumerate(plan):
            url = f"{base}&step={step}" + (f"&frame={k}" if k is not None else "")
            img = shot(url, tmp / f"{i:02d}.png", budget, profile)
            frames.append(img)
            durations.append(dur)
            print("frame", i, step, k)
        frames[-1].save(DOCS / "hero.png")
        small = [f.resize((960, 540), Image.LANCZOS).quantize(colors=200, method=Image.Quantize.MEDIANCUT) for f in frames]
        small[0].save(DOCS / "hero.gif", save_all=True, append_images=small[1:], duration=durations, loop=0, optimize=True)
        # a 2-up still: the attack (collapsed) next to the safe card
        attack = frames[n_frames]  # last attack frame
        two = Image.new("RGB", (1920, 540))
        two.paste(attack.resize((960, 540), Image.LANCZOS), (0, 0))
        two.paste(frames[-1].resize((960, 540), Image.LANCZOS), (960, 0))
        two.save(DOCS / "hero.png")
        print("wrote docs/hero.png, docs/hero.gif")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
