"""Thruster activity between consecutive DMON ``*.asc`` offloads.

Enriches a normalized ASC payload (from ``normalize_dmon_asc_files``) with
``thruster_since_prev`` and subsurface usage stats using dashboard columns
``MThrusterPower`` / ``CThrusterOn`` / ``MDepth`` over ``[prev_mtime, this_mtime)``.

Surface-burst thruster use (associated depth ≤ ``SURFACE_BURST_MAX_DEPTH_M``) is
ignored so Yes means thruster activity that could affect the ASC at depth.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

from app.core.sfmc_transforms import _parse_sfmc_dt

# Surface cleaning burst after surfacing — not "ASC-affecting" thruster use.
SURFACE_BURST_MAX_DEPTH_M = 3.0
# Thruster and depth rarely share an ERDDAP row; associate nearest depth.
DEPTH_ASOF_TOLERANCE = pd.Timedelta(seconds=60)
# Contiguous thruster-on run if successive deep samples are this close.
CLUSTER_GAP_MAX = pd.Timedelta(seconds=120)
# Floor for single-sample / zero-span clusters (sparse telemetry).
MIN_SAMPLE_DWELL = pd.Timedelta(seconds=15)

_DEPTH_COL = "MDepth"
_POWER_COL = "MThrusterPower"
_CMD_COL = "CThrusterOn"


@dataclass(frozen=True)
class ThrusterIntervalStats:
    """Per ASC-interval thruster summary (subsurface only)."""

    thruster_since_prev: Optional[bool]
    thruster_on_minutes_gt3m: Optional[float] = None
    thruster_depth_min_m: Optional[float] = None
    thruster_depth_max_m: Optional[float] = None
    thruster_event_count: Optional[int] = None
    thruster_events: list[dict[str, Any]] = field(default_factory=list)


_NO_PREV = ThrusterIntervalStats(thruster_since_prev=None, thruster_event_count=None)
_NO_USE = ThrusterIntervalStats(thruster_since_prev=False, thruster_event_count=0)


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso_z(dt: datetime | pd.Timestamp) -> str:
    ts = pd.Timestamp(dt)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _cluster_thruster_events(
    samples: pd.DataFrame,
    *,
    interval_start: datetime,
) -> tuple[float, list[dict[str, Any]]]:
    """Cluster deep thruster-on samples; return (total_seconds, event dicts).

    ``samples`` must have columns ``Timestamp`` and ``depth_near``, sorted by time.
    """
    if samples is None or samples.empty:
        return 0.0, []

    ordered = samples.sort_values("Timestamp").reset_index(drop=True)
    floor_s = float(MIN_SAMPLE_DWELL.total_seconds())
    prev_boundary = _ensure_utc(interval_start)

    clusters: list[pd.DataFrame] = []
    start_idx = 0
    for i in range(1, len(ordered)):
        gap = ordered.loc[i, "Timestamp"] - ordered.loc[i - 1, "Timestamp"]
        if gap <= CLUSTER_GAP_MAX:
            continue
        clusters.append(ordered.iloc[start_idx:i])
        start_idx = i
    clusters.append(ordered.iloc[start_idx:])

    total_s = 0.0
    events: list[dict[str, Any]] = []
    for chunk in clusters:
        c_start = pd.Timestamp(chunk["Timestamp"].iloc[0])
        c_end = pd.Timestamp(chunk["Timestamp"].iloc[-1])
        duration_s = max((c_end - c_start).total_seconds(), floor_s)
        total_s += duration_s
        depths = pd.to_numeric(chunk["depth_near"], errors="coerce").dropna()
        d_min = round(float(depths.min()), 1) if not depths.empty else None
        d_max = round(float(depths.max()), 1) if not depths.empty else None
        hours_after = round(
            (c_start.to_pydatetime() - prev_boundary).total_seconds() / 3600.0, 2
        )
        events.append(
            {
                "start_utc": _iso_z(c_start),
                "end_utc": _iso_z(c_end),
                "duration_s": round(duration_s, 1),
                "depth_min_m": d_min,
                "depth_max_m": d_max,
                "hours_after_prev_asc": hours_after,
            }
        )
    return total_s, events


def _thruster_on_mask(window: pd.DataFrame) -> pd.Series:
    power_on = pd.Series(False, index=window.index)
    cmd_on = pd.Series(False, index=window.index)
    if _POWER_COL in window.columns:
        power = pd.to_numeric(window[_POWER_COL], errors="coerce")
        power_on = power > 0
    if _CMD_COL in window.columns:
        cmd = pd.to_numeric(window[_CMD_COL], errors="coerce")
        cmd_on = cmd > 0
    return power_on.fillna(False) | cmd_on.fillna(False)


def analyze_thruster_in_interval(
    df: pd.DataFrame,
    start_utc: datetime,
    end_utc: datetime,
) -> ThrusterIntervalStats:
    """Return subsurface thruster Yes/No and usage stats for ``[start, end)``.

    Thruster-on samples are paired with nearest ``MDepth`` within
    ``DEPTH_ASOF_TOLERANCE``. Only samples with depth ``> SURFACE_BURST_MAX_DEPTH_M``
    count toward Yes / minutes / depth range / timed events. Missing associated
    depth does not count (conservative No when the interval has telemetry).
    """
    if df is None or df.empty or "Timestamp" not in df.columns:
        return _NO_PREV
    if _POWER_COL not in df.columns and _CMD_COL not in df.columns:
        return _NO_PREV

    start = _ensure_utc(start_utc)
    end = _ensure_utc(end_utc)
    if end <= start:
        return _NO_PREV

    work = df.copy()
    work["Timestamp"] = pd.to_datetime(work["Timestamp"], utc=True)
    work = work.sort_values("Timestamp")

    mask = (work["Timestamp"] >= start) & (work["Timestamp"] < end)
    window = work.loc[mask]
    if window.empty:
        return _NO_PREV

    on_mask = _thruster_on_mask(window)
    thruster_rows = window.loc[on_mask, ["Timestamp"]].copy()
    if thruster_rows.empty:
        return _NO_USE

    depth_lo = start - DEPTH_ASOF_TOLERANCE
    depth_hi = end + DEPTH_ASOF_TOLERANCE
    if _DEPTH_COL in work.columns:
        depth_src = work.loc[
            (work["Timestamp"] >= depth_lo) & (work["Timestamp"] <= depth_hi),
            ["Timestamp", _DEPTH_COL],
        ].copy()
        depth_src["depth_near"] = pd.to_numeric(depth_src[_DEPTH_COL], errors="coerce")
        depth_src = depth_src.loc[
            depth_src["depth_near"].notna(), ["Timestamp", "depth_near"]
        ]
        depth_src = depth_src.sort_values("Timestamp")
    else:
        depth_src = pd.DataFrame(columns=["Timestamp", "depth_near"])

    if depth_src.empty:
        return _NO_USE

    associated = pd.merge_asof(
        thruster_rows.sort_values("Timestamp"),
        depth_src,
        on="Timestamp",
        direction="nearest",
        tolerance=DEPTH_ASOF_TOLERANCE,
    )
    deep = associated.loc[
        associated["depth_near"].notna()
        & (associated["depth_near"] > SURFACE_BURST_MAX_DEPTH_M)
    ].copy()
    if deep.empty:
        return _NO_USE

    on_seconds, events = _cluster_thruster_events(deep, interval_start=start)
    depths = pd.to_numeric(deep["depth_near"], errors="coerce").dropna()
    return ThrusterIntervalStats(
        thruster_since_prev=True,
        thruster_on_minutes_gt3m=round(on_seconds / 60.0, 2),
        thruster_depth_min_m=round(float(depths.min()), 1) if not depths.empty else None,
        thruster_depth_max_m=round(float(depths.max()), 1) if not depths.empty else None,
        thruster_event_count=len(events),
        thruster_events=events,
    )


def thruster_used_in_interval(
    df: pd.DataFrame,
    start_utc: datetime,
    end_utc: datetime,
    *,
    power_col: str = _POWER_COL,
    cmd_col: str = _CMD_COL,
) -> Optional[bool]:
    """Return True/False/None for subsurface thruster use in ``[start, end)``.

    ``power_col`` / ``cmd_col`` are accepted for call-site compatibility; analysis
    always uses the standard dashboard columns.
    """
    _ = (power_col, cmd_col)
    return analyze_thruster_in_interval(df, start_utc, end_utc).thruster_since_prev


def enrich_dmon_asc_with_thruster(
    asc_payload: dict[str, Any],
    dashboard_df: pd.DataFrame,
) -> dict[str, Any]:
    """Attach thruster Yes/No + subsurface usage stats to each ASC file row.

    Files are expected in chronological order (as produced by
    ``normalize_dmon_asc_files``). The first file gets null thruster fields
    (no previous boundary). Rows with unparseable timestamps also get nulls.
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
            stats = _NO_PREV
        else:
            stats = analyze_thruster_in_interval(dashboard_df, prev_dt, this_dt)
        entry["thruster_since_prev"] = stats.thruster_since_prev
        entry["thruster_on_minutes_gt3m"] = stats.thruster_on_minutes_gt3m
        entry["thruster_depth_min_m"] = stats.thruster_depth_min_m
        entry["thruster_depth_max_m"] = stats.thruster_depth_max_m
        entry["thruster_event_count"] = stats.thruster_event_count
        entry["thruster_events"] = list(stats.thruster_events)
        enriched.append(entry)
        if this_dt is not None:
            prev_dt = this_dt

    out["files"] = enriched
    return out


def format_thruster_since_prev(value: Any, *, has_previous: bool) -> str:
    """Map boolean enricher value to a short Yes/No/No data label."""
    if not has_previous:
        return "—"
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return "No data"


def _format_depth_range(d_min: Any, d_max: Any) -> Optional[str]:
    try:
        if d_min is None or d_max is None:
            return None
        lo = float(d_min)
        hi = float(d_max)
        if abs(lo - hi) < 0.05:
            return f"{lo:.0f} m" if lo >= 10 else f"{lo:.1f} m"
        return f"{lo:.0f}–{hi:.0f} m" if hi >= 10 else f"{lo:.1f}–{hi:.1f} m"
    except (TypeError, ValueError):
        return None


def format_thruster_event_time_utc(event: dict[str, Any]) -> str:
    """UTC HH:MM (or HH:MM–HH:MM) for one cluster."""
    start_raw = str(event.get("start_utc") or "")
    end_raw = str(event.get("end_utc") or "")
    start_hm = start_raw[11:16] if len(start_raw) >= 16 else None
    end_hm = end_raw[11:16] if len(end_raw) >= 16 else None
    if not start_hm:
        return "—"
    if end_hm and end_hm != start_hm:
        return f"{start_hm}–{end_hm}Z"
    return f"{start_hm}Z"


def format_thruster_event_duration_label(event: dict[str, Any]) -> str:
    """Human-readable cluster duration."""
    try:
        duration_s = float(event.get("duration_s"))
    except (TypeError, ValueError):
        return "—"
    if duration_s < 60.0:
        return f"{duration_s:.0f} s"
    return f"{duration_s / 60.0:.1f} min"


def format_thruster_event_hhmm(event: dict[str, Any]) -> str:
    """Compact HH:MM UTC label for one thruster cluster (hour+minute precision)."""
    parts = [format_thruster_event_time_utc(event)]
    depth_label = _format_depth_range(event.get("depth_min_m"), event.get("depth_max_m"))
    if depth_label:
        parts.append(depth_label)
    hours_after = event.get("hours_after_prev_asc")
    try:
        if hours_after is not None:
            parts.append(f"+{float(hours_after):.1f}h")
    except (TypeError, ValueError):
        pass
    return " · ".join(parts)


def _thruster_event_count(row: dict[str, Any]) -> int:
    count = row.get("thruster_event_count")
    if count is not None:
        try:
            return max(0, int(count))
        except (TypeError, ValueError):
            pass
    events = row.get("thruster_events")
    return len(events) if isinstance(events, list) else 0


def format_thruster_since_prev_summary(
    row: Optional[dict[str, Any]],
    *,
    has_previous: bool,
) -> str:
    """Compact Yes/No summary with event count, minutes, and depth range."""
    if not has_previous:
        return "—"
    if not isinstance(row, dict):
        return "No data"
    flag = row.get("thruster_since_prev")
    if flag is True:
        parts = ["Yes"]
        event_count = _thruster_event_count(row)
        if event_count:
            noun = "event" if event_count == 1 else "events"
            parts.append(f"{event_count} {noun}")
        minutes = row.get("thruster_on_minutes_gt3m")
        if minutes is not None:
            try:
                parts.append(f"{float(minutes):.1f} min")
            except (TypeError, ValueError):
                pass
        depth_label = _format_depth_range(
            row.get("thruster_depth_min_m"), row.get("thruster_depth_max_m")
        )
        if depth_label:
            parts.append(depth_label)
        return " · ".join(parts)
    if flag is False:
        return "No"
    return "No data"


def format_thruster_since_prev_detail(
    row: Optional[dict[str, Any]],
    *,
    has_previous: bool,
) -> str:
    """Display label with subsurface minutes and depth range when Yes."""
    return format_thruster_since_prev_summary(row, has_previous=has_previous)


def build_thruster_event_pdf_rows(
    asc_files: list[dict[str, Any]],
    *,
    newest_first: bool = True,
) -> list[dict[str, Any]]:
    """Flatten ASC rows into one PDF table row per subsurface thruster cluster."""
    files = list(reversed(asc_files)) if newest_first else list(asc_files)
    rows: list[dict[str, Any]] = []
    for asc_row in files:
        if not isinstance(asc_row, dict):
            continue
        events = asc_row.get("thruster_events")
        if not isinstance(events, list) or not events:
            continue
        file_name = str(asc_row.get("fileName") or "—")
        for idx, event in enumerate(events, start=1):
            if not isinstance(event, dict):
                continue
            hours_after = event.get("hours_after_prev_asc")
            try:
                offset = f"+{float(hours_after):.1f}h" if hours_after is not None else "—"
            except (TypeError, ValueError):
                offset = "—"
            depth_label = _format_depth_range(
                event.get("depth_min_m"), event.get("depth_max_m")
            ) or "—"
            rows.append(
                {
                    "file": file_name,
                    "event_num": idx,
                    "time_utc": format_thruster_event_time_utc(event),
                    "duration": format_thruster_event_duration_label(event),
                    "depth": depth_label,
                    "hours_after_prev_asc": offset,
                }
            )
    return rows
