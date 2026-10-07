"""Tests for lifetime metric overrides and odometer sorting in summaries."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from app.core.data import summaries


def test_incremental_odometer_sorts_before_sum():
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    df = pd.DataFrame(
        {
            "Timestamp": [base + timedelta(hours=2), base, base + timedelta(hours=1)],
            "DistanceSinceLastFixM": [1852.0, 1852.0, 1852.0],
        }
    )
    nm = summaries._incremental_odometer_nm(df)
    assert nm == 3.0


def test_navigation_uses_lifetime_override():
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    df = pd.DataFrame(
        {
            "Timestamp": [base, base + timedelta(hours=1)],
            "Latitude": [44.0, 44.01],
            "Longitude": [-63.0, -63.0],
            "GliderHeading": [10.0, 20.0],
            "SpeedOverGround": [1.0, 1.5],
            "DistanceSinceLastFixM": [1852.0, 1852.0],
            "OceanCurrentSpeed": [0.1, 0.2],
            "OceanCurrentDirection": [1.0, 2.0],
        }
    )
    info = summaries.get_navigation_status(df, lifetime_total_distance_nm=99.5)
    assert info["values"]["TotalDistanceTraveledMissionNM"] == 99.5


def test_power_uses_lifetime_observed_max():
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    df = pd.DataFrame(
        {
            "Timestamp": [base, base + timedelta(hours=1)],
            "BatteryWattHours": [100.0, 110.0],
            "SolarInputWatts": [50.0, 60.0],
            "PowerDrawWatts": [10.0, 12.0],
            "NetPowerWatts": [40.0, 48.0],
            "battery_charging_power_w": [5.0, 6.0],
            "output_port_power_w": [1.0, 2.0],
        }
    )
    info = summaries.get_power_status(
        df,
        theoretical_max_wh=2940.0,
        lifetime_observed_max_battery_wh=500.0,
    )
    assert info["values"]["RealisticMaxBatteryWh"] == 500.0
    # Percentage uses effective max = lifetime observed max
    assert info["values"]["BatteryPercentage"] is not None
