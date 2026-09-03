"""Thruster activity between consecutive DMON ``*.asc`` offloads.

Enriches a normalized ASC payload (from ``normalize_dmon_asc_files``) with
``thruster_since_prev`` and subsurface usage stats using dashboard columns
``MThrusterPower`` / ``CThrusterOn`` / ``MDepth`` over ``[prev_mtime, this_mtime)``.

Surface-burst thruster use (associated depth ≤ ``SURFACE_BURST_MAX_DEPTH_M``) is
ignored so Yes means thruster activity that could affect the ASC at depth.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
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


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _cluster_on_seconds(timestamps: list[pd.Timestamp]) -> float:
    """Sum contiguous thruster-on cluster spans (gap ≤ CLUSTER_GAP_MAX)."""
    if not timestamps:
        return 0.0
    ordered = sorted(timestamps)
    floor_s = float(MIN_SAMPLE_DWELL.total_seconds())
    total = 0.0
    cluster_start = ordered[0]
    cluster_end = ordered[0]
    for ts in ordered[1:]:
        if ts - cluster_end <= CLUSTER_GAP_MAX:
            cluster_end = ts
            continue
        total += max((cluster_end - cluster_start).total_seconds(), floor_s)
        cluster_start = ts
        cluster_end = ts
    total += max((cluster_end - cluster_start).total_seconds(), floor_s)
    return total


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
    count toward Yes / minutes / depth range. Missing associated depth does not
    count (conservative No when the interval has telemetry).
    """
    empty = ThrusterIntervalStats(thruster_since_prev=None)
    if df is None or df.empty or "Timestamp" not in df.columns:
        return empty
    if _POWER_COL not in df.columns and _CMD_COL not in df.columns:
        return empty

    start = _ensure_utc(start_utc)
    end = _ensure_utc(end_utc)
    if end <= start:
        return empty

    work = df.copy()
    work["Timestamp"] = pd.to_datetime(work["Timestamp"], utc=True)
    work = work.sort_values("Timestamp")

    mask = (work["Timestamp"] >= start) & (work["Timestamp"] < end)
    window = work.loc[mask]
    if window.empty:
        return empty

    on_mask = _thruster_on_mask(window)
    thruster_rows = window.loc[on_mask, ["Timestamp"]].copy()
    if thruster_rows.empty:
        return ThrusterIntervalStats(thruster_since_prev=False)

    # Depth lookup: allow ±tolerance around the interval so edge thruster samples
    # can still associate a nearby depth sample.
    depth_lo = start - DEPTH_ASOF_TOLERANCE
    depth_hi = end + DEPTH_ASOF_TOLERANCE
    if _DEPTH_COL in work.columns:
        depth_src = work.loc[
            (work["Timestamp"] >= depth_lo) & (work["Timestamp"] <= depth_hi),
            ["Timestamp", _DEPTH_COL],
        ].copy()
        depth_src["depth_near"] = pd.to_numeric(depth_src[_DEPTH_COL], errors="coerce")
        depth_src = depth_src.loc[depth_src["depth_near"].notna(), ["Timestamp", "depth_near"]]
        depth_src = depth_src.sort_values("Timestamp")
    else:
        depth_src = pd.DataFrame(columns=["Timestamp", "depth_near"])

    if depth_src.empty:
        return ThrusterIntervalStats(thruster_since_prev=False)

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
    ]
    if deep.empty:
        return ThrusterIntervalStats(thruster_since_prev=False)

    on_seconds = _cluster_on_seconds(list(deep["Timestamp"]))
    depths = pd.to_numeric(deep["depth_near"], errors="coerce").dropna()
    return ThrusterIntervalStats(
        thruster_since_prev=True,
        thruster_on_minutes_gt3m=round(on_seconds / 60.0, 2),
        thruster_depth_min_m=round(float(depths.min()), 1) if not depths.empty else None,
        thruster_depth_max_m=round(float(depths.max()), 1) if not depths.empty else None,
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

    null_stats = ThrusterIntervalStats(thruster_since_prev=None)
    prev_dt: Optional[datetime] = None
    enriched: list[dict[str, Any]] = []
    for row in files:
        if not isinstance(row, dict):
            continue
        entry = dict(row)
        this_dt = _parse_sfmc_dt(entry.get("dateTimeModified"))
        if prev_dt is None or this_dt is None:
            stats = null_stats
        else:
            stats = analyze_thruster_in_interval(dashboard_df, prev_dt, this_dt)
        entry["thruster_since_prev"] = stats.thruster_since_prev
        entry["thruster_on_minutes_gt3m"] = stats.thruster_on_minutes_gt3m
        entry["thruster_depth_min_m"] = stats.thruster_depth_min_m
        entry["thruster_depth_max_m"] = stats.thruster_depth_max_m
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


def format_thruster_since_prev_detail(
    row: Optional[dict[str, Any]],
    *,
    has_previous: bool,
) -> str:
    """Display label with subsurface minutes and depth range when Yes."""
    if not has_previous:
        return "—"
    if not isinstance(row, dict):
        return "No data"
    flag = row.get("thruster_since_prev")
    if flag is True:
        parts = ["Yes"]
        minutes = row.get("thruster_on_minutes_gt3m")
        if minutes is not None:
            try:
                parts.append(f"{float(minutes):.1f} min")
            except (TypeError, ValueError):
                pass
        d_min = row.get("thruster_depth_min_m")
        d_max = row.get("thruster_depth_max_m")
        try:
            if d_min is not None and d_max is not None:
                lo = float(d_min)
                hi = float(d_max)
                if abs(lo - hi) < 0.05:
                    parts.append(f"{lo:.0f} m" if lo >= 10 else f"{lo:.1f} m")
                else:
                    parts.append(
                        f"{lo:.0f}–{hi:.0f} m" if hi >= 10 else f"{lo:.1f}–{hi:.1f} m"
                    )
        except (TypeError, ValueError):
            pass
        return " · ".join(parts)
    if flag is False:
        return "No"
    return "No data"
