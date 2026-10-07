"""
Lightweight live-value builder for PIC handoff "changes since submission" highlighting.

Uses the same bounded windows and load modes as PIC template autofill.
"""

from __future__ import annotations

import logging
from typing import Dict

from sqlmodel import Session

from app.core import models
from app.core.data import summaries
from app.core.forms.pic_handoff_autofill import (
    AIS_HOURS as AIS_COMPARE_HOURS,
    ERRORS_HOURS as ERRORS_COMPARE_HOURS,
    POWER_HOURS as POWER_COMPARE_HOURS,
    SCIENCE_SENSORS,
    SENSOR_HOURS as SENSOR_COMPARE_HOURS,
    boats_in_area_display as _boats_in_area_display,
    load_pic_reports_parallel,
    mission_title as _mission_title,
    parse_enabled_sensor_cards as _parse_enabled_sensor_cards,
    parse_optional_sensors as _parse_optional_sensors,
    recent_errors_display as _recent_errors_display,
    resolve_mission_overview as _resolve_mission_overview,
    sensor_on_off_value as _sensor_on_off_value,
    total_battery_display as _total_battery_display,
)
from app.core.pic_handoff_optional_sensors import PIC_HANDOFF_OPTIONAL_SENSOR_REGISTRY

logger = logging.getLogger(__name__)

# Re-export window constants for tests / callers.
__all__ = [
    "AIS_COMPARE_HOURS",
    "ERRORS_COMPARE_HOURS",
    "POWER_COMPARE_HOURS",
    "SENSOR_COMPARE_HOURS",
    "_boats_in_area_display",
    "_recent_errors_display",
    "build_pic_handoff_compare_current_values",
]


async def build_pic_handoff_compare_current_values(
    mission_id: str,
    session: Session,
    current_user: models.User,
    *,
    refresh_upstream: bool = False,
) -> Dict[str, str]:
    """
    Return comparable string values for PIC handoff change detection.

    Only loads data needed for comparable item IDs and sensor status rows,
    using short time windows instead of full mission history.
    """
    mission_overview = _resolve_mission_overview(session, mission_id)
    battery_apu = getattr(mission_overview, "battery_apu_count", None) if mission_overview else None
    theoretical_max_wh = summaries.theoretical_max_wh(battery_apu)

    enabled_cards = _parse_enabled_sensor_cards(mission_overview)
    optional_sensors = _parse_optional_sensors(mission_overview)

    sensor_cards = [card for card in SCIENCE_SENSORS if card in enabled_cards]
    load_types = ["power", "ais", "errors", *sensor_cards]

    loaded = await load_pic_reports_parallel(
        mission_id,
        current_user,
        load_types,
        refresh_upstream=refresh_upstream,
    )

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
