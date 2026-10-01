"""Local Wave Glider ORA device power library.

Sensor Tracker knows instrument names. Watts and duty cycle live here, seeded
from the Spring Bloom 2026 request. The vehicle bus is the default row set.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

VEHICLE_BUS: tuple[dict[str, Any], ...] = (
    {"name": "VMC, Rudder, GPS", "power_draw": "~4.0w", "duty_cycle": "100%", "aliases": ("vmc", "rudder")},
    {"name": "Iridium Modem - SBD", "power_draw": "0.3w", "duty_cycle": "100%", "aliases": ("iridium modem", "sbd")},
    {"name": "AMPS", "power_draw": "0.25w", "duty_cycle": "100%", "aliases": ("amps",)},
    {"name": "Weather Station 200X", "power_draw": "1.8w", "duty_cycle": "100%", "aliases": ("weather", "airmar", "200wx")},
    {"name": "Water Speed Sensor", "power_draw": "1.8w", "duty_cycle": "100%", "aliases": ("water speed",)},
    {"name": "AIS Receiver", "power_draw": "1.35w", "duty_cycle": "100%", "aliases": ("ais",)},
    {"name": "Cell Modem", "power_draw": "0.0w", "duty_cycle": "As Needed", "aliases": ("cell modem", "cellular")},
    {"name": "Ethernet Switch", "power_draw": "0.4w", "duty_cycle": "100%", "aliases": ("ethernet switch",)},
    {"name": "Light (Nighttime Visibility)", "power_draw": "0.85w", "duty_cycle": "50%", "aliases": ("nighttime", "nav light")},
    {"name": "Wave Sensor", "power_draw": "1.0w", "duty_cycle": "100%", "aliases": ("wave sensor", "gpswaves")},
    {"name": "Iridium - RUDICS", "power_draw": "4.0w", "duty_cycle": "As Needed", "aliases": ("rudics",)},
    {"name": "SMC", "power_draw": "0.9w", "duty_cycle": "100%", "aliases": ("smc",)},
)

SCIENCE_LIBRARY: tuple[dict[str, Any], ...] = (
    {"name": "Fluorometer", "power_draw": "2.7w", "duty_cycle": "50%", "aliases": ("fluorometer", "flntu", "c3")},
    {"name": "Submersible Pump", "power_draw": "0.3w", "duty_cycle": "5.5%", "aliases": ("pump",)},
    {"name": "RDI 600 ADCP", "power_draw": "2.5w", "duty_cycle": "5.5%", "aliases": ("adcp", "rdi")},
    {"name": "Innovasea VM4", "power_draw": "0.7w", "duty_cycle": "100%", "aliases": ("vm4", "vemco", "innovasea")},
)

_LIBRARY = VEHICLE_BUS + SCIENCE_LIBRARY


def _norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def default_device_rows() -> list[dict[str, Any]]:
    """Vehicle-bus rows that are on for a typical SV3 request."""
    return [
        {
            "name": row["name"],
            "power_draw": row["power_draw"],
            "duty_cycle": row["duty_cycle"],
            "source": "library",
            "included": True,
        }
        for row in VEHICLE_BUS
    ]


def _has_alias(text: str, alias: str) -> bool:
    return f" {alias} " in f" {text} "


def match_library_entry(name: str) -> Optional[dict[str, Any]]:
    text = _norm(name)
    if not text:
        return None
    for entry in _LIBRARY:
        if text == _norm(entry["name"]):
            return entry
        if any(_has_alias(text, alias) for alias in entry["aliases"]):
            return entry
    return None


def instrument_label(row: Any) -> Optional[str]:
    """Best display name from a Tracker instrument relationship payload."""
    if not isinstance(row, dict):
        return None
    nested = row.get("instrument")
    sources = [nested, row] if isinstance(nested, dict) else [row]
    for source in sources:
        for key in (
            "name",
            "identifier",
            "short_name",
            "instrument_name",
            "instrument_identifier",
        ):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def merge_tracker_instruments(
    devices: Iterable[dict[str, Any]] | None,
    instrument_names: Iterable[str],
) -> list[dict[str, Any]]:
    """Mark or append Tracker instruments using library watts when known."""
    base = [dict(row) for row in devices] if devices else default_device_rows()
    by_name = {_norm(str(row.get("name") or "")): row for row in base if row.get("name")}
    for raw in instrument_names:
        label = (raw or "").strip()
        if not label:
            continue
        entry = match_library_entry(label)
        canonical = entry["name"] if entry else label
        key = _norm(canonical)
        existing = by_name.get(key)
        if existing is None:
            existing = by_name.get(_norm(label))
        if existing is not None:
            existing["source"] = "tracker"
            existing["included"] = True
            continue
        row = {
            "name": canonical,
            "power_draw": entry["power_draw"] if entry else "",
            "duty_cycle": entry["duty_cycle"] if entry else "",
            "source": "tracker",
            "included": True,
        }
        base.append(row)
        by_name[key] = row
    return base


def infer_vehicle_model(hull_name: Optional[str]) -> Optional[str]:
    name = (hull_name or "").upper()
    if "SV3" in name:
        return "sv3"
    if "SV2" in name:
        return "sv2"
    return None
