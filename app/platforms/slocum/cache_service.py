"""
Slocum data access layer: rolling mirror + on-demand overage windows.

Compatibility wrappers (`get_cached_or_fetch_dashboard_df`, `get_cached_or_fetch_ctd_df`)
delegate to the generic bundle loader so future sensors register once.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

import pandas as pd

from app.config import settings
from app.core.mission_aliases import resolve_slocum_dataset_id, resolve_slocum_dataset_ids
from app.core.infra.feature_toggles import is_feature_enabled
from .erddap_client import fetch_dataset_time_extent
from .mirror_service import (
    ensure_mirror_synced,
    load_mirror_df,
    sync_dataset_mirror,
)
from .overage_cache import (
    OverageRangeError,
    OverageRequest,
    OverageResult,
    get_bundle_dataframe,
    resolve_time_window_dataframe,
)

logger = logging.getLogger(__name__)

RequestContext = Literal["interactive", "report"]

_DATASETS_CACHE: dict[str, Any] | None = None
_DATASETS_CACHE_TIME: float = 0
_DATASETS_CACHE_TTL_SECONDS = 300

_DATA_LOCK: asyncio.Lock | None = None


def _get_data_lock() -> asyncio.Lock:
    global _DATA_LOCK
    if _DATA_LOCK is None:
        _DATA_LOCK = asyncio.Lock()
    return _DATA_LOCK


def get_datasets_cache() -> tuple[dict[str, Any] | None, float]:
    return _DATASETS_CACHE, _DATASETS_CACHE_TIME


def set_datasets_cache(response: dict[str, Any], cache_time: float) -> None:
    global _DATASETS_CACHE, _DATASETS_CACHE_TIME
    _DATASETS_CACHE = response
    _DATASETS_CACHE_TIME = cache_time


def datasets_cache_ttl_seconds() -> int:
    return _DATASETS_CACHE_TTL_SECONDS


def _round_time_end(now: Optional[datetime] = None) -> datetime:
    time_end = now or datetime.now(timezone.utc)
    window_min = max(1, settings.slocum_cache_window_minutes)
    t = time_end.replace(second=0, microsecond=0)
    return t - timedelta(minutes=t.minute % window_min)


def _iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_slocum_time_window(
    dataset_id: str,
    hours_back: int,
    is_historical: bool,
    start_date: Optional[str],
    end_date: Optional[str],
) -> tuple[Optional[str], Optional[str], bool]:
    """
    Compute display time window for chart/map/report requests.

    All modes return explicit bounded ISO timestamps (never unbounded ERDDAP pulls).
    """
    from .mirror_service import is_historical_dataset

    if not is_historical and is_historical_dataset(dataset_id):
        is_historical = True
    use_date_range = bool(start_date and end_date)
    if use_date_range:
        return (
            start_date.strip() if start_date else None,
            end_date.strip() if end_date else None,
            use_date_range,
        )
    if is_historical:
        resolved_for_extent = resolve_slocum_dataset_id(dataset_id)
        _, max_dt = fetch_dataset_time_extent(resolved_for_extent)
        if max_dt is None:
            time_end = datetime.now(timezone.utc)
        else:
            time_end = max_dt
        time_start = time_end - timedelta(hours=hours_back)
        return _iso_z(time_start), _iso_z(time_end), False
    time_end = _round_time_end()
    time_start = time_end - timedelta(hours=hours_back)
    return _iso_z(time_start), _iso_z(time_end), False


def slice_processed_df(
    processed: pd.DataFrame,
    *,
    hours_back: int,
    use_date_range: bool,
    time_start_str: Optional[str],
    time_end_str: Optional[str],
) -> pd.DataFrame:
    """Trim a processed DataFrame to the requested display window."""
    if processed is None or processed.empty or "Timestamp" not in processed.columns:
        return pd.DataFrame()
    df = processed.copy()
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], utc=True)
    if use_date_range and time_start_str and time_end_str:
        start_dt = pd.to_datetime(time_start_str, utc=True)
        end_dt = pd.to_datetime(time_end_str, utc=True)
        mask = (df["Timestamp"] >= start_dt) & (df["Timestamp"] <= end_dt)
        return df.loc[mask].copy()
    last_dt = df["Timestamp"].max()
    if pd.isna(last_dt):
        return pd.DataFrame()
    cutoff = last_dt - pd.Timedelta(hours=hours_back)
    return df.loc[df["Timestamp"] > cutoff].copy()


def _mirror_fallback_slice(
    dataset_id: str,
    bundle: str,
    *,
    hours_back: int,
    time_start_str: Optional[str],
    time_end_str: Optional[str],
) -> tuple[pd.DataFrame, Optional[str]]:
    """
    Slice on-disk mirror for the requested window.

    When the display window ends after the mirror tail, expand the slice end to
    ``mirror_max`` so stale-but-usable rows are returned instead of an empty chart.
    """
    df = load_mirror_df(dataset_id, bundle)
    if df.empty or "Timestamp" not in df.columns:
        return pd.DataFrame(), None
    use_date_range = bool(time_start_str and time_end_str)
    slice_start = time_start_str
    slice_end = time_end_str
    mirror_max_iso: Optional[str] = None
    ts = pd.to_datetime(df["Timestamp"], utc=True)
    mirror_max = ts.max()
    if pd.notna(mirror_max):
        mirror_max_iso = pd.Timestamp(mirror_max).strftime("%Y-%m-%dT%H:%M:%SZ")
        if use_date_range and time_end_str:
            end_dt = pd.to_datetime(time_end_str, utc=True)
            if mirror_max < end_dt:
                # Prefer overlap ending at mirror tail over empty [start, now] slice.
                if time_start_str:
                    start_dt = pd.to_datetime(time_start_str, utc=True)
                    if mirror_max < start_dt:
                        slice_start = mirror_max_iso
                slice_end = mirror_max_iso
    sliced = slice_processed_df(
        df,
        hours_back=hours_back,
        use_date_range=use_date_range,
        time_start_str=slice_start,
        time_end_str=slice_end,
    )
    return sliced, mirror_max_iso


async def get_cached_or_fetch_bundle_df(
    dataset_id: str,
    bundle: str,
    time_start_str: Optional[str],
    time_end_str: Optional[str],
    *,
    hours_back: int = 24,
    is_historical: bool = False,
    context: RequestContext = "interactive",
    return_metadata: bool = False,
) -> pd.DataFrame | None | OverageResult:
    """
    Generic bundle loader: rolling mirror when coverage allows, else 24h overage cache.

    When ``time_start_str``/``time_end_str`` are provided they define the window.
    Otherwise a hours_back window is computed from now (or historical extent).
    """
    dataset_id = resolve_slocum_dataset_id(dataset_id)
    try:
        if time_start_str and time_end_str:
            start = datetime.fromisoformat(time_start_str.replace("Z", "+00:00"))
            end = datetime.fromisoformat(time_end_str.replace("Z", "+00:00"))
            result = await get_bundle_dataframe(
                OverageRequest(
                    dataset_id=dataset_id,
                    bundle=bundle,
                    start_utc=start,
                    end_utc=end,
                    context=context,
                )
            )
        else:
            result = await resolve_time_window_dataframe(
                dataset_id=dataset_id,
                bundle=bundle,
                hours_back=hours_back,
                is_historical=is_historical,
                start_date=None,
                end_date=None,
                context=context,
            )
    except OverageRangeError:
        raise
    except Exception as err:
        logger.warning(
            "Bundle load failed for %s/%s; falling back to mirror slice: %s",
            dataset_id,
            bundle,
            err,
        )
        # Read mirror first so outages do not wait on ensure_mirror_synced → ERDDAP.
        sliced, mirror_max_iso = _mirror_fallback_slice(
            dataset_id,
            bundle,
            hours_back=hours_back,
            time_start_str=time_start_str,
            time_end_str=time_end_str,
        )
        try:
            await ensure_mirror_synced(
                dataset_id,
                hours_back=max(hours_back, getattr(settings, "slocum_mirror_retention_hours", 72)),
            )
        except Exception as sync_err:
            logger.warning(
                "Post-fallback mirror sync failed for %s/%s: %s",
                dataset_id,
                bundle,
                sync_err,
            )
        if sliced.empty:
            # Re-read after best-effort sync in case cold start just wrote parquet.
            sliced, mirror_max_iso = _mirror_fallback_slice(
                dataset_id,
                bundle,
                hours_back=hours_back,
                time_start_str=time_start_str,
                time_end_str=time_end_str,
            )
        if sliced.empty:
            empty_meta: dict[str, Any] = {
                "data_source": "mirror",
                "error": str(err),
                "stale": True,
            }
            if mirror_max_iso:
                empty_meta["mirror_max"] = mirror_max_iso
            return None if not return_metadata else OverageResult(df=pd.DataFrame(), metadata=empty_meta)
        meta: dict[str, Any] = {
            "data_source": "mirror",
            "fallback_error": str(err),
            "row_count": len(sliced),
            "stale": True,
        }
        if mirror_max_iso:
            meta["mirror_max"] = mirror_max_iso
        result = OverageResult(df=sliced, metadata=meta)

    # Empty primary result with a usable on-disk mirror → serve stale overlap.
    if (
        result is not None
        and (result.df is None or result.df.empty)
        and not (result.metadata or {}).get("fallback_error")
    ):
        sliced, mirror_max_iso = _mirror_fallback_slice(
            dataset_id,
            bundle,
            hours_back=hours_back,
            time_start_str=time_start_str,
            time_end_str=time_end_str,
        )
        if not sliced.empty:
            meta = {
                "data_source": "mirror",
                "fallback_error": "Empty overage/ERDDAP result; served mirror overlap",
                "row_count": len(sliced),
                "stale": True,
            }
            if mirror_max_iso:
                meta["mirror_max"] = mirror_max_iso
            result = OverageResult(df=sliced, metadata=meta)

    if return_metadata:
        return result
    return result.df if result.df is not None and not result.df.empty else None


async def get_cached_or_fetch_dashboard_df(
    dataset_id: str,
    time_start_str: Optional[str],
    time_end_str: Optional[str],
    *,
    hours_back: int = 24,
    is_historical: bool = False,
    context: RequestContext = "interactive",
) -> pd.DataFrame | None:
    """Load dashboard data (mirror + overage when needed)."""
    return await get_cached_or_fetch_bundle_df(
        dataset_id,
        "dashboard",
        time_start_str,
        time_end_str,
        hours_back=hours_back,
        is_historical=is_historical,
        context=context,
    )


async def get_cached_or_fetch_ctd_df(
    dataset_id: str,
    time_start_str: Optional[str],
    time_end_str: Optional[str],
    *,
    hours_back: int = 24,
    is_historical: bool = False,
    context: RequestContext = "interactive",
) -> pd.DataFrame | None:
    """Load CTD data (mirror + overage when needed)."""
    return await get_cached_or_fetch_bundle_df(
        dataset_id,
        "ctd",
        time_start_str,
        time_end_str,
        hours_back=hours_back,
        is_historical=is_historical,
        context=context,
    )


async def warm_active_slocum_datasets(hours_back: int | None = None) -> int:
    """
    Sync parquet mirrors for configured active Slocum datasets.
    Called on leader startup and by the background refresh job.
    """
    if not is_feature_enabled("slocum_platform"):
        return 0

    warm_hours = hours_back if hours_back is not None else getattr(settings, "slocum_warm_hours", 24)
    dataset_ids = resolve_slocum_dataset_ids(settings.active_slocum_datasets)
    if not dataset_ids:
        logger.info("SLOCUM WARM: No active Slocum datasets configured.")
        return 0

    warmed = 0
    for dataset_id in dataset_ids:
        try:
            await sync_dataset_mirror(dataset_id, hours_back=warm_hours)
            warmed += 1
            logger.debug("SLOCUM WARM: Synced mirror for %s", dataset_id)
        except Exception as err:
            logger.warning("SLOCUM WARM: Failed to sync %s: %s", dataset_id, err)
    logger.info(
        "SLOCUM WARM: Synced %s/%s active datasets (window=%sh)",
        warmed,
        len(dataset_ids),
        warm_hours,
    )
    return warmed
