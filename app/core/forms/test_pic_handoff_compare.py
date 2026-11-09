"""Tests for bounded PIC handoff compare value builder."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
from sqlmodel import Session, SQLModel, create_engine

from app.core.forms.pic_handoff_compare import (
    AIS_COMPARE_HOURS,
    ERRORS_COMPARE_HOURS,
    POWER_COMPARE_HOURS,
    SENSOR_COMPARE_HOURS,
    _boats_in_area_display,
    _recent_errors_display,
    build_pic_handoff_compare_current_values,
)
from app.core.models.database import MissionOverview


def test_boats_in_area_display_empty():
    assert _boats_in_area_display(None) == "No recent AIS contacts."
    assert _boats_in_area_display(pd.DataFrame()) == "No recent AIS contacts."


def test_recent_errors_display_empty():
    assert _recent_errors_display(None) == "No recent errors."
    assert _recent_errors_display(pd.DataFrame()) == "No recent errors."


def test_build_compare_uses_bounded_hours_back():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine, tables=[MissionOverview.__table__])
    session = Session(engine)
    session.add(
        MissionOverview(
            mission_id="m227",
            enabled_sensor_cards='["ctd", "weather"]',
            pic_handoff_optional_sensors="[]",
            battery_apu_count=2,
            vessel_standoff_m=500,
        )
    )
    session.commit()

    user = MagicMock(username="pilot", id=1)

    load_calls: list[tuple[str, int | None, str | None, bool]] = []

    async def fake_load(
        report_type,
        mission_id,
        *,
        current_user=None,
        source_preference=None,
        hours_back=None,
        force_refresh=False,
        **kwargs,
    ):
        load_calls.append((report_type, hours_back, source_preference, force_refresh))
        return pd.DataFrame(), "Synced: /tmp/m227", None

    mock_service = MagicMock()
    mock_service.load = AsyncMock(side_effect=fake_load)

    with patch(
        "app.core.forms.pic_handoff_autofill.get_data_service", return_value=mock_service
    ), patch(
        "app.core.forms.pic_handoff_compare._mission_title", return_value="Test Mission"
    ), patch(
        "app.core.forms.pic_handoff_compare._resolve_lifetime_observed_max_battery_wh",
        new_callable=AsyncMock,
        return_value=None,
    ):
        values = asyncio.run(build_pic_handoff_compare_current_values("m227", session, user))

    assert values["glider_id_val"] == "m227"
    assert values["vessel_standoff_m_val"] == "500"
    assert "sensor_ctd_status" in values
    assert "sensor_weather_status" in values

    hours_by_type = {rt: hours for rt, hours, _pref, _force in load_calls}
    assert hours_by_type["ais"] == AIS_COMPARE_HOURS
    assert hours_by_type["errors"] == ERRORS_COMPARE_HOURS
    assert hours_by_type["power"] == POWER_COMPARE_HOURS
    assert hours_by_type["ctd"] == SENSOR_COMPARE_HOURS
    assert hours_by_type["weather"] == SENSOR_COMPARE_HOURS
    assert all(pref == "synced" for _rt, _h, pref, _f in load_calls)
    assert all(force is False for _rt, _h, _p, force in load_calls)


def test_build_compare_total_battery_uses_lifetime_observed_max():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine, tables=[MissionOverview.__table__])
    session = Session(engine)
    session.add(
        MissionOverview(
            mission_id="m227",
            enabled_sensor_cards="[]",
            pic_handoff_optional_sensors="[]",
            battery_apu_count=3,
            vessel_standoff_m=500,
        )
    )
    session.commit()

    user = MagicMock(username="pilot", id=1)
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    power_df = pd.DataFrame(
        {
            "Timestamp": [base, base + timedelta(hours=1)],
            "BatteryWattHours": [2398.0, 2241.0],
            "SolarInputWatts": [50.0, 60.0],
            "PowerDrawWatts": [10.0, 12.0],
            "NetPowerWatts": [40.0, 48.0],
            "battery_charging_power_w": [5.0, 6.0],
            "output_port_power_w": [1.0, 2.0],
        }
    )

    async def fake_load(report_type, mission_id, **kwargs):
        if report_type == "power":
            return power_df, "Synced: /tmp/m227", None
        return pd.DataFrame(), "Synced: /tmp/m227", None

    mock_service = MagicMock()
    mock_service.load = AsyncMock(side_effect=fake_load)

    with patch(
        "app.core.forms.pic_handoff_autofill.get_data_service", return_value=mock_service
    ), patch(
        "app.core.forms.pic_handoff_compare._mission_title", return_value="Test Mission"
    ), patch(
        "app.core.forms.pic_handoff_compare._resolve_lifetime_observed_max_battery_wh",
        new_callable=AsyncMock,
        return_value=3656.0,
    ):
        values = asyncio.run(build_pic_handoff_compare_current_values("m227", session, user))

    assert "Observed max: 3656 Wh" in values["total_battery_val"]
    assert "2398" not in values["total_battery_val"]
