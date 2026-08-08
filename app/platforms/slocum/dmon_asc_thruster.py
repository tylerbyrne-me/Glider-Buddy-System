"""Thruster activity between consecutive DMON ``*.asc`` offloads.

Enriches a normalized ASC payload (from ``normalize_dmon_asc_files``) with
``thruster_since_prev`` per file using dashboard mirror columns
``MThrusterPower`` / ``CThrusterOn`` over ``[prev_mtime, this_mtime)``.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

from app.core.sfmc_transforms import _parse_sfmc_dt


def thruster_used_in_interval(
    df: pd.DataFrame,
    start_utc: datetime,
    end_utc: datetime,
    *,
    power_col: str = "MThrusterPower",
    cmd_col: str = "CThrusterOn",
) -> Optional[bool]:
    """Return True/False when samples exist in ``[start, end)``; None if none."""
    if df is None or df.empty or "Timestamp" not in df.columns:
        return None
    if power_col not in df.columns and cmd_col not in df.columns:
        return None

    start = start_utc if start_utc.tzinfo else start_utc.replace(tzinfo=timezone.utc)
    end = end_utc if end_utc.tzinfo else end_utc.replace(tzinfo=timezone.utc)
    if end <= start:
        return None

    work = df.copy()
    work["Timestamp"] = pd.to_datetime(work["Timestamp"], utc=True)
    mask = (work["Timestamp"] >= start) & (work["Timestamp"] < end)
    window = work.loc[mask]
    if window.empty:
        return None

    power_on = False
    cmd_on = False
    if power_col in window.columns:
        power = pd.to_numeric(window[power_col], errors="coerce")
        power_on = bool((power > 0).any())
    if cmd_col in window.columns:
        cmd = pd.to_numeric(window[cmd_col], errors="coerce")
        cmd_on = bool((cmd > 0).any())

    # Samples exist in the interval — Yes if either channel shows activity.
    return bool(power_on or cmd_on)


def enrich_dmon_asc_with_thruster(
    asc_payload: dict[str, Any],
    dashboard_df: pd.DataFrame,
) -> dict[str, Any]:
    """Attach ``thruster_since_prev`` (bool | None) to each ASC file row.

    Files are expected in chronological order (as produced by
    ``normalize_dmon_asc_files``). The first file gets ``thruster_since_prev=None``
    (no previous boundary). Rows with unparseable timestamps also get None.
    """
    if not isinstance(asc_payload, dict):
        return {"files": [], "file_count": 0, "summary": "", "has_gap_over_16h": False}

    out = deepcopy(asc_payload)
    files = out.get("files")
    if not isinstance(files, list):
        out["files"] = []
        return out

    prev_dt: Optional[datetime] = None
    enriched: list[dict[str, Any]] = []
    for row in files:
        if not isinstance(row, dict):
            continue
        entry = dict(row)
        this_dt = _parse_sfmc_dt(entry.get("dateTimeModified"))
        if prev_dt is None or this_dt is None:
            entry["thruster_since_prev"] = None
        else:
            entry["thruster_since_prev"] = thruster_used_in_interval(
                dashboard_df, prev_dt, this_dt
            )
        enriched.append(entry)
        if this_dt is not None:
            prev_dt = this_dt

    out["files"] = enriched
    return out


def format_thruster_since_prev(value: Any, *, has_previous: bool) -> str:
    """Map enricher value to display label for UI / PDF."""
    if not has_previous:
        return "—"
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return "No data"
