"""
CLS Group Argos / Kinéis api-telemetry client (M2M).

Auth mirrors the official scripts under ``Data/argos``:

- ``POST`` Keycloak token URL with password grant (``client_id=api-telemetry``)
- ``POST /retrieve-bulk`` with Bearer token for historical messages

Failures are best-effort: checklist autofill continues without Argos.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(45.0, connect=15.0)

# In-process token cache (per worker).
_token_cache: dict[str, Any] = {
    "token": None,
    "expires_at": 0.0,
    "fail_until": 0.0,
}
_SIGNIN_FAIL_COOLDOWN_SEC = 60.0
_PAGE_SIZE = 100


def is_argos_configured() -> bool:
    return bool(
        (settings.argos_username or "").strip()
        and (settings.argos_password or "").strip()
    )


def _auth_url() -> str:
    return (settings.argos_auth_url or "").strip()


def _api_base() -> str:
    return (settings.argos_api_base_url or "").strip().rstrip("/")


def _client_id() -> str:
    return (settings.argos_client_id or "api-telemetry").strip() or "api-telemetry"


def _http_timeout() -> httpx.Timeout:
    seconds = float(getattr(settings, "argos_http_timeout_seconds", 45.0) or 45.0)
    return httpx.Timeout(seconds, connect=min(15.0, seconds))


def _mark_signin_failed() -> None:
    _token_cache["token"] = None
    _token_cache["expires_at"] = 0.0
    _token_cache["fail_until"] = time.monotonic() + _SIGNIN_FAIL_COOLDOWN_SEC


async def get_access_token(*, force_refresh: bool = False) -> Optional[str]:
    """OAuth2 password grant → access_token (cached until near expiry)."""
    if not is_argos_configured():
        return None

    now = time.monotonic()
    if not force_refresh and now < float(_token_cache.get("fail_until") or 0.0):
        return None

    cached = _token_cache.get("token")
    expires_at = float(_token_cache.get("expires_at") or 0.0)
    if not force_refresh and cached and now < expires_at:
        return str(cached)

    url = _auth_url()
    if not url:
        logger.warning("Argos auth URL is empty")
        return None

    body = {
        "grant_type": "password",
        "client_id": _client_id(),
        "username": (settings.argos_username or "").strip(),
        "password": (settings.argos_password or "").strip(),
    }
    try:
        async with httpx.AsyncClient(timeout=_http_timeout(), follow_redirects=True) as client:
            response = await client.post(
                url,
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError as err:
        _mark_signin_failed()
        logger.warning("Argos token request failed: %s", err)
        return None

    if response.status_code != 200:
        _mark_signin_failed()
        logger.warning(
            "Argos token → HTTP %s: %s",
            response.status_code,
            response.text[:200],
        )
        return None

    try:
        payload = response.json()
    except ValueError:
        _mark_signin_failed()
        logger.warning("Argos token returned non-JSON body")
        return None

    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token.strip():
        _mark_signin_failed()
        logger.warning("Argos token response missing access_token")
        return None

    expires_in = 300
    try:
        expires_in = int(payload.get("expires_in") or 300)
    except (TypeError, ValueError):
        expires_in = 300
    # Refresh a minute before expiry.
    _token_cache["token"] = token.strip()
    _token_cache["expires_at"] = time.monotonic() + max(30.0, float(expires_in) - 60.0)
    _token_cache["fail_until"] = 0.0
    return token.strip()


def _iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.001Z")


async def retrieve_bulk(
    device_refs: Sequence[str],
    *,
    from_dt: datetime,
    to_dt: datetime,
    page_size: int = _PAGE_SIZE,
) -> list[dict[str, Any]]:
    """
    Fetch all bulk messages for ``device_refs`` in ``[from_dt, to_dt]`` (UTC).

    Paginates with ``after`` / ``endCursor`` until ``hasNextPage`` is false.
    """
    refs = [str(r).strip() for r in device_refs if str(r).strip()]
    if not refs:
        return []

    token = await get_access_token()
    if not token:
        return []

    base = _api_base()
    if not base:
        logger.warning("Argos API base URL is empty")
        return []

    url = f"{base}/retrieve-bulk"
    messages: list[dict[str, Any]] = []
    after: Optional[str] = None
    first = max(1, min(int(page_size or _PAGE_SIZE), 500))

    async with httpx.AsyncClient(timeout=_http_timeout(), follow_redirects=True) as client:
        while True:
            pagination: dict[str, Any] = {"first": first}
            if after:
                pagination["after"] = after
            body: dict[str, Any] = {
                "pagination": pagination,
                "retrieveMetadata": True,
                "retrieveRawData": False,
                "retrieveDoppler": True,
                "retrieveGpsLoc": True,
                "retrieveSensors": False,
                "retrieveAdditionnalProperties": False,
                "deviceRefs": refs,
                "fromDatetime": _iso_z(from_dt),
                "toDatetime": _iso_z(to_dt),
                "datetimeFormat": "DATETIME",
            }
            try:
                response = await client.post(
                    url,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                )
            except httpx.HTTPError as err:
                logger.warning("Argos retrieve-bulk request failed: %s", err)
                break

            if response.status_code == 401:
                token = await get_access_token(force_refresh=True)
                if not token:
                    break
                try:
                    response = await client.post(
                        url,
                        json=body,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Accept": "application/json",
                            "Content-Type": "application/json",
                        },
                    )
                except httpx.HTTPError as err:
                    logger.warning("Argos retrieve-bulk retry failed: %s", err)
                    break

            if response.status_code != 200:
                logger.warning(
                    "Argos retrieve-bulk → HTTP %s: %s",
                    response.status_code,
                    response.text[:200],
                )
                break

            try:
                payload = response.json()
            except ValueError:
                logger.warning("Argos retrieve-bulk returned non-JSON body")
                break

            contents = payload.get("contents") if isinstance(payload, dict) else None
            if isinstance(contents, list):
                for item in contents:
                    if isinstance(item, dict):
                        messages.append(item)

            page_info = payload.get("pageInfo") if isinstance(payload, dict) else None
            has_next = False
            end_cursor: Optional[str] = None
            if isinstance(page_info, dict):
                has_next = bool(page_info.get("hasNextPage"))
                cursor = page_info.get("endCursor")
                if cursor is not None and str(cursor).strip():
                    end_cursor = str(cursor).strip()
            if not has_next or not end_cursor:
                break
            after = end_cursor

    return messages


def _parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        if isinstance(value, str) and not value.strip():
            return None
        num = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(num) or math.isinf(num):
        return None
    return num


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    # Epoch ms
    try:
        as_int = int(text)
        if as_int > 1_000_000_000_000:
            return datetime.fromtimestamp(as_int / 1000.0, tz=timezone.utc)
        if as_int > 1_000_000_000:
            return datetime.fromtimestamp(as_int, tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        pass
    # ISO-ish
    try:
        normalized = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def slim_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Keep fields useful for cache / checklist (drop raw payload)."""
    keys = (
        "deviceRef",
        "deviceUid",
        "msgDatetime",
        "msgTs",
        "dopplerLocLat",
        "dopplerLocLon",
        "dopplerLocAlt",
        "dopplerLocErrorRadius",
        "dopplerLocClass",
        "dopplerDatetime",
        "dopplerTs",
        "gpsLocLat",
        "gpsLocLon",
        "gpsLocDatetime",
    )
    return {k: msg.get(k) for k in keys if k in msg}


def latest_doppler_fix(messages: Sequence[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """
    Return the newest Doppler location among messages.

    Result keys: lat, lon, fix_time (datetime UTC), location_class, error_radius_km,
    device_ref, source_message (slim).
    """
    best: Optional[dict[str, Any]] = None
    best_ts: Optional[datetime] = None

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        lat = _parse_float(msg.get("dopplerLocLat"))
        lon = _parse_float(msg.get("dopplerLocLon"))
        if lat is None or lon is None:
            continue
        if abs(lat) > 90 or abs(lon) > 180:
            continue
        if lat == 0.0 and lon == 0.0:
            continue
        fix_time = (
            _parse_datetime(msg.get("dopplerDatetime"))
            or _parse_datetime(msg.get("dopplerTs"))
            or _parse_datetime(msg.get("msgDatetime"))
            or _parse_datetime(msg.get("msgTs"))
        )
        if fix_time is None:
            continue
        if best_ts is None or fix_time > best_ts:
            best_ts = fix_time
            err = _parse_float(msg.get("dopplerLocErrorRadius"))
            # API may return meters or km; treat values > 500 as meters.
            error_radius_km = None
            if err is not None and err >= 0:
                error_radius_km = err / 1000.0 if err > 500 else err
            best = {
                "lat": lat,
                "lon": lon,
                "fix_time": fix_time,
                "location_class": (
                    str(msg.get("dopplerLocClass")).strip()
                    if msg.get("dopplerLocClass") is not None
                    else None
                ),
                "error_radius_km": error_radius_km,
                "device_ref": (
                    str(msg.get("deviceRef")).strip()
                    if msg.get("deviceRef") is not None
                    else None
                ),
                "source_message": slim_message(msg),
            }

    return best
