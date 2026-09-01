"""
Lightweight live-value builder for PIC handoff "changes since submission" highlighting.

Avoids full ``get_form_template`` (which loads entire mission CSVs). Uses bounded
``hours_back`` windows and parallel loads — critical for long missions like m227.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlmodel import Session, or_, select

from app.core import models, utils
from app.core.data import summaries
from app.core.data.data_service import get_data_service
from app.core.pic_handoff_optional_sensors import PIC_HANDOFF_OPTIONAL_SENSOR_REGISTRY
from app.services.error_classification_service import classify_error_message

logger = logging.getLogger(__name__)

AIS_COMPARE_HOURS = 8
ERRORS_COMPARE_HOURS = 8
POWER_COMPARE_HOURS = 48
SENSOR_COMPARE_HOURS = 24

_SCIENCE_SENSORS = ["ctd", "weather", "waves", "vr2c", "fluorometer", "wg_vm4"]
_STATUS_FUNCTIONS = {
    "ctd": summaries.get_ctd_status,
    "weather": summaries.get_weather_status,
    "waves": summaries.get_wave_status,
    "vr2c": summaries.get_vr2c_status,
    "fluorometer": summaries.get_fluorometer_status,
    "wg_vm4": summaries.get_wg_vm4_status,
}


def _resolve_mission_overview(session: Session, mission_id: str) -> Optional[models.MissionOverview]:
    mission_overview = session.get(models.MissionOverview, mission_id)
    if mission_overview is None and "-" in mission_id:
        mission_overview = session.get(
            models.MissionOverview, utils.deployment_mission_code_from_mission_id(mission_id)
        )
    return mission_overview


def _parse_enabled_sensor_cards(mission_overview: Optional[models.MissionOverview]) -> List[str]:
    if not mission_overview or not mission_overview.enabled_sensor_cards:
        return []
    try:
        return json.loads(mission_overview.enabled_sensor_cards)
    except (json.JSONDecodeError, TypeError):
        return []


def _parse_optional_sensors(mission_overview: Optional[models.MissionOverview]) -> List[str]:
    if not mission_overview or not mission_overview.pic_handoff_optional_sensors:
        return []
    try:
        return json.loads(mission_overview.pic_handoff_optional_sensors)
    except (json.JSONDecodeError, TypeError):
        return []


def _mission_title(session: Session, mission_id: str) -> str:
    mission_base = utils.deployment_mission_code_from_mission_id(mission_id)
    st_deployment = session.exec(
        select(models.SensorTrackerDeployment).where(
            or_(
                models.SensorTrackerDeployment.mission_id == mission_id,
                models.SensorTrackerDeployment.mission_id == mission_base,
            )
        )
    ).first()
    return (st_deployment.title or "Mission Not Assigned") if st_deployment else "Mission Not Assigned"


def _boats_in_area_display(ais_df) -> str:
    vessels = summaries.get_ais_summary(ais_df, max_age_hours=AIS_COMPARE_HOURS) if ais_df is not None and not ais_df.empty else []
    if not vessels:
        return "No recent AIS contacts."
    lines = []
    for vessel in vessels:
        ts = vessel.get("LastSeenTimestamp")
        if ts is not None and hasattr(ts, "strftime"):
            time_str = ts.strftime("%Y-%m-%d %H:%M UTC")
        else:
            time_str = str(ts) if ts else "—"
        since = summaries.time_ago(ts)
        mmsi = vessel.get("MMSI", "—")
        lines.append(f"{time_str} | {since} | MMSI {mmsi}")
    return "\n".join(lines)


def _recent_errors_display(errors_df) -> str:
    recent_errors_raw = (
        summaries.get_recent_errors(errors_df, max_age_hours=ERRORS_COMPARE_HOURS)
        if errors_df is not None and not errors_df.empty
        else []
    )
    if not recent_errors_raw:
        return "No recent errors."
    lines = []
    for err in recent_errors_raw:
        ts = err.get("Timestamp")
        if ts is not None and hasattr(ts, "strftime"):
            time_str = ts.strftime("%Y-%m-%d %H:%M UTC")
        else:
            time_str = str(ts) if ts else "—"
        since = summaries.time_ago(ts) if ts else "—"
        category = "unknown"
        if err.get("ErrorMessage"):
            cat_val, _, _ = classify_error_message(err["ErrorMessage"])
            category = cat_val.value
        self_corr = err.get("SelfCorrected")
        sc_str = (
            "Yes"
            if self_corr in (True, "true", "True", "yes", 1)
            else "No"
            if self_corr is not None
            else "—"
        )
        lines.append(f"{time_str} | {since} | {category} | Self-corrected: {sc_str}")
    return "\n".join(lines)


def _total_battery_display(
    df_power,
    *,
    theoretical_max_wh: Optional[float],
) -> str:
    power_info = (
        summaries.get_power_status(df_power, None, theoretical_max_wh=theoretical_max_wh)
        if df_power is not None and not df_power.empty
        else {}
    )
    values = power_info.get("values", {})
    theoretical_wh = values.get("TheoreticalMaxBatteryWh")
    realistic_wh = values.get("RealisticMaxBatteryWh")
    if theoretical_wh is not None:
        display = f"Max (theoretical): {int(theoretical_wh)} Wh"
        if realistic_wh is not None:
            display += f". Observed max: {int(realistic_wh)} Wh"
        return display
    display = "2775 Wh"
    if realistic_wh is not None:
        display += f". Observed max: {int(realistic_wh)} Wh"
    return display


def _sensor_on_off_value(df_sensor, card: str) -> str:
    status_fn = _STATUS_FUNCTIONS.get(card)
    status = (
        status_fn(df_sensor, None)
        if status_fn and df_sensor is not None and not df_sensor.empty
        else {}
    )
    last_ts = None
    if df_sensor is not None and not df_sensor.empty and "Timestamp" in df_sensor.columns:
        last_ts = df_sensor["Timestamp"].max()
        if hasattr(last_ts, "to_pydatetime"):
            last_ts = last_ts.to_pydatetime()
        if last_ts is not None and (
            last_ts.tzinfo is None or last_ts.tzinfo.utcoffset(last_ts) is None
        ):
            last_ts = last_ts.replace(tzinfo=timezone.utc)
    now_utc = datetime.now(timezone.utc)
    default_on = (
        (now_utc - last_ts).total_seconds() < 3600 if last_ts is not None else False
    )
    return "On" if default_on else "Off"


async def _load_local_then_remote(
    data_service,
    report_type: str,
    mission_id: str,
    current_user: models.User,
    hours_back: int,
):
    df, _, _ = await data_service.load(
        report_type,
        mission_id,
        current_user=current_user,
        source_preference="local",
        hours_back=hours_back,
    )
    if df is None or df.empty:
        df, _, _ = await data_service.load(
            report_type,
            mission_id,
            current_user=current_user,
            source_preference="remote",
            hours_back=hours_back,
        )
    return df


async def build_pic_handoff_compare_current_values(
    mission_id: str,
    session: Session,
    current_user: models.User,
) -> Dict[str, str]:
    """
    Return comparable string values for PIC handoff change detection.

    Only loads data needed for ``PIC_HANDOFF_COMPARABLE_ITEM_IDS`` and sensor
    status rows, using short time windows instead of full mission history.
    """
    mission_overview = _resolve_mission_overview(session, mission_id)
    battery_apu = getattr(mission_overview, "battery_apu_count", None) if mission_overview else None
    theoretical_max_wh = summaries.theoretical_max_wh(battery_apu)

    data_service = get_data_service()
    enabled_cards = _parse_enabled_sensor_cards(mission_overview)
    optional_sensors = _parse_optional_sensors(mission_overview)

    sensor_cards = [card for card in _SCIENCE_SENSORS if card in enabled_cards]
    load_types = ["power", "ais", "errors", *sensor_cards]

    loaded: Dict[str, object] = {}

    async def _load_one(report_type: str):
        hours_back = POWER_COMPARE_HOURS
        if report_type == "ais":
            hours_back = AIS_COMPARE_HOURS
        elif report_type == "errors":
            hours_back = ERRORS_COMPARE_HOURS
        elif report_type in _SCIENCE_SENSORS:
            hours_back = SENSOR_COMPARE_HOURS
        try:
            return report_type, await _load_local_then_remote(
                data_service, report_type, mission_id, current_user, hours_back
            )
        except Exception as exc:
            logger.warning(
                "PIC compare load failed for %s (%s): %s", report_type, mission_id, exc
            )
            return report_type, None

    import asyncio

    results = await asyncio.gather(*[_load_one(rt) for rt in load_types])
    for report_type, df in results:
        loaded[report_type] = df

    standoff = getattr(mission_overview, "vessel_standoff_m", None) if mission_overview else None
    current_values: Dict[str, str] = {
        "glider_id_val": str(mission_id),
        "mission_title_val": _mission_title(session, mission_id),
        "total_battery_val": _total_battery_display(
            loaded.get("power"), theoretical_max_wh=theoretical_max_wh
        ),
        "boats_in_area_val": _boats_in_area_display(loaded.get("ais")),
        "vessel_standoff_m_val": str(standoff) if standoff is not None else "",
        "recent_errors_val": _recent_errors_display(loaded.get("errors")),
    }

    for card in sensor_cards:
        current_values[f"sensor_{card}_status"] = _sensor_on_off_value(loaded.get(card), card)

    for sensor_key in optional_sensors:
        if sensor_key not in PIC_HANDOFF_OPTIONAL_SENSOR_REGISTRY:
            continue
        item_id = f"sensor_{sensor_key}_status"
        if item_id not in current_values:
            current_values[item_id] = "Off"

    return current_values
