"""
Bounded, parallel PIC handoff template autofill.

Initial loads read leader-synced disk only (``source_preference="synced"``).
Explicit refresh checks remote WGMS. Shares display helpers with compare.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session, or_, select

from app.core import models, utils
from app.core.data import summaries
from app.core.data.data_service import get_data_service
from app.core.infra.logging_config import get_request_id
from app.core.pic_handoff_optional_sensors import PIC_HANDOFF_OPTIONAL_SENSOR_REGISTRY
from app.forms.form_definitions import get_static_form_schema
from app.services.error_classification_service import classify_error_message

logger = logging.getLogger(__name__)

AIS_HOURS = 8
ERRORS_HOURS = 8
POWER_HOURS = 48
SENSOR_HOURS = 24

SCIENCE_SENSORS = ["ctd", "weather", "waves", "vr2c", "fluorometer", "wg_vm4"]
SENSOR_LABELS = {
    "ctd": "CTD",
    "weather": "Weather",
    "waves": "Waves",
    "vr2c": "VR2C",
    "fluorometer": "Fluorometer",
    "wg_vm4": "WG-VM4",
}
STATUS_FUNCTIONS = {
    "ctd": summaries.get_ctd_status,
    "weather": summaries.get_weather_status,
    "waves": summaries.get_wave_status,
    "vr2c": summaries.get_vr2c_status,
    "fluorometer": summaries.get_fluorometer_status,
    "wg_vm4": summaries.get_wg_vm4_status,
}

# Sensor sampling rate form item IDs and storage keys (WG-VM4 has no user-configurable rates)
SENSOR_SAMPLING_CONFIG = {
    "ctd": {
        "label": "CTD Sample Rate",
        "hint": "period (sec), samples/block, flush (sec), off (sec). Period cannot exceed 14 sec if O2 sensor installed.",
        "placeholder": "e.g. 10, 10, 100, 400",
        "default": "10, 10, 100, 400",
    },
    "c3": {
        "label": "Fluorometer Sample Rate",
        "hint": "UsePump (true/false), Flush (sec), AvgPeriod/Block (sec), OffTime (sec).",
        "placeholder": "e.g. True, 100, 100, 400",
        "default": "False, 45, 30, 0",
    },
    "fluorometer": {
        "label": "Fluorometer Sample Rate",
        "hint": "UsePump (true/false), Flush (sec), AvgPeriod/Block (sec), OffTime (sec).",
        "placeholder": "e.g. True, 100, 100, 400",
        "default": "False, 45, 30, 0",
    },
    "waves": {
        "label": "Waves Interval",
        "hint": "Collection interval in minutes (default 30).",
        "placeholder": "e.g. 30",
        "default": "30",
    },
    "weather": {
        "label": "Weather Interval",
        "hint": "Collection period in minutes (default 10).",
        "placeholder": "e.g. 10",
        "default": "10",
    },
    "vr2c": {
        "label": "VR2C Status Interval",
        "hint": "Status output interval in minutes (default 60).",
        "placeholder": "e.g. 60",
        "default": "60",
    },
}
SENSOR_SAMPLING_ITEM_ID_TO_KEY = {
    "sensor_ctd_sampling_val": "ctd",
    "sensor_fluorometer_sampling_val": "c3",
    "sensor_waves_sampling_val": "waves",
    "sensor_weather_sampling_val": "weather",
    "sensor_vr2c_sampling_val": "vr2c",
}


def resolve_mission_overview(session: Session, mission_id: str) -> Optional[models.MissionOverview]:
    mission_overview = session.get(models.MissionOverview, mission_id)
    if mission_overview is None and "-" in mission_id:
        mission_overview = session.get(
            models.MissionOverview, utils.deployment_mission_code_from_mission_id(mission_id)
        )
    return mission_overview


def parse_enabled_sensor_cards(mission_overview: Optional[models.MissionOverview]) -> List[str]:
    if not mission_overview or not mission_overview.enabled_sensor_cards:
        return []
    try:
        return json.loads(mission_overview.enabled_sensor_cards)
    except (json.JSONDecodeError, TypeError):
        return []


def parse_optional_sensors(mission_overview: Optional[models.MissionOverview]) -> List[str]:
    if not mission_overview or not mission_overview.pic_handoff_optional_sensors:
        return []
    try:
        return json.loads(mission_overview.pic_handoff_optional_sensors)
    except (json.JSONDecodeError, TypeError):
        return []


def mission_title(session: Session, mission_id: str) -> str:
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


def boats_in_area_display(ais_df) -> str:
    vessels = (
        summaries.get_ais_summary(ais_df, max_age_hours=AIS_HOURS)
        if ais_df is not None and not ais_df.empty
        else []
    )
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


def recent_errors_display(errors_df) -> str:
    recent_errors_raw = (
        summaries.get_recent_errors(errors_df, max_age_hours=ERRORS_HOURS)
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


def total_battery_display(df_power, *, theoretical_max_wh: Optional[float]) -> str:
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


def power_status_values(
    df_power, *, theoretical_max_wh: Optional[float]
) -> Tuple[Any, Any, Optional[float], Optional[float], Optional[float], str]:
    """Return battery_wh, battery_pct, theoretical, realistic, effective, percent_hint."""
    power_info = (
        summaries.get_power_status(df_power, None, theoretical_max_wh=theoretical_max_wh)
        if df_power is not None and not df_power.empty
        else {}
    )
    values = power_info.get("values", {})
    battery_wh = values.get("BatteryWattHours", "N/A")
    battery_pct = values.get("BatteryPercentage", "N/A")
    theoretical_wh = values.get("TheoreticalMaxBatteryWh")
    realistic_wh = values.get("RealisticMaxBatteryWh")
    effective_wh = values.get("EffectiveMaxBatteryWh")
    if effective_wh is not None:
        if realistic_wh is not None and effective_wh == realistic_wh:
            percent_battery_hint = (
                f"% Battery Remaining is calculated using the observed max ({int(realistic_wh)} Wh) for this mission."
            )
        else:
            percent_battery_hint = (
                f"% Battery Remaining is calculated using the theoretical max ({int(effective_wh)} Wh)."
            )
    else:
        percent_battery_hint = (
            "% Battery Remaining is calculated using the theoretical max when set, otherwise the legacy default."
        )
    return battery_wh, battery_pct, theoretical_wh, realistic_wh, effective_wh, percent_battery_hint


def sensor_status_payload(df_sensor, card: str) -> Dict[str, Any]:
    status_fn = STATUS_FUNCTIONS.get(card)
    status = (
        status_fn(df_sensor, None)
        if status_fn and df_sensor is not None and not df_sensor.empty
        else {}
    )
    latest_timestamp_str = status.get("latest_timestamp_str") or "N/A"
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
    return {
        "last_time_str": latest_timestamp_str,
        "value": "On" if default_on else "Off",
        "default_on": default_on,
    }


def sensor_on_off_value(df_sensor, card: str) -> str:
    return sensor_status_payload(df_sensor, card)["value"]


def format_sensor_sampling_display(rates: Optional[dict], sensor_key: str) -> str:
    """Format stored JSON for a sensor into the form display string."""
    if not rates or sensor_key not in rates:
        return SENSOR_SAMPLING_CONFIG.get(sensor_key, {}).get("default", "")
    d = rates[sensor_key]
    if not isinstance(d, dict):
        return str(d) if d is not None else ""
    if sensor_key == "ctd":
        return ", ".join(
            str(d.get(k, ""))
            for k in ("period_sec", "samples_per_block", "flush_time_sec", "off_time_sec")
        )
    if sensor_key == "c3":
        use_pump = d.get("use_pump", False)
        return ", ".join(
            [str(use_pump).lower()]
            + [str(d.get(k, "")) for k in ("flush_sec", "avg_period_block_sec", "off_time_sec")]
        )
    if sensor_key in ("waves", "weather", "vr2c"):
        return str(d.get("interval_min", ""))
    return ""


def hours_back_for_report(report_type: str) -> int:
    if report_type == "ais":
        return AIS_HOURS
    if report_type == "errors":
        return ERRORS_HOURS
    if report_type == "power":
        return POWER_HOURS
    if report_type in SCIENCE_SENSORS:
        return SENSOR_HOURS
    return SENSOR_HOURS


async def load_pic_report(
    data_service,
    report_type: str,
    mission_id: str,
    current_user: Optional[models.User],
    *,
    refresh_upstream: bool,
    hours_back: Optional[int] = None,
):
    """
    Load one report for PIC autofill/compare.

    Default: synced disk only (no remote). Refresh: force remote with cache bypass.
    """
    window = hours_back if hours_back is not None else hours_back_for_report(report_type)
    started = time.monotonic()
    source_preference = "remote" if refresh_upstream else "synced"
    try:
        df, source_path, _ = await data_service.load(
            report_type,
            mission_id,
            current_user=current_user,
            source_preference=source_preference,
            hours_back=window,
            force_refresh=refresh_upstream,
        )
        duration = time.monotonic() - started
        logger.info(
            "PIC_AUTOFILL_LOAD mission=%s report=%s mode=%s hours=%s duration=%.2fs "
            "source=%s rows=%s pid=%s request_id=%s",
            mission_id,
            report_type,
            "remote_refresh" if refresh_upstream else "synced",
            window,
            duration,
            source_path,
            0 if df is None or df.empty else len(df),
            os.getpid(),
            get_request_id(),
        )
        return df
    except Exception as exc:
        duration = time.monotonic() - started
        logger.warning(
            "PIC_AUTOFILL_LOAD_FAIL mission=%s report=%s mode=%s duration=%.2fs err=%s pid=%s request_id=%s",
            mission_id,
            report_type,
            "remote_refresh" if refresh_upstream else "synced",
            duration,
            exc,
            os.getpid(),
            get_request_id(),
        )
        return None


async def load_pic_reports_parallel(
    mission_id: str,
    current_user: Optional[models.User],
    report_types: List[str],
    *,
    refresh_upstream: bool,
) -> Dict[str, Any]:
    data_service = get_data_service()

    async def _one(report_type: str):
        df = await load_pic_report(
            data_service,
            report_type,
            mission_id,
            current_user,
            refresh_upstream=refresh_upstream,
        )
        return report_type, df

    results = await asyncio.gather(*[_one(rt) for rt in report_types])
    return {report_type: df for report_type, df in results}


def _user_display_name(user_in_db: models.UserInDB) -> str:
    name = (user_in_db.full_name or user_in_db.username or "").strip()
    return name or (user_in_db.username or "").strip()


def inject_pic_handoff_rosters(session: Session, schema_dict: dict) -> None:
    """Inject MOS/PIC rosters into PIC handoff dropdowns from the users table."""
    if schema_dict.get("form_type") != "pic_handoff_checklist":
        return

    users_in_db = session.exec(
        select(models.UserInDB).where(models.UserInDB.disabled == False)  # noqa: E712
    ).all()

    mos_options = sorted(
        {_user_display_name(u) for u in users_in_db if getattr(u, "is_mos", False)},
        key=lambda s: s.casefold(),
    )
    pic_options = sorted(
        {_user_display_name(u) for u in users_in_db if getattr(u, "is_pic", False)},
        key=lambda s: s.casefold(),
    )

    for section in schema_dict.get("sections", []) or []:
        for item in section.get("items", []) or []:
            iid = item.get("id")
            if iid == "current_mos_val":
                item["options"] = mos_options
            if iid in ("current_pic_val", "last_pic_val"):
                item["options"] = pic_options


async def build_pic_handoff_autofilled_schema(
    mission_id: str,
    session: Session,
    current_user: Optional[models.User],
    *,
    refresh_upstream: bool = False,
) -> dict:
    """
    Build the PIC handoff template with autofilled live fields.

    ``refresh_upstream=False`` (default): leader-synced disk only, bounded windows.
    ``refresh_upstream=True``: force remote WGMS check in parallel.
    """
    started = time.monotonic()
    schema_obj = get_static_form_schema("pic_handoff_checklist")
    schema = schema_obj.model_dump(mode="python")

    mission_overview = resolve_mission_overview(session, mission_id)
    battery_apu = getattr(mission_overview, "battery_apu_count", None) if mission_overview else None
    theoretical_max_wh = summaries.theoretical_max_wh(battery_apu)
    enabled_cards = parse_enabled_sensor_cards(mission_overview)
    optional_sensors = parse_optional_sensors(mission_overview)
    sensor_cards = [card for card in SCIENCE_SENSORS if card in enabled_cards]
    load_types = ["power", "ais", "errors", *sensor_cards]

    loaded = await load_pic_reports_parallel(
        mission_id,
        current_user,
        load_types,
        refresh_upstream=refresh_upstream,
    )

    battery_wh, battery_pct, theoretical_wh, realistic_wh, _effective_wh, percent_battery_hint = (
        power_status_values(loaded.get("power"), theoretical_max_wh=theoretical_max_wh)
    )
    total_capacity_display = total_battery_display(
        loaded.get("power"), theoretical_max_wh=theoretical_max_wh
    )
    title = mission_title(session, mission_id)
    boats_in_area_display_val = boats_in_area_display(loaded.get("ais"))
    recent_errors_display_val = recent_errors_display(loaded.get("errors"))
    vessel_standoff = getattr(mission_overview, "vessel_standoff_m", None) if mission_overview else None
    vessel_standoff_display = str(vessel_standoff) if vessel_standoff is not None else ""

    sensor_items_to_inject: List[dict] = []
    for card in sensor_cards:
        payload = sensor_status_payload(loaded.get(card), card)
        sensor_items_to_inject.append({
            "id": f"sensor_{card}_status",
            "label": SENSOR_LABELS.get(card, card.upper()),
            "item_type": models.FormItemTypeEnum.SENSOR_STATUS.value,
            "value": json.dumps(payload),
        })

    for sensor_key in optional_sensors:
        if sensor_key not in PIC_HANDOFF_OPTIONAL_SENSOR_REGISTRY:
            continue
        item_id = f"sensor_{sensor_key}_status"
        if any(item["id"] == item_id for item in sensor_items_to_inject):
            continue
        sensor_items_to_inject.append({
            "id": item_id,
            "label": PIC_HANDOFF_OPTIONAL_SENSOR_REGISTRY[sensor_key],
            "item_type": models.FormItemTypeEnum.SENSOR_STATUS.value,
            "value": "Off",
        })

    autofill_map = {
        "glider_id_val": lambda: mission_id,
        "current_battery_wh_val": lambda: battery_wh,
        "percent_battery_val": lambda: battery_pct,
        "total_battery_val": lambda: total_capacity_display,
    }

    for section in schema.get("sections", []):
        for item in section.get("items", []):
            item_id = item.get("id")
            if item_id == "total_battery_val":
                item["value"] = total_capacity_display
            if item_id == "mission_title_val":
                item["value"] = title
            if item_id == "boats_in_area_val":
                item["value"] = boats_in_area_display_val
            if item_id == "vessel_standoff_m_val":
                item["value"] = vessel_standoff_display
            if item_id == "recent_errors_val":
                item["value"] = recent_errors_display_val
            if item.get("item_type") == "autofilled_value":
                autofill_func = autofill_map.get(item_id)
                if autofill_func:
                    item["value"] = autofill_func()
                if item_id == "percent_battery_val":
                    item["hint"] = percent_battery_hint

    wg_vm4_form_items: List[dict] = []
    if "wg_vm4" in enabled_cards:
        wg_vm4_form_items = [
            {
                "id": "wg_vm4_current_station_val",
                "label": "Current Station",
                "item_type": models.FormItemTypeEnum.TEXT_INPUT.value,
                "value": "N/A",
                "placeholder": "e.g. HFX031",
            },
            {
                "id": "wg_vm4_offload_status_val",
                "label": "Offload Status",
                "item_type": models.FormItemTypeEnum.DROPDOWN.value,
                "options": [
                    "N/A",
                    "Connecting to Station",
                    "Connected to Station",
                    "Offloading Station",
                    "Aborting Offload",
                ],
                "value": "N/A",
            },
            {
                "id": "wg_vm4_next_station_val",
                "label": "Next Station",
                "item_type": models.FormItemTypeEnum.TEXT_INPUT.value,
                "value": "N/A",
                "placeholder": "e.g. HFX032",
            },
        ]

    sampling_sensor_keys = ["ctd", "fluorometer", "waves", "weather", "vr2c"]
    item_id_by_key = {
        "ctd": "sensor_ctd_sampling_val",
        "fluorometer": "sensor_fluorometer_sampling_val",
        "waves": "sensor_waves_sampling_val",
        "weather": "sensor_weather_sampling_val",
        "vr2c": "sensor_vr2c_sampling_val",
    }
    rates_json = None
    if mission_overview and mission_overview.sensor_sampling_rates:
        try:
            rates_json = json.loads(mission_overview.sensor_sampling_rates)
        except (json.JSONDecodeError, TypeError):
            rates_json = {}
    sampling_storage_key = {"fluorometer": "c3"}
    sampling_item_by_key: Dict[str, dict] = {}
    for sk in sampling_sensor_keys:
        if sk not in enabled_cards:
            continue
        cfg = SENSOR_SAMPLING_CONFIG.get(sk)
        if not cfg:
            continue
        iid = item_id_by_key.get(sk)
        if not iid:
            continue
        storage_key = sampling_storage_key.get(sk, sk)
        display_val = format_sensor_sampling_display(rates_json, storage_key)
        sampling_item_by_key[sk] = {
            "id": iid,
            "label": cfg["label"],
            "item_type": models.FormItemTypeEnum.TEXT_INPUT.value,
            "value": display_val,
            "placeholder": cfg.get("placeholder", ""),
            "hint": cfg.get("hint"),
        }

    if sensor_items_to_inject or wg_vm4_form_items or sampling_item_by_key:
        for section in schema.get("sections", []):
            if section.get("id") != "general_status":
                continue
            items = section.get("items") or []
            insert_idx = None
            for i, it in enumerate(items):
                if it.get("id") == "recent_errors_val":
                    insert_idx = i + 1
                    break
            if insert_idx is not None:
                sensor_without_vm4 = [
                    s for s in sensor_items_to_inject if s["id"] != "sensor_wg_vm4_status"
                ]
                wg_vm4_status_item = next(
                    (s for s in sensor_items_to_inject if s["id"] == "sensor_wg_vm4_status"),
                    None,
                )
                for sensor_item in reversed(sensor_without_vm4):
                    items.insert(insert_idx, sensor_item)
                    insert_idx += 1
                    card = sensor_item["id"].replace("sensor_", "").replace("_status", "")
                    sampling_item = sampling_item_by_key.get(card)
                    if sampling_item:
                        items.insert(insert_idx, sampling_item)
                        insert_idx += 1
                if wg_vm4_status_item:
                    items.insert(insert_idx, wg_vm4_status_item)
                    insert_idx += 1
                for wg_item in wg_vm4_form_items:
                    items.insert(insert_idx, wg_item)
                    insert_idx += 1
            break

    inject_pic_handoff_rosters(session, schema)
    schema["autofill_meta"] = {
        "mode": "remote_refresh" if refresh_upstream else "synced",
        "hours": {
            "power": POWER_HOURS,
            "ais": AIS_HOURS,
            "errors": ERRORS_HOURS,
            "sensors": SENSOR_HOURS,
        },
        "reports_loaded": load_types,
        "duration_s": round(time.monotonic() - started, 3),
        "pid": os.getpid(),
        "request_id": get_request_id(),
    }
    logger.info(
        "PIC_AUTOFILL_DONE mission=%s mode=%s duration=%.2fs reports=%s pid=%s request_id=%s",
        mission_id,
        schema["autofill_meta"]["mode"],
        schema["autofill_meta"]["duration_s"],
        ",".join(load_types),
        os.getpid(),
        get_request_id(),
    )
    return schema
