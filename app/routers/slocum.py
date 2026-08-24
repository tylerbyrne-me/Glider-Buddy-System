"""
Slocum dataset listing, map integration, and dashboard chart API.

Provides endpoints to list active/config Slocum datasets, search ERDDAP,
and fetch chart data for the Slocum mission dashboard.
"""
import asyncio
import io
import json
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional

import matplotlib
matplotlib.use("Agg")
from matplotlib.colors import to_hex
import cmocean.cm as cmo
import numpy as np
import pandas as pd

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from ..config import settings
from ..core.auth import get_current_active_user, get_current_admin_user, require_platform_access
from ..core import models
from ..core.mission_aliases import (
    configured_slocum_dataset_keys,
    resolve_slocum_dataset_id,
)
from ..core.infra.feature_toggles import is_feature_enabled
from app.platforms.slocum.erddap_client import fetch_slocum_ctd_data, fetch_slocum_dashboard_data, list_slocum_datasets
from app.platforms.slocum.cache_service import (
    datasets_cache_ttl_seconds,
    get_cached_or_fetch_bundle_df,
    get_cached_or_fetch_ctd_df,
    get_cached_or_fetch_dashboard_df,
    get_datasets_cache,
    parse_slocum_time_window,
    set_datasets_cache,
    slice_processed_df,
)
from app.platforms.slocum.mirror_service import (
    dashboard_df_to_track_df,
    get_mirror_cache_status,
    inspect_mirror_dataset,
    load_mirror_df,
    sync_dataset_mirror,
)
from app.platforms.slocum.overage_cache import (
    OverageRangeError,
    OverageResult,
    get_overage_cache_status,
    purge_overage_entries,
)
from ..core.data import processors
from app.platforms.slocum.summaries import build_slocum_sensor_summaries
from ..core.infra.db import get_db_session, SQLModelSession

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/slocum",
    tags=["Slocum"],
    dependencies=[Depends(require_platform_access("slocum"))],
)

ERDDAP_REQUEST_TIMEOUT = 35  # Slightly above client timeout for asyncio.wait_for


def _dataset_row_to_dict(row: pd.Series) -> dict[str, Any]:
    """Convert a DataFrame row to a JSON-serializable dict."""
    out: dict[str, Any] = {}
    for k in row.index:
        v = row[k]
        if pd.isna(v):
            out[str(k)] = None
        elif hasattr(v, "isoformat"):
            out[str(k)] = v.isoformat()
        else:
            out[str(k)] = str(v)
    return out


# Map query variable to processed column name for chart API
def _build_datasets_response(df: pd.DataFrame | None, active_ids: list[str]) -> dict[str, Any]:
    """Build {active, available} response from DataFrame and active IDs."""
    if df is None or df.empty:
        active_list = [
            {"datasetID": did, "title": did, "institution": None, "minTime": None, "maxTime": None}
            for did in active_ids
        ]
        return {"active": active_list, "available": []}
    records = df.to_dict(orient="records")
    available = [_dataset_row_to_dict(pd.Series(r)) for r in records]
    dataset_id_col = "datasetID"
    if dataset_id_col not in df.columns and len(df.columns):
        dataset_id_col = df.columns[0]
    id_to_meta = {str(r.get(dataset_id_col, "")): r for r in records}
    resolved_active_ids = {resolve_slocum_dataset_id(did) for did in active_ids}
    active_list = []
    for did in active_ids:
        canonical = resolve_slocum_dataset_id(did)
        if canonical in id_to_meta:
            row = _dataset_row_to_dict(pd.Series(id_to_meta[canonical]))
            row["datasetID"] = did
            active_list.append(row)
        else:
            active_list.append({
                "datasetID": did,
                "title": did,
                "institution": None,
                "minTime": None,
                "maxTime": None,
            })
    available_only = [
        r for r in available
        if str(r.get("datasetID", "")) not in resolved_active_ids
        and str(r.get("datasetID", "")) not in set(active_ids)
    ]
    return {"active": active_list, "available": available_only}


@router.get("/datasets")
async def get_slocum_datasets(
    current_user: models.User = Depends(get_current_active_user),
):
    """
    Return combined list of Slocum datasets: active (from config) and available (from ERDDAP).
    Active datasets are those listed in settings.active_slocum_datasets; they appear first
    with metadata from ERDDAP when possible. Response is cached for 5 minutes.
    """
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Slocum platform is disabled (feature_toggles.slocum_platform).",
        )
    active_ids = configured_slocum_dataset_keys(settings.active_slocum_datasets)
    cached_response, cached_at = get_datasets_cache()
    now = time.monotonic()
    if cached_response is not None and (now - cached_at) < datasets_cache_ttl_seconds():
        return cached_response
    try:
        df = await asyncio.wait_for(
            asyncio.to_thread(list_slocum_datasets, None),
            timeout=ERDDAP_REQUEST_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("ERDDAP dataset list timed out")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="ERDDAP server did not respond in time. Try again later.",
        ) from None
    except Exception as e:
        logger.exception("Slocum list_slocum_datasets failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ERDDAP dataset list failed: {str(e)}",
        ) from e
    response = _build_datasets_response(df, active_ids)
    set_datasets_cache(response, now)
    return response


@router.get("/available_datasets", response_model=List[str])
async def get_available_datasets(
    current_user: models.User = Depends(get_current_active_user),
):
    """Get list of active Slocum dataset IDs (from config). Mirrors /api/available_missions."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Slocum platform is disabled (feature_toggles.slocum_platform).",
        )
    return configured_slocum_dataset_keys(settings.active_slocum_datasets)


@router.get("/available_historical_datasets", response_model=List[str])
async def get_available_historical_datasets(
    current_user: models.User = Depends(get_current_active_user),
):
    """Get list of historical Slocum dataset IDs (from config). Mirrors /api/available_historical_missions."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Slocum platform is disabled (feature_toggles.slocum_platform).",
        )
    return configured_slocum_dataset_keys(settings.historical_slocum_datasets)


@router.get("/datasets/search")
async def search_slocum_datasets(
    q: str = Query(..., min_length=1, description="Search term for dataset title"),
    current_user: models.User = Depends(get_current_active_user),
):
    """Search ERDDAP for Slocum datasets by title (case-insensitive)."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Slocum platform is disabled (feature_toggles.slocum_platform).",
        )
    try:
        df = await asyncio.wait_for(
            asyncio.to_thread(list_slocum_datasets, q),
            timeout=ERDDAP_REQUEST_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("ERDDAP dataset search timed out")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="ERDDAP server did not respond in time. Try again later.",
        ) from None
    except Exception as e:
        logger.exception("Slocum search failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ERDDAP search failed: {str(e)}",
        ) from e
    if df is None or df.empty:
        return {"datasets": []}
    records = df.to_dict(orient="records")
    datasets = [_dataset_row_to_dict(pd.Series(r)) for r in records]
    return {"datasets": datasets}


# Map query variable to processed column name for chart API
_parse_slocum_time_window = parse_slocum_time_window
_get_cached_or_fetch_dashboard_df = get_cached_or_fetch_dashboard_df
_get_cached_or_fetch_ctd_df = get_cached_or_fetch_ctd_df

_SLOCUM_VARIABLE_TO_COLUMN = {
    "m_depth": "MDepth",
    "m_altitude": "MAltitude",
    "m_raw_altitude": "MRawAltitude",
    "m_water_depth": "MWaterDepth",
    "c_pitch": "CPitch",
    "m_pitch": "MPitch",
    "m_roll": "MRoll",
    "c_roll": "CRoll",
    "c_heading": "CHeading",
    "m_heading": "MHeading",
    "c_fin": "CFin",
    "m_fin": "MFin",
    "m_battery": "MBattery",
    "m_coulomb_amphr_total": "MCoulombAmphrTotal",
    "m_coulomb_current": "MCoulombCurrent",
    "m_bms_pitch_current": "MBmsPitchCurrent",
    "m_bms_aft_current": "MBmsAftCurrent",
    "m_bms_ebay_current": "MBmsEbayCurrent",
    "m_speed": "MSpeed",
    "m_depth_rate_avg_final": "MDepthRateAvgFinal",
    "m_final_water_vx": "MFinalWaterVx",
    "m_final_water_vy": "MFinalWaterVy",
    "m_vacuum": "MVacuum",
    "m_leakdetect_voltage": "MLeakdetectVoltage",
    "m_leakdetect_voltage_forward": "MLeakdetectVoltageForward",
    "m_leakdetect_voltage_science": "MLeakdetectVoltageScience",
    "m_digifin_leakdetect_reading": "MDigifinLeakdetectReading",
    "m_thruster_power": "MThrusterPower",
    "c_thruster_on": "CThrusterOn",
    "sci_dmon_msg_byte_count": "SciDmonMsgByteCount",
    "conductivity": "Conductivity",
    "temperature": "Temperature",
    "pressure": "Pressure",
    "salinity": "Salinity",
    "density": "Density",
}

_SLOCUM_CTD_CHART_VARIABLES = ("conductivity", "temperature", "pressure", "salinity", "density")

# Derived chart keys computed from dashboard columns (not direct ERDDAP columns).
_SLOCUM_DERIVED_CHART_VARIABLES = frozenset({"coulomb_amphr_daily", "water_depth_altimeter", "water_current_speed"})

# CTD depth-vs-time profile variables for Chart.js scatter + cmocean color grading
_SLOCUM_PROFILE_VARIABLES = {
    "temperature": {"column": "Temperature", "unit": "°C"},
    "conductivity": {"column": "Conductivity", "unit": "S m-1"},
    "density": {"column": "Density", "unit": "kg m-3"},
}
_PROFILE_COLORMAP_STOPS = 64
_PROFILE_MAX_POINTS = 15000


def _colormap_hex_stops(cmap, n: int = _PROFILE_COLORMAP_STOPS) -> list[str]:
    """Sample a matplotlib/cmocean colormap into hex stops for client-side coloring."""
    if n < 2:
        return [to_hex(cmap(0.5))]
    return [to_hex(cmap(i / (n - 1))) for i in range(n)]


# Generated once at import; sent to the client with profile-data responses
_SLOCUM_PROFILE_COLORMAPS: dict[str, list[str]] = {
    "temperature": _colormap_hex_stops(cmo.thermal),
    "conductivity": _colormap_hex_stops(cmo.haline),
    "density": _colormap_hex_stops(cmo.dense),
}

# Processed DataFrame column (PascalCase) -> CSV header (snake_case)
_SLOCUM_CSV_COLUMN_RENAME = {
    "MDepth": "m_depth",
    "MAltitude": "m_altitude",
    "MRawAltitude": "m_raw_altitude",
    "MWaterDepth": "m_water_depth",
    "CPitch": "c_pitch",
    "MPitch": "m_pitch",
    "MRoll": "m_roll",
    "CRoll": "c_roll",
    "CHeading": "c_heading",
    "MHeading": "m_heading",
    "CFin": "c_fin",
    "MFin": "m_fin",
    "MBattery": "m_battery",
    "MCoulombAmphrTotal": "m_coulomb_amphr_total",
    "MCoulombCurrent": "m_coulomb_current",
    "MBmsPitchCurrent": "m_bms_pitch_current",
    "MBmsAftCurrent": "m_bms_aft_current",
    "MBmsEbayCurrent": "m_bms_ebay_current",
    "MSpeed": "m_speed",
    "MDepthRateAvgFinal": "m_depth_rate_avg_final",
    "MFinalWaterVx": "m_final_water_vx",
    "MFinalWaterVy": "m_final_water_vy",
    "MVacuum": "m_vacuum",
    "MLeakdetectVoltage": "m_leakdetect_voltage",
    "MLeakdetectVoltageForward": "m_leakdetect_voltage_forward",
    "MLeakdetectVoltageScience": "m_leakdetect_voltage_science",
    "MDigifinLeakdetectReading": "m_digifin_leakdetect_reading",
    "MThrusterPower": "m_thruster_power",
    "CThrusterOn": "c_thruster_on",
    "SciDmonMsgByteCount": "sci_dmon_msg_byte_count",
}

_SLOCUM_CHART_VARIABLES = [
    "m_depth", "m_altitude", "m_raw_altitude", "m_water_depth",
    "c_pitch", "m_pitch", "m_roll", "c_roll",
    "c_heading", "m_heading", "c_fin", "m_fin",
    "m_battery", "m_coulomb_amphr_total", "m_coulomb_current",
    "m_bms_pitch_current", "m_bms_aft_current", "m_bms_ebay_current",
    "m_speed", "m_depth_rate_avg_final",
    "m_final_water_vx", "m_final_water_vy",
    "m_vacuum",
    "m_leakdetect_voltage", "m_leakdetect_voltage_forward", "m_leakdetect_voltage_science",
    "m_digifin_leakdetect_reading",
    "m_thruster_power", "c_thruster_on",
    "sci_dmon_msg_byte_count",
    "coulomb_amphr_daily", "water_depth_altimeter", "water_current_speed",
    "conductivity", "temperature", "pressure", "salinity", "density",
]

# Reused in chart-data and CSV empty responses
_EMPTY_CACHE_METADATA = {"cache_timestamp": None, "last_data_timestamp": None, "file_modification_time": None}


def _cache_metadata(last_data_timestamp: Optional[str] = None) -> dict[str, Any]:
    """Build cache_metadata dict for chart/CSV responses."""
    return {**_EMPTY_CACHE_METADATA, "last_data_timestamp": last_data_timestamp}


def _merge_overage_metadata(
    base: dict[str, Any],
    overage_meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Attach overage/mirror source fields without breaking existing clients."""
    out = dict(base)
    if not overage_meta:
        return out
    for key in (
        "data_source",
        "requested_range",
        "normalized_range",
        "cache_created_at",
        "cache_expires_at",
        "cache_key",
        "bundle",
        "stale",
        "fallback_error",
        "mirror_max",
    ):
        if key in overage_meta:
            out[key] = overage_meta[key]
    return out


_DERIVED_CHART_LOOKBACK_HOURS = 36  # Rolling coulomb rate needs samples before the display window.
_MIRROR_RETENTION_HOURS = 72


def _mirror_max_iso(dataset_id: str, bundle: str = "dashboard") -> Optional[str]:
    """Latest Timestamp in the on-disk mirror, or None if empty."""
    try:
        df = load_mirror_df(dataset_id, bundle)
    except Exception:
        return None
    if df is None or df.empty or "Timestamp" not in df.columns:
        return None
    mirror_max = pd.to_datetime(df["Timestamp"], utc=True).max()
    if pd.isna(mirror_max):
        return None
    return pd.Timestamp(mirror_max).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compute_load_hours_back(
    hours_back: int,
    *,
    has_derived: bool = False,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> int:
    """
    Hours to fetch from mirror/overage (may exceed the display window).

    For hours_back mode, widen so stale mirror tails and derived lookback overlap.
    Date-range mode keeps ``hours_back`` as a span hint; callers shift fetch start instead.
    """
    load = hours_back
    if start_date and end_date:
        if has_derived:
            load = max(load, hours_back + _DERIVED_CHART_LOOKBACK_HOURS)
        return min(_MIRROR_RETENTION_HOURS, load) if has_derived else load
    # Widen load so stale mirror tails overlap the display window (24h vs 48h gap bug).
    load = max(load, min(_MIRROR_RETENTION_HOURS, hours_back + 24))
    if has_derived:
        # Prefer full mirror retention so a stale-anchored display still has lookback rows.
        load = max(load, hours_back + _DERIVED_CHART_LOOKBACK_HOURS, _MIRROR_RETENTION_HOURS)
    return min(_MIRROR_RETENTION_HOURS, load) if has_derived else load


def _widen_fetch_start_iso(time_start_str: str, lookback_hours: int) -> str:
    """Shift a display start ISO timestamp backward for derived-series lookback fetch."""
    start = datetime.fromisoformat(time_start_str.replace("Z", "+00:00"))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    widened = start.astimezone(timezone.utc) - timedelta(hours=lookback_hours)
    return widened.strftime("%Y-%m-%dT%H:%M:%SZ")


def _anchored_display_slice(
    full_df: pd.DataFrame,
    *,
    hours_back: int,
    time_start_str: Optional[str],
    time_end_str: Optional[str],
) -> tuple[pd.DataFrame, Optional[str], Optional[str]]:
    """
    Slice ``full_df`` to the display window; if that is empty but data exists,
    re-anchor the window to the data max timestamp (stale mirror tail).

    Also re-anchors when the mirror ends before the requested end (stale), even if
    a thin partial overlap exists — otherwise a 40h wall-clock window that only
    clips the last ~30m of a stale mirror would hide the rest of the cache.

    Returns ``(display_df, effective_start_iso, effective_end_iso)`` so derived
    series can be filtered to the same window charts use.
    """
    display_df = slice_processed_df(
        full_df,
        hours_back=hours_back,
        use_date_range=True,
        time_start_str=time_start_str,
        time_end_str=time_end_str,
    )
    if full_df.empty or "Timestamp" not in full_df.columns:
        return display_df, time_start_str, time_end_str
    data_max = pd.to_datetime(full_df["Timestamp"], utc=True).max()
    if pd.isna(data_max):
        return display_df, time_start_str, time_end_str

    should_anchor = display_df.empty
    if time_end_str:
        end_dt = pd.to_datetime(time_end_str, utc=True)
        # Mirror tail behind requested end → treat as stale and show last N hours of data.
        if data_max < end_dt - pd.Timedelta(minutes=1):
            should_anchor = True

    if not should_anchor:
        return display_df, time_start_str, time_end_str

    anchored_end = data_max
    anchored_start = anchored_end - pd.Timedelta(hours=hours_back)
    start_iso = anchored_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = anchored_end.strftime("%Y-%m-%dT%H:%M:%SZ")
    display_df = slice_processed_df(
        full_df,
        hours_back=hours_back,
        use_date_range=True,
        time_start_str=start_iso,
        time_end_str=end_iso,
    )
    return display_df, start_iso, end_iso


def _resolve_fetch_window(
    dataset_id: str,
    *,
    hours_back: int,
    is_historical: bool,
    start_date: Optional[str],
    end_date: Optional[str],
    has_derived: bool = False,
) -> tuple[str, str, str, str, int]:
    """
    Return ``(display_start, display_end, fetch_start, fetch_end, fetch_hours_back)``.

    Display bounds stay on the user-selected window; fetch may extend earlier for
    derived lookback / stale-tail overlap. When the on-disk mirror is behind
    wall-clock ``display_end``, fetch is anchored to ``mirror_max`` so lookback
    rows are taken from cached history rather than an empty future window.
    """
    display_start, display_end, _ = _parse_slocum_time_window(
        dataset_id, hours_back, is_historical, start_date, end_date
    )
    if not display_start or not display_end:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not resolve a bounded time window for this request.",
        )
    load_hours = _compute_load_hours_back(
        hours_back,
        has_derived=has_derived,
        start_date=start_date,
        end_date=end_date,
    )

    mirror_max = _mirror_max_iso(dataset_id, "dashboard")
    display_end_dt = datetime.fromisoformat(display_end.replace("Z", "+00:00"))
    if display_end_dt.tzinfo is None:
        display_end_dt = display_end_dt.replace(tzinfo=timezone.utc)
    mirror_is_stale = False
    if mirror_max:
        mirror_max_dt = datetime.fromisoformat(mirror_max.replace("Z", "+00:00"))
        if mirror_max_dt.tzinfo is None:
            mirror_max_dt = mirror_max_dt.replace(tzinfo=timezone.utc)
        mirror_is_stale = mirror_max_dt < display_end_dt - timedelta(minutes=1)

    if start_date and end_date:
        if mirror_is_stale and mirror_max:
            fetch_end = mirror_max
            fetch_start = _widen_fetch_start_iso(
                mirror_max,
                load_hours if has_derived else hours_back,
            )
        else:
            fetch_end = display_end
            if has_derived:
                lookback = min(_DERIVED_CHART_LOOKBACK_HOURS, _MIRROR_RETENTION_HOURS)
                fetch_start = _widen_fetch_start_iso(display_start, lookback)
            else:
                fetch_start = display_start
        return display_start, display_end, fetch_start, fetch_end, load_hours

    if mirror_is_stale and mirror_max:
        # Anchor fetch to mirror tail so stale interactive charts get lookback history.
        fetch_end = mirror_max
        fetch_start = _widen_fetch_start_iso(mirror_max, load_hours)
        return display_start, display_end, fetch_start, fetch_end, load_hours

    fetch_start, fetch_end, _ = _parse_slocum_time_window(
        dataset_id, load_hours, is_historical, None, None
    )
    return display_start, display_end, fetch_start or display_start, fetch_end or display_end, load_hours


async def _load_bundle_result(
    dataset_id: str,
    bundle: str,
    *,
    hours_back: int,
    is_historical: bool,
    start_date: Optional[str],
    end_date: Optional[str],
    fetch_hours_back: Optional[int] = None,
    fetch_start_date: Optional[str] = None,
    fetch_end_date: Optional[str] = None,
) -> OverageResult:
    """
    Load one bundle via mirror/overage; raise HTTPException for range/validation errors.

    ``hours_back`` / ``start_date`` / ``end_date`` define the caller display window.
    Optional ``fetch_*`` override the on-disk/ERDDAP fetch window (e.g. derived lookback).
    """
    if fetch_start_date and fetch_end_date:
        time_start_str, time_end_str = fetch_start_date, fetch_end_date
        load_hours = fetch_hours_back if fetch_hours_back is not None else hours_back
    elif fetch_hours_back is not None and fetch_hours_back != hours_back and not (start_date and end_date):
        time_start_str, time_end_str, _ = _parse_slocum_time_window(
            dataset_id, fetch_hours_back, is_historical, None, None
        )
        load_hours = fetch_hours_back
    else:
        time_start_str, time_end_str, _ = _parse_slocum_time_window(
            dataset_id, hours_back, is_historical, start_date, end_date
        )
        load_hours = hours_back
    try:
        result = await get_cached_or_fetch_bundle_df(
            dataset_id,
            bundle,
            time_start_str,
            time_end_str,
            hours_back=load_hours,
            is_historical=is_historical,
            context="interactive",
            return_metadata=True,
        )
    except OverageRangeError as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err)) from err
    if not isinstance(result, OverageResult):
        df = result if isinstance(result, pd.DataFrame) else pd.DataFrame()
        return OverageResult(df=df if df is not None else pd.DataFrame(), metadata={"data_source": "mirror"})
    return result


def _utc_iso_z(series: pd.Series) -> pd.Series:
    """Format timestamps as explicit UTC ISO 8601 with trailing Z (avoids browser local reinterpretation)."""
    return pd.to_datetime(series, utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _filter_records_to_time_window(
    records: list[dict[str, Any]],
    time_start_str: Optional[str],
    time_end_str: Optional[str],
) -> list[dict[str, Any]]:
    if not records or not time_start_str or not time_end_str:
        return records
    start_dt = pd.to_datetime(time_start_str, utc=True)
    end_dt = pd.to_datetime(time_end_str, utc=True)
    filtered: list[dict[str, Any]] = []
    for row in records:
        ts = row.get("Timestamp")
        if ts is None:
            continue
        pt = pd.to_datetime(ts, utc=True)
        if start_dt <= pt <= end_dt:
            filtered.append(row)
    return filtered


def _resample_series(
    processed: pd.DataFrame,
    value_col: str,
    granularity_minutes: Optional[int],
) -> list[dict[str, Any]]:
    if processed.empty or value_col not in processed.columns:
        return []
    recent = processed.set_index("Timestamp")
    series = recent[value_col].astype(float)
    if granularity_minutes and granularity_minutes > 0:
        out_df = series.resample(f"{granularity_minutes}min").mean().reset_index()
    else:
        out_df = series.reset_index()
    out_df = out_df.rename(columns={value_col: "Value"})
    out_df["Timestamp"] = _utc_iso_z(out_df["Timestamp"])
    out_df = out_df.replace({np.nan: None})
    return out_df.to_dict(orient="records")


def _chart_df_for_variable(df: pd.DataFrame, variable: str, value_col: str) -> pd.DataFrame:
    """Copy + filter water-depth sentinels/spikes so chart axes are not pulled below 0."""
    if variable != "m_water_depth" or value_col not in df.columns:
        return df
    work = df.copy()
    work[value_col] = processors.filter_valid_water_depth_m(work[value_col])
    return work


def _series_records_from_index(
    series: pd.Series,
) -> list[dict[str, Any]]:
    """Convert a Timestamp-indexed Series into chart ``{Timestamp, Value}`` records."""
    if series is None or series.empty:
        return []
    out_df = series.rename("Value").reset_index()
    ts_col = out_df.columns[0]
    out_df["Timestamp"] = _utc_iso_z(out_df[ts_col])
    out_df = out_df[["Timestamp", "Value"]].replace({np.nan: None})
    return out_df.to_dict(orient="records")


def _derive_coulomb_amphr_daily(
    processed: pd.DataFrame,
    granularity_minutes: Optional[int] = None,
) -> list[dict[str, Any]]:
    """
    Rolling AmpHr/day consumption matching checklist ``compute_amphr_usage_rate``.

    At each output timestamp ``t``, find the nearest sample near ``t - 24h`` and
    emit ``(v_now - v_prior) * (24 / hours_elapsed)``. Preferred lookback is
    [12h, 36h]. Shorter positive lags (≥6h) are still accepted and rate-normalized
    the same way weekly report incomplete calendar days are — this fills the start
    of a display window when the mirror has limited pre-window history.
    Negative deltas (counter reset) are null.
    """
    from app.platforms.slocum.checklist_autofill import compute_amphr_usage_rate

    if processed.empty or "Timestamp" not in processed.columns:
        return []
    if "MCoulombAmphrTotal" not in processed.columns:
        return []
    working = processed[["Timestamp", "MCoulombAmphrTotal"]].dropna(subset=["Timestamp"]).copy()
    if working.empty:
        return []
    working["MCoulombAmphrTotal"] = pd.to_numeric(working["MCoulombAmphrTotal"], errors="coerce")
    working = working.dropna(subset=["MCoulombAmphrTotal"]).sort_values("Timestamp")
    if working.empty:
        return []

    working = working.set_index("Timestamp")
    # Deduplicate index (keep last) so asof/loc stay scalar.
    series = working["MCoulombAmphrTotal"].astype(float)
    if not series.index.is_unique:
        series = series.groupby(level=0).last()

    if granularity_minutes and granularity_minutes > 0:
        sample_series = series.resample(f"{granularity_minutes}min").last().dropna()
    else:
        sample_series = series

    if sample_series.empty:
        return []

    ts_values = series.index.to_numpy(dtype="datetime64[ns]")
    amp_values = series.to_numpy(dtype=float)
    lookback = np.timedelta64(24, "h")
    # Prefer ~24h lookback; allow ≥6h (rate-normalized) so stale/short mirrors
    # still populate the start of the display window (report incomplete-day spirit).
    min_lag = np.timedelta64(6, "h")
    max_lag = np.timedelta64(36, "h")

    rates: list[float] = []
    out_ts: list[Any] = []
    for t, v_now in sample_series.items():
        t64 = np.datetime64(pd.Timestamp(t).to_datetime64())
        target = t64 - lookback
        prior_mask = ts_values < t64
        if not prior_mask.any():
            rates.append(float("nan"))
            out_ts.append(t)
            continue
        prior_ts = ts_values[prior_mask]
        prior_amps = amp_values[prior_mask]
        idx = int(np.abs(prior_ts - target).argmin())
        prior_t = prior_ts[idx]
        lag = t64 - prior_t
        if lag < min_lag or lag > max_lag:
            rates.append(float("nan"))
            out_ts.append(t)
            continue
        hours_elapsed = float(lag / np.timedelta64(1, "h"))
        rate = compute_amphr_usage_rate(float(v_now), float(prior_amps[idx]), hours_elapsed)
        rates.append(float(rate) if rate is not None else float("nan"))
        out_ts.append(t)

    result = pd.Series(rates, index=pd.DatetimeIndex(out_ts), dtype=float)
    return _series_records_from_index(result)


def _derive_water_depth_altimeter(processed: pd.DataFrame, granularity_minutes: Optional[int]) -> list[dict[str, Any]]:
    """Water depth estimate: ``MDepth + MAltitude`` when both present."""
    if processed.empty or "Timestamp" not in processed.columns:
        return []
    if "MDepth" not in processed.columns or "MAltitude" not in processed.columns:
        return []
    working = processed[["Timestamp", "MDepth", "MAltitude"]].copy()
    working["WaterDepthAltimeter"] = (
        pd.to_numeric(working["MDepth"], errors="coerce")
        + pd.to_numeric(working["MAltitude"], errors="coerce")
    )
    return _resample_series(working, "WaterDepthAltimeter", granularity_minutes)


def _derive_water_current_speed(processed: pd.DataFrame, granularity_minutes: Optional[int]) -> list[dict[str, Any]]:
    """Depth-averaged current magnitude from ``MFinalWaterVx`` / ``MFinalWaterVy``."""
    if processed.empty or "Timestamp" not in processed.columns:
        return []
    if "MFinalWaterVx" not in processed.columns or "MFinalWaterVy" not in processed.columns:
        return []
    working = processed[["Timestamp", "MFinalWaterVx", "MFinalWaterVy"]].copy()
    vx = pd.to_numeric(working["MFinalWaterVx"], errors="coerce")
    vy = pd.to_numeric(working["MFinalWaterVy"], errors="coerce")
    working["WaterCurrentSpeed"] = np.sqrt(vx.pow(2) + vy.pow(2))
    return _resample_series(working, "WaterCurrentSpeed", granularity_minutes)


def _build_derived_series(
    processed: pd.DataFrame,
    variable: str,
    granularity_minutes: Optional[int],
) -> list[dict[str, Any]]:
    if variable == "coulomb_amphr_daily":
        return _derive_coulomb_amphr_daily(processed, granularity_minutes)
    if variable == "water_depth_altimeter":
        return _derive_water_depth_altimeter(processed, granularity_minutes)
    if variable == "water_current_speed":
        return _derive_water_current_speed(processed, granularity_minutes)
    return []


def _last_dt_from_processed(processed: pd.DataFrame) -> Optional[datetime]:
    """Extract last Timestamp from processed dashboard DataFrame as timezone-aware datetime."""
    if processed.empty or "Timestamp" not in processed.columns:
        return None
    max_ts = processed["Timestamp"].max()
    if pd.isna(max_ts):
        return None
    if hasattr(max_ts, "to_pydatetime"):
        last_dt = max_ts.to_pydatetime()
    else:
        last_dt = pd.to_datetime(max_ts, utc=True)
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=timezone.utc)
    return last_dt


# Single source for CSV empty/header-only content (must match _SLOCUM_CSV_COLUMN_RENAME keys)
_SLOCUM_CSV_EMPTY_HEADER = (
    "Timestamp,m_depth,m_altitude,m_raw_altitude,m_water_depth,"
    "c_pitch,m_pitch,m_roll,c_roll,c_heading,m_heading,c_fin,m_fin,"
    "m_battery,m_coulomb_amphr_total,m_coulomb_current,"
    "m_bms_pitch_current,m_bms_aft_current,m_bms_ebay_current,"
    "m_speed,m_depth_rate_avg_final,m_final_water_vx,m_final_water_vy,"
    "m_vacuum,m_leakdetect_voltage,m_leakdetect_voltage_forward,m_leakdetect_voltage_science,"
    "m_digifin_leakdetect_reading,m_thruster_power,c_thruster_on\n"
)


@router.get("/cache-status/{dataset_id}")
async def get_slocum_cache_status(
    dataset_id: str,
    current_user: models.User = Depends(get_current_active_user),
):
    """Mirror cache status for Slocum dashboard/CTD bundles (frontend polling)."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Slocum platform is disabled.")
    status_payload = get_mirror_cache_status(dataset_id)
    return status_payload


@router.get("/sfmc/connection-durations/{dataset_id}")
async def get_slocum_sfmc_connection_durations(
    dataset_id: str,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """
    Cached SFMC surface-call connection durations for Vehicle Health charts.

    Reads the SFMC snapshot only (no live SFMC HTTP). Returns an empty list
    with ``sfmc_configured=false`` when SFMC credentials are not set.
    """
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Slocum platform is disabled.")

    from ..core.sfmc_cache_service import get_cached_connection_durations
    from app.platforms.slocum.deployment_service import resolve_deployment_for_dataset

    deployment = resolve_deployment_for_dataset(session, dataset_id)
    if deployment is None:
        return {
            "connections": [],
            "sfmc_configured": False,
            "fetched_at_utc": None,
            "fetch_error": "No deployment found for dataset",
        }

    durations, fetched_at, fetch_error, configured = get_cached_connection_durations(
        session, deployment.id
    )
    return {
        "connections": durations,
        "sfmc_configured": configured,
        "fetched_at_utc": fetched_at.isoformat() if fetched_at else None,
        "fetch_error": fetch_error,
    }


@router.get("/sfmc/dmon-asc-files/{dataset_id}")
async def get_slocum_sfmc_dmon_asc_files(
    dataset_id: str,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """
    Cached SFMC ``from-glider`` ``*.asc`` listing for DMON sensor card / checklist.

    Reads the SFMC snapshot only (no live SFMC HTTP). Enriches each file with
    ``thruster_since_prev`` from the dashboard mirror over the interval since
    the previous ``*.asc`` (when telemetry is available).
    """
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Slocum platform is disabled.")

    from ..core.sfmc_cache_service import get_cached_dmon_asc_files
    from ..core.sfmc_transforms import DMON_ASC_WINDOW_HOURS
    from app.platforms.slocum.deployment_service import resolve_deployment_for_dataset
    from app.platforms.slocum.dmon_asc_thruster import enrich_dmon_asc_with_thruster

    deployment = resolve_deployment_for_dataset(session, dataset_id)
    if deployment is None:
        return {
            "files": [],
            "hours_since_last": None,
            "has_gap_over_16h": False,
            "file_count": 0,
            "summary": "No deployment found for dataset",
            "sfmc_configured": False,
            "fetched_at_utc": None,
            "fetch_error": "No deployment found for dataset",
        }

    payload, fetched_at, fetch_error, configured = get_cached_dmon_asc_files(
        session, deployment.id
    )
    if not isinstance(payload, dict):
        payload = {}

    resolved_id = resolve_slocum_dataset_id(dataset_id)
    try:
        dashboard_df = await get_cached_or_fetch_dashboard_df(
            resolved_id,
            None,
            None,
            hours_back=int(DMON_ASC_WINDOW_HOURS),
            context="interactive",
        )
        if dashboard_df is None:
            dashboard_df = pd.DataFrame()
        payload = enrich_dmon_asc_with_thruster(payload, dashboard_df)
    except Exception as err:
        logger.debug(
            "DMON ASC thruster enrich skipped for %s: %s",
            resolved_id,
            err,
        )

    files = payload.get("files") if isinstance(payload.get("files"), list) else []
    return {
        "files": files,
        "hours_since_last": payload.get("hours_since_last"),
        "has_gap_over_16h": bool(payload.get("has_gap_over_16h")),
        "file_count": int(payload.get("file_count") or len(files)),
        "summary": payload.get("summary") or "",
        "sfmc_configured": configured,
        "fetched_at_utc": fetched_at.isoformat() if fetched_at else None,
        "fetch_error": fetch_error,
    }


@router.get("/dmon/review/{dataset_id}")
async def get_slocum_dmon_review(
    dataset_id: str,
    recent_hours: float = Query(48.0, ge=0, description="Recent window in hours for dashboard table"),
    start_date: Optional[str] = Query(None, description="ISO date (inclusive) for report filtering"),
    end_date: Optional[str] = Query(None, description="ISO date (inclusive) for report filtering"),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """
    Cached Robots4Whales daily analyst-review detections for a Slocum dataset.

    Reads disk cache only (leader job refreshes). Attribution includes Analysts for
    reporting consumers; dashboard UI should show site/program credit only.
    """
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Slocum platform is disabled.")

    from datetime import date as date_cls

    from app.platforms.slocum.deployment_service import resolve_deployment_for_dataset
    from app.platforms.slocum.dmon_review import (
        default_attribution,
        filter_dmon_review,
        get_cached_dmon_review,
    )
    from app.core.mission_aliases import resolved_slocum_mission_key

    deployment = resolve_deployment_for_dataset(session, dataset_id)
    source_url = (deployment.robots4whales_url if deployment else None) or None
    configured = bool(source_url and str(source_url).strip())
    empty_attr = default_attribution(source_url=source_url)
    if deployment is None:
        return {
            "configured": False,
            "source_url": None,
            "fetched_at_utc": None,
            "attribution": empty_attr,
            "species": [],
            "recent": [],
            "all": [],
            "summary": {"detected_species_recent": []},
            "meta": {"message": "No deployment found for dataset"},
        }

    mission_key = (
        deployment.mission_key
        or resolved_slocum_mission_key(dataset_id)
        or ""
    )
    cached = get_cached_dmon_review(mission_key) if mission_key else None

    parsed_start = None
    parsed_end = None
    if start_date:
        try:
            parsed_start = date_cls.fromisoformat(start_date[:10])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid start_date; use YYYY-MM-DD") from exc
    if end_date:
        try:
            parsed_end = date_cls.fromisoformat(end_date[:10])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid end_date; use YYYY-MM-DD") from exc

    filtered = filter_dmon_review(
        cached,
        start_date=parsed_start,
        end_date=parsed_end,
        recent_hours=recent_hours if recent_hours > 0 else None,
    )
    if not configured:
        filtered["attribution"] = empty_attr
        filtered["meta"] = {
            **(filtered.get("meta") or {}),
            "message": "Configure Robots4Whales URL in Mission Overviews",
        }
    elif cached is None:
        filtered["meta"] = {
            **(filtered.get("meta") or {}),
            "message": "Waiting for first sync",
        }
    # Prefer live deployment URL over stale cache URL
    if source_url:
        filtered["source_url"] = source_url
        if isinstance(filtered.get("attribution"), dict):
            filtered["attribution"]["source_url"] = source_url

    return {
        "configured": configured,
        "source_url": filtered.get("source_url") or source_url,
        "fetched_at_utc": filtered.get("fetched_at_utc"),
        "attribution": filtered.get("attribution") or empty_attr,
        "species": filtered.get("species") or [],
        "recent": filtered.get("recent") or [],
        "all": filtered.get("all") or [],
        "summary": filtered.get("summary") or {"detected_species_recent": []},
        "meta": filtered.get("meta") or {},
    }


@router.get("/sensor-summaries/{dataset_id}")
async def get_slocum_sensor_summaries(
    dataset_id: str,
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    """
    Left-nav sensor card summaries (values + mini_trend) for enabled Slocum cards.
    Used for soft refresh when mirror cache advances without a full page reload.
    """
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Slocum platform is disabled.")

    # Import here to avoid circular import at module load (home imports summaries only).
    from .home import _resolve_slocum_enabled_sensor_cards

    enabled_cards = _resolve_slocum_enabled_sensor_cards(
        session,
        dataset_id,
        username=current_user.username if current_user else "system",
    )
    summaries = build_slocum_sensor_summaries(dataset_id, enabled_cards)
    return summaries.get("sensors") or {}


@router.get("/cache-inspect/{dataset_id}")
async def inspect_slocum_dataset_cache(
    dataset_id: str,
    hours_back: int = Query(72, ge=1, le=8760),
    current_admin: models.User = Depends(get_current_admin_user),
):
    """
    Admin Cached Dataset Inspector: mirror row counts, column non-nulls, and
    profile-ready science point counts for the selected hours window.
    """
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Slocum platform is disabled.")

    report = inspect_mirror_dataset(dataset_id, hours_back=hours_back)
    report["overage"] = get_overage_cache_status(dataset_id)

    # Profile point count from the current mirror (no ERDDAP round-trip)
    try:
        ctd_df = load_mirror_df(dataset_id, "ctd")
        sliced = slice_processed_df(
            ctd_df,
            hours_back=hours_back,
            use_date_range=False,
            time_start_str=None,
            time_end_str=None,
        )
        profile = _build_profile_payload(sliced)
        report["profile"] = {
            "points": len(profile.get("points") or []),
            "ranges": profile.get("ranges") or {},
            "units": profile.get("units") or {},
        }
    except Exception as err:
        logger.warning("Cache inspect profile summary failed for %s: %s", dataset_id, err)
        report["profile"] = {"points": 0, "error": str(err)}

    return report


@router.post("/mirror/{dataset_id}/sync")
async def force_sync_slocum_mirror(
    dataset_id: str,
    rebuild_ctd: bool = Query(
        True,
        description="Clear and re-fetch CTD without ERDDAP orderByClosest so dive profiles are preserved.",
    ),
    hours_back: Optional[int] = Query(None, ge=1, le=8760),
    current_admin: models.User = Depends(get_current_admin_user),
):
    """Admin: force an ERDDAP mirror sync (optionally rebuild undecimated CTD)."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Slocum platform is disabled.")
    try:
        summary = await sync_dataset_mirror(
            dataset_id,
            hours_back=hours_back,
            force=True,
            rebuild_ctd=rebuild_ctd,
        )
    except Exception as err:
        logger.exception("Forced Slocum mirror sync failed for %s", dataset_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(err)) from err
    logger.info(
        "Admin '%s' forced mirror sync for %s (rebuild_ctd=%s)",
        current_admin.username,
        dataset_id,
        rebuild_ctd,
    )
    return summary


@router.post("/erddap-poke")
async def poke_slocum_erddap(
    dataset_id: Optional[str] = Query(
        None,
        description="Poke one dataset (alias OK). Omit to poke all active warm keys.",
    ),
    sync_if_new: bool = Query(
        True,
        description="Run an incremental mirror sync when allDatasets maxTime advanced.",
    ),
    hours_back: Optional[int] = Query(None, ge=1, le=8760),
    current_admin: models.User = Depends(get_current_admin_user),
):
    """Admin: cheap ERDDAP maxTime poke; sync only when Ocean Track has new data."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Slocum platform is disabled.")
    from app.platforms.slocum.erddap_poke import poke_active_slocum_datasets, poke_dataset

    try:
        if dataset_id and dataset_id.strip():
            result = await poke_dataset(
                dataset_id.strip(),
                hours_back=hours_back,
                sync_if_new=sync_if_new,
                use_cache=False,
            )
            summary = {
                "poked": 1,
                "synced": 1 if result.get("action") == "synced" else 0,
                "skipped": 1 if result.get("action") in {"skipped", "new_data"} else 0,
                "errors": 1 if result.get("action") == "error" else 0,
                "datasets": [result],
            }
        else:
            summary = await poke_active_slocum_datasets(
                hours_back=hours_back,
                sync_if_new=sync_if_new,
                use_cache=False,
            )
    except Exception as err:
        logger.exception("Admin ERDDAP poke failed (dataset_id=%s)", dataset_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(err)) from err
    logger.info(
        "Admin '%s' ERDDAP poke (dataset_id=%s, sync_if_new=%s, synced=%s)",
        current_admin.username,
        dataset_id,
        sync_if_new,
        summary.get("synced"),
    )
    return summary


@router.get("/overage-cache/status")
async def get_slocum_overage_cache_status(
    dataset_id: Optional[str] = Query(None),
    current_admin: models.User = Depends(get_current_admin_user),
):
    """Admin: list temporary overage-cache entries and hit/miss counters."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Slocum platform is disabled.")
    return get_overage_cache_status(dataset_id)


@router.post("/overage-cache/purge")
async def purge_slocum_overage_cache(
    dataset_id: Optional[str] = Query(None, description="Limit purge to one dataset; omit for all."),
    force_all: bool = Query(False, description="Remove valid entries too (not only expired)."),
    current_admin: models.User = Depends(get_current_admin_user),
):
    """Admin: purge expired/corrupt overage entries (or wipe a dataset's temporary cache)."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Slocum platform is disabled.")
    summary = purge_overage_entries(dataset_id=dataset_id, force_all=force_all)
    logger.info(
        "Admin '%s' purged Slocum overage cache (dataset_id=%s, force_all=%s, removed=%s)",
        current_admin.username,
        dataset_id,
        force_all,
        summary.get("removed_files"),
    )
    return summary


def _profile_depth_series(df: pd.DataFrame) -> pd.Series:
    """Prefer Depth (m); fall back to Pressure (dbar ≈ m) for science samples without Depth."""
    if "Depth" in df.columns:
        depth = pd.to_numeric(df["Depth"], errors="coerce")
    else:
        depth = pd.Series(np.nan, index=df.index, dtype=float)
    if "Pressure" in df.columns:
        pressure = pd.to_numeric(df["Pressure"], errors="coerce")
        depth = depth.fillna(pressure)
    return depth


def _nice_colorbar_range(series: pd.Series) -> dict[str, Optional[int]]:
    """
    Robust color-scale bounds for profile charts.

    Uses the central 2nd–98th percentile so outliers (e.g. zeroed conductivity)
    do not flatten the cmocean gradient, then snaps outward to whole-number
    colorbar labels (e.g. 10, 36, 1024).
    """
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return {"min": None, "max": None}

    if len(values) >= 8:
        lo = float(values.quantile(0.02))
        hi = float(values.quantile(0.98))
    else:
        lo = float(values.min())
        hi = float(values.max())

    if not math.isfinite(lo) or not math.isfinite(hi):
        return {"min": None, "max": None}
    if lo > hi:
        lo, hi = hi, lo
    if lo == hi:
        # Degenerate span: pad by 1 unit around the value
        center = lo
        lo = center - 0.5
        hi = center + 0.5

    nice_min = int(math.floor(lo))
    nice_max = int(math.ceil(hi))
    if nice_min == nice_max:
        nice_max = nice_min + 1
    return {"min": nice_min, "max": nice_max}


def _build_profile_payload(sliced: pd.DataFrame) -> dict[str, Any]:
    """
    Build Chart.js-ready profile payload from a sliced CTD DataFrame.
    Depth uses Depth with Pressure fallback; rows without depth are dropped.
    Decimates by stride when the window exceeds _PROFILE_MAX_POINTS (mean
    resampling would destroy vertical profile structure).
    """
    empty = {
        "points": [],
        "ranges": {key: {"min": None, "max": None} for key in _SLOCUM_PROFILE_VARIABLES},
        "colormaps": dict(_SLOCUM_PROFILE_COLORMAPS),
        "units": {key: cfg["unit"] for key, cfg in _SLOCUM_PROFILE_VARIABLES.items()},
    }
    if sliced is None or sliced.empty or "Timestamp" not in sliced.columns:
        return empty

    work = sliced.copy()
    work["depth"] = _profile_depth_series(work)
    work = work.dropna(subset=["depth"])
    if work.empty:
        return empty

    for key, cfg in _SLOCUM_PROFILE_VARIABLES.items():
        col = cfg["column"]
        if col in work.columns:
            work[key] = pd.to_numeric(work[col], errors="coerce")
        else:
            work[key] = np.nan

    # Keep rows that have at least one profile variable
    value_cols = list(_SLOCUM_PROFILE_VARIABLES.keys())
    work = work.dropna(subset=value_cols, how="all")
    if work.empty:
        return empty

    if len(work) > _PROFILE_MAX_POINTS:
        stride = int(np.ceil(len(work) / _PROFILE_MAX_POINTS))
        work = work.iloc[::stride].copy()

    ts = pd.to_datetime(work["Timestamp"], utc=True, errors="coerce")
    valid_ts = ts.notna()
    work = work.loc[valid_ts].copy()
    ts = ts.loc[valid_ts]
    if work.empty:
        return empty

    out = pd.DataFrame({
        "t": _utc_iso_z(ts),
        "depth": work["depth"].astype(float),
    })
    for key in value_cols:
        out[key] = work[key].astype(float)
    out = out.replace({np.nan: None})
    points = out.to_dict(orient="records")

    ranges: dict[str, dict[str, Optional[int]]] = {}
    for key in value_cols:
        ranges[key] = _nice_colorbar_range(work[key])

    return {
        "points": points,
        "ranges": ranges,
        "colormaps": dict(_SLOCUM_PROFILE_COLORMAPS),
        "units": {key: cfg["unit"] for key, cfg in _SLOCUM_PROFILE_VARIABLES.items()},
    }


def _build_depth_overlay_records(dashboard_df: pd.DataFrame) -> list[dict[str, Any]]:
    """Dashboard ``MDepth`` track for CTD background overlay (same shape as chart series)."""
    if dashboard_df is None or dashboard_df.empty:
        return []
    if "Timestamp" not in dashboard_df.columns or "MDepth" not in dashboard_df.columns:
        return []
    working = dashboard_df[["Timestamp", "MDepth"]].dropna(subset=["Timestamp"]).copy()
    if working.empty:
        return []
    working["MDepth"] = pd.to_numeric(working["MDepth"], errors="coerce")
    working = working.dropna(subset=["MDepth"]).sort_values("Timestamp")
    if working.empty:
        return []
    if len(working) > _PROFILE_MAX_POINTS:
        stride = int(np.ceil(len(working) / _PROFILE_MAX_POINTS))
        working = working.iloc[::stride].copy()
    working["Timestamp"] = _utc_iso_z(pd.to_datetime(working["Timestamp"], utc=True))
    working = working.rename(columns={"MDepth": "Value"}).replace({np.nan: None})
    return working[["Timestamp", "Value"]].to_dict(orient="records")


@router.get("/profile-data/{dataset_id}")
async def get_slocum_profile_data(
    dataset_id: str,
    hours_back: int = Query(24, ge=1, le=8760),
    is_historical: bool = Query(False),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    current_user: models.User = Depends(get_current_active_user),
):
    """
    CTD depth-vs-time profile points for Chart.js scatter charts.
    Returns temperature, conductivity, and density with cmocean colormap stops.
    Also includes dashboard ``m_depth`` as ``depth_overlay`` for the background layer.
    Time-mean resampling is not applied (it would destroy profile structure);
    large windows are stride-decimated instead.
    """
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Slocum platform is disabled.")

    display_start, display_end, fetch_start, fetch_end, load_hours = _resolve_fetch_window(
        dataset_id,
        hours_back=hours_back,
        is_historical=is_historical,
        start_date=start_date,
        end_date=end_date,
        has_derived=False,
    )

    try:
        ctd_result, dashboard_result = await asyncio.gather(
            _load_bundle_result(
                dataset_id,
                "ctd",
                hours_back=hours_back,
                is_historical=is_historical,
                start_date=start_date,
                end_date=end_date,
                fetch_hours_back=load_hours,
                fetch_start_date=fetch_start,
                fetch_end_date=fetch_end,
            ),
            _load_bundle_result(
                dataset_id,
                "dashboard",
                hours_back=hours_back,
                is_historical=is_historical,
                start_date=start_date,
                end_date=end_date,
                fetch_hours_back=load_hours,
                fetch_start_date=fetch_start,
                fetch_end_date=fetch_end,
            ),
            return_exceptions=True,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Slocum profile data fetch failed for %s", dataset_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Data fetch failed: {str(e)}") from e

    if isinstance(ctd_result, HTTPException):
        raise ctd_result
    if isinstance(ctd_result, Exception):
        logger.exception("Slocum profile CTD fetch failed for %s", dataset_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Data fetch failed: {str(ctd_result)}",
        ) from ctd_result

    depth_overlay: list[dict[str, Any]] = []
    if isinstance(dashboard_result, Exception):
        logger.warning(
            "Slocum profile depth overlay load failed for %s: %s",
            dataset_id,
            dashboard_result,
        )
    else:
        dash_full = dashboard_result.df if dashboard_result.df is not None else pd.DataFrame()
        dash_df, _, _ = _anchored_display_slice(
            dash_full,
            hours_back=hours_back,
            time_start_str=display_start,
            time_end_str=display_end,
        )
        depth_overlay = _build_depth_overlay_records(dash_df)

    ctd_full = ctd_result.df if ctd_result.df is not None else pd.DataFrame()
    sliced, _, _ = _anchored_display_slice(
        ctd_full,
        hours_back=hours_back,
        time_start_str=display_start,
        time_end_str=display_end,
    )
    if sliced.empty:
        payload = _build_profile_payload(pd.DataFrame())
        payload["depth_overlay"] = depth_overlay
        payload["cache_metadata"] = _merge_overage_metadata(_cache_metadata(), ctd_result.metadata)
        return payload

    last_dt = _last_dt_from_processed(sliced)
    payload = _build_profile_payload(sliced)
    payload["depth_overlay"] = depth_overlay
    payload["cache_metadata"] = _merge_overage_metadata(
        _cache_metadata(last_dt.isoformat() if last_dt else None),
        ctd_result.metadata,
    )
    return payload


@router.get("/chart-data-bulk/{dataset_id}")
async def get_slocum_chart_data_bulk(
    dataset_id: str,
    variables: str = Query(..., description="Comma-separated variable names"),
    hours_back: int = Query(24, ge=1, le=8760),
    granularity_minutes: Optional[int] = Query(15, ge=0, le=60),
    is_historical: bool = Query(False),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    current_user: models.User = Depends(get_current_active_user),
):
    """Fetch multiple Slocum chart variables in one request (one mirror read, one resample pass)."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Slocum platform is disabled.")

    requested = [v.strip() for v in variables.split(",") if v.strip()]
    invalid = [v for v in requested if v not in _SLOCUM_CHART_VARIABLES]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown variables: {', '.join(invalid)}",
        )

    ctd_vars = [v for v in requested if v in _SLOCUM_CTD_CHART_VARIABLES]
    derived_vars = [v for v in requested if v in _SLOCUM_DERIVED_CHART_VARIABLES]
    dash_vars = [
        v for v in requested
        if v not in _SLOCUM_CTD_CHART_VARIABLES and v not in _SLOCUM_DERIVED_CHART_VARIABLES
    ]
    needs_dashboard = bool(dash_vars or derived_vars)

    display_start, display_end, fetch_start, fetch_end, load_hours = _resolve_fetch_window(
        dataset_id,
        hours_back=hours_back,
        is_historical=is_historical,
        start_date=start_date,
        end_date=end_date,
        has_derived=bool(derived_vars),
    )
    time_start_str, time_end_str = display_start, display_end

    try:
        dashboard_result = None
        ctd_result = None
        if needs_dashboard:
            dashboard_result = await _load_bundle_result(
                dataset_id,
                "dashboard",
                hours_back=hours_back,
                is_historical=is_historical,
                start_date=start_date,
                end_date=end_date,
                fetch_hours_back=load_hours,
                fetch_start_date=fetch_start,
                fetch_end_date=fetch_end,
            )
        if ctd_vars:
            _, _, ctd_fetch_start, ctd_fetch_end, ctd_load = _resolve_fetch_window(
                dataset_id,
                hours_back=hours_back,
                is_historical=is_historical,
                start_date=start_date,
                end_date=end_date,
                has_derived=False,
            )
            ctd_result = await _load_bundle_result(
                dataset_id,
                "ctd",
                hours_back=hours_back,
                is_historical=is_historical,
                start_date=start_date,
                end_date=end_date,
                fetch_hours_back=ctd_load,
                fetch_start_date=ctd_fetch_start,
                fetch_end_date=ctd_fetch_end,
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Slocum bulk chart data fetch failed for %s", dataset_id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Data fetch failed: {str(e)}") from e

    series: dict[str, list[dict[str, Any]]] = {}
    last_dt: Optional[datetime] = None
    source_meta: dict[str, Any] = {}
    display_df = pd.DataFrame()

    if needs_dashboard and dashboard_result is not None and not dashboard_result.df.empty:
        full_df = dashboard_result.df
        display_df, filter_start, filter_end = _anchored_display_slice(
            full_df,
            hours_back=hours_back,
            time_start_str=time_start_str,
            time_end_str=time_end_str,
        )
        last_dt = _last_dt_from_processed(display_df) or _last_dt_from_processed(full_df)
        source_meta = dashboard_result.metadata or source_meta
        for variable in dash_vars:
            value_col = _SLOCUM_VARIABLE_TO_COLUMN[variable]
            chart_df = _chart_df_for_variable(display_df, variable, value_col)
            series[variable] = _resample_series(chart_df, value_col, granularity_minutes)
        for variable in derived_vars:
            derived_records = _build_derived_series(full_df, variable, granularity_minutes)
            series[variable] = _filter_records_to_time_window(
                derived_records, filter_start, filter_end,
            )

    if ctd_vars and ctd_result is not None and not ctd_result.df.empty:
        sliced, _, _ = _anchored_display_slice(
            ctd_result.df,
            hours_back=hours_back,
            time_start_str=time_start_str,
            time_end_str=time_end_str,
        )
        ctd_last = _last_dt_from_processed(sliced)
        if ctd_last and (last_dt is None or ctd_last > last_dt):
            last_dt = ctd_last
        source_meta = ctd_result.metadata or source_meta
        for variable in ctd_vars:
            value_col = _SLOCUM_VARIABLE_TO_COLUMN[variable]
            series[variable] = _resample_series(sliced, value_col, granularity_minutes)

    for variable in requested:
        series.setdefault(variable, [])

    return {
        "series": series,
        "cache_metadata": _merge_overage_metadata(
            _cache_metadata(last_dt.isoformat() if last_dt else None),
            source_meta,
        ),
    }


@router.get("/chart-data/{dataset_id}")
async def get_slocum_chart_data(
    dataset_id: str,
    variable: str = Query(..., description="Variable to plot"),
    hours_back: int = Query(24, ge=1, le=8760, description="Hours of data (used when start_date/end_date not provided)"),
    granularity_minutes: Optional[int] = Query(15, ge=0, le=60, description="Resampling interval (minutes). 0 = show all data (no resampling)."),
    is_historical: bool = Query(False, description="If true, fetch full dataset and show last N hours from data end (like WG historical)."),
    start_date: Optional[str] = Query(None, description="Start time ISO 8601 (e.g. 2025-08-01T00:00:00Z). Use with end_date for date range."),
    end_date: Optional[str] = Query(None, description="End time ISO 8601 (e.g. 2025-08-31T23:59:59Z). Use with start_date for date range."),
    current_user: models.User = Depends(get_current_active_user),
):
    """
    Fetch Slocum ERDDAP data for one dashboard variable and return resampled series
    for charting. Supports dashboard variables, derived series, and CTD science vars.
    """
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Slocum platform is disabled (feature_toggles.slocum_platform).",
        )
    if variable not in _SLOCUM_CHART_VARIABLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown variable: {variable}",
        )
    is_ctd = variable in _SLOCUM_CTD_CHART_VARIABLES
    is_derived = variable in _SLOCUM_DERIVED_CHART_VARIABLES
    display_start, display_end, fetch_start, fetch_end, load_hours = _resolve_fetch_window(
        dataset_id,
        hours_back=hours_back,
        is_historical=is_historical,
        start_date=start_date,
        end_date=end_date,
        has_derived=is_derived,
    )
    try:
        result = await _load_bundle_result(
            dataset_id,
            "ctd" if is_ctd else "dashboard",
            hours_back=hours_back,
            is_historical=is_historical,
            start_date=start_date,
            end_date=end_date,
            fetch_hours_back=load_hours,
            fetch_start_date=fetch_start,
            fetch_end_date=fetch_end,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Slocum chart data fetch failed for %s", dataset_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Data fetch failed: {str(e)}",
        ) from e

    full_df = result.df if result.df is not None else pd.DataFrame()
    if full_df.empty or "Timestamp" not in full_df.columns:
        return {
            "data": [],
            "cache_metadata": _merge_overage_metadata(_cache_metadata(), result.metadata),
        }

    display_df, filter_start, filter_end = _anchored_display_slice(
        full_df,
        hours_back=hours_back,
        time_start_str=display_start,
        time_end_str=display_end,
    )
    last_dt = _last_dt_from_processed(display_df) or _last_dt_from_processed(full_df)
    if is_derived:
        derived_records = _build_derived_series(full_df, variable, granularity_minutes)
        data = _filter_records_to_time_window(derived_records, filter_start, filter_end)
    else:
        value_col = _SLOCUM_VARIABLE_TO_COLUMN[variable]
        if value_col not in display_df.columns:
            return {
                "data": [],
                "cache_metadata": _merge_overage_metadata(
                    _cache_metadata(last_dt.isoformat() if last_dt else None),
                    result.metadata,
                ),
            }
        data = _resample_series(
            _chart_df_for_variable(display_df, variable, value_col),
            value_col,
            granularity_minutes,
        )
    return {
        "data": data,
        "cache_metadata": _merge_overage_metadata(
            _cache_metadata(last_dt.isoformat() if last_dt else None),
            result.metadata,
        ),
    }


@router.get("/csv/{dataset_id}")
async def get_slocum_csv(
    dataset_id: str,
    hours_back: int = Query(24, ge=1, le=8760, description="Hours of data (used when start_date/end_date not provided)"),
    granularity_minutes: Optional[int] = Query(15, ge=0, le=60, description="Resampling interval (minutes). 0 = show all data (no resampling)."),
    is_historical: bool = Query(False, description="If true, fetch full dataset and trim to last N hours from data end."),
    start_date: Optional[str] = Query(None, description="Start time ISO 8601. Use with end_date for date range."),
    end_date: Optional[str] = Query(None, description="End time ISO 8601. Use with start_date for date range."),
    current_user: models.User = Depends(get_current_active_user),
):
    """
    Download Slocum dashboard data (all variables) as CSV for the same time window and
    granularity as the chart controls. Uses same auth and feature toggle as chart-data.
    """
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Slocum platform is disabled (feature_toggles.slocum_platform).",
        )
    time_start_str, time_end_str, use_date_range = _parse_slocum_time_window(
        dataset_id, hours_back, is_historical, start_date, end_date
    )
    try:
        dash_result = await _load_bundle_result(
            dataset_id,
            "dashboard",
            hours_back=hours_back,
            is_historical=is_historical,
            start_date=start_date,
            end_date=end_date,
        )
        processed = dash_result.df
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Slocum CSV fetch failed for %s", dataset_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Data fetch failed: {str(e)}",
        ) from e

    def _empty_csv_response() -> StreamingResponse:
        buf = io.StringIO()
        buf.write(_SLOCUM_CSV_EMPTY_HEADER)
        buf.seek(0)
        filename = f"slocum_{dataset_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
        return StreamingResponse(
            io.BytesIO(buf.getvalue().encode("utf-8")),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if processed is None or processed.empty or "Timestamp" not in processed.columns:
        return _empty_csv_response()

    last_dt = _last_dt_from_processed(processed)
    if last_dt is None:
        return _empty_csv_response()

    recent = slice_processed_df(
        processed,
        hours_back=hours_back,
        use_date_range=use_date_range,
        time_start_str=time_start_str,
        time_end_str=time_end_str,
    )
    if recent.empty:
        return _empty_csv_response()

    recent = recent.set_index("Timestamp")
    numeric_cols = [c for c in recent.columns if c in _SLOCUM_CSV_COLUMN_RENAME]
    if not numeric_cols:
        numeric_cols = recent.select_dtypes(include=["number"]).columns.tolist()
    if granularity_minutes and granularity_minutes > 0:
        out_df = recent[numeric_cols].resample(f"{granularity_minutes}min").mean().reset_index()
    else:
        out_df = recent[numeric_cols].reset_index()
    out_df["Timestamp"] = _utc_iso_z(out_df["Timestamp"])
    out_df = out_df.rename(columns=_SLOCUM_CSV_COLUMN_RENAME)
    output = io.StringIO()
    out_df.to_csv(output, index=False)
    output.seek(0)
    filename = f"slocum_{dataset_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/data/{variable}/{dataset_id}")
async def get_slocum_data_shim(
    dataset_id: str,
    variable: str,
    hours_back: int = Query(72, ge=1, le=8760),
    granularity_minutes: Optional[int] = Query(15, ge=0, le=60),
    is_historical: bool = Query(False),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    current_user: models.User = Depends(get_current_active_user),
):
    """WG-style shim: ``/api/slocum/data/{variable}/{dataset_id}`` mirrors ``/api/data/{type}/{mission}``."""
    return await get_slocum_chart_data(
        dataset_id=dataset_id,
        variable=variable,
        hours_back=hours_back,
        granularity_minutes=granularity_minutes,
        is_historical=is_historical,
        start_date=start_date,
        end_date=end_date,
        current_user=current_user,
    )


@router.get("/forecast/{dataset_id}")
async def get_slocum_forecast(
    dataset_id: str,
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    is_historical: bool = Query(False),
    current_user: models.User = Depends(get_current_active_user),
):
    """Open-Meteo forecast at dataset last known position (mirrors WG ``/api/forecast``)."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=403, detail="Slocum platform is disabled.")
    if is_historical:
        raise HTTPException(status_code=400, detail="Forecasts are not available for historical datasets.")
    final_lat, final_lon = lat, lon
    if final_lat is None or final_lon is None:
        time_start, time_end, _ = _parse_slocum_time_window(dataset_id, 24, False, None, None)
        processed = await _get_cached_or_fetch_dashboard_df(
            dataset_id, time_start, time_end, hours_back=24
        )
        track_df = dashboard_df_to_track_df(processed) if processed is not None else pd.DataFrame()
        if not track_df.empty and "Latitude" in track_df.columns:
            last = track_df.dropna(subset=["Latitude", "Longitude"]).iloc[-1]
            final_lat, final_lon = float(last["Latitude"]), float(last["Longitude"])
    if final_lat is None or final_lon is None:
        raise HTTPException(status_code=400, detail="Lat/lon required and could not be inferred from track.")
    from ..core.geo import forecast as geo_forecast
    forecast_data = await geo_forecast.get_general_meteo_forecast(final_lat, final_lon)
    if forecast_data is None:
        raise HTTPException(status_code=503, detail="Forecast service unavailable.")
    return forecast_data


@router.get("/marine_forecast/{dataset_id}")
async def get_slocum_marine_forecast(
    dataset_id: str,
    lat: Optional[float] = Query(None),
    lon: Optional[float] = Query(None),
    is_historical: bool = Query(False),
    current_user: models.User = Depends(get_current_active_user),
):
    """Marine forecast at dataset last known position (mirrors WG ``/api/marine_forecast``)."""
    if not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=403, detail="Slocum platform is disabled.")
    if is_historical:
        raise HTTPException(status_code=400, detail="Marine forecasts are not available for historical datasets.")
    final_lat, final_lon = lat, lon
    if final_lat is None or final_lon is None:
        time_start, time_end, _ = _parse_slocum_time_window(dataset_id, 24, False, None, None)
        processed = await _get_cached_or_fetch_dashboard_df(
            dataset_id, time_start, time_end, hours_back=24
        )
        track_df = dashboard_df_to_track_df(processed) if processed is not None else pd.DataFrame()
        if not track_df.empty:
            last = track_df.dropna(subset=["Latitude", "Longitude"]).iloc[-1]
            final_lat, final_lon = float(last["Latitude"]), float(last["Longitude"])
    if final_lat is None or final_lon is None:
        raise HTTPException(status_code=400, detail="Lat/lon required and could not be inferred from track.")
    from ..core.geo import forecast as geo_forecast
    marine_data = await geo_forecast.get_marine_meteo_forecast(final_lat, final_lon)
    if marine_data is None:
        raise HTTPException(status_code=503, detail="Marine forecast service unavailable.")
    return marine_data
