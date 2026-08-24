"""Live, read-only Sensor Tracker query helpers for the Team browser.

Uses authenticated httpx against the Tracker REST API. Does not use
``sensor_tracker_client`` (unreliable GETs / missing auth on fallbacks).
Mission sync/enrich stays in ``sensor_tracker_service``.
"""

from __future__ import annotations

import json
import logging
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx
from sqlmodel import Session as SQLModelSession, select

from app.config import settings
from app.core.models.database import SensorTrackerDeployment
from app.services.sensor_tracker_service import format_attached_time_for_api
from app.services.sensor_tracker_analytics import (
    build_analytics_payload,
    format_days,
    intersect_intervals,
    is_current_at,
    metric,
    open_windows,
    parse_window_time,
    total_days,
    windows_to_intervals,
)

logger = logging.getLogger(__name__)

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
RELATIONSHIP_FETCH_CAP = 500
# Tracker /api/sensor/ is ~235k rows and ignores search=/serial=; exact identifier=
# works, and attached sensors live on the much smaller sensor_on_instrument list.
IDENTIFIER_LOOKUP_MAX_COUNT = 100
SENSOR_ATTACH_SCAN_CAP = 2500
# Tracker /api/deployment/ ignores search=/title= (~1k rows). After platform_name=,
# Buddy may walk that catalog (never the 235k sensor list).
DEPLOYMENT_SCAN_CAP = 2500
REQUEST_TIMEOUT_S = 30.0
PROBE_TTL_S = 300.0

_PROBE_CACHE: Dict[str, Tuple[bool, float]] = {}
# Paths where a Token header 403s lists that work anonymously (prod pattern).
_AUTH_403_PATHS: set[str] = set()
# Query keys Tracker has 403'd on a given list path ("doesn't accept … parameter").
_REJECTED_PARAMS_BY_PATH: Dict[str, set[str]] = {}
# Same-request cache for relationship list walks (analytics N+1).
_ST_WALK_CACHE: ContextVar[Optional[Dict[Tuple[Any, ...], Any]]] = ContextVar(
    "st_walk_cache", default=None
)


class SensorTrackerQueryError(Exception):
    """Upstream Tracker or validation failure for the Team browser."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class EntitySpec:
    key: str
    label: str
    path: str
    search_hint: str
    search_params: Tuple[str, ...]
    columns: Tuple[str, ...]
    relations: Tuple[str, ...]
    optional: bool = False
    extra_list_params: Dict[str, Any] = field(default_factory=dict)
    alt_paths: Tuple[str, ...] = ()


ENTITY_REGISTRY: Dict[str, EntitySpec] = {
    "platform": EntitySpec(
        key="platform",
        label="Platforms",
        path="platform",
        search_hint="Partial name or serial (e.g. 1070)",
        search_params=("name",),
        columns=("id", "name", "serial_number", "active"),
        relations=("deployments", "loggers", "instruments", "components"),
    ),
    "deployment": EntitySpec(
        key="deployment",
        label="Deployments",
        path="deployment",
        search_hint="Number, m###, title, or platform (partial OK)",
        search_params=("deployment_number", "platform_name", "title"),
        columns=("id", "deployment_number", "title", "platform", "start_time", "end_time"),
        relations=("platform", "loggers", "instruments", "sensors", "components"),
    ),
    "data_logger": EntitySpec(
        key="data_logger",
        label="Loggers",
        path="data_logger",
        search_hint="Partial identifier, name, or serial",
        search_params=("identifier", "name"),
        columns=("id", "identifier", "name", "serial"),
        relations=("instruments",),
        optional=True,
        alt_paths=("datalogger",),
    ),
    "instrument": EntitySpec(
        key="instrument",
        label="Instruments",
        path="instrument",
        search_hint="Partial identifier, serial, or short name",
        search_params=("identifier", "serial"),
        columns=("id", "identifier", "serial", "short_name", "active"),
        relations=("sensors",),
    ),
    "sensor": EntitySpec(
        key="sensor",
        label="Sensors",
        path="sensor",
        search_hint="Id, exact identifier, or a token from an attached sensor (e.g. SBE43F, 4051)",
        search_params=("identifier", "short_name", "long_name"),
        columns=("id", "identifier", "short_name", "long_name", "serial"),
        relations=("instruments",),
    ),
    "component": EntitySpec(
        key="component",
        label="Components",
        path="component",
        search_hint="Partial name or serial",
        search_params=("name", "serial"),
        columns=("id", "name", "serial", "comment"),
        relations=("platforms", "deployments"),
        optional=True,
        alt_paths=("platform_component",),
    ),
}

RELATION_TARGET: Dict[str, str] = {
    "deployments": "deployment",
    "loggers": "data_logger",
    "instruments": "instrument",
    "sensors": "sensor",
    "platform": "platform",
    "platforms": "platform",
    "components": "component",
}

_NESTED_KEYS: Dict[str, Tuple[str, ...]] = {
    "deployment": ("deployment",),
    "data_logger": ("data_logger", "logger"),
    "instrument": ("instrument",),
    "sensor": ("sensor",),
    "platform": ("platform",),
    "component": ("component",),
}


def get_spec(entity: str) -> EntitySpec:
    spec = ENTITY_REGISTRY.get(entity)
    if spec is None:
        raise SensorTrackerQueryError(f"Unknown entity type: {entity}", status_code=404)
    return spec


def clamp_page(page: Optional[int]) -> int:
    try:
        value = int(page) if page is not None else 1
    except (TypeError, ValueError):
        value = 1
    return max(1, value)


def clamp_page_size(page_size: Optional[int]) -> int:
    try:
        value = int(page_size) if page_size is not None else DEFAULT_PAGE_SIZE
    except (TypeError, ValueError):
        value = DEFAULT_PAGE_SIZE
    return max(1, min(value, MAX_PAGE_SIZE))


def tracker_base_url() -> str:
    if settings.sensor_tracker_debug:
        host = settings.sensor_tracker_debug_host or settings.sensor_tracker_host
    else:
        host = settings.sensor_tracker_host
    return str(host).rstrip("/")


def _auth_headers() -> Dict[str, str]:
    headers = {"Accept": "application/json"}
    token = settings.sensor_tracker_token
    if token:
        headers["Authorization"] = f"Token {token}"
    return headers


def _httpx_auth() -> Optional[Tuple[str, str]]:
    if settings.sensor_tracker_token:
        return None
    username = settings.sensor_tracker_username
    password = settings.sensor_tracker_password
    if username and password:
        return (username, password)
    return None


def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fmt_cell(value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, dict):
        nested = (
            value.get("name")
            or value.get("identifier")
            or value.get("title")
            or value.get("short_name")
            or value.get("id")
            or value.get("pk")
        )
        return _fmt_cell(nested)
    if isinstance(value, (list, tuple)):
        return None
    return str(value)


def _record_id(row: Dict[str, Any]) -> Optional[int]:
    return _as_int(row.get("id") if row.get("id") is not None else row.get("pk"))


def _title_for(entity: str, row: Dict[str, Any]) -> str:
    for key in (
        "title",
        "name",
        "identifier",
        "short_name",
        "long_name",
        "platform_name",
        "deployment_number",
    ):
        text = _fmt_cell(row.get(key))
        if text:
            return text
    rec_id = _record_id(row)
    if rec_id is not None:
        return f"{entity} {rec_id}"
    return entity


def summarize_cells(entity: str, row: Dict[str, Any]) -> Dict[str, Optional[str]]:
    spec = ENTITY_REGISTRY.get(entity)
    columns = spec.columns if spec else ("id",)
    cells: Dict[str, Optional[str]] = {}
    for col in columns:
        if col == "id":
            rec_id = _record_id(row)
            cells[col] = str(rec_id) if rec_id is not None else None
        else:
            cells[col] = _fmt_cell(row.get(col))
    return cells


def summarize_row(entity: str, row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": _record_id(row),
        "entity": entity,
        "title": _title_for(entity, row),
        "cells": summarize_cells(entity, row),
    }


def looks_like_pk(query: str) -> Optional[int]:
    stripped = query.strip()
    if stripped.isdigit():
        return int(stripped)
    return None


def parse_deployment_number(query: str) -> Optional[int]:
    stripped = query.strip()
    if not stripped:
        return None
    if stripped.lower().startswith("m") and stripped[1:].isdigit():
        return int(stripped[1:])
    if stripped.isdigit():
        return int(stripped)
    return None


def build_search_params(spec: EntitySpec, query: str) -> Dict[str, Any]:
    """Map a single search box string onto Tracker filter params.

    Exact ``deployment_number`` is kept for ``m###`` / digits. Everything else
    uses DRF ``search=`` (substring across Tracker search fields when supported).
    """
    q = (query or "").strip()
    params: Dict[str, Any] = {}
    params.update(spec.extra_list_params)
    if not q:
        return params

    if spec.key == "deployment":
        number = parse_deployment_number(q)
        if number is not None and (q.isdigit() or (
            q.lower().startswith("m") and q[1:].isdigit()
        )):
            params["deployment_number"] = number
            return params

    params["search"] = q
    return params


def _append_search_text(value: Any, parts: List[str], *, depth: int = 0) -> None:
    if value in (None, "") or depth > 2:
        return
    if isinstance(value, dict):
        for nested in value.values():
            _append_search_text(nested, parts, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for nested in value[:30]:
            _append_search_text(nested, parts, depth=depth + 1)
        return
    text = _fmt_cell(value)
    if text:
        parts.append(text)


def search_haystack(entity: str, row: Dict[str, Any]) -> str:
    """Flatten displayed + common Tracker fields for substring matching."""
    if not isinstance(row, dict):
        return ""
    parts: List[str] = []
    summary = summarize_row(entity, row)
    rec_id = summary.get("id")
    if rec_id is not None:
        parts.append(str(rec_id))
    title = summary.get("title")
    if title:
        parts.append(str(title))
    for value in (summary.get("cells") or {}).values():
        if value not in (None, ""):
            parts.append(str(value))
    for key in (
        "name",
        "identifier",
        "serial",
        "serial_number",
        "short_name",
        "long_name",
        "title",
        "deployment_number",
        "platform_name",
    ):
        _append_search_text(row.get(key), parts)
    _append_search_text(row.get("platform"), parts)
    if entity == "deployment":
        number = row.get("deployment_number")
        if number not in (None, ""):
            parts.append(f"m{number}")
    return " ".join(parts).casefold()


def search_tokens(query: str) -> List[str]:
    """Whitespace tokens that should participate in AND matching.

    Punctuation-only pieces (``-``, ``·``) are skipped so a related-list title
    like ``Oxygen - 4051`` still matches identifier ``… Oxygen - 4051``.
    """
    tokens: List[str] = []
    for token in (query or "").strip().casefold().split():
        if not token or not any(char.isalnum() for char in token):
            continue
        tokens.append(token)
    return tokens


def identifier_lookup_candidates(query: str) -> List[str]:
    """Exact Tracker ``identifier=`` strings to try for a Sensors-tab query.

    Related-list titles append serial with `` · ``, and when the identifier
    already ends in that serial the UI can look like ``… - 4051 - 4051``.
    Tracker ``identifier=`` is exact-only (``SBE43F`` returns 0).
    """
    text = (query or "").strip()
    if not text:
        return []
    candidates: List[str] = []

    def add(value: str) -> None:
        stripped = value.strip()
        if stripped and stripped not in candidates:
            candidates.append(stripped)

    add(text)
    if " · " in text:
        add(text.split(" · ", 1)[0])
    parts = re.split(r"\s+[·\-]\s+", text)
    if len(parts) >= 3 and parts[-1].casefold() == parts[-2].casefold():
        add(" - ".join(parts[:-1]))
    return candidates


def row_matches_search(entity: str, row: Dict[str, Any], query: str) -> bool:
    """True when every useful whitespace token in ``query`` appears in the row."""
    tokens = search_tokens(query)
    if not tokens:
        return not (query or "").strip()
    hay = search_haystack(entity, row)
    return all(token in hay for token in tokens)


def _search_sort_key(entity: str, row: Dict[str, Any], query: str) -> Tuple[int, str]:
    needle = (query or "").strip().casefold()
    title = (summarize_row(entity, row).get("title") or "").casefold()
    if needle and title == needle:
        tier = 0
    elif needle and title.startswith(needle):
        tier = 1
    elif needle and needle in title:
        tier = 2
    else:
        tier = 3
    return (tier, title)


def normalize_list_payload(
    data: Any,
    *,
    page: int,
    page_size: int,
) -> Tuple[List[Dict[str, Any]], int, bool, bool]:
    """Return (results, count, has_next, has_prev)."""
    results: List[Dict[str, Any]] = []
    count: Optional[int] = None
    has_next: Optional[bool] = None
    has_prev: Optional[bool] = None
    paginated = False

    if isinstance(data, dict) and isinstance(data.get("results"), list):
        results = [r for r in data["results"] if isinstance(r, dict)]
        if "count" in data:
            try:
                count = int(data["count"])
            except (TypeError, ValueError):
                count = None
        if "next" in data or "previous" in data:
            paginated = True
            has_next = bool(data.get("next"))
            has_prev = bool(data.get("previous"))
    elif isinstance(data, list):
        results = [r for r in data if isinstance(r, dict)]
    elif isinstance(data, dict):
        results = [data]
    else:
        results = []

    if paginated:
        total = count if count is not None else len(results)
        return results, total, bool(has_next), bool(has_prev)

    total = count if count is not None else len(results)
    start = (page - 1) * page_size
    sliced = results[start : start + page_size]
    return sliced, total, start + page_size < total, page > 1 and start > 0


# Tracker often 403s unknown filter keys (same pattern as instrument=<id>).
_ST_PAGINATION_PARAMS = frozenset({"page", "page_size", "limit", "offset"})


def _api_url(path: str, resource_id: Optional[int] = None) -> str:
    base = tracker_base_url()
    suffix = f"{path.strip('/')}/"
    if resource_id is not None:
        return f"{base}/api/{suffix}{resource_id}/"
    return f"{base}/api/{suffix}"


def sanitize_tracker_params(
    params: Optional[Dict[str, Any]],
    path: Optional[str] = None,
) -> Dict[str, Any]:
    """Drop empty values, pagination keys, and params Tracker already 403'd on ``path``."""
    banned = set(_ST_PAGINATION_PARAMS)
    if path:
        banned.update(_REJECTED_PARAMS_BY_PATH.get(path, ()))
    clean: Dict[str, Any] = {}
    for key, value in (params or {}).items():
        if value is None or value == "":
            continue
        if key in banned:
            continue
        clean[key] = value
    return clean


_REJECTED_PARAM_RE = re.compile(
    r"doesn't accept following parameter:\s*(.+)",
    re.IGNORECASE,
)


def parse_rejected_params(body: str) -> Tuple[str, ...]:
    """Parse Tracker's 403 list of disallowed query keys."""
    text = body or ""
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            text = str(data.get("error detail") or data.get("detail") or text)
    except (TypeError, ValueError):
        pass
    match = _REJECTED_PARAM_RE.search(text)
    if not match:
        return ()
    names = []
    for part in match.group(1).split(","):
        name = part.strip().strip("'\").").strip()
        if name:
            names.append(name)
    return tuple(names)


def _body_snippet(response: httpx.Response, limit: int = 180) -> str:
    text = (response.text or "").strip().replace("\n", " ")
    if len(text) > limit:
        return text[:limit] + "…"
    return text


async def st_get_json(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    resource_id: Optional[int] = None,
    client: Optional[httpx.AsyncClient] = None,
    absolute_url: Optional[str] = None,
) -> Any:
    """GET a Tracker API path and return parsed JSON."""
    url = absolute_url or _api_url(path, resource_id)
    clean_params = {} if absolute_url else sanitize_tracker_params(params, path=path)
    owns_client = client is None
    headers = _auth_headers()
    auth = _httpx_auth()
    if owns_client:
        client = httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_S,
            follow_redirects=True,
        )
    try:
        request_headers = dict(headers)
        anon_headers = {
            k: v for k, v in request_headers.items() if k.lower() != "authorization"
        }
        skip_auth = bool(path) and path in _AUTH_403_PATHS

        async def _get(
            use_headers: Dict[str, str],
            use_auth: Any,
            extra_params: Optional[Dict[str, Any]] = None,
        ) -> httpx.Response:
            # Do not pass params={} on Tracker next URLs — httpx then strips the
            # existing query (depth, identifier, offset) and later pages un-nest.
            kwargs: Dict[str, Any] = {"headers": use_headers, "auth": use_auth}
            if extra_params is not None:
                kwargs["params"] = extra_params
            elif not absolute_url:
                kwargs["params"] = clean_params
            return await client.get(url, **kwargs)

        if skip_auth:
            response = await _get(anon_headers, None)
        else:
            response = await _get(request_headers, auth)
        # Prod Tracker GET is documented as anonymous; a stale Token header 403s
        # lists that succeed without Authorization (catalog uses skip_auth).
        sent_auth = (not skip_auth) and (
            "Authorization" in request_headers or auth is not None
        )
        if response.status_code in (401, 403) and sent_auth:
            logger.info(
                "Sensor Tracker HTTP %s with auth on %s; retrying anonymous GET",
                response.status_code,
                response.url,
            )
            if path:
                _AUTH_403_PATHS.add(path)
            response = await _get(anon_headers, None)
        if response.status_code == 403 and clean_params:
            rejected = parse_rejected_params(response.text or "")
            dropped = {k: v for k, v in clean_params.items() if k not in rejected}
            if rejected and dropped != clean_params:
                logger.info(
                    "Sensor Tracker rejected params %s on %s; retrying without them",
                    ",".join(rejected),
                    path,
                )
                if path:
                    _REJECTED_PARAMS_BY_PATH.setdefault(path, set()).update(rejected)
                clean_params = dropped
                response = await _get(anon_headers, None, extra_params=dropped)
        if response.status_code == 404:
            raise SensorTrackerQueryError("Not found in Sensor Tracker", status_code=404)
        if response.status_code in (401, 403):
            logger.warning(
                "Sensor Tracker GET %s failed: HTTP %s body=%s",
                response.url,
                response.status_code,
                _body_snippet(response),
            )
            raise SensorTrackerQueryError(
                "Sensor Tracker refused this query (HTTP 403). "
                "Enter a name, identifier, serial, or id — unfiltered lists and "
                "unknown query parameters are often blocked.",
                status_code=400,
            )
        if response.status_code >= 400:
            logger.warning(
                "Sensor Tracker GET %s failed: HTTP %s body=%s",
                response.url,
                response.status_code,
                _body_snippet(response),
            )
            raise SensorTrackerQueryError(
                f"Sensor Tracker returned HTTP {response.status_code}",
                status_code=502,
            )
        try:
            return response.json()
        except Exception as exc:
            raise SensorTrackerQueryError(
                "Sensor Tracker returned a non-JSON response",
                status_code=502,
            ) from exc
    except SensorTrackerQueryError:
        raise
    except httpx.TimeoutException as exc:
        raise SensorTrackerQueryError(
            "Sensor Tracker request timed out",
            status_code=504,
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning("Sensor Tracker HTTP error for %s: %s", url, exc)
        raise SensorTrackerQueryError(
            "Could not reach Sensor Tracker",
            status_code=502,
        ) from exc
    finally:
        if owns_client and client is not None:
            await client.aclose()


async def _probe_path(path: str, client: Optional[httpx.AsyncClient] = None) -> bool:
    cached = _PROBE_CACHE.get(path)
    now = time.monotonic()
    if cached and (now - cached[1]) < PROBE_TTL_S:
        return cached[0]
    available = False
    url = _api_url(path)
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_S,
            follow_redirects=True,
            headers=_auth_headers(),
            auth=_httpx_auth(),
        )
    try:
        response = await client.get(url)
        if response.status_code == 404:
            available = False
        else:
            # 200, 401/403 (exists but gated), 400 (bad filter) all mean the route exists.
            available = response.status_code != 404
    except httpx.HTTPError:
        # Network blip: do not hide the tab.
        available = True
        logger.warning("Sensor Tracker probe failed for %s; leaving tab visible", path)
    finally:
        if owns_client and client is not None:
            await client.aclose()
    _PROBE_CACHE[path] = (available, now)
    return available


def clear_probe_cache() -> None:
    _PROBE_CACHE.clear()
    _AUTH_403_PATHS.clear()
    _REJECTED_PARAMS_BY_PATH.clear()


async def resolve_entity_path(
    spec: EntitySpec,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    if not spec.optional and not spec.alt_paths:
        return spec.path
    if await _probe_path(spec.path, client=client):
        return spec.path
    for alt in spec.alt_paths:
        if await _probe_path(alt, client=client):
            return alt
    if spec.optional:
        raise SensorTrackerQueryError(
            f"Sensor Tracker has no {spec.label.lower()} list endpoint",
            status_code=404,
        )
    return spec.path


async def is_entity_available(
    spec: EntitySpec,
    client: Optional[httpx.AsyncClient] = None,
) -> bool:
    if not spec.optional:
        return True
    try:
        await resolve_entity_path(spec, client=client)
        return True
    except SensorTrackerQueryError:
        return False


async def probe_connection(client: Optional[httpx.AsyncClient] = None) -> Tuple[bool, Optional[str]]:
    try:
        await st_get_json("platform", client=client)
        return True, None
    except SensorTrackerQueryError as exc:
        return False, exc.message


async def list_entity_meta(client: Optional[httpx.AsyncClient] = None) -> Dict[str, Any]:
    connected, error = await probe_connection(client=client)
    entities = []
    for spec in ENTITY_REGISTRY.values():
        available = await is_entity_available(spec, client=client)
        entities.append(
            {
                "key": spec.key,
                "label": spec.label,
                "available": available,
                "search_hint": spec.search_hint,
                "columns": list(spec.columns),
                "relations": list(spec.relations),
            }
        )
    return {
        "host": tracker_base_url(),
        "connected": connected,
        "error": error,
        "entities": entities,
    }


def _coerce_detail_record(data: Any) -> Dict[str, Any]:
    if isinstance(data, list):
        if not data or not isinstance(data[0], dict):
            raise SensorTrackerQueryError("Not found in Sensor Tracker", status_code=404)
        data = data[0]
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        rows = [r for r in data["results"] if isinstance(r, dict)]
        if not rows:
            raise SensorTrackerQueryError("Not found in Sensor Tracker", status_code=404)
        data = rows[0]
    if not isinstance(data, dict):
        raise SensorTrackerQueryError("Unexpected Sensor Tracker detail payload", status_code=502)
    return data


async def get_entity_record(
    entity: str,
    resource_id: int,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    spec = get_spec(entity)
    last_error: Optional[SensorTrackerQueryError] = None
    for path in (spec.path, *spec.alt_paths):
        try:
            data = await st_get_json(path, resource_id=resource_id, client=client)
            return _coerce_detail_record(data)
        except SensorTrackerQueryError as exc:
            last_error = exc
            if exc.status_code != 404:
                raise
    raise last_error or SensorTrackerQueryError("Not found in Sensor Tracker", status_code=404)


def _web_url(spec: EntitySpec, resource_id: Optional[int]) -> Optional[str]:
    if resource_id is None:
        return tracker_base_url() or None
    # Best-effort: Tracker UI paths vary (Django admin vs Svelte). API URL is always valid.
    return _api_url(spec.path, resource_id)


async def get_entity_detail(
    entity: str,
    resource_id: int,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    spec = get_spec(entity)
    record = await get_entity_record(entity, resource_id, client=client)
    rec_id = _record_id(record) or resource_id
    return {
        "entity": entity,
        "id": rec_id,
        "title": _title_for(entity, record),
        "summary": summarize_cells(entity, record),
        "relations": list(spec.relations),
        "st_api_url": _api_url(spec.path, rec_id),
        "st_web_url": _web_url(spec, rec_id),
        "raw": record,
    }


def _windows_from_rows(rows: Sequence[Dict[str, Any]]) -> List[Tuple[Any, Any]]:
    windows: List[Tuple[Any, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        windows.append(relationship_window(row))
    return windows


def _attachment_service_metrics(
    attached_windows: Sequence[Tuple[Any, Any]],
    sea: Sequence[Tuple[datetime, datetime]],
    current_sea: Sequence[Tuple[datetime, datetime]],
    as_of: datetime,
) -> List[Dict[str, str]]:
    attached = windows_to_intervals(attached_windows, as_of)
    attached_days = total_days(attached)
    sea_days = total_days(sea)
    shelf_days = round(max(0.0, attached_days - sea_days), 1)
    return [
        metric("days_at_sea", "Days at sea", format_days(sea_days)),
        metric(
            "days_on_current_deployment",
            "Days on current deployment",
            format_days(total_days(current_sea)),
        ),
        metric("days_attached", "Days attached", format_days(attached_days)),
        metric(
            "days_on_shelf",
            "Days on shelf (attached, not deployed)",
            format_days(shelf_days),
        ),
        metric(
            "currently_attached",
            "Currently attached",
            "yes" if is_current_at(attached_windows, as_of) else "no",
        ),
    ]


async def _deployment_records_for_platform(
    *,
    platform_id: Optional[int],
    platform_name: Optional[str],
    platform_serial: Optional[str],
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[List[Dict[str, Any]], bool]:
    if not platform_name and platform_id is not None:
        try:
            record = await get_entity_record("platform", platform_id, client=client)
        except SensorTrackerQueryError:
            record = None
        if isinstance(record, dict):
            platform_name = _platform_name(record)
            platform_serial = platform_serial or _serial_of(record)
    if not platform_name:
        return [], False
    raw_rows, _, more = await _walk_tracker_pages(
        "deployment",
        {"platform_name": platform_name},
        min_rows=RELATIONSHIP_FETCH_CAP,
        max_rows=RELATIONSHIP_FETCH_CAP,
        client=client,
    )
    if platform_id is not None:
        raw_rows = pin_relationship_rows(
            raw_rows,
            parent_id=platform_id,
            parent_entity="platform",
            parent_serial=platform_serial,
            require_match=False,
        )
    return raw_rows, more


async def _deployment_windows_for_platform(
    *,
    platform_id: Optional[int],
    platform_name: Optional[str],
    platform_serial: Optional[str],
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[List[Tuple[Any, Any]], bool]:
    raw_rows, more = await _deployment_records_for_platform(
        platform_id=platform_id,
        platform_name=platform_name,
        platform_serial=platform_serial,
        client=client,
    )
    return _windows_from_rows(raw_rows), more


async def _pinned_relationship_history(
    path: str,
    params: Dict[str, Any],
    *,
    parent_id: int,
    parent_entity: str,
    parent_serial: Optional[str],
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[List[Dict[str, Any]], bool]:
    try:
        rows, _count, more = await _walk_tracker_pages(
            path,
            params,
            min_rows=RELATIONSHIP_FETCH_CAP,
            max_rows=RELATIONSHIP_FETCH_CAP,
            client=client,
        )
    except SensorTrackerQueryError as exc:
        if exc.status_code == 404:
            return [], False
        raise
    pinned = pin_relationship_rows(
        rows,
        parent_id=parent_id,
        parent_entity=parent_entity,
        parent_serial=parent_serial,
    )
    return pinned, more


async def _nested_or_fetched_record(
    nested: Any,
    entity: str,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[Dict[str, Any]]:
    if isinstance(nested, dict):
        return nested
    fk = _as_int(nested)
    if fk is None:
        return None
    try:
        return await get_entity_record(entity, fk, client=client)
    except SensorTrackerQueryError:
        return None


async def _platform_ref_from_relationship(
    row: Dict[str, Any],
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    nested = row.get("platform")
    if isinstance(nested, dict):
        plat_id = _record_id(nested)
        name = _platform_name(nested)
        serial = _serial_of(nested)
        if name or plat_id is None:
            return plat_id, name, serial
        record = await _nested_or_fetched_record(plat_id, "platform", client=client)
        if not isinstance(record, dict):
            return plat_id, None, serial
        return plat_id, _platform_name(record), serial or _serial_of(record)
    fk = _as_int(nested)
    if fk is None:
        return None, None, None
    record = await _nested_or_fetched_record(fk, "platform", client=client)
    if not isinstance(record, dict):
        return fk, None, None
    return _record_id(record) or fk, _platform_name(record), _serial_of(record)


async def _logger_ref_from_relationship(
    row: Dict[str, Any],
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    nested = row.get("data_logger")
    if nested is None:
        nested = row.get("logger")
    if isinstance(nested, dict):
        return (
            _record_id(nested),
            _identifier(nested, "identifier"),
            _serial_of(nested),
        )
    record = await _nested_or_fetched_record(nested, "data_logger", client=client)
    if not isinstance(record, dict):
        return _as_int(nested), None, None
    return (
        _record_id(record) or _as_int(nested),
        _identifier(record, "identifier"),
        _serial_of(record),
    )


async def _platform_sea_cache_entry(
    *,
    plat_id: Optional[int],
    plat_name: Optional[str],
    plat_serial: Optional[str],
    as_of: datetime,
    cache: Dict[Tuple[Optional[int], Optional[str]], Tuple[List[Tuple[datetime, datetime]], List[Tuple[datetime, datetime]], bool]],
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[List[Tuple[datetime, datetime]], List[Tuple[datetime, datetime]], bool]:
    cache_key = (plat_id, plat_name)
    if cache_key not in cache:
        windows, more = await _deployment_windows_for_platform(
            platform_id=plat_id,
            platform_name=plat_name,
            platform_serial=plat_serial,
            client=client,
        )
        cache[cache_key] = (
            windows_to_intervals(windows, as_of),
            windows_to_intervals(open_windows(windows, as_of), as_of),
            more,
        )
    return cache[cache_key]


async def _logger_on_platform_rows(
    *,
    logger_id: int,
    logger_identifier: Optional[str],
    logger_serial: Optional[str],
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[List[Dict[str, Any]], bool]:
    if not logger_identifier:
        return [], False
    return await _pinned_relationship_history(
        "data_logger_on_platform",
        {"depth": 1, "data_logger_identifier": logger_identifier},
        parent_id=logger_id,
        parent_entity="data_logger",
        parent_serial=logger_serial,
        client=client,
    )


async def _sea_intervals_for_attachment_rows(
    rows: Sequence[Dict[str, Any]],
    as_of: datetime,
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[List[Tuple[datetime, datetime]], List[Tuple[datetime, datetime]], bool]:
    """Intersect attachment windows with platform deployments.

    Rows may be ``*_on_platform`` (nested platform) or ``instrument_on_data_logger``
    (nested logger → logger-on-platform → that platform's deployments).
    """
    plat_cache: Dict[
        Tuple[Optional[int], Optional[str]],
        Tuple[List[Tuple[datetime, datetime]], List[Tuple[datetime, datetime]], bool],
    ] = {}
    logger_cache: Dict[int, Tuple[List[Dict[str, Any]], bool]] = {}
    sea: List[Tuple[datetime, datetime]] = []
    current_sea: List[Tuple[datetime, datetime]] = []
    truncated = False

    async def _add_platform_sea(
        attached_one: List[Tuple[datetime, datetime]],
        plat_id: Optional[int],
        plat_name: Optional[str],
        plat_serial: Optional[str],
    ) -> None:
        nonlocal truncated
        if not plat_name and plat_id is None:
            return
        plat_sea, plat_current, more = await _platform_sea_cache_entry(
            plat_id=plat_id,
            plat_name=plat_name,
            plat_serial=plat_serial,
            as_of=as_of,
            cache=plat_cache,
            client=client,
        )
        truncated = truncated or more
        sea.extend(intersect_intervals(attached_one, plat_sea))
        current_sea.extend(intersect_intervals(attached_one, plat_current))

    for row in rows:
        if not isinstance(row, dict):
            continue
        attached_one = windows_to_intervals([relationship_window(row)], as_of)
        if not attached_one:
            continue
        plat_id, plat_name, plat_serial = await _platform_ref_from_relationship(
            row, client=client
        )
        if plat_name or plat_id is not None:
            await _add_platform_sea(attached_one, plat_id, plat_name, plat_serial)
            continue
        logger_id, logger_ident, logger_serial = await _logger_ref_from_relationship(
            row, client=client
        )
        if logger_id is None:
            continue
        if logger_id not in logger_cache:
            logger_cache[logger_id] = await _logger_on_platform_rows(
                logger_id=logger_id,
                logger_identifier=logger_ident,
                logger_serial=logger_serial,
                client=client,
            )
        logger_rows, more = logger_cache[logger_id]
        truncated = truncated or more
        for logger_row in logger_rows:
            if not isinstance(logger_row, dict):
                continue
            on_logger_plat = windows_to_intervals(
                [relationship_window(logger_row)], as_of
            )
            overlap = intersect_intervals(attached_one, on_logger_plat)
            if not overlap:
                continue
            lp_id, lp_name, lp_serial = await _platform_ref_from_relationship(
                logger_row, client=client
            )
            await _add_platform_sea(overlap, lp_id, lp_name, lp_serial)
    return sea, current_sea, truncated


async def _instrument_attachment_rows(
    record: Dict[str, Any],
    rec_id: int,
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[List[Dict[str, Any]], bool, List[str]]:
    identifier = _identifier(record, "identifier")
    notes: List[str] = []
    if not identifier:
        notes.append(
            "No identifier on this record, so attachment history cannot be queried."
        )
        return [], False, notes
    serial = _serial_of(record)
    rows: List[Dict[str, Any]] = []
    truncated = False
    for path in ("instrument_on_platform", "instrument_on_data_logger"):
        pinned, more = await _pinned_relationship_history(
            path,
            {"depth": 1, "instrument_identifier": identifier},
            parent_id=rec_id,
            parent_entity="instrument",
            parent_serial=serial,
            client=client,
        )
        truncated = truncated or more
        rows.extend(pinned)
    return rows, truncated, notes


async def _sensor_parent_instrument(
    record: Dict[str, Any],
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[Dict[str, Any]]:
    nested = record.get("current_instrument")
    if nested in (None, ""):
        nested = record.get("instrument")
    if isinstance(nested, dict):
        rec_id = _record_id(nested)
        if rec_id is not None and _identifier(nested, "identifier") is None:
            fetched = await _nested_or_fetched_record(rec_id, "instrument", client=client)
            return fetched if isinstance(fetched, dict) else nested
        return nested
    return await _nested_or_fetched_record(nested, "instrument", client=client)


async def _sensor_on_instrument_rows(
    record: Dict[str, Any],
    rec_id: int,
    *,
    rel_params: Optional[Dict[str, Any]] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[List[Dict[str, Any]], bool]:
    """``sensor_on_instrument`` rows pinned to this sensor instance."""
    params: Dict[str, Any] = {"depth": 1}
    if rel_params:
        params.update({k: v for k, v in rel_params.items() if v not in (None, "")})
    identifier = _identifier(record, "identifier")
    serial = _serial_of(record)

    async def _pin(query: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Optional[int], bool]:
        rows, count, more = await _walk_tracker_pages(
            "sensor_on_instrument",
            query,
            min_rows=SENSOR_ATTACH_SCAN_CAP,
            max_rows=SENSOR_ATTACH_SCAN_CAP,
            client=client,
        )
        pinned = pin_relationship_rows(
            rows,
            parent_id=rec_id,
            parent_entity="sensor",
            parent_serial=serial,
        )
        return pinned, count, more

    if identifier:
        ident_query = dict(params)
        ident_query["sensor_identifier"] = identifier
        pinned, count, more = await _pin(ident_query)
        if pinned:
            return pinned, more
        if count == 0:
            return [], False
    pinned, _count, more = await _pin(params)
    return pinned, more


async def _component_attachment_rows(
    record: Dict[str, Any],
    rec_id: int,
    *,
    rel_params: Optional[Dict[str, Any]] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[List[Dict[str, Any]], bool]:
    params = {"depth": 1}
    if rel_params:
        params.update(rel_params)
    return await _pinned_relationship_history(
        "component_on_platform",
        params,
        parent_id=rec_id,
        parent_entity="component",
        parent_serial=_serial_of(record),
        client=client,
    )


def _fmt_interval_bound(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


async def _overlapping_deployment_rows(
    attach_rows: Sequence[Dict[str, Any]],
    as_of: datetime,
    client: Optional[httpx.AsyncClient] = None,
) -> List[Dict[str, Any]]:
    """Deployment records whose windows overlap a component/logger attach stint."""
    cache: Dict[
        Tuple[Optional[int], Optional[str]],
        Tuple[List[Dict[str, Any]], bool],
    ] = {}
    wrappers: List[Dict[str, Any]] = []
    seen_dep: set[int] = set()
    for attach in attach_rows:
        if not isinstance(attach, dict):
            continue
        attach_iv = windows_to_intervals([relationship_window(attach)], as_of)
        if not attach_iv:
            continue
        _attach_start, attach_end = relationship_window(attach)
        plat_id, plat_name, plat_serial = await _platform_ref_from_relationship(
            attach, client=client
        )
        cache_key = (plat_id, plat_name)
        if cache_key not in cache:
            cache[cache_key] = await _deployment_records_for_platform(
                platform_id=plat_id,
                platform_name=plat_name,
                platform_serial=plat_serial,
                client=client,
            )
        dep_rows, _more = cache[cache_key]
        for dep in dep_rows:
            if not isinstance(dep, dict):
                continue
            dep_id = _record_id(dep)
            overlap = intersect_intervals(
                attach_iv,
                windows_to_intervals([relationship_window(dep)], as_of),
            )
            if not overlap:
                continue
            if dep_id is not None:
                if dep_id in seen_dep:
                    continue
                seen_dep.add(dep_id)
            ov_start, ov_end = overlap[0]
            _dep_start, dep_end = relationship_window(dep)
            still_open = (
                parse_window_time(attach_end) is None
                and parse_window_time(dep_end) is None
            )
            wrappers.append(
                {
                    "deployment": dep,
                    "start_time": _fmt_interval_bound(ov_start),
                    "end_time": None if still_open else _fmt_interval_bound(ov_end),
                }
            )
    return wrappers


def _skips_current_attachment_filter(entity: str, relation: str) -> bool:
    """True for relations that are not attachment lists (FK or platform mission list)."""
    if relation == "platform":
        return True
    return entity == "platform" and relation == "deployments"


async def get_entity_analytics(
    entity: str,
    resource_id: int,
    client: Optional[httpx.AsyncClient] = None,
    as_of: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Live days-at-sea / days-attached totals from Tracker relationship windows."""
    walk_token = _ST_WALK_CACHE.set({})
    try:
        return await _get_entity_analytics_body(
            entity, resource_id, client=client, as_of=as_of
        )
    finally:
        _ST_WALK_CACHE.reset(walk_token)


async def _get_entity_analytics_body(
    entity: str,
    resource_id: int,
    client: Optional[httpx.AsyncClient] = None,
    as_of: Optional[datetime] = None,
) -> Dict[str, Any]:
    spec = get_spec(entity)
    record = await get_entity_record(entity, resource_id, client=client)
    rec_id = _record_id(record) or resource_id
    as_of = as_of or datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    else:
        as_of = as_of.astimezone(timezone.utc)
    truncated = False
    metrics: List[Dict[str, str]] = []
    extra_notes: List[str] = []

    try:
        if entity == "deployment":
            windows = [relationship_window(record)]
            sea = windows_to_intervals(windows, as_of)
            metrics = [
                metric("days_deployed", "Days deployed", format_days(total_days(sea))),
                metric(
                    "currently_deployed",
                    "Currently deployed",
                    "yes" if is_current_at(windows, as_of) else "no",
                ),
            ]
        elif entity == "platform":
            windows, more = await _deployment_windows_for_platform(
                platform_id=rec_id,
                platform_name=_platform_name(record),
                platform_serial=_serial_of(record),
                client=client,
            )
            truncated = more
            sea = windows_to_intervals(windows, as_of)
            current_sea = windows_to_intervals(open_windows(windows, as_of), as_of)
            metrics = [
                metric("days_at_sea", "Days at sea", format_days(total_days(sea))),
                metric(
                    "days_on_current_deployment",
                    "Days on current deployment",
                    format_days(total_days(current_sea)),
                ),
                metric("deployment_count", "Deployments counted", str(len(windows))),
                metric(
                    "currently_at_sea",
                    "Currently at sea",
                    "yes" if is_current_at(windows, as_of) else "no",
                ),
            ]
        elif entity == "data_logger":
            identifier = _identifier(record, "identifier")
            if not identifier:
                extra_notes.append(
                    "No identifier on this record, so platform attachment history cannot be queried."
                )
            else:
                rows, more = await _pinned_relationship_history(
                    "data_logger_on_platform",
                    {"depth": 1, "data_logger_identifier": identifier},
                    parent_id=rec_id,
                    parent_entity="data_logger",
                    parent_serial=_serial_of(record),
                    client=client,
                )
                truncated = more
                sea, current_sea, sea_more = await _sea_intervals_for_attachment_rows(
                    rows, as_of, client=client
                )
                truncated = truncated or sea_more
                metrics = _attachment_service_metrics(
                    _windows_from_rows(rows), sea, current_sea, as_of
                )
        elif entity == "instrument":
            rows, more, notes = await _instrument_attachment_rows(
                record, rec_id, client=client
            )
            extra_notes.extend(notes)
            truncated = more
            if not notes:
                if not rows:
                    extra_notes.append(
                        "No platform or data-logger attachment history for this instrument instance."
                    )
                sea, current_sea, sea_more = await _sea_intervals_for_attachment_rows(
                    rows, as_of, client=client
                )
                truncated = truncated or sea_more
                metrics = _attachment_service_metrics(
                    _windows_from_rows(rows), sea, current_sea, as_of
                )
        elif entity == "sensor":
            soi_rows, soi_more = await _sensor_on_instrument_rows(
                record, rec_id, client=client
            )
            truncated = truncated or soi_more
            sea: List[Tuple[datetime, datetime]] = []
            current_sea: List[Tuple[datetime, datetime]] = []
            attached_windows: List[Tuple[Any, Any]] = []
            if soi_rows:
                attached_windows = _windows_from_rows(soi_rows)
                inst_cache: Dict[int, Tuple[List[Dict[str, Any]], bool]] = {}
                inst_sea_cache: Dict[
                    int,
                    Tuple[
                        List[Tuple[datetime, datetime]],
                        List[Tuple[datetime, datetime]],
                        bool,
                    ],
                ] = {}
                for soi in soi_rows:
                    sensor_one = windows_to_intervals(
                        [relationship_window(soi)], as_of
                    )
                    if not sensor_one:
                        continue
                    inst = soi.get("instrument")
                    inst_record = inst if isinstance(inst, dict) else None
                    inst_id = _record_id(inst_record) if inst_record else _as_int(inst)
                    if inst_id is None:
                        continue
                    if inst_id not in inst_cache:
                        if inst_record is None or _identifier(inst_record, "identifier") is None:
                            fetched = await _nested_or_fetched_record(
                                inst_id, "instrument", client=client
                            )
                            inst_record = fetched if isinstance(fetched, dict) else inst_record
                        if not isinstance(inst_record, dict):
                            inst_cache[inst_id] = ([], False)
                        else:
                            inst_rows, inst_more, _inst_notes = (
                                await _instrument_attachment_rows(
                                    inst_record, inst_id, client=client
                                )
                            )
                            inst_cache[inst_id] = (inst_rows, inst_more)
                    inst_rows, inst_more = inst_cache[inst_id]
                    truncated = truncated or inst_more
                    if inst_id not in inst_sea_cache:
                        inst_sea_cache[inst_id] = await _sea_intervals_for_attachment_rows(
                            inst_rows, as_of, client=client
                        )
                    inst_sea, inst_current, sea_more = inst_sea_cache[inst_id]
                    truncated = truncated or sea_more
                    sea.extend(intersect_intervals(sensor_one, inst_sea))
                    current_sea.extend(intersect_intervals(sensor_one, inst_current))
            if not attached_windows:
                parent = await _sensor_parent_instrument(record, client=client)
                if parent is None:
                    extra_notes.append(
                        "No current_instrument on this sensor and "
                        "sensor_on_instrument history was empty."
                    )
                else:
                    parent_id = _record_id(parent) or 0
                    extra_notes.append(
                        "Using the current parent instrument's attachment windows "
                        "(sensor_on_instrument history was empty)."
                    )
                    inst_rows, inst_more, inst_notes = await _instrument_attachment_rows(
                        parent, parent_id, client=client
                    )
                    extra_notes.extend(inst_notes)
                    truncated = truncated or inst_more
                    attached_windows = _windows_from_rows(inst_rows)
                    sea, current_sea, sea_more = await _sea_intervals_for_attachment_rows(
                        inst_rows, as_of, client=client
                    )
                    truncated = truncated or sea_more
            if attached_windows:
                metrics = _attachment_service_metrics(
                    attached_windows, sea, current_sea, as_of
                )
        elif entity == "component":
            rows, more = await _component_attachment_rows(
                record, rec_id, client=client
            )
            truncated = more
            if not rows:
                extra_notes.append(
                    "No component_on_platform history for this instance."
                )
            sea, current_sea, sea_more = await _sea_intervals_for_attachment_rows(
                rows, as_of, client=client
            )
            truncated = truncated or sea_more
            metrics = _attachment_service_metrics(
                _windows_from_rows(rows), sea, current_sea, as_of
            )
        else:
            extra_notes.append(
                f"No deployment/attachment history endpoint wired for {spec.label.lower()} yet."
            )
    except SensorTrackerQueryError as exc:
        extra_notes.append(exc.message)

    return build_analytics_payload(
        as_of=as_of,
        metrics=metrics,
        notes=extra_notes,
        truncated=truncated,
    )


def _dedupe_sensor_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    unique: List[Dict[str, Any]] = []
    seen: set[int] = set()
    extras: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rec_id = _record_id(row)
        if rec_id is None:
            extras.append(row)
            continue
        if rec_id in seen:
            continue
        seen.add(rec_id)
        unique.append(row)
    unique.extend(extras)
    return unique


async def _sensors_by_exact_identifier(
    query: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> List[Dict[str, Any]]:
    """Tracker ``identifier=`` is exact; ignore huge unfiltered pages."""
    found: List[Dict[str, Any]] = []
    for identifier in identifier_lookup_candidates(query):
        data = await st_get_json("sensor", {"identifier": identifier}, client=client)
        rows, count, _has_next, _has_prev = normalize_list_payload(
            data, page=1, page_size=MAX_PAGE_SIZE
        )
        needle = identifier.casefold()
        matching = [
            row
            for row in rows
            if (_fmt_cell(row.get("identifier")) or "").casefold() == needle
        ]
        if not matching:
            continue
        if count is not None and count > IDENTIFIER_LOOKUP_MAX_COUNT:
            continue
        found.extend(matching)
    return _dedupe_sensor_rows(found)


async def _attached_sensors_matching(
    query: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[List[Dict[str, Any]], Optional[int], bool]:
    """Local-match nested sensors on ``sensor_on_instrument`` (hundreds, not 235k)."""
    rows, tracker_count, more_upstream = await _walk_tracker_pages(
        "sensor_on_instrument",
        {"depth": 1},
        min_rows=SENSOR_ATTACH_SCAN_CAP,
        max_rows=SENSOR_ATTACH_SCAN_CAP,
        client=client,
    )
    matched: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        sensor = row.get("sensor") if isinstance(row.get("sensor"), dict) else None
        if sensor is None:
            continue
        if row_matches_search("sensor", sensor, query):
            matched.append(sensor)
    unique = _dedupe_sensor_rows(matched)
    return unique, tracker_count, more_upstream


def _tracker_filter_looks_honored(
    count: Optional[int], ignored_count: Optional[int]
) -> bool:
    """True when Tracker ``count`` is a real filter hit, not the unfiltered catalog.

    Prod ``search=`` on ``/api/deployment/`` returns the same ~923 ``count`` as a
    bare list. ``platform_name=`` is honored (9 rows, or 0 for a title string).
    """
    if count is None or count <= 0:
        return False
    if ignored_count is None:
        return True
    return count != ignored_count


async def _deployments_matching_fallback(
    query: str,
    *,
    ignored_count: Optional[int],
    client: Optional[httpx.AsyncClient] = None,
) -> List[Dict[str, Any]]:
    """Find deployments when Tracker ignores ``search=`` / ``title=``.

    ``platform_name=`` is honored (list rows often store ``platform`` as an int
    FK, so a local haystack match on the hull name would miss). A zero-count
    ``platform_name=`` is a real miss — then walk the modest catalog and match
    title/number locally (unnumbered / dateless rows included).
    """
    q = (query or "").strip()
    if not q:
        return []
    plat_rows, plat_count, plat_more = await _walk_tracker_pages(
        "deployment",
        {"platform_name": q},
        min_rows=DEPLOYMENT_SCAN_CAP,
        max_rows=DEPLOYMENT_SCAN_CAP,
        client=client,
    )
    if _tracker_filter_looks_honored(plat_count, ignored_count):
        return plat_rows

    scan_rows = plat_rows
    reuse_ignored_walk = (
        plat_count is not None
        and ignored_count is not None
        and plat_count == ignored_count
        and not plat_more
        and len(plat_rows) >= plat_count
    )
    if plat_count == 0 or not reuse_ignored_walk:
        scan_rows, _count, _more = await _walk_tracker_pages(
            "deployment",
            {},
            min_rows=DEPLOYMENT_SCAN_CAP,
            max_rows=DEPLOYMENT_SCAN_CAP,
            client=client,
        )
    return [row for row in scan_rows if row_matches_search("deployment", row, q)]


async def list_entities(
    entity: str,
    *,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    extra_filters: Optional[Dict[str, Any]] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    spec = get_spec(entity)
    page = clamp_page(page)
    page_size = clamp_page_size(page_size)
    query = (q or "").strip()
    needed = page * page_size

    if query:
        pk = looks_like_pk(query)
        if pk is not None:
            try:
                record = await get_entity_record(entity, pk, client=client)
                return {
                    "entity": entity,
                    "count": 1,
                    "page": 1,
                    "page_size": page_size,
                    "has_next": False,
                    "has_prev": False,
                    "results": [summarize_row(entity, record)],
                }
            except SensorTrackerQueryError as exc:
                if exc.status_code != 404:
                    raise

    path = await resolve_entity_path(spec, client=client)

    base_params: Dict[str, Any] = {}
    if extra_filters:
        base_params.update({k: v for k, v in extra_filters.items() if v not in (None, "")})
    params = build_search_params(spec, query)
    if extra_filters:
        params.update({k: v for k, v in extra_filters.items() if v not in (None, "")})

    scanning = bool(query)
    rows, tracker_count, more_upstream = await _walk_tracker_pages(
        path,
        params,
        min_rows=RELATIONSHIP_FETCH_CAP if scanning else needed,
        max_rows=RELATIONSHIP_FETCH_CAP,
        client=client,
    )
    if query:
        matched = [row for row in rows if row_matches_search(entity, row, query)]
        narrowed = set(params) - set(base_params)
        skip_unfiltered_scan = (
            entity in ("sensor", "deployment")
            and more_upstream
            and tracker_count is not None
            and tracker_count > RELATIONSHIP_FETCH_CAP
        )
        if not matched and narrowed and not skip_unfiltered_scan:
            rows, tracker_count, more_upstream = await _walk_tracker_pages(
                path,
                base_params,
                min_rows=RELATIONSHIP_FETCH_CAP,
                max_rows=RELATIONSHIP_FETCH_CAP,
                client=client,
            )
            matched = [row for row in rows if row_matches_search(entity, row, query)]
        if not matched and entity == "deployment":
            matched = await _deployments_matching_fallback(
                query, ignored_count=tracker_count, client=client
            )
        if not matched and entity == "sensor":
            ident_rows = await _sensors_by_exact_identifier(query, client=client)
            matched = [
                row for row in ident_rows if row_matches_search(entity, row, query)
            ]
            if not matched:
                attached, _soi_count, _soi_more = await _attached_sensors_matching(
                    query, client=client
                )
                matched = attached
        matched.sort(key=lambda row: _search_sort_key(entity, row, query))
        rows = matched
        tracker_count = len(matched)
        more_upstream = False

    start = (page - 1) * page_size
    sliced = rows[start : start + page_size]
    if tracker_count is not None:
        total = tracker_count
    else:
        total = len(rows)
        if more_upstream:
            total = max(total, start + page_size + 1)
    has_next = start + page_size < total
    has_prev = page > 1 and start > 0
    return {
        "entity": entity,
        "count": total,
        "page": page,
        "page_size": page_size,
        "has_next": has_next,
        "has_prev": has_prev,
        "results": [summarize_row(entity, row) for row in sliced],
    }


def _platform_name(record: Dict[str, Any]) -> Optional[str]:
    """Return a Tracker platform *name*, never a numeric FK stringified as one."""
    for key in ("name", "platform_name"):
        text = _fmt_cell(record.get(key))
        if text:
            return text
    platform = record.get("platform")
    if isinstance(platform, dict):
        return _fmt_cell(platform.get("name") or platform.get("platform_name"))
    return None


def _platform_fk_id(record: Dict[str, Any]) -> Optional[int]:
    platform = record.get("platform")
    if isinstance(platform, dict):
        return _record_id(platform)
    return _as_int(platform)


def _identifier(record: Dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        text = _fmt_cell(record.get(key))
        if text:
            return text
    return None


def _serial_of(record: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(record, dict):
        return None
    return _fmt_cell(
        record.get("serial")
        or record.get("serial_number")
        or record.get("serial_no")
    )


_PARENT_NESTED_KEYS: Dict[str, Tuple[str, ...]] = {
    "platform": ("platform",),
    "deployment": ("deployment",),
    "data_logger": ("data_logger", "logger"),
    "instrument": ("instrument",),
    "sensor": ("sensor",),
    "component": ("component",),
}


def _nested_parent(row: Dict[str, Any], *keys: str) -> Optional[Dict[str, Any]]:
    for key in keys:
        value = row.get(key)
        if isinstance(value, dict):
            return value
    return None


def _related_item_title(entity: str, row: Dict[str, Any]) -> str:
    """Type label plus serial or #id so shared identifiers are not shown alone."""
    title = _title_for(entity, row)
    identifier = _fmt_cell(row.get("identifier"))
    serial = _serial_of(row)
    rec_id = _record_id(row)
    if serial and serial.casefold() != title.casefold():
        return f"{title} · {serial}"
    if identifier and title.casefold() == identifier.casefold() and rec_id is not None:
        return f"{title} · #{rec_id}"
    return title


def _first_present(row: Dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def relationship_window(row: Dict[str, Any]) -> Tuple[Any, Any]:
    """Attachment start/end on the relationship row (not the nested entity)."""
    start = _first_present(row, ("start_time", "attached_time", "start"))
    end = _first_present(row, ("end_time", "end", "end_date", "removed_time"))
    return start, end


def unwrap_related_row(relation: str, row: Dict[str, Any]) -> Dict[str, Any]:
    target = RELATION_TARGET.get(relation, relation)
    nested = None
    for key in _NESTED_KEYS.get(target, (target,)):
        value = row.get(key)
        if isinstance(value, dict):
            nested = value
            break
    payload = nested if nested is not None else row
    rec_id = _record_id(payload)
    if rec_id is None:
        rec_id = _as_int(payload) if not isinstance(payload, dict) else None
    title_source = payload if isinstance(payload, dict) else row
    start, end = relationship_window(row)
    return {
        "entity": target,
        "id": rec_id,
        "title": (
            _related_item_title(target, title_source)
            if isinstance(title_source, dict)
            else str(title_source)
        ),
        "start_time": _fmt_cell(start),
        "end_time": _fmt_cell(end),
        "cells": summarize_cells(target, title_source) if isinstance(title_source, dict) else {},
    }


def _nested_record_id(row: Dict[str, Any], *keys: str) -> Optional[int]:
    for key in keys:
        value = row.get(key)
        if isinstance(value, dict):
            rec_id = _record_id(value)
            if rec_id is not None:
                return rec_id
        rec_id = _as_int(value)
        if rec_id is not None:
            return rec_id
    return None


def pin_relationship_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    parent_id: int,
    parent_entity: str,
    parent_serial: Optional[str] = None,
    require_match: bool = True,
) -> List[Dict[str, Any]]:
    """Keep relationship rows that belong to one parent instance.

    Tracker list filters (``data_logger_identifier``, ``instrument_identifier``)
    are type-level. Shared labels such as ``flight computer`` / ``CTD`` must
    never be treated as instance keys. Membership is nested parent **id**, or
    nested **serial** when id is absent.

    When ``require_match`` is true (identifier queries), unproven rows are
    dropped. When false (``platform_name`` queries, which are already
    instance-scoped), rows with no nested parent are kept; mismatched ids
    are still dropped.
    """
    keys = _PARENT_NESTED_KEYS.get(parent_entity, (parent_entity,))
    expected_serial = (parent_serial or "").strip() or None
    matched: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        nested_id = _nested_record_id(row, *keys)
        if nested_id is not None:
            if nested_id == parent_id:
                matched.append(row)
            continue
        nested = _nested_parent(row, *keys)
        serial = _serial_of(nested)
        if expected_serial and serial and serial == expected_serial:
            matched.append(row)
            continue
        if not require_match and nested is None:
            matched.append(row)
    return matched


def _attachment_time_key(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    text = str(value).strip().replace("T", " ")
    return text or None


def is_currently_attached(row: Dict[str, Any], as_of: Optional[str] = None) -> bool:
    """True when the relationship has no end date, or the end is after ``as_of``."""
    if not isinstance(row, dict):
        return False
    start, end = relationship_window(row)
    as_of_key = _attachment_time_key(as_of)
    start_key = _attachment_time_key(start)
    end_key = _attachment_time_key(end)
    if as_of_key and start_key and start_key > as_of_key:
        return False
    if not end_key:
        return True
    if not as_of_key:
        return False
    return end_key > as_of_key


def sort_related_attachment_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Open-ended attachments first, then newest start within each group."""
    ordered = [row for row in rows if isinstance(row, dict)]

    def start_key(row: Dict[str, Any]) -> str:
        start, _end = relationship_window(row)
        return _attachment_time_key(start) or ""

    def is_ended(row: Dict[str, Any]) -> int:
        _start, end = relationship_window(row)
        return 1 if _attachment_time_key(end) else 0

    ordered.sort(key=start_key, reverse=True)
    ordered.sort(key=is_ended)
    return ordered


def _page_related(
    rows: Sequence[Dict[str, Any]],
    relation: str,
    *,
    page: int,
    page_size: int,
) -> Tuple[List[Dict[str, Any]], int, bool, bool]:
    items = [unwrap_related_row(relation, row) for row in rows if isinstance(row, dict)]
    total = len(items)
    start = (page - 1) * page_size
    sliced = list(items[start : start + page_size])
    return sliced, total, start + page_size < total, page > 1 and start > 0


async def _walk_tracker_pages(
    path: str,
    params: Optional[Dict[str, Any]],
    *,
    min_rows: int,
    max_rows: int,
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[List[Dict[str, Any]], Optional[int], bool]:
    """Follow Tracker ``next`` until ``min_rows`` (capped at ``max_rows``).

    First request does not send ``page`` / ``limit`` / ``offset`` (Tracker 403s
    those keys). Later pages use Tracker's own ``next`` URL as-is.
    Returns ``(rows, tracker_count, more_upstream)``.
    """
    cache = _ST_WALK_CACHE.get()

    def _cache_key(query: Optional[Dict[str, Any]]) -> Tuple[Any, ...]:
        clean = sanitize_tracker_params(query, path=path)
        return (path, tuple(sorted((str(k), str(v)) for k, v in clean.items())))

    key_before = _cache_key(params)
    if cache is not None and key_before in cache:
        return cache[key_before]

    data = await st_get_json(path, params, client=client)
    rows: List[Dict[str, Any]] = []
    seen_next: set[str] = set()
    tracker_count: Optional[int] = None
    target = min(max(min_rows, 0), max_rows)
    more_upstream = False

    while True:
        page_rows, count, has_next, _has_prev = normalize_list_payload(
            data, page=1, page_size=max_rows
        )
        if count is not None:
            tracker_count = count
        rows.extend(page_rows)
        next_url = data.get("next") if isinstance(data, dict) else None
        if len(rows) >= max_rows:
            more_upstream = bool(has_next or next_url)
            break
        if len(rows) >= target:
            more_upstream = bool(has_next or next_url)
            break
        if not has_next or not next_url:
            more_upstream = False
            break
        next_key = str(next_url)
        if next_key in seen_next:
            more_upstream = False
            break
        seen_next.add(next_key)
        data = await st_get_json(path, client=client, absolute_url=next_key)

    result = (rows[:max_rows], tracker_count, more_upstream)
    if cache is not None:
        cache[key_before] = result
        cache[_cache_key(params)] = result
    return result


async def _list_relationship(
    path: str,
    params: Dict[str, Any],
    client: Optional[httpx.AsyncClient] = None,
) -> List[Dict[str, Any]]:
    rows, _count, _more = await _walk_tracker_pages(
        path,
        params,
        min_rows=RELATIONSHIP_FETCH_CAP,
        max_rows=RELATIONSHIP_FETCH_CAP,
        client=client,
    )
    return rows


async def _resolve_platform_scope(
    entity: str,
    record: Dict[str, Any],
    resource_id: int,
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """Return (platform_id, platform_name, platform_serial) for relationship pins."""
    if entity == "platform":
        return (
            _record_id(record) or resource_id,
            _platform_name(record),
            _serial_of(record),
        )
    plat_id = _platform_fk_id(record)
    name = _platform_name(record)
    serial: Optional[str] = None
    nested = record.get("platform") if isinstance(record.get("platform"), dict) else None
    if nested:
        serial = _serial_of(nested)
        name = name or _platform_name(nested)
        plat_id = plat_id or _record_id(nested)
    if plat_id is not None and (not name or not serial):
        try:
            platform = await get_entity_record("platform", plat_id, client=client)
            name = name or _platform_name(platform)
            serial = serial or _serial_of(platform)
            plat_id = _record_id(platform) or plat_id
        except SensorTrackerQueryError:
            pass
    return plat_id, name, serial


async def _platform_related_rows(
    path: str,
    *,
    platform_id: Optional[int],
    platform_name: Optional[str],
    platform_serial: Optional[str],
    rel_params: Dict[str, Any],
    client: Optional[httpx.AsyncClient] = None,
) -> List[Dict[str, Any]]:
    if not platform_name or platform_id is None:
        return []
    params = dict(rel_params)
    params["platform_name"] = platform_name
    fetched = await _list_relationship(path, params, client=client)
    return pin_relationship_rows(
        fetched,
        parent_id=platform_id,
        parent_entity="platform",
        parent_serial=platform_serial,
        require_match=False,
    )


async def _sensors_for_instruments(
    inst_rows: Sequence[Dict[str, Any]],
    *,
    attached: Optional[str],
    client: Optional[httpx.AsyncClient] = None,
) -> List[Dict[str, Any]]:
    """Load sensors via sensor_on_instrument, pinned to each instrument id."""
    sensor_params: Dict[str, Any] = {"depth": 1}
    if attached:
        sensor_params["attached_time"] = attached
    cache: Dict[str, List[Dict[str, Any]]] = {}
    seen_ids: set[int] = set()
    rows: List[Dict[str, Any]] = []
    for inst_row in inst_rows:
        inst = (
            inst_row.get("instrument")
            if isinstance(inst_row.get("instrument"), dict)
            else inst_row
        )
        if not isinstance(inst, dict):
            continue
        inst_id = _record_id(inst)
        if inst_id is None:
            continue
        identifier = _identifier(inst, "identifier")
        if not identifier:
            continue
        if identifier not in cache:
            query = dict(sensor_params)
            query["instrument_identifier"] = identifier
            cache[identifier] = await _list_relationship(
                "sensor_on_instrument", query, client=client
            )
        pinned = pin_relationship_rows(
            cache[identifier],
            parent_id=inst_id,
            parent_entity="instrument",
            parent_serial=_serial_of(inst),
        )
        for row in pinned:
            sensor = row.get("sensor") if isinstance(row.get("sensor"), dict) else row
            sid = _record_id(sensor) if isinstance(sensor, dict) else None
            if sid is not None:
                if sid in seen_ids:
                    continue
                seen_ids.add(sid)
            rows.append(row)
            if len(rows) >= RELATIONSHIP_FETCH_CAP:
                return rows
    return rows


async def list_related(
    entity: str,
    resource_id: int,
    relation: str,
    *,
    as_of: Optional[str] = None,
    current: bool = True,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    spec = get_spec(entity)
    if relation not in spec.relations:
        raise SensorTrackerQueryError(
            f"Unknown relation {relation!r} for {entity}",
            status_code=400,
        )
    page = clamp_page(page)
    page_size = clamp_page_size(page_size)
    record = await get_entity_record(entity, resource_id, client=client)
    attached = format_attached_time_for_api(as_of) if as_of else None
    if not attached and entity == "deployment" and not current:
        attached = format_attached_time_for_api(record.get("start_time"))
    skip_current = _skips_current_attachment_filter(entity, relation)
    if current and not attached and not skip_current:
        attached = format_attached_time_for_api(datetime.now(timezone.utc))

    rel_params: Dict[str, Any] = {"depth": 1}
    if attached:
        rel_params["attached_time"] = attached

    rows: List[Dict[str, Any]] = []
    target = RELATION_TARGET.get(relation, relation)
    plat_id: Optional[int] = None
    plat_name: Optional[str] = None
    plat_serial: Optional[str] = None
    if entity in ("platform", "deployment"):
        plat_id, plat_name, plat_serial = await _resolve_platform_scope(
            entity, record, resource_id, client=client
        )

    if entity == "platform" and relation == "deployments":
        if not plat_name:
            raise SensorTrackerQueryError(
                "Platform has no name to query deployments", status_code=502
            )
        raw_rows, _, _ = await _walk_tracker_pages(
            "deployment",
            {"platform_name": plat_name},
            min_rows=RELATIONSHIP_FETCH_CAP,
            max_rows=RELATIONSHIP_FETCH_CAP,
            client=client,
        )
        if plat_id is not None:
            raw_rows = pin_relationship_rows(
                raw_rows,
                parent_id=plat_id,
                parent_entity="platform",
                parent_serial=plat_serial,
                require_match=False,
            )
        results, count, has_next, has_prev = _page_related(
            raw_rows, relation, page=page, page_size=page_size
        )
        return {
            "entity": entity,
            "id": resource_id,
            "relation": relation,
            "target_entity": target,
            "count": count,
            "page": page,
            "page_size": page_size,
            "has_next": has_next,
            "has_prev": has_prev,
            "results": results,
        }

    if entity == "platform" and relation == "loggers":
        rows = await _platform_related_rows(
            "data_logger_on_platform",
            platform_id=plat_id,
            platform_name=plat_name,
            platform_serial=plat_serial,
            rel_params=rel_params,
            client=client,
        )

    elif entity == "platform" and relation == "instruments":
        rows = await _platform_related_rows(
            "instrument_on_platform",
            platform_id=plat_id,
            platform_name=plat_name,
            platform_serial=plat_serial,
            rel_params=rel_params,
            client=client,
        )

    elif entity == "platform" and relation == "components":
        try:
            rows = await _platform_related_rows(
                "component_on_platform",
                platform_id=plat_id,
                platform_name=plat_name,
                platform_serial=plat_serial,
                rel_params=rel_params,
                client=client,
            )
        except SensorTrackerQueryError as exc:
            if exc.status_code != 404:
                raise
            rows = []

    elif entity == "deployment" and relation == "platform":
        platform_raw = record.get("platform")
        platform_id = (
            _as_int(platform_raw)
            if not isinstance(platform_raw, dict)
            else _record_id(platform_raw)
        )
        if isinstance(platform_raw, dict):
            rows = [platform_raw]
        elif platform_id is not None:
            try:
                rows = [await get_entity_record("platform", platform_id, client=client)]
            except SensorTrackerQueryError:
                rows = []

    elif entity == "deployment" and relation in ("loggers", "instruments", "sensors", "components"):
        if relation == "loggers":
            rows = await _platform_related_rows(
                "data_logger_on_platform",
                platform_id=plat_id,
                platform_name=plat_name,
                platform_serial=plat_serial,
                rel_params=rel_params,
                client=client,
            )
        elif relation == "instruments":
            rows = await _platform_related_rows(
                "instrument_on_platform",
                platform_id=plat_id,
                platform_name=plat_name,
                platform_serial=plat_serial,
                rel_params=rel_params,
                client=client,
            )
        elif relation == "components":
            try:
                rows = await _platform_related_rows(
                    "component_on_platform",
                    platform_id=plat_id,
                    platform_name=plat_name,
                    platform_serial=plat_serial,
                    rel_params=rel_params,
                    client=client,
                )
            except SensorTrackerQueryError as exc:
                if exc.status_code != 404:
                    raise
                rows = []
        else:
            inst_rows = await _platform_related_rows(
                "instrument_on_platform",
                platform_id=plat_id,
                platform_name=plat_name,
                platform_serial=plat_serial,
                rel_params=rel_params,
                client=client,
            )
            rows = await _sensors_for_instruments(
                inst_rows, attached=attached, client=client
            )

    elif entity == "data_logger" and relation == "instruments":
        logger_id = _record_id(record) or resource_id
        identifier = _identifier(record, "identifier", "data_logger_identifier")
        if identifier:
            rel_params["data_logger_identifier"] = identifier
            fetched = await _list_relationship(
                "instrument_on_data_logger", rel_params, client=client
            )
            rows = pin_relationship_rows(
                fetched,
                parent_id=logger_id,
                parent_entity="data_logger",
                parent_serial=_serial_of(record),
            )

    elif entity == "instrument" and relation == "sensors":
        identifier = _identifier(record, "identifier")
        instrument_id = _record_id(record) or resource_id
        if identifier:
            rel_params["instrument_identifier"] = identifier
            fetched = await _list_relationship(
                "sensor_on_instrument", rel_params, client=client
            )
            rows = pin_relationship_rows(
                fetched,
                parent_id=instrument_id,
                parent_entity="instrument",
                parent_serial=_serial_of(record),
            )

    elif entity == "sensor" and relation == "instruments":
        rec_id = _record_id(record) or resource_id
        rows, _more = await _sensor_on_instrument_rows(
            record, rec_id, rel_params=rel_params, client=client
        )
        if not rows:
            parent = await _sensor_parent_instrument(record, client=client)
            if isinstance(parent, dict):
                rows = [
                    {
                        "instrument": parent,
                        "sensor": {
                            "id": rec_id,
                            "identifier": _identifier(record, "identifier"),
                            "serial": _serial_of(record),
                        },
                    }
                ]

    elif entity == "component" and relation == "platforms":
        rec_id = _record_id(record) or resource_id
        rows, _more = await _component_attachment_rows(
            record, rec_id, rel_params=rel_params, client=client
        )

    elif entity == "component" and relation == "deployments":
        rec_id = _record_id(record) or resource_id
        attach_rows, _more = await _component_attachment_rows(
            record, rec_id, rel_params=rel_params, client=client
        )
        as_of_dt = datetime.now(timezone.utc)
        if as_of:
            parsed = parse_window_time(as_of)
            if parsed is not None:
                as_of_dt = parsed
        rows = await _overlapping_deployment_rows(
            attach_rows, as_of_dt, client=client
        )

    else:
        raise SensorTrackerQueryError(
            f"Relation {relation!r} is not implemented for {entity}",
            status_code=400,
        )

    if current and not skip_current:
        rows = [
            row for row in rows
            if is_currently_attached(row, as_of=as_of)
        ]
        rows = sort_related_attachment_rows(rows)

    results, count, has_next, has_prev = _page_related(
        rows, relation, page=page, page_size=page_size
    )
    return {
        "entity": entity,
        "id": resource_id,
        "relation": relation,
        "target_entity": target,
        "count": count,
        "page": page,
        "page_size": page_size,
        "has_next": has_next,
        "has_prev": has_prev,
        "results": results,
    }


def lookup_buddy_deployment(
    session: SQLModelSession,
    st_deployment_id: int,
) -> Optional[Dict[str, Any]]:
    """Local overlay: whether this Tracker deployment was synced into Buddy."""
    row = session.exec(
        select(SensorTrackerDeployment).where(
            SensorTrackerDeployment.sensor_tracker_deployment_id == st_deployment_id
        )
    ).first()
    if row is None:
        return None
    return {
        "mission_id": row.mission_id,
        "last_synced_at": row.last_synced_at,
        "sync_status": row.sync_status,
    }
