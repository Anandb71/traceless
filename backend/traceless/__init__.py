"""TRACELESS backend."""

import os
from pathlib import Path

# Every torch-hub checkpoint (LPIPS SqueezeNet, SuperPoint, LightGlue, EigenPlaces)
# lives under models/weights/torch so the demo runs with Wi-Fi off.
os.environ.setdefault("TORCH_HOME", str(Path(__file__).resolve().parents[2] / "models" / "weights" / "torch"))
