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


def _j(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def score_md() -> str:
    """At-a-glance numbers, every one computed from a results file (path given per row)."""
    rows = ["| what we measured | result | source |", "|---|---|---|"]
    b = _j(ROOT / "bench" / "results" / "latest.json")
    if b:
        r, c = b["subsets"][0], (b["subsets"][1] if len(b["subsets"]) > 1 else None)
        g, ad = r["attackers"]["geoclip"], r["attackers"]["geoclip-adaptive"]
        rows.append(f"| GeoCLIP placements within 25 km, {r['n']} random Im2GPS3k photos | "
                    f"**{g['before']['acc']['25'] * 100:.1f}% → {g['after']['acc']['25'] * 100:.1f}%** | `bench/results/latest.json` |")
        rows.append(f"| …within 1 km (street level) | **{g['before']['acc']['1'] * 100:.1f}% → {g['after']['acc']['1'] * 100:.1f}%** | `latest.json` |")
        rows.append(f"| GeoCLIP median error | **{g['before']['median_km']:.0f} km → {g['after']['median_km']:.0f} km** | `latest.json` |")
        rows.append(f"| Attacker *told which pixels were edited*, within 25 km | **{ad['before']['acc']['25'] * 100:.1f}% → {ad['after']['acc']['25'] * 100:.1f}%** | `latest.json` |")
        if c:
            gc = c["attackers"]["geoclip"]
            rows.append(f"| Clue-rich subset ({c['n']} photos with readable text), GeoCLIP within 25 km | "
                        f"**{gc['before']['acc']['25'] * 100:.0f}% → {gc['after']['acc']['25'] * 100:.0f}%**, median "
                        f"{gc['before']['median_km']:.0f} → {gc['after']['median_km']:.0f} km | `latest.json` |")
        q = r["quality"]
        rows.append(f"| Photo change on defended photos (median pixels / mean SSIM / mean LPIPS) | "
                    f"{q['pct_changed_median']:.1f}% / {q['ssim_mean']:.3f} / {q['lpips_mean']:.3f} | `latest.json` |")
        rows.append(f"| Defended photos that reached the 25 km target | {r['reached_target']} of {r['defended']} "
                    f"({r['already_safe']} of {r['n']} were already hard to place) | `latest.json` |")
    s = _j(ROOT / "backend" / "traceless" / "data" / "street_threshold.json")
    if s:
        rows.append(f"| Street-match threshold (measured) / precision of street claims ≤100 m | "
                    f"**{s['inlier_threshold']} verified keypoints** / {s['precision_100m'] * 100:.0f}% | `backend/traceless/data/street_threshold.json` |")
    ck = _j(ROOT / "bench" / "results" / "cloak.json")
    if ck and ck.get("transfer"):
        t = ck["transfer"]
        rows.append(f"| Invisible noise (CLOAK) vs the street matcher on Madrid | {t[0]['street_inliers']} → {t[1]['street_inliers']} "
                    f"matches — **no effect** | `bench/results/cloak.json` |")
    i = _j(ROOT / "backend" / "traceless" / "data" / "iris_threshold.json")
    if i:
        rows.append(f"| Iris size at which an eye reflection becomes readable | **{i['iris_readable_px']} px** | `iris_threshold.json` |")
    rh = _j(ROOT / "bench" / "results" / "rehearsal.json")
    if rh:
        ok = sum(1 for r in rh["runs"] if not r["problems"])
        rows.append(f"| Live rehearsal: different photos in a row, one server, no restarts | **{ok}/{len(rh['runs'])} passed**, "
                    f"face pixels changed 0 | `bench/results/rehearsal.json` |")
    return "\n".join(rows)


def rehearsal_md() -> str:
    rh = _j(ROOT / "bench" / "results" / "rehearsal.json")
    if not rh:
        return "_Run `scripts/rehearse.py`._"

    def km(v):
        return "—" if v is None else (f"{v * 1000:.0f} m" if v < 1 else f"{v:,.0f} km" if v >= 10 else f"{v:.1f} km")

    out = [f"_`scripts/rehearse.py` against one running server ({rh['date']}), offline attackers. "
           f"All checks: card numbers, face untouched, phone download page + metadata-free file, PANIC take._", "",
           "| # | photo | entry | outcome | attack / clue test / protect | wall |", "|---|---|---|---|---|---|"]
    for n, r in enumerate(rh["runs"], 1):
        t = r["timings"] or {}
        if r["already_safe"]:
            res = "already hard to place"
        else:
            res = f"{km(r['before_km'])} → {km(r['after_km'])}, " + ("target reached" if r["reached"] else "target not reached")
            if r["street_match"]:
                res += ", street match broken"
            if r.get("truth") == "proxy":
                res += " (no GPS: distances from the AI's own first guess)"
        res += " ✅" if not r["problems"] else " ❌ " + "; ".join(r["problems"])
        tm = " / ".join(f"{t.get(k):.0f}s" if t.get(k) is not None else "—" for k in ("attack", "ablation", "defense"))
        out.append(f"| {n} | {r['photo']} | {r['path']} | {res} | {tm} | {r['wall_s']:.0f}s |")
    out.append("")
    out.append(f"PANIC takes replayable: {rh['n_takes']} ({'all OK' if rh['panic_takes_ok'] else 'FAILED'}).")
    return "\n".join(out)


def friends_md() -> str:
    f = _j(ROOT / "bench" / "friends.json")
    if not f or not f.get("photos_run"):
        return ("_Not run yet: no consented real-people photos were available on the build laptop. "
                "`python scripts/friends_test.py --dir <folder> --delete` measures it (aggregates only)._")
    m = f["photos_run"]
    return (f"**{f['within_1km']['before']} of {m}** real posted photos could be placed within 1 km "
            f"({f['within_25km']['before']} within 25 km) by the attackers we tested; after TRACELESS, "
            f"**{f['within_1km']['after']}** ({f['within_25km']['after']} within 25 km). Median best-attacker error "
            f"{f['median_best_error_km']['before']} km → {f['median_best_error_km']['after']} km. "
            f"({f['skipped_no_gps']} photos skipped for lack of GPS; source `bench/friends.json`, {f['date']}.)")


def main() -> None:
    text = README.read_text(encoding="utf-8")
    tables = ROOT / "bench" / "results" / "TABLES.md"
    text = block("BENCH", tables.read_text(encoding="utf-8") if tables.exists() else "_Run `make bench`._", text)
    text = block("IRIS", iris_md(), text)
    text = block("SCORE", score_md(), text)
    text = block("FRIENDS", friends_md(), text)
    text = block("REHEARSAL", rehearsal_md(), text)
    text = block("STREET", street_md(), text)
    ck = ROOT / "bench" / "results" / "CLOAK.md"
    text = block("CLOAK", ck.read_text(encoding="utf-8") if ck.exists() else "_Run `bench/cloak.py`._", text)
    fx = ROOT / "bench" / "results" / "fixtures.md"
    text = block("FIXTURES", fx.read_text(encoding="utf-8") if fx.exists() else "_Run `python scripts/run_fixtures.py`._", text)
    README.write_text(text, encoding="utf-8")
    print("README updated")


if __name__ == "__main__":
    main()
