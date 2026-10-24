"""Fetch every model weight TRACELESS needs into models/weights/ (idempotent).

Disk-frugal by design: for CLIP ViT-L/14 (GeoCLIP's backbone) we read the
safetensors header with an HTTP range request and download only the vision
tower + projection (~1.2 GB fp32 -> stored as ~0.6 GB fp16), never the text
tower. Run:  backend/.venv/Scripts/python scripts/fetch_models.py
"""

from __future__ import annotations

import io
import json
import struct
import sys
import time
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = ROOT / "models" / "weights"
UA = {"User-Agent": "traceless-setup/0.1"}

CLIP_URL = "https://huggingface.co/openai/clip-vit-large-patch14/resolve/main/model.safetensors"
CLIP_OUT = WEIGHTS / "clip-vit-l14-vision-fp16.safetensors"

LAMA_URL = "https://github.com/enesmsahin/simple-lama-inpainting/releases/download/v0.1.0/big-lama.pt"
LAMA_OUT = WEIGHTS / "big-lama.pt"

YUNET_URL = "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"
YUNET_OUT = WEIGHTS / "face_detection_yunet_2023mar.onnx"

GEONAMES_URL = "https://download.geonames.org/export/dump/cities5000.zip"
GEONAMES_OUT = ROOT / "models" / "weights" / "cities5000.txt"
GEONAMES_EXTRA = {
    "countryInfo.txt": "https://download.geonames.org/export/dump/countryInfo.txt",
    "admin1CodesASCII.txt": "https://download.geonames.org/export/dump/admin1CodesASCII.txt",
}


def _get_range(client: httpx.Client, url: str, start: int, end: int) -> bytes:
    for attempt in range(5):
        try:
            r = client.get(url, headers={**UA, "Range": f"bytes={start}-{end}"})
            r.raise_for_status()
            if len(r.content) != end - start + 1:
                raise IOError(f"short read {len(r.content)} != {end - start + 1}")
            return r.content
        except Exception as e:  # network hiccup: retry with backoff
            print(f"  range retry {attempt + 1}: {e}")
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"failed range {start}-{end}")


def fetch_clip_vision() -> None:
    if CLIP_OUT.exists():
        print(f"ok  {CLIP_OUT.name} already present")
        return
    import numpy as np
    import torch
    from safetensors.torch import save_file

    with httpx.Client(follow_redirects=True, timeout=120) as c:
        n = struct.unpack("<Q", _get_range(c, CLIP_URL, 0, 7))[0]
        header = json.loads(_get_range(c, CLIP_URL, 8, 8 + n - 1))
        base = 8 + n
        keys = sorted(
            (
                k
                for k in header
                if k.startswith(("vision_model.", "visual_projection."))
                and header[k]["dtype"] == "F32"  # skip int64 position_ids buffers
            ),
            key=lambda k: header[k]["data_offsets"][0],
        )
        total = sum(header[k]["data_offsets"][1] - header[k]["data_offsets"][0] for k in keys)
        print(f"get CLIP vision tower: {len(keys)} tensors, {total / 1e9:.2f} GB fp32")
        # Coalesce contiguous tensors into ~64 MB range requests.
        out: dict[str, torch.Tensor] = {}
        i, done = 0, 0
        while i < len(keys):
            j = i
            s = header[keys[i]]["data_offsets"][0]
            e = header[keys[i]]["data_offsets"][1]
            while (
                j + 1 < len(keys)
                and header[keys[j + 1]]["data_offsets"][0] == e
                and e - s < 64_000_000
            ):
                j += 1
                e = header[keys[j]]["data_offsets"][1]
            blob = _get_range(c, CLIP_URL, base + s, base + e - 1)
            for k in keys[i : j + 1]:
                meta = header[k]
                a, b = meta["data_offsets"]
                assert meta["dtype"] == "F32", meta["dtype"]
                arr = np.frombuffer(blob[a - s : b - s], dtype=np.float32).reshape(meta["shape"])
                out[k] = torch.from_numpy(arr.copy()).to(torch.float16)
            done += e - s
            print(f"  {done / total:6.1%}", end="\r")
            i = j + 1
    WEIGHTS.mkdir(parents=True, exist_ok=True)
    save_file(out, str(CLIP_OUT))
    print(f"\nok  {CLIP_OUT.name} ({CLIP_OUT.stat().st_size / 1e6:.0f} MB)")


def fetch_file(url: str, out: Path) -> None:
    if out.exists():
        print(f"ok  {out.name} already present")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=300, headers=UA) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.rename(out)
    print(f"ok  {out.name} ({out.stat().st_size / 1e6:.0f} MB)")


def fetch_geonames() -> None:
    for name, url in GEONAMES_EXTRA.items():
        fetch_file(url, WEIGHTS / name)
    if GEONAMES_OUT.exists():
        print(f"ok  {GEONAMES_OUT.name} already present")
        return
    r = httpx.get(GEONAMES_URL, follow_redirects=True, timeout=300, headers=UA)
    r.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        GEONAMES_OUT.write_bytes(z.read("cities5000.txt"))
    print(f"ok  {GEONAMES_OUT.name} ({GEONAMES_OUT.stat().st_size / 1e6:.0f} MB)")


DEPTH_REPO = "https://huggingface.co/depth-anything/Depth-Anything-V2-Small-hf/resolve/main/"
DEPTH_DIR = WEIGHTS / "depth-anything-v2-small"


def fetch_depth() -> None:
    """Plain HTTP (huggingface_hub's client hung on this network)."""
    for f in ("config.json", "preprocessor_config.json", "model.safetensors"):
        fetch_file(DEPTH_REPO + f, DEPTH_DIR / f)


def fetch_torch_hub() -> None:
    """Street matcher (EigenPlaces, SuperPoint, LightGlue) + LPIPS SqueezeNet, into
    models/weights/torch so they load with Wi-Fi off."""
    sys.path.insert(0, str(ROOT / "backend"))
    import traceless  # noqa: F401  (sets TORCH_HOME)
    from traceless.attackers.street import StreetModels
    from traceless.metrics import _lpips

    StreetModels.get()
    _lpips()
    print("ok  street matcher + LPIPS checkpoints")


if __name__ == "__main__":
    which = set(sys.argv[1:]) or {"clip", "lama", "geonames", "yunet", "hub", "depth"}
    if "depth" in which:
        fetch_depth()
    if "hub" in which:
        fetch_torch_hub()
    if "yunet" in which:
        fetch_file(YUNET_URL, YUNET_OUT)
    if "geonames" in which:
        fetch_geonames()
    if "lama" in which:
        fetch_file(LAMA_URL, LAMA_OUT)
    if "clip" in which:
        fetch_clip_vision()
