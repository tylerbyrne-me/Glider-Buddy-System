"""Shared latitude/longitude validation for telemetry tracks.

When a glider powers on before GPS lock, platforms often log exact (0, 0).
That point is real geographically (Gulf of Guinea) but is a sentinel for
"no fix" in our Wave Glider / Slocum / future platform pipelines — and it
destroys map extents and track-length calculations.

Slocum tracks also need GPS-quality and kinematics checks: ERDDAP
``latitude``/``longitude`` are often carried or dead-reckoned between sparse
``m_gps_status`` updates, which can place points tens of nautical miles off
the true track until the next valid surface fix.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Tuple, Union

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

LatLon = Union[float, int, np.floating, np.integer]


def is_null_island(lat: Any, lon: Any) -> bool:
    """True when both coordinates are exactly 0 (GPS-unlock sentinel)."""
    if lat is None or lon is None:
        return False
    try:
        if pd.isna(lat) or pd.isna(lon):
            return False
        return float(lat) == 0.0 and float(lon) == 0.0
    except (TypeError, ValueError):
        return False


# Slocum m_gps_status values that indicate an unusable fix for mapping.
# 2 = INVALID_FIX, 3 = WRONG_SENTENCE, -2 = BEST_GUESS_INVALID.
# Keep 0 (valid), 1 (first ignored valid), and -1 (best-guess ignored).
SLOCUM_GPS_STATUS_SUPPRESS = frozenset({2, 3, -2})

# Dead-reckoned / carried lat-lon between sparse GPS updates can drift tens of nm.
# Trust only status==0 anchors; mask intermediate points that imply impossible speed.
SLOCUM_TRACK_MAX_SPEED_KT = 3.0
SLOCUM_TRACK_MIN_JUMP_NM = 1.0
_EARTH_RADIUS_NM = 3440.065


def _haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlmb = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2.0) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2.0) ** 2
    return float(2.0 * _EARTH_RADIUS_NM * np.arcsin(np.minimum(1.0, np.sqrt(a))))


def mask_null_island_coordinates(
    df: pd.DataFrame,
    lat_col: str = "Latitude",
    lon_col: str = "Longitude",
) -> pd.DataFrame:
    """
    Set lat/lon to NaN where both are exactly 0.0.

    Preserves the row so non-position sensor columns remain available
    (important for Slocum dashboard bundles). Existing dropna(lat, lon)
    paths then exclude these points from maps and track metrics.
    """
    if df is None or df.empty:
        return df
    if lat_col not in df.columns or lon_col not in df.columns:
        return df

    lat = pd.to_numeric(df[lat_col], errors="coerce")
    lon = pd.to_numeric(df[lon_col], errors="coerce")
    mask = (lat == 0.0) & (lon == 0.0)
    if not mask.any():
        return df

    out = df.copy()
    out.loc[mask, lat_col] = np.nan
    out.loc[mask, lon_col] = np.nan
    logger.debug(
        "Masked %s null-island (0,0) coordinate row(s) in %s/%s",
        int(mask.sum()),
        lat_col,
        lon_col,
    )
    return out


def mask_invalid_slocum_gps_status(
    df: pd.DataFrame,
    lat_col: str = "Latitude",
    lon_col: str = "Longitude",
    status_col: str = "MGpsStatus",
) -> pd.DataFrame:
    """
    Set lat/lon to NaN where m_gps_status indicates an invalid fix.

    Suppresses statuses in ``SLOCUM_GPS_STATUS_SUPPRESS`` (2, 3, -2).
    If ``status_col`` is missing (older mirrors), returns ``df`` unchanged.
    Preserves the row so non-position sensor columns remain available.
    """
    if df is None or df.empty:
        return df
    if status_col not in df.columns:
        return df
    if lat_col not in df.columns or lon_col not in df.columns:
        return df

    status = pd.to_numeric(df[status_col], errors="coerce")
    mask = status.isin(SLOCUM_GPS_STATUS_SUPPRESS)
    if not mask.any():
        return df

    out = df.copy()
    out.loc[mask, lat_col] = np.nan
    out.loc[mask, lon_col] = np.nan
    logger.debug(
        "Masked %s invalid m_gps_status coordinate row(s) in %s/%s (status in %s)",
        int(mask.sum()),
        lat_col,
        lon_col,
        sorted(SLOCUM_GPS_STATUS_SUPPRESS),
    )
    return out


def mask_implausible_slocum_track_coordinates(
    df: pd.DataFrame,
    lat_col: str = "Latitude",
    lon_col: str = "Longitude",
    status_col: str = "MGpsStatus",
    time_col: str = "Timestamp",
    max_speed_kt: float = SLOCUM_TRACK_MAX_SPEED_KT,
    min_dist_nm: float = SLOCUM_TRACK_MIN_JUMP_NM,
) -> pd.DataFrame:
    """
    Mask lat/lon that imply an impossible speed from the last trusted GPS fix.

    ERDDAP ``latitude``/``longitude`` are often carried or dead-reckoned between
    sparse ``m_gps_status`` updates. Status filtering alone misses those rows
    (status is NaN). Only ``m_gps_status == 0`` advances the trusted anchor;
    intermediate points faster than ``max_speed_kt`` over ``min_dist_nm`` are
    NaN'd. A new status==0 fix is always kept (even after a large snap-back).
    """
    if df is None or df.empty:
        return df
    if lat_col not in df.columns or lon_col not in df.columns:
        return df
    if time_col not in df.columns:
        return df

    lat = pd.to_numeric(df[lat_col], errors="coerce")
    lon = pd.to_numeric(df[lon_col], errors="coerce")
    ts = pd.to_datetime(df[time_col], utc=True, errors="coerce")
    if status_col in df.columns:
        status = pd.to_numeric(df[status_col], errors="coerce")
    else:
        status = pd.Series(np.nan, index=df.index, dtype=float)

    order = np.argsort(ts.to_numpy(), kind="mergesort")
    mask_drop = np.zeros(len(df), dtype=bool)
    trusted_lat: Optional[float] = None
    trusted_lon: Optional[float] = None
    trusted_ts: Any = None
    masked_count = 0

    for pos in order:
        if pd.isna(lat.iloc[pos]) or pd.isna(lon.iloc[pos]) or pd.isna(ts.iloc[pos]):
            continue
        cur_lat = float(lat.iloc[pos])
        cur_lon = float(lon.iloc[pos])
        cur_ts = ts.iloc[pos]
        st = status.iloc[pos]
        is_gps0 = pd.notna(st) and float(st) == 0.0

        if trusted_lat is None:
            trusted_lat, trusted_lon, trusted_ts = cur_lat, cur_lon, cur_ts
            continue

        dt_h = (cur_ts - trusted_ts).total_seconds() / 3600.0
        if dt_h <= 0:
            continue
        dist_nm = _haversine_nm(trusted_lat, trusted_lon, cur_lat, cur_lon)
        speed_kt = dist_nm / dt_h
        implausible = dist_nm >= min_dist_nm and speed_kt > max_speed_kt

        if implausible and not is_gps0:
            mask_drop[pos] = True
            masked_count += 1
            continue

        if is_gps0:
            trusted_lat, trusted_lon, trusted_ts = cur_lat, cur_lon, cur_ts

    if not masked_count:
        return df

    out = df.copy()
    drop_labels = df.index.to_numpy()[mask_drop]
    out.loc[drop_labels, lat_col] = np.nan
    out.loc[drop_labels, lon_col] = np.nan
    logger.debug(
        "Masked %s implausible Slocum track coordinate row(s) "
        "(max_speed_kt=%s, min_dist_nm=%s)",
        masked_count,
        max_speed_kt,
        min_dist_nm,
    )
    return out


def drop_null_island_rows(
    df: pd.DataFrame,
    lat_col: str = "Latitude",
    lon_col: str = "Longitude",
) -> pd.DataFrame:
    """Return a copy without rows whose lat and lon are both exactly 0.0."""
    if df is None or df.empty:
        return df
    if lat_col not in df.columns or lon_col not in df.columns:
        return df

    lat = pd.to_numeric(df[lat_col], errors="coerce")
    lon = pd.to_numeric(df[lon_col], errors="coerce")
    mask = ~((lat == 0.0) & (lon == 0.0))
    dropped = int((~mask).sum())
    if dropped:
        logger.debug(
            "Dropped %s null-island (0,0) coordinate row(s) from %s/%s",
            dropped,
            lat_col,
            lon_col,
        )
    return df.loc[mask].copy()


def latest_valid_lat_lon(
    df: pd.DataFrame,
    lat_col: str = "Latitude",
    lon_col: str = "Longitude",
    time_col: Optional[str] = "Timestamp",
) -> Tuple[Optional[float], Optional[float], Any]:
    """
    Return the most recent non-null, non-(0,0) lat/lon (and optional timestamp).

    Returns ``(None, None, None)`` when no valid fix exists.
    """
    if df is None or df.empty:
        return None, None, None
    if lat_col not in df.columns or lon_col not in df.columns:
        return None, None, None

    work = mask_null_island_coordinates(df, lat_col=lat_col, lon_col=lon_col)
    work = work.dropna(subset=[lat_col, lon_col])
    if work.empty:
        return None, None, None

    if time_col and time_col in work.columns:
        work = work.sort_values(time_col)
    row = work.iloc[-1]
    ts = row[time_col] if time_col and time_col in work.columns else None
    return float(row[lat_col]), float(row[lon_col]), ts
