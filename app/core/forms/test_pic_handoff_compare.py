"""Tests for bounded PIC handoff compare value builder."""

from __future__ import annotations

import asyncio
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

    load_calls: list[tuple[str, int | None]] = []

    async def fake_load(report_type, mission_id, *, current_user, source_preference, hours_back):
        load_calls.append((report_type, hours_back))
        return pd.DataFrame(), None, None

    mock_service = MagicMock()
    mock_service.load = AsyncMock(side_effect=fake_load)

    with patch(
        "app.core.forms.pic_handoff_compare.get_data_service", return_value=mock_service
    ), patch(
        "app.core.forms.pic_handoff_compare._mission_title", return_value="Test Mission"
    ):
        values = asyncio.run(build_pic_handoff_compare_current_values("m227", session, user))

    assert values["glider_id_val"] == "m227"
    assert values["vessel_standoff_m_val"] == "500"
    assert "sensor_ctd_status" in values
    assert "sensor_weather_status" in values

    hours_by_type = dict(load_calls)
    assert hours_by_type["ais"] == AIS_COMPARE_HOURS
    assert hours_by_type["errors"] == ERRORS_COMPARE_HOURS
    assert hours_by_type["power"] == POWER_COMPARE_HOURS
    assert hours_by_type["ctd"] == SENSOR_COMPARE_HOURS
    assert hours_by_type["weather"] == SENSOR_COMPARE_HOURS
