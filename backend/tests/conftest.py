import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


def pytest_configure(config):
    config.addinivalue_line("markers", "golden: full pipeline on fixture photos (slow, loads models)")


def pytest_collection_modifyitems(config, items):
    if "golden" in (config.getoption("-m") or ""):
        return
    skip = pytest.mark.skip(reason="golden tests run with: pytest -m golden")
    for it in items:
        if "golden" in it.keywords:
            it.add_marker(skip)
