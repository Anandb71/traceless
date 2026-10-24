"""Re-attach GPS EXIF to SIM fixture photos so "clue zero" can be demoed.

Wikimedia's resized copies drop EXIF. Phone photos usually carry GPS, so for
SIM mode we write each fixture's Commons *camera-location* coordinates back
into its EXIF, plus an ImageDescription saying exactly that (no fake camera
make/model). The portrait and indoor fixtures are left without GPS to keep
the "no GPS in this file" path covered. Idempotent.
"""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

import piexif

ROOT = Path(__file__).resolve().parents[1]
SKIP = {"portrait", "indoor"}
NOTE = b"SIM fixture: GPS re-attached from Wikimedia Commons camera-location metadata"


def dms(v: float):
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    s = Fraction((v - d - m / 60) * 3600).limit_denominator(10000)
    return ((d, 1), (m, 1), (s.numerator, s.denominator))


def main() -> None:
    man = json.loads((ROOT / "fixtures" / "manifest.json").read_text(encoding="utf-8"))
    for m in man:
        p = ROOT / "fixtures" / m["file"]
        if m["category"] in SKIP:
            piexif.remove(str(p))
            print("no gps ", m["id"])
            continue
        exif = {
            "0th": {piexif.ImageIFD.ImageDescription: NOTE},
            "GPS": {
                piexif.GPSIFD.GPSVersionID: (2, 3, 0, 0),
                piexif.GPSIFD.GPSLatitudeRef: b"N" if m["lat"] >= 0 else b"S",
                piexif.GPSIFD.GPSLatitude: dms(m["lat"]),
                piexif.GPSIFD.GPSLongitudeRef: b"E" if m["lon"] >= 0 else b"W",
                piexif.GPSIFD.GPSLongitude: dms(m["lon"]),
            },
        }
        piexif.insert(piexif.dump(exif), str(p))
        print("gps    ", m["id"])


if __name__ == "__main__":
    main()
