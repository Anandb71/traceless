"""Geography: distances, H3 probability distributions, credible areas, regions.

Credible area (BRIEF: "area of the smallest hexagon set holding 90% of the
probability") is always computed on the SAME H3 resolution (ANALYSIS_RES) so
that before/after numbers are comparable. Every attacker's output is reduced
to weighted "atoms" (lat, lon, mass); atoms land in their analysis cell; the
90% set is the cells sorted by mass, accumulated until 90%.

Approximation (labeled): resolution 6 cells average ~36 km^2, so the smallest
measurable area is one cell. VLM hypotheses carry a stated radius; we sample
them into atoms (Gaussian, sigma = radius / 2), which slightly under-counts
area for continent-scale guesses.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import h3
import numpy as np

from .schemas import HexCell, Hypothesis

ANALYSIS_RES = 6
EARTH_R_KM = 6371.0088
WEIGHTS_DIR = Path(__file__).resolve().parents[2] / "models" / "weights"


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance; works on scalars or numpy arrays."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(np.asarray(lon2) - np.asarray(lon1))
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    d = 2 * EARTH_R_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
    return float(d) if np.ndim(d) == 0 else d


# --------------------------------------------------------------------------- #
# Distributions
# --------------------------------------------------------------------------- #


@dataclass
class Distribution:
    """Probability mass on ANALYSIS_RES cells (dict cell -> mass, sums to ~1)."""

    cells: dict[str, float]

    @classmethod
    def from_atoms(cls, lats, lons, masses, res: int = ANALYSIS_RES) -> "Distribution":
        masses = np.asarray(masses, dtype=np.float64)
        total = masses.sum()
        if total <= 0:
            return cls({})
        masses = masses / total
        cells: dict[str, float] = {}
        for la, lo, m in zip(np.asarray(lats), np.asarray(lons), masses):
            if m <= 0:
                continue
            c = h3.latlng_to_cell(float(la), float(lo), res)
            cells[c] = cells.get(c, 0.0) + float(m)
        return cls(cells)

    @classmethod
    def from_hypotheses(
        cls,
        hyps: list[Hypothesis],
        default_radius_km: float = 25.0,
        samples: int = 60_000,
        seed: int = 0,
    ) -> "Distribution":
        """Spread each hypothesis as a Gaussian of sigma = radius/2 (sampled)."""
        hyps = [h for h in hyps if h.probability > 0]
        if not hyps:
            return cls({})
        rng = np.random.default_rng(seed)
        w = np.array([h.probability for h in hyps], dtype=np.float64)
        w /= w.sum()
        counts = rng.multinomial(samples, w)
        lats, lons = [], []
        for h, n in zip(hyps, counts):
            if n == 0:
                continue
            r = max(1.0, h.radius_km or default_radius_km)
            sigma = r / 2.0
            # Sample in a local tangent plane: km offsets -> degrees.
            dy = rng.normal(0, sigma, n)
            dx = rng.normal(0, sigma, n)
            la = np.clip(h.lat + dy / 111.32, -89.9, 89.9)
            lo = h.lon + dx / (111.32 * max(0.05, math.cos(math.radians(h.lat))))
            lo = (lo + 180.0) % 360.0 - 180.0
            lats.append(la)
            lons.append(lo)
        lats_a, lons_a = np.concatenate(lats), np.concatenate(lons)
        return cls.from_atoms(lats_a, lons_a, np.ones(len(lats_a)))

    def mixture(self, other: "Distribution", w_self: float = 0.5) -> "Distribution":
        cells = {c: w_self * p for c, p in self.cells.items()}
        for c, p in other.cells.items():
            cells[c] = cells.get(c, 0.0) + (1 - w_self) * p
        return Distribution(cells)

    def credible_area_km2(self, level: float = 0.9) -> float | None:
        if not self.cells:
            return None
        items = sorted(self.cells.items(), key=lambda kv: kv[1], reverse=True)
        acc, area = 0.0, 0.0
        for c, p in items:
            acc += p
            area += _cell_area(c)
            if acc >= level - 1e-9:
                break
        return area

    def mode(self) -> tuple[float, float] | None:
        if not self.cells:
            return None
        c = max(self.cells.items(), key=lambda kv: kv[1])[0]
        return h3.cell_to_latlng(c)

    def display(self, max_cells: int = 2500, level: float = 0.97) -> tuple[int, list[HexCell]]:
        """Coarsen for the globe: pick the finest res where the credible set fits."""
        if not self.cells:
            return ANALYSIS_RES, []
        for res in range(ANALYSIS_RES, 1, -1):
            agg: dict[str, float] = {}
            for c, p in self.cells.items():
                pc = h3.cell_to_parent(c, res) if res < ANALYSIS_RES else c
                agg[pc] = agg.get(pc, 0.0) + p
            items = sorted(agg.items(), key=lambda kv: kv[1], reverse=True)
            acc, keep = 0.0, []
            for c, p in items:
                keep.append(HexCell(h3=c, p=round(p, 6)))
                acc += p
                if acc >= level:
                    break
            if len(keep) <= max_cells:
                return res, keep
        return res, keep[:max_cells]


@lru_cache(maxsize=200_000)
def _cell_area(c: str) -> float:
    return h3.cell_area(c, unit="km^2")


# --------------------------------------------------------------------------- #
# Gazetteer (GeoNames cities15000, CC-BY 4.0)
# --------------------------------------------------------------------------- #


@dataclass
class Place:
    name: str
    lat: float
    lon: float
    country_code: str
    country: str
    admin1: str
    population: int


class Gazetteer:
    def __init__(self, weights_dir: Path = WEIGHTS_DIR):
        self.countries: dict[str, dict] = {}
        for line in (weights_dir / "countryInfo.txt").read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or not line.strip():
                continue
            f = line.split("\t")
            self.countries[f[0]] = {
                "iso": f[0],
                "name": f[4],
                "capital": f[5],
                "continent": f[8],
                "tld": f[9],
                "currency": f[10],
                "phone": f[12],
                "languages": f[15].split(",") if len(f) > 15 else [],
            }
        self.admin1: dict[str, str] = {}
        for line in (weights_dir / "admin1CodesASCII.txt").read_text(encoding="utf-8").splitlines():
            f = line.split("\t")
            if len(f) >= 2:
                self.admin1[f[0]] = f[1]
        names, lats, lons, ccs, a1s, pops, alts = [], [], [], [], [], [], []
        with open(weights_dir / "cities15000.txt", encoding="utf-8") as fh:
            for line in fh:
                f = line.rstrip("\n").split("\t")
                names.append(f[1])
                alts.append(f[3])
                lats.append(float(f[4]))
                lons.append(float(f[5]))
                ccs.append(f[8])
                a1s.append(f"{f[8]}.{f[10]}")
                pops.append(int(f[14] or 0))
        self.names = names
        self.alternates = alts
        self.lat = np.array(lats)
        self.lon = np.array(lons)
        self.cc = ccs
        self.a1 = a1s
        self.pop = np.array(pops)
        self._xyz = _to_xyz(self.lat, self.lon)

    def place(self, i: int) -> Place:
        cc = self.cc[i]
        return Place(
            name=self.names[i],
            lat=float(self.lat[i]),
            lon=float(self.lon[i]),
            country_code=cc,
            country=self.countries.get(cc, {}).get("name", cc),
            admin1=self.admin1.get(self.a1[i], ""),
            population=int(self.pop[i]),
        )

    def nearest(self, lat: float, lon: float) -> tuple[Place, float]:
        q = _to_xyz(np.array([lat]), np.array([lon]))[0]
        i = int(np.argmax(self._xyz @ q))
        return self.place(i), haversine_km(lat, lon, self.lat[i], self.lon[i])

    def region_label(self, lat: float, lon: float, precise: bool = False) -> str:
        """Privacy mode: admin region + country. precise=True adds the city."""
        p, d = self.nearest(lat, lon)
        if d > 300:  # open ocean / wilderness
            return f"{abs(lat):.0f}°{'N' if lat >= 0 else 'S'}, {abs(lon):.0f}°{'E' if lon >= 0 else 'W'}"
        parts = [p.name] if precise else []
        if p.admin1 and p.admin1 != p.name:
            parts.append(p.admin1)
        parts.append(p.country)
        return ", ".join(parts)

    def search(self, query: str, limit: int = 8) -> list[Place]:
        """Owner's private 'where was this taken?' lookup (offline)."""
        q = query.strip().lower()
        if len(q) < 2:
            return []
        hits = []
        for i, n in enumerate(self.names):
            nl = n.lower()
            if nl.startswith(q):
                hits.append((0, -self.pop[i], i))
            elif q in nl:
                hits.append((1, -self.pop[i], i))
        hits.sort()
        return [self.place(i) for _, _, i in hits[:limit]]


def _to_xyz(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    la, lo = np.radians(lat), np.radians(lon)
    return np.stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)], axis=1)


_GAZ: Gazetteer | None = None


def gazetteer() -> Gazetteer:
    global _GAZ
    if _GAZ is None:
        _GAZ = Gazetteer()
    return _GAZ


def fmt_area(km2: float | None) -> str:
    if km2 is None:
        return "—"
    if km2 >= 1e6:
        return f"{km2 / 1e6:.1f} million km²"
    if km2 >= 1e4:
        return f"{km2 / 1e3:,.0f}k km²"
    return f"{km2:,.0f} km²"
