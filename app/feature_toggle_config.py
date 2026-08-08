"""
Feature toggle defaults and loading from .env JSON or an optional JSON file.

Prefer ``FEATURE_TOGGLES_FILE`` (pretty-printed, one flag per line) over the
single-line ``FEATURE_TOGGLES_JSON`` string when managing many toggles.

Lives at ``app/feature_toggle_config.py`` (not under ``app.core``) so ``app.config``
can import it without a circular import through ``app.core.infra.db``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

_logger = logging.getLogger(__name__)

# Canonical defaults — merged under overrides so new toggles get safe defaults.
DEFAULT_FEATURE_TOGGLES: dict[str, bool] = {
    "pic_management": True,
    "admin_management": True,
    "station_offloads": True,
    "vm4_offload_parser": False,
    "local_data_loading": False,
    "slocum_platform": True,
    "wave_glider_specific_nav": True,
    "wave_glider_knowledge_base": True,
    "slocum_knowledge_base": True,
    "report_bathymetry_contours": True,
    "weather_map_layers": False,
    "iridium_map_layer": False,
    "map_vector_layers": False,
    "slocum_auto_checklist_submit": False,
    "public_login_map": False,
    # Legacy / template toggles (often omitted from .env; default on)
    "mission_dashboard": True,
    "forms": True,
    "reporting": True,
    "authentication": True,
}


def _coerce_toggle_map(raw: Any, *, source: str) -> dict[str, bool]:
    if not isinstance(raw, dict):
        raise ValueError(f"{source} must be a JSON object")
    out: dict[str, bool] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if not isinstance(value, bool):
            raise ValueError(f"{source}: toggle {key!r} must be true or false, got {value!r}")
        out[key.strip()] = value
    return out


def load_feature_toggles(
    *,
    json_str: str,
    file_path: Optional[Path] = None,
) -> dict[str, bool]:
    """
    Load feature toggles: defaults ← file (if set) ← inline JSON string.

    ``FEATURE_TOGGLES_FILE`` wins over ``FEATURE_TOGGLES_JSON`` when the file exists.
    """
    merged = dict(DEFAULT_FEATURE_TOGGLES)

    if file_path is not None:
        path = Path(file_path)
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                merged.update(_coerce_toggle_map(raw, source=str(path)))
                return merged
            except Exception as err:
                _logger.error("Failed to load FEATURE_TOGGLES_FILE %s: %s", path, err)
                raise
        if str(file_path).strip():
            _logger.warning(
                "FEATURE_TOGGLES_FILE=%r not found; falling back to FEATURE_TOGGLES_JSON",
                file_path,
            )

    text = (json_str or "").strip()
    if text:
        try:
            raw = json.loads(text)
            merged.update(_coerce_toggle_map(raw, source="FEATURE_TOGGLES_JSON"))
        except Exception as err:
            _logger.error("Failed to parse FEATURE_TOGGLES_JSON: %s", err)
            raise
    return merged


def default_feature_toggles_json() -> str:
    """Compact JSON for Settings default / docs."""
    return json.dumps(DEFAULT_FEATURE_TOGGLES, separators=(",", ":"))
