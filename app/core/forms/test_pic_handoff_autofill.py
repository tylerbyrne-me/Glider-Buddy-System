"""Tests for PIC handoff template autofill (synced default + remote refresh)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
from sqlmodel import Session, SQLModel, create_engine

from app.core.forms.pic_handoff_autofill import (
    AIS_HOURS,
    ERRORS_HOURS,
    POWER_HOURS,
    SENSOR_HOURS,
    build_pic_handoff_autofilled_schema,
    load_pic_reports_parallel,
    power_status_values,
    total_battery_display,
)
from app.core.models.database import MissionOverview, UserInDB
from app.core.models.enums import UserRoleEnum


def _session_with_overview():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        engine, tables=[MissionOverview.__table__, UserInDB.__table__]
    )
    session = Session(engine)
    session.add(
        MissionOverview(
            mission_id="m227",
            enabled_sensor_cards='["ctd"]',
            pic_handoff_optional_sensors='["adcp"]',
            battery_apu_count=1,
            vessel_standoff_m=1500,
            sensor_sampling_rates='{"ctd": {"period_sec": 10, "samples_per_block": 10, "flush_time_sec": 100, "off_time_sec": 400}}',
        )
    )
    session.add(
        UserInDB(
            username="pilot1",
            hashed_password="x",
            role=UserRoleEnum.pilot,
            is_pic=True,
            is_mos=True,
            disabled=False,
        )
    )
    session.commit()
    return session


def test_load_pic_reports_synced_default_no_remote():
    load_calls = []

    async def fake_load(report_type, mission_id, **kwargs):
        load_calls.append(kwargs)
        return pd.DataFrame(), "Synced: /data/m227", None

    mock_service = MagicMock()
    mock_service.load = AsyncMock(side_effect=fake_load)
    user = MagicMock(username="pilot")

    with patch(
        "app.core.forms.pic_handoff_autofill.get_data_service", return_value=mock_service
    ):
        asyncio.run(
            load_pic_reports_parallel(
                "m227", user, ["power", "ais"], refresh_upstream=False
            )
        )

    assert len(load_calls) == 2
    assert all(c.get("source_preference") == "synced" for c in load_calls)
    assert all(c.get("force_refresh") is False for c in load_calls)


def test_load_pic_reports_refresh_uses_remote_force():
    load_calls = []

    async def fake_load(report_type, mission_id, **kwargs):
        load_calls.append(kwargs)
        return pd.DataFrame(), "Remote: /wgms", None

    mock_service = MagicMock()
    mock_service.load = AsyncMock(side_effect=fake_load)
    user = MagicMock(username="pilot")

    with patch(
        "app.core.forms.pic_handoff_autofill.get_data_service", return_value=mock_service
    ):
        asyncio.run(
            load_pic_reports_parallel(
                "m227", user, ["power"], refresh_upstream=True
            )
        )

    assert load_calls[0]["source_preference"] == "remote"
    assert load_calls[0]["force_refresh"] is True
    assert load_calls[0]["hours_back"] == POWER_HOURS


def _power_df_with_window_max(*, current_wh: float, window_max_wh: float) -> pd.DataFrame:
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    return pd.DataFrame(
        {
            "Timestamp": [base, base + timedelta(hours=1)],
            "BatteryWattHours": [window_max_wh, current_wh],
            "SolarInputWatts": [50.0, 60.0],
            "PowerDrawWatts": [10.0, 12.0],
            "NetPowerWatts": [40.0, 48.0],
            "battery_charging_power_w": [5.0, 6.0],
            "output_port_power_w": [1.0, 2.0],
        }
    )


def test_power_helpers_prefer_lifetime_observed_max():
    df = _power_df_with_window_max(current_wh=2241.0, window_max_wh=2398.0)
    theoretical = 3920.0
    lifetime = 3656.0

    display = total_battery_display(
        df,
        theoretical_max_wh=theoretical,
        lifetime_observed_max_battery_wh=lifetime,
    )
    assert "Observed max: 3656 Wh" in display
    assert "2398" not in display

    battery_wh, battery_pct, _th, realistic, effective, hint = power_status_values(
        df,
        theoretical_max_wh=theoretical,
        lifetime_observed_max_battery_wh=lifetime,
    )
    assert realistic == lifetime
    assert effective == lifetime
    assert battery_wh == 2241.0
    assert abs(float(battery_pct) - (2241.0 / lifetime * 100)) < 0.1
    assert "3656" in hint


def test_power_helpers_do_not_use_48h_peak_without_lifetime():
    df = _power_df_with_window_max(current_wh=2241.0, window_max_wh=2398.0)
    display = total_battery_display(
        df,
        theoretical_max_wh=3920.0,
        lifetime_observed_max_battery_wh=None,
        allow_frame_lifetime_fallback=False,
    )
    assert "Observed max" not in display
    assert "2398" not in display

    _wh, _pct, _th, realistic, effective, _hint = power_status_values(
        df,
        theoretical_max_wh=3920.0,
        lifetime_observed_max_battery_wh=None,
        allow_frame_lifetime_fallback=False,
    )
    assert realistic is None
    assert effective == 3920.0


def test_build_autofilled_schema_injects_fields_and_meta():
    session = _session_with_overview()
    user = MagicMock(username="pilot", id=1)

    async def fake_load(report_type, mission_id, **kwargs):
        return pd.DataFrame(), "Synced: /data/m227", None

    mock_service = MagicMock()
    mock_service.load = AsyncMock(side_effect=fake_load)

    with patch(
        "app.core.forms.pic_handoff_autofill.get_data_service", return_value=mock_service
    ), patch(
        "app.core.forms.pic_handoff_autofill.mission_title", return_value="Test Mission"
    ), patch(
        "app.core.forms.pic_handoff_autofill.resolve_lifetime_observed_max_battery_wh",
        new_callable=AsyncMock,
        return_value=None,
    ):
        schema = asyncio.run(
            build_pic_handoff_autofilled_schema(
                "m227", session, user, refresh_upstream=False
            )
        )

    assert schema["form_type"] == "pic_handoff_checklist"
    assert schema["autofill_meta"]["mode"] == "synced"
    assert schema["autofill_meta"]["hours"]["ais"] == AIS_HOURS
    assert schema["autofill_meta"]["hours"]["errors"] == ERRORS_HOURS
    assert schema["autofill_meta"]["hours"]["sensors"] == SENSOR_HOURS

    items_by_id = {
        item["id"]: item
        for section in schema["sections"]
        for item in section.get("items") or []
    }
    assert items_by_id["glider_id_val"]["value"] == "m227"
    assert items_by_id["mission_title_val"]["value"] == "Test Mission"
    assert items_by_id["vessel_standoff_m_val"]["value"] == "1500"
    assert "sensor_ctd_status" in items_by_id
    assert "sensor_ctd_sampling_val" in items_by_id
    assert "sensor_adcp_status" in items_by_id
    assert "pilot1" in (items_by_id["current_pic_val"].get("options") or [])


def test_build_autofilled_schema_uses_lifetime_observed_max():
    session = _session_with_overview()
    user = MagicMock(username="pilot", id=1)
    # battery_apu_count=1 → theoretical 1960 Wh in overview fixture; override via power cols.
    power_df = _power_df_with_window_max(current_wh=2241.0, window_max_wh=2398.0)

    async def fake_load(report_type, mission_id, **kwargs):
        if report_type == "power":
            return power_df, "Synced: /data/m227", None
        return pd.DataFrame(), "Synced: /data/m227", None

    mock_service = MagicMock()
    mock_service.load = AsyncMock(side_effect=fake_load)

    with patch(
        "app.core.forms.pic_handoff_autofill.get_data_service", return_value=mock_service
    ), patch(
        "app.core.forms.pic_handoff_autofill.mission_title", return_value="Test Mission"
    ), patch(
        "app.core.forms.pic_handoff_autofill.resolve_lifetime_observed_max_battery_wh",
        new_callable=AsyncMock,
        return_value=3656.0,
    ):
        schema = asyncio.run(
            build_pic_handoff_autofilled_schema(
                "m227", session, user, refresh_upstream=False
            )
        )

    items_by_id = {
        item["id"]: item
        for section in schema["sections"]
        for item in section.get("items") or []
    }
    assert "Observed max: 3656 Wh" in items_by_id["total_battery_val"]["value"]
    assert "2398" not in items_by_id["total_battery_val"]["value"]
    pct = float(items_by_id["percent_battery_val"]["value"])
    assert abs(pct - (2241.0 / 3656.0 * 100)) < 0.1
    assert "3656" in (items_by_id["percent_battery_val"].get("hint") or "")
