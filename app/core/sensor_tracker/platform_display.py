"""Sensor Tracker hull / asset display labels.

Tracker list rows often store ``platform`` as a numeric FK or id-only stub.
User-facing labels resolve: nested name → batch-resolved name → ``str(platform_id)``.

This is distinct from GBS product platforms (``wave_glider`` / ``slocum`` in
``app.core.platforms``) and from catalog prefix matching
(``normalize_platform_prefix``).
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

_PLATFORM_DISPLAY_CACHE: ContextVar[Optional[Dict[int, str]]] = ContextVar(
    "st_platform_display_cache", default=None
)

PlatformRecordFetcher = Callable[[int], Awaitable[Optional[Dict[str, Any]]]]


def clear_platform_display_cache() -> None:
    _PLATFORM_DISPLAY_CACHE.set({})


def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _record_id(row: Dict[str, Any]) -> Optional[int]:
    return _as_int(row.get("id") if row.get("id") is not None else row.get("pk"))


def _cell_text(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, dict):
        nested = (
            value.get("name")
            or value.get("identifier")
            or value.get("title")
            or value.get("short_name")
            or value.get("id")
            or value.get("pk")
        )
        return _cell_text(nested)
    if isinstance(value, (list, tuple)):
        return None
    return str(value)


def platform_name_from_record(record: Optional[Dict[str, Any]]) -> Optional[str]:
    """Return a Tracker platform *name*, never a numeric FK stringified as one."""
    if not isinstance(record, dict):
        return None
    for key in ("name", "platform_name"):
        text = _cell_text(record.get(key))
        if text:
            return text
    platform = record.get("platform")
    if isinstance(platform, dict):
        return _cell_text(platform.get("name") or platform.get("platform_name"))
    return None


def platform_fk_from_value(value: Any) -> Optional[int]:
    if isinstance(value, dict):
        return _record_id(value)
    return _as_int(value)


def platform_label_from_value(value: Any) -> Optional[str]:
    """Hull name when Tracker nested it on a deployment or platform stub."""
    if isinstance(value, dict):
        return platform_name_from_record(value)
    return None


def platform_display_cache() -> Dict[int, str]:
    cache = _PLATFORM_DISPLAY_CACHE.get()
    if cache is None:
        cache = {}
        _PLATFORM_DISPLAY_CACHE.set(cache)
    return cache


def format_platform_label(
    value: Any,
    *,
    platform_labels: Optional[Dict[int, str]] = None,
) -> Optional[str]:
    """Resolve a platform field to a user-facing hull label.

    Order: nested name → ``platform_labels`` / request cache → ``str(id)``.
    """
    label = platform_label_from_value(value)
    if label:
        return label
    plat_id = platform_fk_from_value(value)
    if plat_id is not None:
        labels = (
            platform_labels
            if platform_labels is not None
            else _PLATFORM_DISPLAY_CACHE.get()
        )
        if labels and plat_id in labels:
            return labels[plat_id]
        return str(plat_id)
    return _cell_text(value)


def collect_deployment_platform_ids(rows: Sequence[Dict[str, Any]]) -> List[int]:
    ids: List[int] = []
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        value = row.get("platform")
        if platform_label_from_value(value):
            continue
        plat_id = platform_fk_from_value(value)
        if plat_id is not None and plat_id not in seen:
            seen.add(plat_id)
            ids.append(plat_id)
    return ids


def collect_row_platform_ids(rows: Sequence[Dict[str, Any]]) -> List[int]:
    """Collect unresolved platform FKs from deployment-like or compact rows."""
    ids: List[int] = []
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("platform_name"):
            continue
        plat_id = platform_fk_from_value(row.get("platform"))
        if plat_id is None:
            plat_id = _as_int(row.get("platform_id"))
        if plat_id is not None and plat_id not in seen:
            seen.add(plat_id)
            ids.append(plat_id)
    return ids


async def ensure_platform_labels(
    platform_ids: Sequence[int],
    *,
    fetch_platform: PlatformRecordFetcher,
    seed: Optional[Dict[int, str]] = None,
) -> Dict[int, str]:
    """Warm the request cache for ``platform_ids`` via ``fetch_platform``.

    ``seed`` merges known id→name mappings (e.g. from a fleet platforms list)
    without contacting Tracker. Missing names fall back to ``str(id)``.
    """
    cache = platform_display_cache()
    if seed:
        for plat_id, name in seed.items():
            if plat_id is None:
                continue
            text = str(name).strip() if name else ""
            cache[int(plat_id)] = text if text else str(plat_id)
    missing = [pid for pid in platform_ids if pid is not None and pid not in cache]
    for plat_id in missing:
        try:
            record = await fetch_platform(int(plat_id))
            name = platform_name_from_record(record) if isinstance(record, dict) else None
            cache[int(plat_id)] = name if name else str(plat_id)
        except Exception:
            cache[int(plat_id)] = str(plat_id)
    return cache


async def prepare_deployment_platform_labels(
    rows: Sequence[Dict[str, Any]],
    *,
    fetch_platform: PlatformRecordFetcher,
) -> Dict[int, str]:
    ids = collect_deployment_platform_ids(rows)
    if not ids:
        return platform_display_cache()
    return await ensure_platform_labels(ids, fetch_platform=fetch_platform)


def enrich_rows_platform_names(
    rows: Sequence[Dict[str, Any]],
    id_to_name: Dict[int, str],
) -> None:
    """Fill missing ``platform_name`` on compact rows from ``id_to_name`` (in place)."""
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("platform_name"):
            continue
        plat_id = _as_int(row.get("platform_id"))
        if plat_id is None:
            plat_id = platform_fk_from_value(row.get("platform"))
        if plat_id is None:
            continue
        name = id_to_name.get(plat_id)
        if name:
            row["platform_name"] = name
