import math

import h3
import numpy as np

from traceless.geo import ANALYSIS_RES, Distribution, gazetteer, haversine_km
from traceless.schemas import Hypothesis


def test_haversine_known_distance():
    # Paris -> London ~ 344 km
    d = haversine_km(48.8566, 2.3522, 51.5074, -0.1278)
    assert 340 < d < 348


def test_haversine_vectorized():
    d = haversine_km(0.0, 0.0, np.array([0.0, 0.0]), np.array([0.0, 1.0]))
    assert d[0] == 0 and abs(d[1] - 111.2) < 0.5


def test_single_atom_credible_area_is_one_cell():
    d = Distribution.from_atoms([48.85], [2.35], [1.0])
    c = h3.latlng_to_cell(48.85, 2.35, ANALYSIS_RES)
    assert math.isclose(d.credible_area_km2(0.9), h3.cell_area(c, unit="km^2"))


def test_credible_area_grows_with_spread():
    tight = Distribution.from_hypotheses([Hypothesis(lat=40, lon=-3, probability=1, radius_km=5)])
    wide = Distribution.from_hypotheses([Hypothesis(lat=40, lon=-3, probability=1, radius_km=500)])
    assert wide.credible_area_km2() > 50 * tight.credible_area_km2()


def test_credible_area_is_90_percent_mass():
    d = Distribution.from_atoms([0, 50], [0, 50], [0.5, 0.5])
    assert d.credible_area_km2(0.9) > 1.5 * d.credible_area_km2(0.4)


def test_display_fits_budget():
    d = Distribution.from_hypotheses([Hypothesis(lat=10, lon=10, probability=1, radius_km=3000)])
    res, cells = d.display(max_cells=500)
    assert len(cells) <= 500 and res <= ANALYSIS_RES


def test_region_label_privacy():
    g = gazetteer()
    coarse = g.region_label(48.8584, 2.2945)
    fine = g.region_label(48.8584, 2.2945, precise=True)
    assert "France" in coarse and "Paris" not in coarse
    assert fine.startswith("Paris")
