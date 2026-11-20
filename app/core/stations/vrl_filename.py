"""VRL filename timestamp helpers shared by VM4 attach and audit cleanup."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

_VRL_STAMP_RE = re.compile(r"(?<!\d)(\d{14})(?!\d)")
_VRL_DAY_RE = re.compile(r"(?<!\d)(\d{8})(?!\d)")


def parse_vrl_filename_timestamp(vrl_file_name: Optional[str]) -> Optional[datetime]:
    """
    Extract a UTC timestamp from a VRL filename when present.

    Prefers a 14-digit stamp (YYYYMMDDHHMMSS); falls back to YYYYMMDD at noon UTC.
    """
    name = (vrl_file_name or "").strip()
    if not name:
        return None
    match = _VRL_STAMP_RE.search(name)
    if match:
        raw = match.group(1)
        try:
            return datetime.strptime(raw, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    match = _VRL_DAY_RE.search(name)
    if match:
        raw = match.group(1)
        try:
            return datetime.strptime(raw, "%Y%m%d").replace(
                hour=12, tzinfo=timezone.utc
            )
        except ValueError:
            return None
    return None


def log_reference_timestamp(log: Any) -> Optional[datetime]:
    """Best available attempt time for comparing against a VRL stamp."""
    for attr in (
        "offload_end_time_utc",
        "offload_start_time_utc",
        "time_first_command_sent_utc",
        "arrival_date",
        "log_timestamp_utc",
    ):
        value = getattr(log, attr, None)
        if value is None:
            continue
        if isinstance(value, datetime):
            if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
    return None
