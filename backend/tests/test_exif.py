import io

import piexif
from PIL import Image
from traceless.exif import has_any_metadata, load_clean, read_exif, save_clean_jpeg


def _dms(v):
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    s = round(((v - d) * 60 - m) * 60 * 100)
    return ((d, 1), (m, 1), (s, 100))


def _jpeg_with_gps(lat=40.4168, lon=-3.7038) -> bytes:
    exif = {
        "0th": {piexif.ImageIFD.Make: b"Apple", piexif.ImageIFD.Model: b"iPhone 15", piexif.ImageIFD.Orientation: 6},
        "GPS": {
            piexif.GPSIFD.GPSLatitudeRef: b"N" if lat >= 0 else b"S",
            piexif.GPSIFD.GPSLatitude: _dms(lat),
            piexif.GPSIFD.GPSLongitudeRef: b"E" if lon >= 0 else b"W",
            piexif.GPSIFD.GPSLongitude: _dms(lon),
        },
    }
    buf = io.BytesIO()
    Image.new("RGB", (64, 32), (200, 10, 10)).save(buf, "JPEG", exif=piexif.dump(exif))
    return buf.getvalue()


def test_reads_gps_and_camera():
    rep = read_exif(_jpeg_with_gps())
    assert rep.has_gps
    assert abs(rep.gps.lat - 40.4168) < 1e-3 and abs(rep.gps.lon + 3.7038) < 1e-3
    assert rep.camera == "Apple iPhone 15"
    assert any(f.startswith("GPS") for f in rep.fields)


def test_clean_load_strips_everything_and_applies_orientation(tmp_path):
    img = load_clean(_jpeg_with_gps())
    assert img.size == (32, 64)  # orientation 6 = rotated 90 degrees
    p = tmp_path / "x.jpg"
    save_clean_jpeg(img, p)
    assert not has_any_metadata(p)
    assert not read_exif(p.read_bytes()).has_gps


def test_no_gps():
    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, "PNG")
    rep = read_exif(buf.getvalue())
    assert not rep.has_gps and rep.gps is None
