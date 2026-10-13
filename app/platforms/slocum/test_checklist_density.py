"""Checklist density range: reporting floor excludes sub-floor samples only."""

from __future__ import annotations

import pandas as pd

from app.platforms.slocum.checklist_autofill import (
    DENSITY_REPORTING_FLOOR_KG_M3,
    compute_density_range,
)


def test_density_range_empty():
    result = compute_density_range(pd.Series(dtype=float))
    assert result["min"] is None
    assert result["max"] is None
    assert result["range"] is None
    assert result["over_threshold"] is False
    assert result["floor_applied"] is False
    assert result["display"] == "N/A"


def test_density_range_realistic_unchanged():
    # All samples above the floor → report the true lowest value (not the floor).
    series = pd.Series([1024.5, 1026.0, 1027.2])
    result = compute_density_range(series)
    assert result["min"] == 1024.5
    assert result["max"] == 1027.2
    assert abs(result["range"] - (1027.2 - 1024.5)) < 1e-9
    assert result["floor_applied"] is False
    assert result["over_threshold"] is False
    assert result["min"] > DENSITY_REPORTING_FLOOR_KG_M3


def test_density_range_ignores_sub_floor_outliers():
    # Surface noise below the floor is ignored; reported min is lowest retained sample.
    series = pd.Series([980.0, 1025.0, 1026.5])
    result = compute_density_range(series)
    assert result["min"] == 1025.0
    assert result["max"] == 1026.5
    assert abs(result["range"] - (1026.5 - 1025.0)) < 1e-9
    assert result["floor_applied"] is True
    # Source series is untouched (presentation filter only).
    assert float(series.min()) == 980.0


def test_density_range_all_below_floor():
    series = pd.Series([990.0, 995.0, 1000.0])
    result = compute_density_range(series)
    assert result["min"] is None
    assert result["max"] is None
    assert result["range"] is None
    assert result["floor_applied"] is True
    assert result["over_threshold"] is False
    assert result["display"] == "N/A"


def test_density_range_exactly_at_floor_is_retained():
    series = pd.Series([1005.0, 1020.0])
    result = compute_density_range(series)
    assert result["min"] == DENSITY_REPORTING_FLOOR_KG_M3
    assert result["max"] == 1020.0
    assert result["floor_applied"] is False
