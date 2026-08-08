"""
Wave Glider sensor-card summaries and mini-trends.

Builds the shared card contract
({values, latest_timestamp_str, time_ago_str, mini_trend}) for SSR and the
soft-refresh JSON API. Reuses ``app.core.data.summaries`` status/trend helpers.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from app.core import models
from app.core import utils
from app.core.data import summaries as core_summaries
from app.core.data.data_service import get_cache_timestamp, get_data_service
from app.core.infra.db import SQLModelSession

logger = logging.getLogger(__name__)

_EMPTY_SHELL: Dict[str, Any] = {
    "values": {},
    "latest_timestamp_str": "N/A",
    "time_ago_str": "N/A",
    "mini_trend": [],
}

# Card category -> report type used by load_data_source / cache keys.
SENSOR_TO_REPORT_MAPPING: Dict[str, str] = {
    "navigation": "telemetry",
    "power": "power",
    "ctd": "ctd",
    "weather": "weather",
    "waves": "waves",
    "vr2c": "vr2c",
    "fluorometer": "fluorometer",
    "wg_vm4": "wg_vm4",
}

# Match _render_dashboard: full history for mission-peak / track-length metrics.
FULL_HISTORY_REPORT_TYPES = frozenset({"ais", "errors", "telemetry", "power"})

DEFAULT_ENABLED_SENSOR_CARDS = [
    "navigation",
    "power",
    "ctd",
    "weather",
    "waves",
    "ais",
    "errors",
]


def _to_python_scalar(value: Any) -> Any:
    """Convert numpy/pandas scalars to JSON-friendly Python types."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return value


def _sanitize_values(values: Dict[str, Any]) -> Dict[str, Any]:
    return {key: _to_python_scalar(val) for key, val in (values or {}).items()}


def _empty_sensor_payload() -> Dict[str, Any]:
    return dict(_EMPTY_SHELL)


def _sanitize_mini_trend(mini_trend: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    sanitized: List[Dict[str, Any]] = []
    for point in mini_trend or []:
        ts = point.get("Timestamp")
        if ts is None:
            continue
        sanitized.append({
            "Timestamp": ts,
            "value": _to_python_scalar(point.get("value")),
        })
    return sanitized


def _sensor_payload_from_info(info: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "values": _sanitize_values(info.get("values") or {}),
        "latest_timestamp_str": info.get("latest_timestamp_str", "N/A"),
        "time_ago_str": info.get("time_ago_str", "N/A"),
        "mini_trend": _sanitize_mini_trend(info.get("mini_trend")),
    }
    if "ess_state" in info:
        payload["ess_state"] = info.get("ess_state")
    return payload


WG_SENSOR_SUMMARY_SPECS: Dict[str, Dict[str, Any]] = {
    "navigation": {
        "report_type": "telemetry",
        "info_key": "navigation_info",
        "values_key": "navigation_values",
    },
    "power": {
        "report_type": "power",
        "info_key": "power_info",
        "values_key": "power_values",
    },
    "ctd": {
        "report_type": "ctd",
        "info_key": "ctd_info",
        "values_key": "ctd_values",
    },
    "weather": {
        "report_type": "weather",
        "info_key": "weather_info",
        "values_key": "weather_values",
    },
    "waves": {
        "report_type": "waves",
        "info_key": "wave_info",
        "values_key": "wave_values",
    },
    "vr2c": {
        "report_type": "vr2c",
        "info_key": "vr2c_info",
        "values_key": "vr2c_values",
    },
    "fluorometer": {
        "report_type": "fluorometer",
        "info_key": "fluorometer_info",
        "values_key": "fluorometer_values",
    },
    "wg_vm4": {
        "report_type": "wg_vm4",
        "info_key": "wg_vm4_info",
        "values_key": "wg_vm4_values",
    },
}


def _resolve_file_mod_time(
    report_type: str,
    file_mod_times_map: Optional[Dict[str, Optional[datetime]]],
    mission_id: Optional[str],
    source_preference: Optional[str],
) -> Optional[datetime]:
    if file_mod_times_map and file_mod_times_map.get(report_type) is not None:
        return file_mod_times_map.get(report_type)
    if mission_id:
        return get_cache_timestamp(report_type, mission_id, source_preference)
    return None


def _build_card_info(
    card_name: str,
    data_frames: Dict[str, Optional[pd.DataFrame]],
    file_mod_times_map: Optional[Dict[str, Optional[datetime]]],
    mission_id: Optional[str],
    source_preference: Optional[str],
    theoretical_max_wh: Optional[float],
) -> Dict[str, Any]:
    spec = WG_SENSOR_SUMMARY_SPECS[card_name]
    report_type = spec["report_type"]
    df = data_frames.get(report_type)
    if df is None or (hasattr(df, "empty") and df.empty):
        empty = _empty_sensor_payload()
        if card_name == "waves":
            empty["ess_state"] = None
        return empty

    file_mod_time = _resolve_file_mod_time(
        report_type, file_mod_times_map, mission_id, source_preference
    )

    try:
        if card_name == "power":
            info = core_summaries.get_power_status(
                df,
                data_frames.get("solar"),
                file_mod_time,
                theoretical_max_wh=theoretical_max_wh,
            )
            info["mini_trend"] = core_summaries.get_power_mini_trend(df)
        elif card_name == "navigation":
            info = core_summaries.get_navigation_status(df, file_mod_time)
            info["mini_trend"] = core_summaries.get_navigation_mini_trend(df)
        elif card_name == "ctd":
            info = core_summaries.get_ctd_status(df, file_mod_time)
            info["mini_trend"] = core_summaries.get_ctd_mini_trend(df)
        elif card_name == "weather":
            info = core_summaries.get_weather_status(df, file_mod_time)
            info["mini_trend"] = core_summaries.get_weather_mini_trend(df)
        elif card_name == "waves":
            info = core_summaries.get_wave_status(df, file_mod_time)
            info["mini_trend"] = core_summaries.get_wave_mini_trend(df)
        elif card_name == "vr2c":
            info = core_summaries.get_vr2c_status(df, file_mod_time)
            info["mini_trend"] = core_summaries.get_vr2c_mini_trend(df)
        elif card_name == "fluorometer":
            info = core_summaries.get_fluorometer_status(df, file_mod_time)
            info["mini_trend"] = core_summaries.get_fluorometer_mini_trend(df)
        elif card_name == "wg_vm4":
            info = core_summaries.get_wg_vm4_status(df, file_mod_time)
            info["mini_trend"] = core_summaries.get_wg_vm4_mini_trend(df)
        else:
            return _empty_sensor_payload()

        if info.get("values") is None:
            info["values"] = {}
        else:
            info["values"] = _sanitize_values(info["values"])
        info["mini_trend"] = _sanitize_mini_trend(info.get("mini_trend"))
        return info
    except Exception as e:
        logger.warning(
            "Failed to build Wave Glider summary for %s: %s",
            card_name,
            e,
            exc_info=True,
        )
        empty = _empty_sensor_payload()
        if card_name == "waves":
            empty["ess_state"] = None
        return empty


def build_wg_sensor_summaries_from_frames(
    data_frames: Dict[str, Optional[pd.DataFrame]],
    *,
    enabled_cards: Optional[Sequence[str]] = None,
    file_mod_times_map: Optional[Dict[str, Optional[datetime]]] = None,
    mission_id: Optional[str] = None,
    source_preference: Optional[str] = None,
    theoretical_max_wh: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Build template/API context for enabled Wave Glider sensor cards.

    Returns flat keys for SSR (``power_info``, ``ctd_info``, ...) plus a nested
    ``sensors`` map keyed by card name for the JSON API.
    """
    context: Dict[str, Any] = {"sensors": {}}
    data_frames = data_frames or {}

    if enabled_cards is None:
        # Process any card whose report type is present in the frames.
        enabled = {
            card
            for card, report_type in SENSOR_TO_REPORT_MAPPING.items()
            if report_type in data_frames and data_frames.get(report_type) is not None
        }
    else:
        enabled = {str(card) for card in enabled_cards}

    for card_name, spec in WG_SENSOR_SUMMARY_SPECS.items():
        info_key = spec["info_key"]
        values_key = spec["values_key"]
        empty = _empty_sensor_payload()
        if card_name == "waves":
            empty["ess_state"] = None
        context[info_key] = empty
        context[values_key] = {}

        if card_name not in enabled:
            continue

        info = _build_card_info(
            card_name,
            data_frames,
            file_mod_times_map,
            mission_id,
            source_preference,
            theoretical_max_wh,
        )
        context[info_key] = info
        context[values_key] = info.get("values") or {}
        context["sensors"][card_name] = _sensor_payload_from_info(info)

    return context


def resolve_enabled_sensor_cards(
    session: SQLModelSession,
    mission_id: str,
) -> List[str]:
    """Resolve enabled sensor cards from mission overview (read-only; no auto-create)."""
    mission_overview = utils.find_mission_overview_for_mission(session, mission_id)
    if not mission_overview or not mission_overview.enabled_sensor_cards:
        return list(DEFAULT_ENABLED_SENSOR_CARDS)
    try:
        parsed = json.loads(mission_overview.enabled_sensor_cards)
        if isinstance(parsed, list) and parsed:
            return [str(c) for c in parsed]
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(
            "Failed to parse enabled_sensor_cards for %s: %s. Using defaults.",
            mission_id,
            e,
        )
    return list(DEFAULT_ENABLED_SENSOR_CARDS)


def report_types_for_enabled_cards(enabled_cards: Sequence[str]) -> List[str]:
    """Map enabled sensor cards to report types (includes solar when power is on)."""
    report_types: List[str] = []
    for sensor_card in enabled_cards:
        report_type = SENSOR_TO_REPORT_MAPPING.get(sensor_card)
        if report_type and report_type not in report_types:
            report_types.append(report_type)
        if sensor_card == "power" and "solar" not in report_types:
            report_types.append("solar")
    return report_types


async def build_wave_glider_sensor_summaries(
    mission_id: str,
    enabled_cards: Sequence[str],
    *,
    source_preference: Optional[str] = None,
    custom_local_path: Optional[str] = None,
    current_user: Optional[models.User] = None,
    session: Optional[SQLModelSession] = None,
    hours: int = 24,
) -> Dict[str, Any]:
    """
    Load mission data and build sensor-card summaries (same window rules as dashboard SSR).
    """
    report_types = report_types_for_enabled_cards(enabled_cards)
    # Summaries API only needs left-nav sensor cards (not ais/errors tables).
    report_types = [rt for rt in report_types if rt not in ("ais", "errors")]

    theoretical_max_wh: Optional[float] = None
    if session is not None:
        mission_overview = session.get(models.MissionOverview, mission_id)
        if mission_overview is None:
            mission_overview = utils.find_mission_overview_for_mission(session, mission_id)
        battery_apu = (
            getattr(mission_overview, "battery_apu_count", None)
            if mission_overview
            else None
        )
        theoretical_max_wh = core_summaries.theoretical_max_wh(battery_apu)

    data_service = get_data_service()
    results = await asyncio.gather(
        *[
            data_service.load(
                report_type=rt,
                mission_id=mission_id,
                source_preference=source_preference,
                custom_local_path=custom_local_path,
                current_user=current_user,
                hours_back=None if rt in FULL_HISTORY_REPORT_TYPES else hours,
            )
            for rt in report_types
        ],
        return_exceptions=True,
    )

    data_frames: Dict[str, Optional[pd.DataFrame]] = {}
    file_mod_times_map: Dict[str, Optional[datetime]] = {}
    for i, report_type in enumerate(report_types):
        result = results[i]
        if isinstance(result, Exception):
            logger.error(
                "Exception loading %s for mission %s summaries: %s",
                report_type,
                mission_id,
                result,
            )
            data_frames[report_type] = None
            file_mod_times_map[report_type] = None
            continue
        if isinstance(result, tuple) and len(result) >= 3:
            df_loaded, _path, file_mod_time = result[0], result[1], result[2]
            data_frames[report_type] = (
                df_loaded if df_loaded is not None and not df_loaded.empty else None
            )
            file_mod_times_map[report_type] = file_mod_time
        elif isinstance(result, tuple) and len(result) >= 2:
            df_loaded = result[0]
            data_frames[report_type] = (
                df_loaded if df_loaded is not None and not df_loaded.empty else None
            )
            file_mod_times_map[report_type] = None
        else:
            data_frames[report_type] = None
            file_mod_times_map[report_type] = None

    return build_wg_sensor_summaries_from_frames(
        data_frames,
        enabled_cards=enabled_cards,
        file_mod_times_map=file_mod_times_map,
        mission_id=mission_id,
        source_preference=source_preference,
        theoretical_max_wh=theoretical_max_wh,
    )
