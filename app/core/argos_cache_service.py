"""Disk cache for CLS Argos latest Doppler fixes (checklist on-demand).

Per-device JSON under ``settings.argos_cache_dir``. On miss/stale, bulk-fetches
the last ``argos_fix_max_age_hours`` window and stores the latest Doppler fix.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from app.config import settings
from app.core import argos_client
from app.core.utils import replace_path_with_retries, unique_sibling_tmp_path

logger = logging.getLogger(__name__)


def _cache_dir() -> Path:
    path = Path(getattr(settings, "argos_cache_dir", Path("data_store/argos_cache")))
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_device_ref(device_ref: str) -> str:
    return str(device_ref or "").strip()


def _safe_filename(device_ref: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", normalize_device_ref(device_ref))
    return safe or "unknown"


def _cache_path(device_ref: str) -> Path:
    return _cache_dir() / f"{_safe_filename(device_ref)}.json"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = unique_sibling_tmp_path(path)
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        replace_path_with_retries(tmp_path, path)
    except Exception:
        try:
            if tmp_path.is_file():
                tmp_path.unlink()
        except OSError:
            pass
        raise


def _read_json_file(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read Argos cache %s: %s", path, exc)
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _parse_iso(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _ttl_minutes() -> float:
    return max(1.0, float(getattr(settings, "argos_cache_ttl_minutes", 30) or 30))


def _lookback_hours() -> float:
    return max(1.0, float(getattr(settings, "argos_fix_max_age_hours", 48) or 48))


def _serialize_fix(fix: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not fix:
        return None
    out = dict(fix)
    fix_time = out.get("fix_time")
    if isinstance(fix_time, datetime):
        out["fix_time"] = fix_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return out


def _deserialize_fix(raw: Any) -> Optional[dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    lat = raw.get("lat")
    lon = raw.get("lon")
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return None
    fix_time = _parse_iso(raw.get("fix_time"))
    if fix_time is None:
        return None
    return {
        "lat": lat_f,
        "lon": lon_f,
        "fix_time": fix_time,
        "location_class": raw.get("location_class"),
        "error_radius_km": raw.get("error_radius_km"),
        "device_ref": raw.get("device_ref"),
        "source_message": raw.get("source_message") if isinstance(raw.get("source_message"), dict) else None,
    }


def _cache_is_fresh(payload: dict[str, Any]) -> bool:
    fetched_at = _parse_iso(payload.get("fetched_at"))
    if fetched_at is None:
        return False
    age = datetime.now(timezone.utc) - fetched_at
    return age <= timedelta(minutes=_ttl_minutes())


async def get_latest_argos_fix(
    device_ref: str,
    *,
    force_refresh: bool = False,
) -> Optional[dict[str, Any]]:
    """
    Return latest Doppler fix for ``device_ref`` (cached).

    Shape matches ``argos_client.latest_doppler_fix``. Returns None when
    credentials/device missing or no Doppler location in the lookback window.
    """
    ref = normalize_device_ref(device_ref)
    if not ref:
        return None
    if not argos_client.is_argos_configured():
        return None

    path = _cache_path(ref)
    if not force_refresh:
        cached = _read_json_file(path)
        if cached and _cache_is_fresh(cached):
            return _deserialize_fix(cached.get("latest_fix"))

    now = datetime.now(timezone.utc)
    from_dt = now - timedelta(hours=_lookback_hours())
    try:
        messages = await argos_client.retrieve_bulk([ref], from_dt=from_dt, to_dt=now)
    except Exception as err:
        logger.warning("Argos bulk fetch failed for %s: %s", ref, err)
        cached = _read_json_file(path)
        if cached:
            return _deserialize_fix(cached.get("latest_fix"))
        return None

    latest = argos_client.latest_doppler_fix(messages)
    payload = {
        "device_ref": ref,
        "fetched_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lookback_hours": _lookback_hours(),
        "message_count": len(messages),
        "latest_fix": _serialize_fix(latest),
        "messages": [argos_client.slim_message(m) for m in messages[-50:]],
    }
    try:
        _atomic_write_json(path, payload)
    except OSError as err:
        logger.warning("Could not write Argos cache for %s: %s", ref, err)

    return latest
