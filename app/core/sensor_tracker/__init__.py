"""Shared Sensor Tracker helpers (hull display, etc.).

Product/area platforms (``wave_glider``, ``slocum``) live in ``app.core.platforms``.
"""

from app.core.sensor_tracker.platform_display import (
    clear_platform_display_cache,
    enrich_rows_platform_names,
    ensure_platform_labels,
    format_platform_label,
    platform_fk_from_value,
    platform_name_from_record,
    prepare_deployment_platform_labels,
)

__all__ = [
    "clear_platform_display_cache",
    "enrich_rows_platform_names",
    "ensure_platform_labels",
    "format_platform_label",
    "platform_fk_from_value",
    "platform_name_from_record",
    "prepare_deployment_platform_labels",
]
