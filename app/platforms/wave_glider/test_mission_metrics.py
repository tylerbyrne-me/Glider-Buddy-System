"""Tests for Wave Glider persisted lifetime mission metrics."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from app.platforms.wave_glider import mission_metrics as mm


def _telemetry_frame(*, unordered: bool = False, with_odometer: bool = True) -> pd.DataFrame:
    base = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    rows = [
        {"Timestamp": base, "Latitude": 44.0, "Longitude": -63.0, "DistanceSinceLastFixM": 1852.0},
        {
            "Timestamp": base + timedelta(hours=1),
            "Latitude": 44.01,
            "Longitude": -63.0,
            "DistanceSinceLastFixM": 1852.0,
        },
        {
            "Timestamp": base + timedelta(hours=2),
            "Latitude": 44.02,
            "Longitude": -63.0,
            "DistanceSinceLastFixM": 1852.0,
        },
    ]
    if unordered:
        rows = [rows[2], rows[0], rows[1]]
    df = pd.DataFrame(rows)
    if not with_odometer:
        df = df.drop(columns=["DistanceSinceLastFixM"])
    return df


def test_compute_total_distance_odometer_sorts_and_dedupes():
    df = _telemetry_frame(unordered=True)
    # Duplicate middle timestamp with a corrected distance.
    dup = df.iloc[1].copy()
    dup["DistanceSinceLastFixM"] = 9999.0
    df = pd.concat([df, pd.DataFrame([dup])], ignore_index=True)

    with patch(
        "app.platforms.wave_glider.mission_metrics.preprocess_telemetry_df",
        side_effect=lambda x: x,
    ):
        nm, method = mm.compute_total_distance_nm(df)

    assert method == "odometer"
    # 3 unique timestamps × 1852 m = 3 NM (duplicate overwritten by keep=last → 9999)
    # After sort+dedupe keep last for the duplicated timestamp: rows become
    # t0:1852, t1:9999 (dup), t2:1852 → sum = 1852+9999+1852
    assert nm is not None
    assert abs(nm - ((1852 + 9999 + 1852) / 1852.0)) < 1e-6


def test_compute_total_distance_great_circle_fallback():
    df = _telemetry_frame(with_odometer=False)
    with patch(
        "app.platforms.wave_glider.mission_metrics.preprocess_telemetry_df",
        side_effect=lambda x: x,
    ):
        nm, method = mm.compute_total_distance_nm(df)
    assert method == "great_circle"
    assert nm is not None and nm > 0


def test_compute_observed_max_battery_wh_ignores_invalid():
    df = pd.DataFrame(
        {
            "Timestamp": [
                datetime(2026, 6, 1, tzinfo=timezone.utc),
                datetime(2026, 6, 2, tzinfo=timezone.utc),
                datetime(2026, 6, 3, tzinfo=timezone.utc),
            ],
            "BatteryWattHours": [100.0, -5.0, 250.5],
        }
    )
    with patch(
        "app.platforms.wave_glider.mission_metrics.preprocess_power_df",
        side_effect=lambda x: x,
    ):
        assert mm.compute_observed_max_battery_wh(df) == pytest.approx(250.5)


def test_refresh_skips_unchanged_mtime():
    row = MagicMock()
    row.total_distance_nm = 12.0
    row.distance_method = "odometer"
    row.telemetry_source_mtime = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    row.observed_max_battery_wh = 200.0
    row.power_source_mtime = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    row.calculation_version = mm.CALCULATION_VERSION

    session = MagicMock()
    session.get.return_value = row

    same_mtime = row.telemetry_source_mtime
    df = _telemetry_frame()

    async def _run():
        with patch(
            "app.platforms.wave_glider.mission_metrics._load_synced_report",
            new=AsyncMock(return_value=(df, same_mtime, "/data/m1")),
        ), patch(
            "app.platforms.wave_glider.mission_metrics.compute_total_distance_nm"
        ) as compute_dist:
            await mm.refresh_mission_metrics_for_reports(
                "m1", ["telemetry"], session=session, force=False
            )
            compute_dist.assert_not_called()

    asyncio.run(_run())


def test_refresh_force_on_version_bump_recomputes():
    row = MagicMock()
    row.total_distance_nm = 1.0
    row.distance_method = "odometer"
    row.telemetry_source_mtime = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    row.observed_max_battery_wh = None
    row.power_source_mtime = None
    row.calculation_version = 0  # older than CALCULATION_VERSION
    row.telemetry_data_through_ts = None
    row.power_data_through_ts = None
    row.computed_at_utc = datetime(2026, 1, 1, tzinfo=timezone.utc)

    session = MagicMock()
    session.get.return_value = row

    df = _telemetry_frame()
    mtime = row.telemetry_source_mtime

    async def _run():
        with patch(
            "app.platforms.wave_glider.mission_metrics._load_synced_report",
            new=AsyncMock(return_value=(df, mtime, "/data/m1")),
        ), patch(
            "app.platforms.wave_glider.mission_metrics.preprocess_telemetry_df",
            side_effect=lambda x: x,
        ):
            await mm.refresh_mission_metrics_for_reports(
                "m1", ["telemetry"], session=session, force=False
            )

    asyncio.run(_run())
    assert row.calculation_version == mm.CALCULATION_VERSION
    assert row.total_distance_nm is not None
    session.commit.assert_called()


def test_independent_partial_power_update():
    row = MagicMock()
    row.total_distance_nm = 10.0
    row.distance_method = "odometer"
    row.telemetry_source_mtime = datetime(2026, 6, 1, tzinfo=timezone.utc)
    row.observed_max_battery_wh = None
    row.power_source_mtime = None
    row.calculation_version = mm.CALCULATION_VERSION
    row.power_data_through_ts = None
    row.computed_at_utc = datetime(2026, 1, 1, tzinfo=timezone.utc)

    session = MagicMock()
    session.get.return_value = row

    power_df = pd.DataFrame(
        {
            "Timestamp": [datetime(2026, 6, 2, tzinfo=timezone.utc)],
            "BatteryWattHours": [321.0],
        }
    )
    mtime = datetime(2026, 6, 2, tzinfo=timezone.utc)

    async def _run():
        with patch(
            "app.platforms.wave_glider.mission_metrics._load_synced_report",
            new=AsyncMock(return_value=(power_df, mtime, "/data/m1")),
        ), patch(
            "app.platforms.wave_glider.mission_metrics.preprocess_power_df",
            side_effect=lambda x: x,
        ):
            await mm.refresh_mission_metrics_for_reports(
                "m1", ["power"], session=session, force=False
            )

    asyncio.run(_run())
    assert row.observed_max_battery_wh == pytest.approx(321.0)
    assert row.total_distance_nm == 10.0  # untouched
