"""
Read-only SFMC HTTP client (Teledyne Slocum Fleet Mission Control).

Auth and paths mirror Teledyne's Node ``sfmc`` package:

- ``POST /sfmc/api/signin`` with ``{clientId, secret}`` → ``{token: ...}``
- ``GET /sfmc/api/v1/...`` with ``Authorization: Bearer <token>``

Failures are best-effort: checklist autofill continues without SFMC.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any, Optional
from urllib.parse import quote

import asyncio
import httpx

from ..config import settings
from .sfmc_transforms import (
    dialog_values_for_checklist,
    extract_from_dockserver_commands,
    extract_from_surface_events_payload,
    extract_connection_durations,
    merge_sfmc_checklist_values,
    normalize_dmon_asc_files,
    parse_goto_ma,
    parse_surface_dialog_log,
    pick_latest_goto_archive_filename,
    pick_latest_network_log_filename,
    script_basename,
)


logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(45.0, connect=15.0)

# In-process token cache (per worker).
_token_cache: dict[str, Any] = {
    "token": None,
    "expires_at": 0.0,
    # After a failed signin, skip retries briefly to avoid log spam on multi-call refresh.
    "fail_until": 0.0,
    "fail_reason": None,
}
_SIGNIN_FAIL_COOLDOWN_SEC = 60.0

# Global request pacing (SFMC ~25 req/min). Shared across all SFMC calls in this worker.
_rate_lock: Optional[asyncio.Lock] = None
_last_request_mono: float = 0.0
_rate_limited_until_mono: float = 0.0


def _get_rate_lock() -> asyncio.Lock:
    global _rate_lock
    if _rate_lock is None:
        _rate_lock = asyncio.Lock()
    return _rate_lock


def _max_requests_per_minute() -> int:
    return max(1, int(getattr(settings, "sfmc_max_requests_per_minute", 20) or 20))


async def _await_rate_slot() -> None:
    """Space SFMC HTTP calls to stay under ``sfmc_max_requests_per_minute``."""
    global _last_request_mono, _rate_limited_until_mono
    min_interval = 60.0 / float(_max_requests_per_minute())
    async with _get_rate_lock():
        now = time.monotonic()
        if now < _rate_limited_until_mono:
            await asyncio.sleep(_rate_limited_until_mono - now)
            now = time.monotonic()
        wait = (_last_request_mono + min_interval) - now
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_mono = time.monotonic()


def _note_rate_limit(*, retry_after_sec: Optional[float] = None) -> None:
    """Extend the global cooldown after a 429."""
    global _rate_limited_until_mono
    backoff = 60.0 if retry_after_sec is None else max(5.0, float(retry_after_sec))
    until = time.monotonic() + backoff
    if until > _rate_limited_until_mono:
        _rate_limited_until_mono = until
    logger.warning("SFMC rate limit: backing off %.0fs", backoff)


def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def sfmc_is_configured() -> bool:
    return bool(
        (settings.sfmc_base_url or "").strip()
        and (settings.sfmc_client_id or "").strip()
        and (settings.sfmc_client_secret or "").strip()
    )


def _base_url() -> str:
    raw = (settings.sfmc_base_url or "").strip().rstrip("/")
    if not raw:
        return ""
    if "://" not in raw:
        return f"https://{raw}"
    return raw


def _verify_tls() -> bool:
    return bool(settings.sfmc_verify_tls)


def _extract_token(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    for key in ("token", "access_token", "accessToken"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _mark_signin_failed(reason: str) -> None:
    _token_cache["token"] = None
    _token_cache["expires_at"] = 0.0
    _token_cache["fail_until"] = time.monotonic() + _SIGNIN_FAIL_COOLDOWN_SEC
    _token_cache["fail_reason"] = reason


async def get_access_token(*, force_refresh: bool = False) -> Optional[str]:
    """POST /sfmc/api/signin with Teledyne ``clientId`` / ``secret`` body."""
    if not sfmc_is_configured():
        return None

    now = time.monotonic()
    if not force_refresh and now < float(_token_cache.get("fail_until") or 0.0):
        return None

    cached = _token_cache.get("token")
    expires_at = float(_token_cache.get("expires_at") or 0.0)
    if not force_refresh and cached and now < expires_at:
        return str(cached)

    url = f"{_base_url()}/sfmc/api/signin"
    body = {
        "clientId": settings.sfmc_client_id,
        "secret": settings.sfmc_client_secret,
    }
    try:
        await _await_rate_slot()
        async with httpx.AsyncClient(
            verify=_verify_tls(), timeout=_TIMEOUT, follow_redirects=True
        ) as client:
            response = await client.post(url, json=body)
    except httpx.HTTPError as err:
        reason = str(err)
        _mark_signin_failed(reason)
        if "CERTIFICATE_VERIFY_FAILED" in reason or "SSL" in reason.upper():
            logger.warning(
                "SFMC signin TLS failed (set SFMC_VERIFY_TLS=false for self-signed "
                "institutional certs): %s",
                err,
            )
        else:
            logger.warning("SFMC signin request failed: %s", err)
        return None

    if response.status_code == 429:
        _note_rate_limit(retry_after_sec=_retry_after_seconds(response))
        _mark_signin_failed("HTTP 429")
        logger.warning("SFMC signin rate-limited")
        return None

    if response.status_code != 200:
        _mark_signin_failed(f"HTTP {response.status_code}")
        logger.warning("SFMC signin → HTTP %s: %s", response.status_code, response.text[:200])
        return None

    try:
        payload = response.json()
    except ValueError:
        _mark_signin_failed("non-JSON body")
        logger.warning("SFMC signin returned non-JSON body")
        return None

    token = _extract_token(payload)
    if not token:
        _mark_signin_failed("missing token field")
        logger.warning("SFMC signin JSON missing token field (keys=%s)", list(payload)[:12])
        return None

    # Tokens typically last many minutes; refresh early if no expiry provided.
    ttl = 15 * 60
    expires_in = payload.get("expires_in") or payload.get("expiresIn")
    if isinstance(expires_in, (int, float)) and expires_in > 60:
        ttl = float(expires_in) - 60.0
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + ttl
    _token_cache["fail_until"] = 0.0
    _token_cache["fail_reason"] = None
    return token


async def _request(
    method: str,
    path: str,
    *,
    params: Optional[dict[str, Any]] = None,
    expect_json: bool = True,
    _retry_on_429: bool = True,
) -> Optional[Any]:
    token = await get_access_token()
    if not token:
        return None

    url = f"{_base_url()}{path}"

    async def _once(auth_token: str) -> httpx.Response:
        await _await_rate_slot()
        async with httpx.AsyncClient(
            verify=_verify_tls(), timeout=_TIMEOUT, follow_redirects=True
        ) as client:
            return await client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {auth_token}"},
                params=params,
            )

    try:
        response = await _once(token)
    except httpx.HTTPError as err:
        logger.debug("SFMC %s %s failed: %s", method, path, err)
        return None

    if response.status_code == 401:
        token = await get_access_token(force_refresh=True)
        if not token:
            return None
        try:
            response = await _once(token)
        except httpx.HTTPError as err:
            logger.debug("SFMC retry %s %s failed: %s", method, path, err)
            return None

    if response.status_code == 429:
        retry_after = _retry_after_seconds(response)
        _note_rate_limit(retry_after_sec=retry_after)
        logger.warning("SFMC rate-limited on %s %s", method, path)
        if _retry_on_429:
            # One retry after the global cooldown (still paced by the rate slot).
            return await _request(
                method,
                path,
                params=params,
                expect_json=expect_json,
                _retry_on_429=False,
            )
        return None
    if response.status_code != 200:
        logger.debug("SFMC %s %s → %s", method, path, response.status_code)
        return None

    if expect_json:
        try:
            return response.json()
        except ValueError:
            logger.debug("SFMC %s %s non-JSON", method, path)
            return None
    return response.text


async def _get_json(path: str, *, params: Optional[dict[str, Any]] = None) -> Optional[Any]:
    payload = await _request("GET", path, params=params, expect_json=True)
    return _unwrap_data(payload)


def _unwrap_data(payload: Any) -> Any:
    """SFMC v1 responses are often ``{\"data\": ...}``; unwrap when present."""
    if isinstance(payload, dict) and "data" in payload and len(payload) <= 3:
        return payload["data"]
    return payload


async def _get_text(path: str, *, params: Optional[dict[str, Any]] = None) -> Optional[str]:
    result = await _request("GET", path, params=params, expect_json=False)
    return result if isinstance(result, str) else None


def _folder_names_from_listing(payload: Any) -> list[str]:
    if payload is None:
        return []
    if isinstance(payload, list):
        names: list[str] = []
        for item in payload:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                name = (
                    item.get("fileName")
                    or item.get("filename")
                    or item.get("name")
                    or item.get("path")
                )
                if name:
                    names.append(str(name))
        return names
    if isinstance(payload, dict):
        # Live SFMC: {links, limit, results:[{fileName, dateTimeModified, fileSize}]}
        for key in ("results", "files", "listing", "content", "entries", "fileListing"):
            if key in payload:
                return _folder_names_from_listing(payload[key])
    return []


def _folder_entries_from_listing(payload: Any) -> list[dict[str, Any]]:
    """
    Preserve ``fileName`` / ``dateTimeModified`` / ``fileSize`` from a folder listing.

    Unlike ``_folder_names_from_listing``, timestamps are retained for ASC gap checks.
    """
    if payload is None:
        return []
    if isinstance(payload, list):
        entries: list[dict[str, Any]] = []
        for item in payload:
            if isinstance(item, str):
                entries.append({"fileName": item, "dateTimeModified": None, "fileSize": None})
                continue
            if not isinstance(item, dict):
                continue
            name = (
                item.get("fileName")
                or item.get("filename")
                or item.get("name")
                or item.get("path")
            )
            if not name:
                continue
            entries.append(
                {
                    "fileName": str(name),
                    "dateTimeModified": (
                        item.get("dateTimeModified")
                        or item.get("lastModified")
                        or item.get("modified")
                        or item.get("mtime")
                    ),
                    "fileSize": item.get("fileSize") or item.get("size"),
                }
            )
        return entries
    if isinstance(payload, dict):
        for key in ("results", "files", "listing", "content", "entries", "fileListing"):
            if key in payload:
                return _folder_entries_from_listing(payload[key])
        # Sometimes the listing is nested under data
        if "data" in payload:
            return _folder_entries_from_listing(payload["data"])
    return []


def _listing_has_next_page(payload: Any) -> bool:
    """True when SFMC folder listing JSON advertises another page (``links.next``)."""
    if not isinstance(payload, dict):
        return False
    links = payload.get("links")
    if isinstance(links, dict) and links.get("next"):
        return True
    data = payload.get("data")
    if isinstance(data, dict):
        nested = data.get("links")
        if isinstance(nested, dict) and nested.get("next"):
            return True
    return False


_FOLDER_LISTING_MAX_PAGES = 50


async def fetch_folder_listing_all_pages(
    glider_name: str,
    folder: str,
    *,
    filter_glob: Optional[str] = "*",
    last_modified_after: Optional[str] = None,
    max_pages: int = _FOLDER_LISTING_MAX_PAGES,
) -> list[dict[str, Any]]:
    """Paginate SFMC folder listings (limit is typically 20 per page)."""
    all_entries: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    page_limit = max(1, int(max_pages))
    for page in range(page_limit):
        payload = await fetch_folder_listing(
            glider_name,
            folder,
            page=page,
            filter_glob=filter_glob,
            last_modified_after=last_modified_after,
        )
        if payload is None:
            break
        batch = _folder_entries_from_listing(payload)
        if not batch:
            break
        for entry in batch:
            name = str(entry.get("fileName") or "").strip()
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            all_entries.append(entry)
        if not _listing_has_next_page(payload):
            break
    else:
        logger.warning(
            "SFMC folder listing hit max_pages=%s for %s/%s (filter=%s)",
            page_limit,
            glider_name,
            folder,
            filter_glob,
        )
    return all_entries


def _extract_script_from_scripts_payload(payload: Any) -> Optional[str]:
    """Best-effort assigned/current script name from scripts-for-glider JSON."""
    if payload is None:
        return None
    payload = _unwrap_data(payload)
    if isinstance(payload, str) and payload.strip().endswith((".xml", ".mi")):
        return script_basename(payload)
    if isinstance(payload, list):
        for item in payload:
            found = _extract_script_from_scripts_payload(item)
            if found:
                return found
        return None
    if not isinstance(payload, dict):
        return None

    for key in (
        "assignedScript",
        "assignedScriptName",
        "assignedDockServerScript",
        "dockServerScriptName",
        "currentScript",
        "scriptName",
        "script",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return script_basename(value)
        if isinstance(value, dict):
            nested = value.get("name") or value.get("path") or value.get("fileName")
            if isinstance(nested, str) and nested.strip():
                return script_basename(nested)

    for key in ("scripts", "availableScripts", "userScripts", "content", "items"):
        if key in payload:
            found = _extract_script_from_scripts_payload(payload[key])
            if found:
                return found

    for item in payload.get("userScripts") or payload.get("scripts") or payload.get("content") or []:
        if isinstance(item, dict) and (
            item.get("assigned") or item.get("isAssigned") or item.get("active")
        ):
            name = item.get("name") or item.get("scriptName") or item.get("path") or item.get("fileName")
            if name:
                return script_basename(str(name))
    return None


def _mission_name_from_payload(payload: Any) -> Optional[str]:
    payload = _unwrap_data(payload)
    if not isinstance(payload, dict):
        return None
    name = payload.get("missionName") or payload.get("mission_file") or payload.get("missionFile")
    if isinstance(name, str) and name.strip():
        return name.strip()
    mission = payload.get("mission")
    if isinstance(mission, dict):
        nested = mission.get("name") or mission.get("missionName")
        if isinstance(nested, str) and nested.strip():
            return nested.strip()
    if isinstance(mission, str) and mission.strip():
        return mission.strip()
    return None


async def fetch_active_deployment(glider_name: str) -> Optional[dict[str, Any]]:
    # Live SFMC only exposes the *active* deployment for a glider. Archived SFMC
    # missions / historical logs may use separate API paths that are not explored
    # or implemented here — do not poll archived Buddy deployments on the active
    # refresh loop. On-demand historical SFMC autofill would be a later path.
    payload = await _get_json(f"/sfmc/api/v1/active-deployment/{quote(glider_name, safe='')}")
    return payload if isinstance(payload, dict) else None


async def fetch_newest_mission_details(glider_name: str) -> Optional[dict[str, Any]]:
    payload = await _get_json(f"/sfmc/api/v1/newest-mission-details/{quote(glider_name, safe='')}")
    return payload if isinstance(payload, dict) else None


async def fetch_scripts_for_glider(glider_name: str) -> Optional[Any]:
    return await _get_json(f"/sfmc/api/v1/scripts-for-glider/{quote(glider_name, safe='')}")


async def fetch_folder_listing(
    glider_name: str,
    folder: str,
    *,
    page: int = 0,
    filter_glob: Optional[str] = "*",
    last_modified_after: Optional[str] = None,
) -> Optional[Any]:
    """
    ``GET /sfmc/api/v1/glider-folder-file-listing/{glider}/{folder}``

    ``last_modified_after`` format: ``yyyyMMddHHmm`` (Teledyne convention).
    """
    params: dict[str, Any] = {"page": page}
    # Teledyne also accepts filter / lastModifiedAfter as query params (with page).
    if filter_glob is not None:
        params["filter"] = filter_glob
    if last_modified_after is not None:
        params["lastModifiedAfter"] = last_modified_after
    path = (
        f"/sfmc/api/v1/glider-folder-file-listing/"
        f"{quote(glider_name, safe='')}/{quote(folder, safe='')}"
    )
    return await _get_json(path, params=params)


async def download_glider_file_text(glider_name: str, folder: str, file_name: str) -> Optional[str]:
    path = (
        f"/sfmc/api/v1/download-glider-file/"
        f"{quote(glider_name, safe='')}/"
        f"{quote(folder, safe='')}/"
        f"{quote(file_name, safe='')}"
    )
    return await _get_text(path)


def _last_modified_after_24h() -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=24)
    return dt.strftime("%Y%m%d%H%M")


def _last_modified_after_hours(hours: float) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=max(0.0, float(hours)))
    return dt.strftime("%Y%m%d%H%M")


async def fetch_dmon_asc_files(
    glider_name: str,
    *,
    hours: float = 48.0,
    last_modified_after: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    List ``from-glider`` ``*.asc`` files (with timestamps) for DMON diagnostics.

    Paginates SFMC listings (typically 20 files/page). Uses ``lastModifiedAfter``
    for the rolling window (``hours`` back from now, or an explicit
    ``yyyyMMddHHmm`` stamp). When that window is empty but SFMC responds, falls
    back to an unfiltered ``*.asc`` listing so callers can still compute
    hours-since-last.
    """
    after = last_modified_after or _last_modified_after_hours(hours)
    entries = await fetch_folder_listing_all_pages(
        glider_name,
        "from-glider",
        filter_glob="*.asc",
        last_modified_after=after,
    )
    if entries:
        return entries
    # Empty window — try newest overall so gap-since-last still works.
    return await fetch_folder_listing_all_pages(
        glider_name,
        "from-glider",
        filter_glob="*.asc",
    )


async def fetch_surface_events_payload(glider_name: str) -> Optional[dict[str, Any]]:
    """Active deployment details (often includes mission / surface-event maps)."""
    payload = await fetch_active_deployment(glider_name)
    if isinstance(payload, dict) and (
        "missionExecutionsMap" in payload
        or "surfaceEventsPage" in payload
        or "missionName" in payload
        or "mission" in payload
    ):
        return payload
    return payload if isinstance(payload, dict) else None


async def fetch_dockserver_commands(glider_name: str) -> list[dict[str, Any]]:
    """
    Prefer scripts endpoint; command-log shape is not in the Teledyne REST lib.
    Returns [] when payload is not a command list (script name handled separately).
    """
    payload = await fetch_scripts_for_glider(glider_name)
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        if "dockServerScriptName" in payload[0] or "command" in payload[0]:
            return [c for c in payload if isinstance(c, dict)]
    if isinstance(payload, dict):
        for key in ("commands", "content", "items"):
            items = payload.get(key)
            if isinstance(items, list) and items and isinstance(items[0], dict):
                if "command" in items[0] or "dockServerScriptName" in items[0]:
                    return [c for c in items if isinstance(c, dict)]
    return []


async def fetch_latest_goto_from_archive(glider_name: str) -> Optional[dict[str, Any]]:
    """List ``archive`` for ``*_goto_*.ma``, download newest, parse ``initial_wpt``."""
    payload = await fetch_folder_listing(
        glider_name,
        "archive",
        page=0,
        filter_glob="*_goto_*.ma",
    )
    names = _folder_names_from_listing(payload)
    if not names:
        # Broader listing if filter unsupported
        payload = await fetch_folder_listing(glider_name, "archive", page=0, filter_glob="*")
        names = _folder_names_from_listing(payload)

    latest = pick_latest_goto_archive_filename(names)
    if not latest:
        return None

    text = await download_glider_file_text(glider_name, "archive", latest)
    if not text:
        return None
    parsed = parse_goto_ma(text)
    parsed["archive_filename"] = latest
    return parsed


async def fetch_offload_hint(glider_name: str) -> Optional[str]:
    """Yes if ``from-glider`` has files modified in the last 24h."""
    payload = await fetch_folder_listing(
        glider_name,
        "from-glider",
        page=0,
        filter_glob="*",
        last_modified_after=_last_modified_after_24h(),
    )
    names = _folder_names_from_listing(payload)
    if names:
        return "Yes"
    # Empty filtered listing → no recent files (or empty folder)
    if payload is not None:
        return "No — manual offload ASAP"
    return None


def _collect_log_filenames(obj: Any, found: Optional[list[str]] = None) -> list[str]:
    """Walk nested JSON for network log paths (``logFilePath`` / basename)."""
    if found is None:
        found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_l = str(key).lower()
            if key_l in ("logfilepath", "logfile", "logfilename", "logfile_name") and value:
                base = PurePosixPath(str(value).replace("\\", "/")).name
                if base and base not in found:
                    found.append(base)
            else:
                _collect_log_filenames(value, found)
    elif isinstance(obj, list):
        for item in obj:
            _collect_log_filenames(item, found)
    elif isinstance(obj, str) and "_network_net_" in obj.lower() and obj.lower().endswith(".log"):
        base = PurePosixPath(obj.replace("\\", "/")).name
        if base and base not in found:
            found.append(base)
    return found


async def fetch_glider_details(glider_name: str) -> Optional[dict[str, Any]]:
    payload = await _get_json(f"/sfmc/api/v1/gliders/{quote(glider_name, safe='')}")
    return payload if isinstance(payload, dict) else None


def _glider_id_from_details(payload: Optional[dict[str, Any]]) -> Optional[int]:
    if not isinstance(payload, dict):
        return None
    for key in ("id", "gliderId", "glider_id"):
        value = payload.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return None


async def fetch_glider_log_tail(
    glider_id: int,
    log_file_name: str,
    *,
    byte_count: int = 8000,
) -> Optional[str]:
    """
    Tail a dockserver network log via UI/API path:

    ``GET /sfmc/glider-requests/get-last-x-bytes-of-glider-log-file/{id}/{log}/{bytes}``

    Response shape: ``{success, data, startPosition, endPosition}``.
    Works with Bearer when the host permits API tokens on ``glider-requests``.
    """
    if glider_id <= 0 or not (log_file_name or "").strip() or byte_count <= 0:
        return None
    path = (
        "/sfmc/glider-requests/get-last-x-bytes-of-glider-log-file/"
        f"{int(glider_id)}/"
        f"{quote(log_file_name.strip(), safe='')}/"
        f"{int(byte_count)}"
    )
    payload = await _request("GET", path, expect_json=True)
    if not isinstance(payload, dict):
        return None
    if payload.get("success") is False:
        return None
    data = payload.get("data")
    if isinstance(data, str) and data.strip():
        return data
    return None


async def fetch_dialog_checklist_values(
    glider_name: str,
    *,
    details: Optional[dict[str, Any]] = None,
    deployment: Optional[dict[str, Any]] = None,
) -> dict[str, str]:
    """
    Resolve glider id + newest network log, read dialog text, map to checklist fields.

    Primary use: ``aborts_oddities_val`` from Device Status (t/m/s) + ABORT HISTORY.

    Live v1 active-deployment / gliders payloads often omit ``logFilePath``; when
    that happens we list the dockserver ``logs`` folder for ``*_network_net_*.log``.

    Prefer ``GET /sfmc/api/v1/download-glider-file/.../logs/...`` (Bearer works).
    The UI ``glider-requests`` log-tail path often returns the login HTML page.
    """
    if details is None:
        details = await fetch_glider_details(glider_name)

    candidates: list[str] = []
    if details:
        candidates.extend(_collect_log_filenames(details))

    if deployment is None:
        deployment = await fetch_active_deployment(glider_name)
    if deployment:
        candidates.extend(_collect_log_filenames(deployment))

    if not candidates:
        # Live REST shapes lack connectionsMap.logFilePath — list dockserver logs.
        try:
            listing = await fetch_folder_listing(
                glider_name,
                "logs",
                page=0,
                filter_glob="*_network_net_*.log",
            )
            candidates.extend(_folder_names_from_listing(listing))
        except Exception as err:
            logger.debug("SFMC logs folder listing failed for %s: %s", glider_name, err)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for name in candidates:
        if name not in seen:
            seen.add(name)
            unique.append(name)

    latest = pick_latest_network_log_filename(unique)
    if not latest:
        logger.warning(
            "SFMC dialog: no network log found for %s; Device Status skipped",
            glider_name,
        )
        return {}

    text = await download_glider_file_text(glider_name, "logs", latest)
    if not text:
        # Fallback: UI tail endpoint (may require session cookie on some hosts).
        glider_id = _glider_id_from_details(details)
        if glider_id is not None:
            text = await fetch_glider_log_tail(glider_id, latest, byte_count=24000)

    if not text or text.lstrip().startswith("<!DOCTYPE") or text.lstrip().startswith("<html"):
        logger.warning(
            "SFMC dialog: could not read network log for %s / %s",
            glider_name,
            latest,
        )
        return {}

    # Device Status / ABORT HISTORY sit at the end of the surface dialog.
    return dialog_values_for_checklist(parse_surface_dialog_log(text[-24000:]))


def _normalize_active_deployment_for_transforms(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Ensure transform helpers see missionExecutionsMap-style keys when the API
    returns a flatter active-deployment object.
    """
    if "missionExecutionsMap" in payload or "surfaceEventsPage" in payload:
        return payload

    out = dict(payload)
    mission_name = _mission_name_from_payload(payload)
    if mission_name:
        out.setdefault(
            "missionExecutionsMap",
            {
                "0": {
                    "missionName": mission_name,
                    "endDateTime": None,
                    "complete": False,
                }
            },
        )
    return out


async def load_sfmc_checklist_values(glider_name: str) -> dict[str, Any]:
    """
    Pull SFMC-derived checklist autofill for ``glider_name`` (e.g. ``peggy``).

    Returns empty dict when SFMC is unconfigured or unreachable/unauthorized.
    Requests are paced by ``sfmc_max_requests_per_minute`` and reuse payloads
    where possible to stay under SFMC's ~25 req/min limit.

    Scope: **active** SFMC deployments only (``active-deployment``, newest mission,
    live folder listings). Archived SFMC missions are not covered — callers must
    skip archived Buddy ``SlocumDeployment`` rows on the background refresh loop.

    May include a non-string ``connection_durations`` list for Vehicle Health charts
    and a ``dmon_asc_files`` list (normalized) for DMON ASC gap checks.
    """
    name = (glider_name or "").strip()
    if not name or not sfmc_is_configured():
        return {}

    parts: list[dict[str, str]] = []
    # Prefer active-deployment script name over scripts catalog (catalog has no assignment).
    active_script: Optional[str] = None
    surface: Optional[dict[str, Any]] = None
    connection_durations: list[dict[str, Any]] = []
    dmon_asc_raw: list[dict[str, Any]] = []

    try:
        mission = await fetch_newest_mission_details(name)
        mission_name = _mission_name_from_payload(mission)
        if mission_name:
            parts.append({"mission_file_running_val": mission_name})
    except Exception as err:
        logger.warning("SFMC newest-mission-details failed for %s: %s", name, err)

    try:
        surface = await fetch_surface_events_payload(name)
        if surface:
            normalized = _normalize_active_deployment_for_transforms(surface)
            transformed = extract_from_surface_events_payload(normalized)
            parts.append(transformed)
            connection_durations = extract_connection_durations(normalized)
            script_from_active = transformed.get("script_running_val")
            if script_from_active:
                active_script = script_from_active
            elif isinstance(surface.get("currentScriptName"), str):
                display = script_basename(surface["currentScriptName"])
                if surface.get("isCurrentScriptRunning") is False:
                    display = f"{display} (not running)"
                active_script = display
                parts.append({"script_running_val": display})
    except Exception as err:
        logger.warning("SFMC active-deployment fetch failed for %s: %s", name, err)

    try:
        # Reuse active-deployment payload; only fetch /gliders/{name} for id/log paths.
        dialog = await fetch_dialog_checklist_values(
            name,
            deployment=surface,
        )
        if dialog:
            parts.append(dialog)
    except Exception as err:
        logger.warning("SFMC dialog log-tail failed for %s: %s", name, err)

    # Scripts catalog / dockserver command log only when active-deployment
    # did not already provide the running script.
    if not active_script:
        try:
            scripts_payload = await fetch_scripts_for_glider(name)
            script_name = _extract_script_from_scripts_payload(scripts_payload)
            if script_name:
                parts.append({"script_running_val": script_name})
            # Reuse same payload when it is a command list; avoid a second GET.
            if isinstance(scripts_payload, list) and scripts_payload and isinstance(
                scripts_payload[0], dict
            ):
                if "dockServerScriptName" in scripts_payload[0] or "command" in scripts_payload[0]:
                    parts.append(extract_from_dockserver_commands(scripts_payload))
        except Exception as err:
            logger.warning("SFMC scripts fetch failed for %s: %s", name, err)

    try:
        offload = await fetch_offload_hint(name)
        if offload:
            parts.append({"offloaded_24h_val": offload})
    except Exception as err:
        logger.warning("SFMC from-glider listing failed for %s: %s", name, err)

    try:
        goto = await fetch_latest_goto_from_archive(name)
        if goto and goto.get("display"):
            parts.append({"goto_state_val": str(goto["display"])})
    except Exception as err:
        logger.warning("SFMC goto archive fetch failed for %s: %s", name, err)

    try:
        dmon_asc_raw = await fetch_dmon_asc_files(name, hours=48.0)
    except Exception as err:
        logger.warning("SFMC DMON *.asc listing failed for %s: %s", name, err)

    merged: dict[str, Any] = merge_sfmc_checklist_values(*parts)
    if connection_durations:
        merged["connection_durations"] = connection_durations
    if dmon_asc_raw is not None:
        # Store normalized summary (files + gap flags) so cache consumers share one shape.
        merged["dmon_asc_files"] = normalize_dmon_asc_files(dmon_asc_raw)
    if merged:
        logger.info(
            "SFMC checklist autofill for %s: %s",
            name,
            sorted(
                k
                for k in merged.keys()
                if k not in ("connection_durations", "dmon_asc_files")
            ),
        )
    return merged
