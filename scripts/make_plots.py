"""README plots, drawn only from measured results files (nothing hand-entered).

  bench/results/latest.json      -> docs/plots/bench_accuracy.png
  bench/results/per_image.jsonl  -> docs/plots/bench_scatter.png
  bench/results/cloak.json       -> docs/plots/cloak.png
  backend/traceless/data/iris_threshold.json -> docs/plots/iris.png
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "bench" / "results"
OUT = ROOT / "docs" / "plots"
BEFORE, AFTER, INK, MUTE, BG = "#ff3b5c", "#2ee6a6", "#e8edf7", "#8a95ab", "#0a0e18"


def style(ax, title):
    ax.set_facecolor(BG)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color("#2b3858")
    ax.tick_params(colors=MUTE)
    ax.title.set_color(INK)
    ax.xaxis.label.set_color(MUTE)
    ax.yaxis.label.set_color(MUTE)
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold", color=INK)
    ax.grid(axis="y", color="#1c2333", linewidth=0.8)


def fig(w=9, h=4.2):
    f, ax = plt.subplots(figsize=(w, h), dpi=150)
    f.patch.set_facecolor(BG)
    return f, ax


def bench_accuracy():
    d = json.loads((RES / "latest.json").read_text(encoding="utf-8"))
    sub = d["subsets"][0]
    th = [str(t) for t in d["thresholds_km"]]
    names = {"1": "street\n≤1 km", "25": "city\n≤25 km", "200": "region\n≤200 km", "750": "country\n≤750 km", "2500": "continent\n≤2500 km"}
    f, ax = fig()
    x = np.arange(len(th))
    w = 0.2
    for i, (aid, lab) in enumerate([("geoclip", "GeoCLIP"), ("geoclip-adaptive", "GeoCLIP adaptive")]):
        a = sub["attackers"][aid]
        b = [a["before"]["acc"][t] * 100 for t in th]
        af = [a["after"]["acc"][t] * 100 for t in th]
        off = (i - 0.5) * 2 * w
        ax.bar(x + off - w / 2, b, w, color=BEFORE, alpha=1 if i == 0 else 0.55, label=f"{lab} · before")
        ax.bar(x + off + w / 2, af, w, color=AFTER, alpha=1 if i == 0 else 0.55, label=f"{lab} · after")
    ax.set_xticks(x, [names[t] for t in th])
    ax.set_ylabel("% of photos placed within")
    style(ax, f"Im2GPS3k, {sub['n']} random photos: placement accuracy before vs after TRACELESS")
    ax.legend(frameon=False, labelcolor=INK, fontsize=8, ncol=2)
    f.tight_layout()
    f.savefig(OUT / "bench_accuracy.png", facecolor=BG)


def bench_scatter():
    recs = [json.loads(l) for l in (RES / "per_image.jsonl").read_text(encoding="utf-8").splitlines()]
    pts = [(r["before"]["geoclip"]["d"], r["after"].get("geoclip", {}).get("d"))
           for r in recs if r.get("ok") and r.get("subset") == "random" and not r["already_safe"]]
    pts = [(b, a) for b, a in pts if b is not None and a is not None]
    b = np.maximum([p[0] for p in pts], 0.01)
    a = np.maximum([p[1] for p in pts], 0.01)
    f, ax = fig(6.2, 5.2)
    lim = (0.01, 20000)
    ax.plot(lim, lim, color="#2b3858", lw=1)
    ax.axvline(25, color=MUTE, lw=0.8, ls=":")
    ax.axhline(25, color=MUTE, lw=0.8, ls=":")
    moved = a > b
    ax.scatter(b[moved], a[moved], s=16, color=AFTER, label=f"moved further away ({moved.sum()})")
    ax.scatter(b[~moved], a[~moved], s=16, color=BEFORE, label=f"not moved ({(~moved).sum()})")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(lim)
    ax.set_ylim(lim)
    ax.set_xlabel("GeoCLIP error before (km)")
    ax.set_ylabel("GeoCLIP error after (km)")
    style(ax, f"Every defended photo ({len(pts)}): error before → after")
    ax.grid(color="#1c2333", linewidth=0.6)
    ax.legend(frameon=False, labelcolor=INK, fontsize=8, loc="lower right")
    f.tight_layout()
    f.savefig(OUT / "bench_scatter.png", facecolor=BG)


def cloak():
    d = json.loads((RES / "cloak.json").read_text(encoding="utf-8"))
    rows = [r for r in d["geoclip"] if r["eps"] == "2/255"]
    tr = d.get("transfer", [])
    f, ax = fig(9, 4.4)
    ids = [r["id"].split("-")[0] for r in rows]
    x = np.arange(len(rows))
    w = 0.27
    ax.bar(x - w, [max(r["geoclip_before_km"], 0.01) for r in rows], w, color=BEFORE, label="GeoCLIP, clean photo")
    ax.bar(x, [max(r["geoclip_after_km"], 0.01) for r in rows], w, color=AFTER, label="GeoCLIP, CLOAK 2/255 (white-box)")
    ax.bar(x + w, [max(r["adaptive_after_km"], 0.01) for r in rows], w, color="#ffb020", label="same model, unattacked crops")
    ax.set_yscale("log")
    ax.set_xticks(x, ids, rotation=30, ha="right")
    ax.set_ylabel("top-1 error (km, log)")
    t = ""
    if tr:
        o, c = tr[0], tr[1]
        t = f" · street matcher on Madrid: {o['street_inliers']} → {c['street_inliers']} matches, still {o['street_km'] * 1000:.0f} m"
    style(ax, "CLOAK: invisible noise fools the model it targets, not the others" + "")
    ax.text(0, -0.32, "Transfer to other model families" + t, transform=ax.transAxes, color=MUTE, fontsize=8)
    ax.legend(frameon=False, labelcolor=INK, fontsize=8)
    f.tight_layout()
    f.savefig(OUT / "cloak.png", facecolor=BG)


def iris():
    d = json.loads((ROOT / "backend" / "traceless" / "data" / "iris_threshold.json").read_text(encoding="utf-8"))
    t = d["table"]
    f, ax = fig(7, 3.8)
    ax.plot([r["iris_px"] for r in t], [r["readable_rate"] * 100 for r in t], color=BEFORE, marker="o", label="readable (GeoCLIP or OCR)")
    ax.plot([r["iris_px"] for r in t], [r["ocr_rate"] * 100 for r in t], color=MUTE, marker="o", label="OCR reads a word")
    ax.axvline(d["iris_readable_px"], color=AFTER, ls="--", lw=1)
    ax.text(d["iris_readable_px"] * 1.05, 5, f"threshold {d['iris_readable_px']} px", color=AFTER, fontsize=9)
    ax.set_xscale("log")
    ax.set_xlabel("iris diameter in the photo (px)")
    ax.set_ylabel("% of scenes recovered")
    style(ax, "When can a reflection in an eye be read?")
    ax.legend(frameon=False, labelcolor=INK, fontsize=8)
    f.tight_layout()
    f.savefig(OUT / "iris.png", facecolor=BG)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for fn in (bench_accuracy, bench_scatter, cloak, iris):
        fn()
        print("ok", fn.__name__)
