"""Shared field model and option labels for the CCG NAVWARN request form.

Labels must match the checkbox captions in
``templates/navwarn_request_form.docx`` exactly so the .docx filler can map
``w14:checkbox`` controls by following text.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional, Sequence

NAVWARN_DESKS: dict[str, tuple[str, str]] = {
    "sydney": ("Sydney", "NAVWARN.MCTSSydney@innav.gc.ca"),
    "port_aux_basques": (
        "Port aux Basques",
        "navwarn.mctsportauxbasques@innav.gc.ca",
    ),
}

REGION_LINE = "Canadian Coast Guard Atlantic Region"
FORM_TITLE = "NAVWARN Request Form"
NIS_URL = "https://nis.ccg-gcc.gc.ca/public/rest/menu/en/topics"
WAVE_GLIDER_OVERVIEW_URL = (
    "https://www.liquid-robotics.com/wave-glider/overview/"
)

PUBLISH_CONTACT_OPTIONS = (
    ("no", "No"),
    ("yes_same", "Yes, the same information as in (1.), (2.) and (3.)"),
    ("yes_custom", "Yes, the following contact information:"),
)
UPDATE_OR_CANCEL_OPTIONS = (
    ("yes", "Yes"),
    ("no", "No"),
)
TIMEZONE_OPTIONS = (
    ("local", "Local Time"),
    ("utc", "UTC (Coordinated Universal Time)"),
)
DAYS_OPTIONS = (
    ("weekdays", "Weekdays only"),
    ("weekends", "Weekends only"),
    ("daily", "Daily"),
    ("intermittently", "Intermittently"),
    ("other", "Other (please specify)"),
)
HOURS_OPTIONS = (
    ("daylight", "Daylight hours only"),
    ("24h", "24 hours"),
    ("other", "Other (please specify)"),
)
FIRM_ESTIMATED_OPTIONS = (
    ("firm", "Firm"),
    ("estimated", "Estimated"),
)
POSITION_FORMATS = (
    ("dm", "degrees and minutes"),
    ("dms", "degrees minutes and seconds"),
    ("dmm", "degrees minutes and decimal minutes"),
)
MARINE_WORKS_OPTIONS = (
    ("breakwater", "Breakwater construction"),
    ("cable_laying", "Cable laying operations"),
    ("dredging", "Dredging operations"),
    ("floating_dock", "Floating dock"),
    ("hydrographic", "Hydrographic survey"),
    ("seismic", "Seismic survey"),
    ("wharf", "Wharf construction"),
    ("other", "Marine works (other). Please briefly describe:"),
)
OBSTRUCTION_OPTIONS = (
    ("acoustic_recorder", "Acoustic recorder"),
    ("aquaculture", "Aquaculture site"),
    ("diving", "Diving operations"),
    ("ice_boom", "Ice boom"),
    ("mussel_farm", "Mussel farm"),
    ("repair", "Repair work"),
    ("scientific_buoy", "Scientific buoy and apparatus"),
    ("scientific_moorings", "Scientific moorings"),
    ("submerged_object", "Submerged object"),
    ("subsurface_moorings", "Subsurface moorings"),
    ("subsurface_pipelines", "Subsurface pipelines"),
    ("tide_gauges", "Tide gauges"),
    ("uncharted_cables", "Uncharted submarine cables"),
    ("underwater_installation", "Underwater installation"),
    ("wreck", "Wreck"),
    ("other", "Obstruction (other). Please briefly describe:"),
)
OFFSHORE_OPTIONS = (
    ("drill_on_location", "Drill rig on location"),
    ("drill_under_tow", "Drill rig under tow"),
    ("drilling_site", "Drilling site operations"),
    ("other", "Offshore works (other). Please briefly describe:"),
)
RECREATIONAL_OPTIONS = (
    ("fireworks", "Fireworks"),
    ("race", "Race"),
    ("regattas", "Regattas"),
    ("swimmers", "Swimmers"),
    ("other", "Recreational event (other). Please briefly describe:"),
)
WASH_BERTH_OPTIONS = (
    ("none", "None"),
    ("minimum_wash", "Minimum wash"),
    ("wide_berth", "Wide berth"),
)

NATURE_CATEGORIES = (
    ("marine_works", "Marine works", MARINE_WORKS_OPTIONS),
    ("obstruction", "Obstruction", OBSTRUCTION_OPTIONS),
    ("offshore", "Offshore works", OFFSHORE_OPTIONS),
    ("recreational", "Recreational event", RECREATIONAL_OPTIONS),
)

# Ordered checkbox labels as they appear in the official template (53 total).
TEMPLATE_CHECKBOX_LABELS: tuple[str, ...] = (
    *(label for _, label in PUBLISH_CONTACT_OPTIONS),
    *(label for _, label in UPDATE_OR_CANCEL_OPTIONS),
    *(label for _, label in TIMEZONE_OPTIONS),
    *(label for _, label in DAYS_OPTIONS),
    *(label for _, label in HOURS_OPTIONS),
    *(label for _, label in FIRM_ESTIMATED_OPTIONS),
    *(label for _, label in MARINE_WORKS_OPTIONS),
    *(label for _, label in OBSTRUCTION_OPTIONS),
    *(label for _, label in OFFSHORE_OPTIONS),
    *(label for _, label in RECREATIONAL_OPTIONS),
    *(label for _, label in WASH_BERTH_OPTIONS),
)


@dataclass
class NavwarnDocumentFields:
    desk: str = "sydney"
    title: str = ""
    catalog_mission_id: Optional[str] = None
    hull_name: str = ""
    requester_name: str = ""
    telephone: str = ""
    email: str = ""
    publish_contact: Optional[str] = "no"
    publish_contact_custom: str = ""
    is_update_or_cancel: Optional[str] = "no"
    previous_navwarn_number: str = ""
    start_datetime: str = ""
    timezone: Optional[str] = "utc"
    days_of_operation: Optional[str] = "daily"
    days_other: str = ""
    hours_of_operation: Optional[str] = "24h"
    hours_other: str = ""
    completion_datetime: str = ""
    completion_firmness: Optional[str] = "estimated"
    position_format: str = "dmm"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    place_name: str = ""
    extra_positions: str = ""
    nature_category: Optional[str] = "obstruction"
    nature_topic: Optional[str] = "other"
    nature_other: str = "Acoustic/Oceanographic Survey"
    vessels_on_scene: str = ""
    markers_description: str = ""
    wash_berth: Optional[str] = "none"
    other_details: str = ""


def desk_name(desk: str) -> str:
    return NAVWARN_DESKS.get(desk, NAVWARN_DESKS["sydney"])[0]


def desk_email(desk: str) -> str:
    return NAVWARN_DESKS.get(desk, NAVWARN_DESKS["sydney"])[1]


def desk_title_line(desk: str) -> str:
    return f"{desk_name(desk)} Navigation Warning Issuing Desk"


def option_label(value: Optional[str], options: Sequence[tuple[str, str]]) -> str:
    if not value:
        return ""
    for key, label in options:
        if key == value:
            return label
    return value


def nature_options_for(category: Optional[str]) -> tuple[tuple[str, str], ...]:
    for key, _label, options in NATURE_CATEGORIES:
        if key == category:
            return options
    return ()


FLOAT_SV3_HULL_RE = re.compile(
    r"^\s*Float\s+SV3\s*[-–—]\s*([A-Za-z0-9]+)\s*$",
    re.IGNORECASE,
)


def parse_float_sv3_hull_id(component_name: Optional[str]) -> Optional[str]:
    """Extract ``C34167NS`` from a Tracker component name like ``Float SV3 - C34167NS``."""
    text = (component_name or "").strip()
    if not text:
        return None
    match = FLOAT_SV3_HULL_RE.match(text)
    if not match:
        return None
    return match.group(1).strip() or None


def default_vessels_text(hull_name: str) -> str:
    hull = (hull_name or "").strip() or "CXXXXXNS"
    return (
        f"Wave Glider {hull}, equipped with a non-transmitting AIS receiver."
    )


def default_markers_text(hull_name: str) -> str:
    hull = (hull_name or "").strip() or "CXXXXXNS"
    return (
        f"Wave glider {hull} is copper in colour with a mast extending 1.5 metre "
        "above the surface of the water, supporting a solid white light and orange "
        "visibility flag, and several other masts extending <1m above the water line."
    )


def default_other_details_text(
    *,
    contact_name: str = "Tyler Byrne",
    contact_phone: str = "902-719-7078",
    secondary_name: str = "Sue L'Orsa",
    secondary_phone: str = "250-877-8052",
) -> str:
    return (
        "The Wave Glider is remotely operated, moving at a speed of approximately "
        "1.3 knots and measuring 3.05 metres by 0.81 metres.  For further "
        f"information, authorities and mariners may contact {secondary_name} "
        f"at {secondary_phone}, {contact_name} {contact_phone}, or Liquid Robotics "
        "Wave Glider Operations Centre at +1 888-574-4574 or 408-636-4205."
    )


def _hemisphere_lat(lat: float) -> str:
    return "N" if lat >= 0 else "S"


def _hemisphere_lon(lon: float) -> str:
    return "E" if lon >= 0 else "W"


def format_position_parts(
    lat: Optional[float],
    lon: Optional[float],
    position_format: str,
) -> dict[str, str]:
    """Plain numeric strings for the three position rows (no degree symbols)."""
    empty = {
        "lat_text": "",
        "lon_text": "",
        "lat_hemisphere": "N",
        "lon_hemisphere": "W",
    }
    if lat is None or lon is None:
        return empty

    lat_h = _hemisphere_lat(lat)
    lon_h = _hemisphere_lon(lon)
    alat = abs(lat)
    alon = abs(lon)

    if position_format == "dm":
        lat_text = _format_dm(alat)
        lon_text = _format_dm(alon)
    elif position_format == "dms":
        lat_text = _format_dms(alat)
        lon_text = _format_dms(alon)
    else:
        # degrees + decimal minutes stored as a single decimal degrees value
        # in the sample form (44.512 / -63.409). Keep signed lon as sample did.
        lat_text = _format_decimal(alat if lat >= 0 else -alat)
        lon_text = _format_decimal(lon)

    return {
        "lat_text": lat_text,
        "lon_text": lon_text,
        "lat_hemisphere": lat_h,
        "lon_hemisphere": lon_h,
    }


def _format_decimal(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text or "0"


def _format_dm(abs_degrees: float) -> str:
    degrees = int(math.floor(abs_degrees))
    minutes = (abs_degrees - degrees) * 60.0
    return f"{degrees} {_format_decimal(minutes)}"


def _format_dms(abs_degrees: float) -> str:
    degrees = int(math.floor(abs_degrees))
    minutes_full = (abs_degrees - degrees) * 60.0
    minutes = int(math.floor(minutes_full))
    seconds = (minutes_full - minutes) * 60.0
    return f"{degrees} {minutes:02d} {_format_decimal(seconds)}"


def selected_checkbox_indices(fields: NavwarnDocumentFields) -> set[int]:
    """Absolute checkbox indices (0..52) that should be ticked.

    Index-based because some labels repeat (``No``, ``Other (please specify)``).
    """
    selected: set[int] = set()
    cursor = 0

    def add_group(
        value: Optional[str], options: Sequence[tuple[str, str]]
    ) -> None:
        nonlocal cursor
        for offset, (key, _label) in enumerate(options):
            if value and key == value:
                selected.add(cursor + offset)
        cursor += len(options)

    add_group(fields.publish_contact, PUBLISH_CONTACT_OPTIONS)
    add_group(fields.is_update_or_cancel, UPDATE_OR_CANCEL_OPTIONS)
    add_group(fields.timezone, TIMEZONE_OPTIONS)
    add_group(fields.days_of_operation, DAYS_OPTIONS)
    add_group(fields.hours_of_operation, HOURS_OPTIONS)
    add_group(fields.completion_firmness, FIRM_ESTIMATED_OPTIONS)
    for key, _label, options in NATURE_CATEGORIES:
        if key == fields.nature_category:
            add_group(fields.nature_topic, options)
        else:
            cursor += len(options)
    add_group(fields.wash_berth, WASH_BERTH_OPTIONS)
    return selected


def selected_checkbox_labels(fields: NavwarnDocumentFields) -> set[str]:
    """Labels for the selected indices (for PDF rendering)."""
    indices = selected_checkbox_indices(fields)
    return {TEMPLATE_CHECKBOX_LABELS[i] for i in indices}


def nature_other_for(fields: NavwarnDocumentFields) -> str:
    if fields.nature_topic != "other":
        return ""
    return (fields.nature_other or "").strip()


def pdf_or_docx_basename(
    fields: NavwarnDocumentFields,
    *,
    created: Optional[date] = None,
) -> str:
    """``NAVWARN_Request_C34167NS_YYYY-MM-DD`` (hull ID + generation date)."""
    when = created or datetime.now(timezone.utc).date()
    hull = re.sub(r"[^A-Za-z0-9_-]+", "", (fields.hull_name or "").strip())[:40]
    if not hull:
        hull = "Unknown"
    return f"NAVWARN_Request_{hull}_{when.isoformat()}"
