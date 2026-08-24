"""
Cheap ERDDAP “poke” for Slocum datasets.

Uses allDatasets ``maxTime`` (one metadata query for the active set) to notice
when Ocean Track has processed new files, then runs a full incremental mirror
sync only for datasets whose tail advanced. Aligns Buddy refresh with Ocean
Track’s ~3h processing cadence without a dashboard/CTD/checklist pull every tick.

Wave Glider realtime is not on ERDDAP yet. When it is, lift the probe (not the
parquet refresh) into core — see ``docs/wiki/how-tos/erddap_poke.md``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pandas as pd

from app.config import settings
from app.core.infra.feature_toggles import is_feature_enabled
from app.core.mission_aliases import resolve_slocum_dataset_id, resolve_slocum_dataset_ids
from app.platforms.slocum.erddap_client import (
    _parse_erddap_time,
    fetch_dataset_time_extent,
    list_slocum_datasets,
)
from app.platforms.slocum.mirror_service import (
    dashboard_mirror_exists,
    is_historical_dataset,
    read_mirror_meta,
    sync_dataset_mirror,
    update_mirror_meta,
)

logger = logging.getLogger(__name__)

# Ignore sub-second / rounding jitter between allDatasets and parquet tails.
_NEW_DATA_EPSILON = timedelta(seconds=1)


def _iso_z(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: object) -> Optional[datetime]:
    return _parse_erddap_time(value)


def _column_by_prefix(df: pd.DataFrame, prefix: str) -> Optional[str]:
    needle = prefix.lower().replace(" ", "")
    for col in df.columns:
        if str(col).lower().replace(" ", "").startswith(needle):
            return str(col)
    return None


def parse_alldatasets_max_times(df: pd.DataFrame) -> dict[str, datetime]:
    """Map datasetID → maxTime from an allDatasets tabledap frame."""
    if df is None or df.empty:
        return {}
    id_col = _column_by_prefix(df, "datasetid")
    max_col = _column_by_prefix(df, "maxtime")
    if not id_col or not max_col:
        return {}
    out: dict[str, datetime] = {}
    for _, row in df.iterrows():
        dataset_id = str(row[id_col]).strip() if row[id_col] is not None else ""
        if not dataset_id or dataset_id.lower() == "nan":
            continue
        max_dt = _parse_erddap_time(row[max_col])
        if max_dt is not None:
            out[dataset_id] = max_dt
    return out


def known_mirror_max_time(dataset_id: str) -> Optional[datetime]:
    """Best local tail: parquet ``last_data_timestamp``, else last poked ERDDAP max."""
    meta = read_mirror_meta(dataset_id)
    return _parse_iso(meta.get("last_data_timestamp")) or _parse_iso(meta.get("erddap_max_time"))


def has_new_erddap_data(
    erddap_max: Optional[datetime],
    known_max: Optional[datetime],
    *,
    has_mirror: bool,
) -> bool:
    """True when ERDDAP’s tail is ahead of the local mirror (or there is no mirror)."""
    if not has_mirror or known_max is None:
        return erddap_max is not None
    if erddap_max is None:
        return False
    return erddap_max > (known_max + _NEW_DATA_EPSILON)


def _has_dashboard_mirror(dataset_id: str) -> bool:
    if read_mirror_meta(dataset_id).get("last_data_timestamp"):
        return True
    return dashboard_mirror_exists(dataset_id)


def _record_poke(
    dataset_id: str,
    *,
    erddap_max: Optional[datetime],
    has_new: bool,
    action: str,
    error: Optional[str] = None,
) -> None:
    now = datetime.now(timezone.utc)
    updates: dict[str, Any] = {
        "last_poke_timestamp": now.isoformat(),
        "erddap_max_time": _iso_z(erddap_max),
        "last_poke_has_new": has_new,
        "last_poke_action": action,
    }
    if error:
        updates["last_poke_error"] = error
    else:
        updates["last_poke_error"] = None
    try:
        update_mirror_meta(dataset_id, updates)
    except Exception as err:
        logger.warning("SLOCUM POKE: failed to write meta for %s: %s", dataset_id, err)


def _empty_result(dataset_id: str, *, reason: str, action: str = "skipped") -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "erddap_max_time": None,
        "known_max_time": None,
        "has_new_data": False,
        "action": action,
        "reason": reason,
    }


def _build_result(
    dataset_id: str,
    *,
    erddap_max: Optional[datetime],
    known_max: Optional[datetime],
    has_new: bool,
    action: str,
    reason: str,
    sync_summary: Optional[dict[str, Any]] = None,
    error: Optional[str] = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "dataset_id": dataset_id,
        "erddap_max_time": _iso_z(erddap_max),
        "known_max_time": _iso_z(known_max),
        "has_new_data": has_new,
        "action": action,
        "reason": reason,
    }
    if sync_summary is not None:
        out["sync"] = sync_summary
    if error:
        out["error"] = error
    return out


def fetch_erddap_max_times(
    dataset_ids: list[str],
    *,
    use_cache: bool = False,
) -> dict[str, Optional[datetime]]:
    """
    Cheap maxTime lookup for ``dataset_ids``.

    Prefers one allDatasets query; falls back to ``fetch_dataset_time_extent``
    per missing id (orderByMax only when allDatasets has no maxTime).
    """
    resolved = [resolve_slocum_dataset_id(did) for did in dataset_ids if did and str(did).strip()]
    unique_ids = list(dict.fromkeys(resolved))
    found: dict[str, Optional[datetime]] = {did: None for did in unique_ids}
    if not unique_ids:
        return found

    try:
        meta_df = list_slocum_datasets(dataset_ids=unique_ids)
        for dataset_id, max_dt in parse_alldatasets_max_times(meta_df).items():
            key = resolve_slocum_dataset_id(dataset_id)
            if key in found:
                found[key] = max_dt
    except Exception as err:
        logger.warning("SLOCUM POKE: allDatasets batch failed: %s", err)

    for dataset_id, max_dt in list(found.items()):
        if max_dt is not None:
            continue
        try:
            _, extent_max = fetch_dataset_time_extent(dataset_id, use_cache=use_cache)
            found[dataset_id] = extent_max
        except Exception as err:
            logger.warning("SLOCUM POKE: extent fallback failed for %s: %s", dataset_id, err)
    return found


def evaluate_dataset_poke(
    dataset_id: str,
    erddap_max: Optional[datetime],
) -> dict[str, Any]:
    """Decide whether ``dataset_id`` needs a mirror sync from a poked maxTime."""
    dataset_id = resolve_slocum_dataset_id(dataset_id)
    if is_historical_dataset(dataset_id):
        return _empty_result(dataset_id, reason="historical")
    known_max = known_mirror_max_time(dataset_id)
    has_mirror = _has_dashboard_mirror(dataset_id)
    if erddap_max is None:
        return _build_result(
            dataset_id,
            erddap_max=None,
            known_max=known_max,
            has_new=False,
            action="error",
            reason="erddap_max_unavailable",
            error="Could not read ERDDAP maxTime",
        )
    has_new = has_new_erddap_data(erddap_max, known_max, has_mirror=has_mirror)
    if has_new:
        reason = "no_mirror" if not has_mirror or known_max is None else "erddap_max_advanced"
        return _build_result(
            dataset_id,
            erddap_max=erddap_max,
            known_max=known_max,
            has_new=True,
            action="pending",
            reason=reason,
        )
    return _build_result(
        dataset_id,
        erddap_max=erddap_max,
        known_max=known_max,
        has_new=False,
        action="skipped",
        reason="unchanged",
    )


async def poke_dataset(
    dataset_id: str,
    *,
    hours_back: Optional[int] = None,
    sync_if_new: bool = True,
    erddap_max: Optional[datetime] = None,
    use_cache: bool = False,
) -> dict[str, Any]:
    """Poke one dataset; optionally incremental-sync when maxTime advanced."""
    dataset_id = resolve_slocum_dataset_id(dataset_id)
    if erddap_max is None:
        times = fetch_erddap_max_times([dataset_id], use_cache=use_cache)
        erddap_max = times.get(dataset_id)
    result = evaluate_dataset_poke(dataset_id, erddap_max)
    if result["action"] == "error":
        _record_poke(
            dataset_id,
            erddap_max=erddap_max,
            has_new=False,
            action="error",
            error=result.get("error"),
        )
        return result
    if result["action"] == "skipped" or result.get("reason") == "historical":
        _record_poke(
            dataset_id,
            erddap_max=erddap_max,
            has_new=False,
            action="skipped",
        )
        return result
    if not sync_if_new:
        result["action"] = "new_data"
        _record_poke(dataset_id, erddap_max=erddap_max, has_new=True, action="new_data")
        return result

    try:
        sync_summary = await sync_dataset_mirror(dataset_id, hours_back=hours_back)
        result["action"] = "synced"
        result["sync"] = sync_summary
        _record_poke(dataset_id, erddap_max=erddap_max, has_new=True, action="synced")
        logger.info(
            "SLOCUM POKE: synced %s (reason=%s, erddap_max=%s)",
            dataset_id,
            result.get("reason"),
            result.get("erddap_max_time"),
        )
    except Exception as err:
        logger.warning("SLOCUM POKE: sync failed for %s: %s", dataset_id, err)
        result["action"] = "error"
        result["error"] = str(err)
        _record_poke(
            dataset_id,
            erddap_max=erddap_max,
            has_new=True,
            action="error",
            error=str(err),
        )
    return result


async def poke_active_slocum_datasets(
    *,
    hours_back: Optional[int] = None,
    sync_if_new: bool = True,
    dataset_ids: Optional[list[str]] = None,
    use_cache: bool = False,
) -> dict[str, Any]:
    """
    Poke active Slocum datasets (one allDatasets query) and sync those with new tails.

    ``dataset_ids`` overrides the warm-key list (aliases resolved). Historical
    ids in that list are skipped.
    """
    if not is_feature_enabled("slocum_platform"):
        return {
            "poked": 0,
            "synced": 0,
            "skipped": 0,
            "errors": 0,
            "datasets": [],
            "reason": "slocum_platform disabled",
        }

    if dataset_ids is None:
        from app.platforms.slocum.cache_service import list_slocum_warm_source_keys

        dataset_ids = resolve_slocum_dataset_ids(list_slocum_warm_source_keys())
    else:
        dataset_ids = resolve_slocum_dataset_ids(dataset_ids)

    if not dataset_ids:
        logger.info("SLOCUM POKE: No active Slocum datasets configured.")
        return {"poked": 0, "synced": 0, "skipped": 0, "errors": 0, "datasets": []}

    max_times = fetch_erddap_max_times(dataset_ids, use_cache=use_cache)
    results: list[dict[str, Any]] = []
    synced = 0
    skipped = 0
    errors = 0
    for dataset_id in dataset_ids:
        result = await poke_dataset(
            dataset_id,
            hours_back=hours_back,
            sync_if_new=sync_if_new,
            erddap_max=max_times.get(dataset_id),
            use_cache=use_cache,
        )
        results.append(result)
        action = result.get("action")
        if action == "synced":
            synced += 1
        elif action == "error":
            errors += 1
        else:
            skipped += 1

    logger.info(
        "SLOCUM POKE: poked=%s synced=%s skipped=%s errors=%s",
        len(results),
        synced,
        skipped,
        errors,
    )
    return {
        "poked": len(results),
        "synced": synced,
        "skipped": skipped,
        "errors": errors,
        "datasets": results,
    }
