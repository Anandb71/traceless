"""GeoCLIP location encoder, vendored from the `geoclip` package (MIT,
Vicente Vivanco Cepeda et al.) so we can load its weights without importing
the package (whose __init__ pulls in `transformers`, ~45 s cold on Windows).
Weights are read from the installed geoclip package directory.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import torch
from torch import nn

A1, A2, A3, A4, SF = 1.340264, -0.081106, 0.000893, 0.003796, 66.50336


def geoclip_dir() -> Path:
    spec = importlib.util.find_spec("geoclip")
    if spec is None or not spec.submodule_search_locations:
        raise RuntimeError("geoclip package not installed (uv sync in backend/)")
    return Path(list(spec.submodule_search_locations)[0]) / "model"


def equal_earth_projection(L: torch.Tensor) -> torch.Tensor:
    lat, lon = torch.deg2rad(L[:, 0]), torch.deg2rad(L[:, 1])
    theta = torch.asin((np.sqrt(3.0) / 2) * torch.sin(lat))
    den = 3 * (9 * A4 * theta**8 + 7 * A3 * theta**6 + 3 * A2 * theta**2 + A1)
    x = (2 * np.sqrt(3.0) * lon * torch.cos(theta)) / den
    y = A4 * theta**9 + A3 * theta**7 + A2 * theta**3 + A1 * theta
    return (torch.stack((x, y), dim=1) * SF) / 180


class _GaussianEncoding(nn.Module):
    def __init__(self):
        super().__init__()
        self.b = nn.Parameter(torch.zeros(256, 2), requires_grad=False)

    def forward(self, v):
        vp = 2 * np.pi * v @ self.b.T
        return torch.cat((torch.cos(vp), torch.sin(vp)), dim=-1)


class _Capsule(nn.Module):
    def __init__(self):
        super().__init__()
        self.capsule = nn.Sequential(
            _GaussianEncoding(),
            nn.Linear(512, 1024), nn.ReLU(),
            nn.Linear(1024, 1024), nn.ReLU(),
            nn.Linear(1024, 1024), nn.ReLU(),
        )
        self.head = nn.Sequential(nn.Linear(1024, 512))

    def forward(self, x):
        return self.head(self.capsule(x))


class LocationEncoder(nn.Module):
    def __init__(self, n: int = 3):
        super().__init__()
        self.n = n
        for i in range(n):
            self.add_module(f"LocEnc{i}", _Capsule())

    def forward(self, loc):
        loc = equal_earth_projection(loc)
        out = torch.zeros(loc.shape[0], 512)
        for i in range(self.n):
            out += self._modules[f"LocEnc{i}"](loc)
        return out
