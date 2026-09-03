"""Tests for DMON ASC thruster surface-burst filter and subsurface stats."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from app.platforms.slocum.dmon_asc_thruster import (
    MIN_SAMPLE_DWELL,
    analyze_thruster_in_interval,
    enrich_dmon_asc_with_thruster,
    format_thruster_since_prev_detail,
)


def _ts(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 9, 1, hour, minute, second, tzinfo=timezone.utc)


def _dash_rows(rows: list[tuple[datetime, float | None, float | None, float | None]]) -> pd.DataFrame:
    """Build a dashboard frame: (Timestamp, MDepth, MThrusterPower, CThrusterOn)."""
    return pd.DataFrame(
        [
            {
                "Timestamp": ts,
                "MDepth": depth,
                "MThrusterPower": power,
                "CThrusterOn": cmd,
            }
            for ts, depth, power, cmd in rows
        ]
    )


def test_surface_only_thruster_is_no():
    start, end = _ts(10), _ts(12)
    df = _dash_rows(
        [
            (_ts(10, 30), 1.0, None, None),  # depth sample
            (_ts(10, 30, 5), None, 3.0, None),  # thruster near surface
        ]
    )
    stats = analyze_thruster_in_interval(df, start, end)
    assert stats.thruster_since_prev is False
    assert stats.thruster_on_minutes_gt3m is None


def test_deep_only_thruster_is_yes_with_floor_minutes():
    start, end = _ts(10), _ts(12)
    df = _dash_rows(
        [
            (_ts(10, 30), 15.0, None, None),
            (_ts(10, 30, 5), None, 2.5, None),
        ]
    )
    stats = analyze_thruster_in_interval(df, start, end)
    assert stats.thruster_since_prev is True
    assert stats.thruster_on_minutes_gt3m == round(MIN_SAMPLE_DWELL.total_seconds() / 60.0, 2)
    assert stats.thruster_depth_min_m == 15.0
    assert stats.thruster_depth_max_m == 15.0


def test_mixed_surface_and_deep_counts_deep_only():
    start, end = _ts(10), _ts(14)
    df = _dash_rows(
        [
            (_ts(10, 30), 1.2, None, None),
            (_ts(10, 30, 5), None, 3.0, None),  # surface burst
            (_ts(11, 0), 18.0, None, None),
            (_ts(11, 0, 10), None, 4.0, None),  # deep
            (_ts(11, 0, 40), None, 4.0, None),  # deep +30s same cluster
        ]
    )
    stats = analyze_thruster_in_interval(df, start, end)
    assert stats.thruster_since_prev is True
    assert stats.thruster_on_minutes_gt3m == round(30.0 / 60.0, 2)
    assert stats.thruster_depth_min_m == 18.0
    assert stats.thruster_depth_max_m == 18.0


def test_thruster_on_without_nearby_depth_is_no():
    start, end = _ts(10), _ts(12)
    # Depth sample more than 60s away from thruster-on.
    df = _dash_rows(
        [
            (_ts(10, 0), 20.0, None, None),
            (_ts(10, 30), None, 5.0, None),
        ]
    )
    stats = analyze_thruster_in_interval(df, start, end)
    assert stats.thruster_since_prev is False


def test_empty_interval_is_none():
    start, end = _ts(10), _ts(12)
    df = _dash_rows([(_ts(8), 10.0, 1.0, None)])
    stats = analyze_thruster_in_interval(df, start, end)
    assert stats.thruster_since_prev is None


def test_cluster_two_deep_samples_thirty_seconds():
    start, end = _ts(10), _ts(12)
    t0 = _ts(10, 45)
    t1 = t0 + timedelta(seconds=30)
    df = _dash_rows(
        [
            (t0, 12.0, 1.0, None),
            (t1, 14.0, 1.0, None),
        ]
    )
    stats = analyze_thruster_in_interval(df, start, end)
    assert stats.thruster_since_prev is True
    assert stats.thruster_on_minutes_gt3m == round(30.0 / 60.0, 2)
    assert stats.thruster_depth_min_m == 12.0
    assert stats.thruster_depth_max_m == 14.0


def test_enrich_and_format_detail():
    start = _ts(10)
    mid = _ts(11)
    end = _ts(12)
    df = _dash_rows(
        [
            (start + timedelta(minutes=10), 20.0, None, None),
            (start + timedelta(minutes=10, seconds=5), None, 2.0, None),
        ]
    )
    payload = {
        "files": [
            {"fileName": "a.asc", "dateTimeModified": start.strftime("%Y-%m-%dT%H:%M:%SZ")},
            {
                "fileName": "b.asc",
                "dateTimeModified": mid.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "gap_after_prev_hours": 1.0,
            },
            {
                "fileName": "c.asc",
                "dateTimeModified": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "gap_after_prev_hours": 1.0,
            },
        ]
    }
    out = enrich_dmon_asc_with_thruster(payload, df)
    first, second, third = out["files"]
    assert first["thruster_since_prev"] is None
    assert format_thruster_since_prev_detail(first, has_previous=False) == "—"
    assert second["thruster_since_prev"] is True
    label = format_thruster_since_prev_detail(second, has_previous=True)
    assert label.startswith("Yes · ")
    assert "min" in label and "m" in label
    assert third["thruster_since_prev"] is None
    assert format_thruster_since_prev_detail(third, has_previous=True) == "No data"
