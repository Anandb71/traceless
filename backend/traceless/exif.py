"""Clue zero: location data in the file. Read it, show it, strip it.

Truth rule 1: EXIF/GPS is never attack input. `load_clean` returns only
pixels (orientation applied, every metadata block dropped); attackers only
ever receive images produced by it. GPS, if present, becomes the answer key.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import ExifTags, Image, ImageOps

from .schemas import ExifReport, LatLon

try:  # iPhone HEIC via AirDrop/USB
    from pillow_heif import register_heif_opener

    register_heif_opener()
except Exception:  # pragma: no cover - optional
    pass

MAX_SIDE = 2048  # working resolution cap (keeps CPU budget predictable)

_GPS_IFD = 0x8825
_EXIF_IFD = 0x8769


def _ratio(v) -> float:
    try:
        return float(v)
    except TypeError:
        num, den = v
        return float(num) / float(den) if den else 0.0


def _dms(vals, ref) -> float | None:
    try:
        d, m, s = (_ratio(x) for x in vals)
    except Exception:
        return None
    out = d + m / 60.0 + s / 3600.0
    if isinstance(ref, bytes):
        ref = ref.decode(errors="ignore")
    if str(ref).strip().upper() in ("S", "W"):
        out = -out
    return out


def read_exif(data: bytes) -> ExifReport:
    img = Image.open(io.BytesIO(data))
    exif = img.getexif()
    fields: list[str] = []
    for tag in exif:
        fields.append(ExifTags.TAGS.get(tag, f"0x{tag:04x}"))
    gps = None
    try:
        g = exif.get_ifd(_GPS_IFD)
    except Exception:
        g = {}
    if g:
        fields += [str(ExifTags.GPSTAGS.get(t, f"GPS_{t}")) for t in g]
        lat = _dms(g.get(2), g.get(1)) if 2 in g else None
        lon = _dms(g.get(4), g.get(3)) if 4 in g else None
        if lat is not None and lon is not None and not (lat == 0 and lon == 0):
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                gps = LatLon(lat=lat, lon=lon)
    sub = {}
    try:
        sub = exif.get_ifd(_EXIF_IFD)
    except Exception:
        pass
    make = str(exif.get(0x010F, "") or "").strip("\x00 ")
    model = str(exif.get(0x0110, "") or "").strip("\x00 ")
    camera = " ".join(x for x in (make, model) if x) or None
    taken = sub.get(0x9003) or exif.get(0x0132)
    for k in ("xmp", "icc_profile", "photoshop"):
        if img.info.get(k):
            fields.append(k.upper())
    return ExifReport(
        has_gps=gps is not None,
        gps=gps,
        camera=camera,
        taken_at=str(taken).strip("\x00 ") if taken else None,
        fields=sorted(set(fields)),
    )


def load_clean(data: bytes, max_side: int = MAX_SIDE) -> Image.Image:
    """Pixels only: orientation applied, metadata gone, RGB, capped size."""
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    # Re-materialize into a fresh image object: no .info, no exif, no icc.
    clean = Image.new("RGB", img.size)
    clean.paste(img)
    return clean


def save_clean_jpeg(img: Image.Image, path: Path, quality: int = 92) -> None:
    """Write a JPEG with no EXIF/XMP/ICC blocks at all."""
    img.save(path, "JPEG", quality=quality, optimize=True, exif=b"")


def has_any_metadata(path: Path) -> bool:
    img = Image.open(path)
    return bool(img.getexif()) or any(img.info.get(k) for k in ("exif", "xmp", "icc_profile"))
