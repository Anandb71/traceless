"""Download a street-level reference set around a point and index it (Attacker C).

    python scripts/build_street_index.py --lat 37.7793 --lon -122.4193 --radius-km 2 --name venue
        [--source mapillary|commons|auto] [--max 1500]

- mapillary: needs MAPILLARY_TOKEN (backend/.env). Images CC BY-SA 4.0; credited.
- commons:   geotagged Wikimedia Commons photos (camera location) — the
             no-token fallback. Only freely licensed files are kept.
- auto:      mapillary if a token is set, else commons.

Writes models/weights/street/<name>/{img/*.jpg, index.npz, meta.json} and
prints the image count + a coverage summary (and writes coverage.geojson).
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import math
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / "backend" / ".env")

UA = {"User-Agent": "TracelessHackathon/0.1 (anand@getarbor.dev)"}
COMMONS = "https://commons.wikimedia.org/w/api.php"
FREE = ("cc0", "cc-by", "cc by", "public domain", "pd", "cc-zero")


def km_to_deg(lat: float, km: float) -> tuple[float, float]:
    return km / 111.32, km / (111.32 * max(0.05, math.cos(math.radians(lat))))


def hav(a, b, c, d):
    p1, p2 = math.radians(a), math.radians(c)
    x = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(d - b) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(x))


# --------------------------------------------------------------------------- #
def from_mapillary(lat, lon, radius_km, limit, token) -> list[dict]:
    dlat, dlon = km_to_deg(lat, radius_km)
    out, seen = [], set()
    step = 0.004  # tile the bbox; Mapillary caps results per request
    la = lat - dlat
    while la < lat + dlat and len(out) < limit:
        lo = lon - dlon
        while lo < lon + dlon and len(out) < limit:
            bbox = f"{lo},{la},{min(lo + step, lon + dlon)},{min(la + step, lat + dlat)}"
            r = httpx.get("https://graph.mapillary.com/images", timeout=60, params={
                "access_token": token, "bbox": bbox, "limit": 200,
                "fields": "id,computed_geometry,geometry,compass_angle,computed_compass_angle,thumb_1024_url,creator,is_pano",
            })
            r.raise_for_status()
            for it in r.json().get("data", []):
                if it.get("is_pano") or it["id"] in seen or not it.get("thumb_1024_url"):
                    continue
                g = (it.get("computed_geometry") or it.get("geometry"))["coordinates"]
                if hav(lat, lon, g[1], g[0]) > radius_km:
                    continue
                seen.add(it["id"])
                out.append({
                    "id": f"mly{it['id']}", "lat": g[1], "lon": g[0],
                    "compass": it.get("computed_compass_angle") or it.get("compass_angle"),
                    "url": it["thumb_1024_url"],
                    "attribution": f"Mapillary / {(it.get('creator') or {}).get('username', 'contributor')} (CC BY-SA 4.0)",
                })
            lo += step
        la += step
    return out[:limit]


def from_commons(lat, lon, radius_km, limit) -> list[dict]:
    """Geosearch in rings (API max radius 10 km, 500 results per query)."""
    pts = [(lat, lon)]
    if radius_km > 0.6:
        for ring in (radius_km * 0.5, radius_km * 0.9):
            n = max(6, int(2 * math.pi * ring / 0.8))
            for k in range(n):
                a = 2 * math.pi * k / n
                dlat, dlon = km_to_deg(lat, ring)
                pts.append((lat + dlat * math.sin(a), lon + dlon * math.cos(a)))
    titles: dict[str, tuple[float, float]] = {}
    with httpx.Client(headers=UA, timeout=60) as c:
        for la, lo in pts:
            r = c.get(COMMONS, params={"action": "query", "list": "geosearch", "gscoord": f"{la}|{lo}",
                                       "gsradius": int(min(10000, max(500, radius_km * 1000 * 0.6))),
                                       "gslimit": 500, "gsnamespace": 6, "format": "json"})
            for g in r.json().get("query", {}).get("geosearch", []):
                if hav(lat, lon, g["lat"], g["lon"]) <= radius_km and g["title"].lower().endswith((".jpg", ".jpeg")):
                    titles[g["title"]] = (g["lat"], g["lon"])
            if len(titles) > limit * 2:
                break
        out = []
        names = list(titles)
        for i in range(0, len(names), 50):
            r = c.get(COMMONS, params={"action": "query", "titles": "|".join(names[i:i + 50]), "prop": "imageinfo",
                                       "iiprop": "url|extmetadata|size", "iiurlwidth": 1024, "format": "json"})
            for p in r.json().get("query", {}).get("pages", {}).values():
                ii = (p.get("imageinfo") or [{}])[0]
                meta = ii.get("extmetadata", {})
                lic = (meta.get("LicenseShortName", {}).get("value") or "").lower()
                if not any(f in lic for f in FREE) or not ii.get("thumburl"):
                    continue
                if ii.get("width", 0) < 800 or ii.get("width", 0) > 3 * ii.get("height", 1):  # skip tiny + panoramas
                    continue
                la, lo = titles[p["title"]]
                artist = meta.get("Artist", {}).get("value", "")
                import re

                artist = re.sub("<[^>]+>", "", artist).strip()[:60] or "Commons contributor"
                out.append({
                    "id": f"wc{p.get('pageid')}", "lat": la, "lon": lo, "compass": None, "url": ii["thumburl"],
                    "attribution": f"Wikimedia Commons / {artist} ({meta.get('LicenseShortName', {}).get('value', '')})",
                    "title": p["title"],
                })
            if len(out) >= limit:
                break
    return out[:limit]


# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--radius-km", type=float, default=2.0)
    ap.add_argument("--name", default="venue")
    ap.add_argument("--source", default="auto", choices=["auto", "mapillary", "commons"])
    ap.add_argument("--max", type=int, default=1500)
    ap.add_argument("--exclude-title", action="append", default=[], help="Commons titles to leave out (held-out queries)")
    args = ap.parse_args()

    token = os.environ.get("MAPILLARY_TOKEN")
    source = args.source if args.source != "auto" else ("mapillary" if token else "commons")
    t0 = time.time()
    if source == "mapillary":
        if not token:
            raise SystemExit("MAPILLARY_TOKEN not set (backend/.env)")
        items = from_mapillary(args.lat, args.lon, args.radius_km, args.max, token)
    else:
        items = from_commons(args.lat, args.lon, args.radius_km, args.max)
        # never index our own fixture photos: matching a photo against itself is not a street match
        man = json.loads((ROOT / "fixtures" / "manifest.json").read_text(encoding="utf-8"))
        own = {"File:" + m["commons_url"].rsplit("File:", 1)[-1] for m in man if "File:" in m.get("commons_url", "")}
        from urllib.parse import unquote

        own = {unquote(t).replace("_", " ") for t in own}
        items = [i for i in items if i.get("title") not in set(args.exclude_title) | own]
    print(f"{len(items)} {source} images listed in {time.time() - t0:.0f}s")

    root = ROOT / "models" / "weights" / "street" / args.name
    (root / "img").mkdir(parents=True, exist_ok=True)

    def fetch(it):
        p = root / "img" / f"{it['id']}.jpg"
        if not p.exists():
            for attempt in range(3):
                try:
                    r = httpx.get(it["url"], headers=UA, timeout=60, follow_redirects=True)
                    r.raise_for_status()
                    p.write_bytes(r.content)
                    break
                except Exception:
                    time.sleep(1 + attempt)
        it["file"] = p.name
        return it if p.exists() else None

    with cf.ThreadPoolExecutor(8) as ex:
        items = [i for i in ex.map(fetch, items) if i]
    print(f"{len(items)} images downloaded")

    from PIL import Image

    from traceless.attackers.street import StreetModels

    sm = StreetModels.get()
    descs, keep = [], []
    for it in items:
        try:
            descs.append(sm.describe([Image.open(root / "img" / it["file"])])[0])
            keep.append(it)
        except Exception as e:
            print("skip", it["id"], e)
    import numpy as np

    np.savez_compressed(root / "index.npz", desc=np.stack(descs).astype(np.float16))
    meta = {
        "source": source, "center": {"lat": args.lat, "lon": args.lon}, "radius_km": args.radius_km,
        "built": time.strftime("%Y-%m-%d %H:%M"), "count": len(keep),
        "images": [{k: it.get(k) for k in ("id", "lat", "lon", "compass", "file", "attribution", "title")} for it in keep],
    }
    (root / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    cov = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [it["lon"], it["lat"]]}, "properties": {"id": it["id"]}}
        for it in keep]}
    (root / "coverage.geojson").write_text(json.dumps(cov), encoding="utf-8")
    d = [hav(args.lat, args.lon, it["lat"], it["lon"]) for it in keep]
    print(f"indexed {len(keep)} images · source {source} · radius {args.radius_km} km · "
          f"median distance from center {sorted(d)[len(d) // 2]:.2f} km · {time.time() - t0:.0f}s total")


if __name__ == "__main__":
    main()
