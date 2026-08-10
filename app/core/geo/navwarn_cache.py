"""CCG NAVWARN disk cache for home-page Leaflet overlays.

Scrapes HTML from ``nis.ccg-gcc.gc.ca`` (no public JSON search API):

- Active published warnings: search page message IDs + per-message ``var data`` geometries
- Area reference polygons: ``var areaFeatures`` + ``#messageZone`` option names/levels

Refresh is incremental (diff message IDs); a daily full re-validate catches edits.
"""

from __future__ import annotations

import asyncio
import hashlib
import html as html_lib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from ...config import settings
from ..infra.feature_toggles import is_feature_enabled
from ..utils import (
    promote_orphan_tmp_file,
    replace_path_with_retries,
    resolve_data_path,
    unique_sibling_tmp_path,
)

logger = logging.getLogger(__name__)

NAVWARN_BASE_URL = "https://nis.ccg-gcc.gc.ca"
NAVWARN_SEARCH_PATH = "/public/rest/messages/en/search"
NAVWARN_MESSAGE_PATH = "/public/rest/messages/en/message/{message_id}"
ROOT_CANADA_AREA_ID = 1
AREA_FEATURE_LEVEL_DEFAULT = "l2"

_HTTP_HEADERS = {
    "User-Agent": "WaveGliderBuddySystem/1.0 (navwarn-map-overlay; local cache)",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}

_MESSAGE_ID_RE = re.compile(
    r"/public/rest/messages/en/message/(\d+)",
    re.IGNORECASE,
)
_VAR_DATA_RE = re.compile(
    r"var\s+data\s*=\s*(\{.*?\});\s*(?:var\s+lang|\n)",
    re.DOTALL,
)
_AREA_FEATURES_RE = re.compile(
    r"var\s+areaFeatures\s*=\s*(\[[\s\S]*?\])\s*;",
    re.DOTALL,
)
_MESSAGE_ZONE_OPTION_RE = re.compile(
    r'<option\s+([^>]*?)value="(\d+)"([^>]*)>',
    re.IGNORECASE | re.DOTALL,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_JS_BARE_KEY_RE = re.compile(r"([{\[,]\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:")
_JS_SINGLE_QUOTE_RE = re.compile(r"'([^'\\]*(?:\\.[^'\\]*)*)'")
_JS_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
# Observed NIS search page cap (verify against returned count).
_OBSERVED_PAGE_CAP = 50

_stats: dict[str, Any] = {
    "cache_hits": 0,
    "cache_misses": 0,
    "upstream_fetches": 0,
    "upstream_blocked_by_rate_limit": 0,
    "detail_fetches": 0,
    "last_fetch_at": None,
    "last_fetch_ok": None,
    "last_error": None,
    "last_prefetch_at": None,
    "last_prefetch_summary": None,
    "last_cleanup_at": None,
    "last_cleanup_summary": None,
    "active_warning_count": 0,
    "area_count": 0,
}
_fetch_lock = asyncio.Lock()


def _cache_dir() -> Path:
    return resolve_data_path(settings.navwarn_cache_dir)


def _active_path() -> Path:
    return _cache_dir() / "active_warnings.geojson"


def _areas_path() -> Path:
    return _cache_dir() / "areas.geojson"


def _meta_path() -> Path:
    return _cache_dir() / "meta.json"


def _rate_limit_path() -> Path:
    return _cache_dir() / "upstream_rate_limit.json"


def _ensure_cache_dir() -> None:
    _cache_dir().mkdir(parents=True, exist_ok=True)


def _ttl_seconds() -> int:
    return max(60, int(getattr(settings, "navwarn_cache_ttl_seconds", 1800) or 1800))


def _areas_ttl_seconds() -> int:
    return max(60, int(getattr(settings, "navwarn_areas_ttl_seconds", 86400) or 86400))


def _min_interval_seconds() -> int:
    return max(
        30,
        int(getattr(settings, "navwarn_upstream_min_interval_seconds", 300) or 300),
    )


def _search_max_hits() -> int:
    return max(1, int(getattr(settings, "navwarn_search_max_hits", 500) or 500))


def _http_timeout() -> float:
    return max(5.0, float(getattr(settings, "navwarn_http_timeout_seconds", 45.0) or 45.0))


def _detail_concurrency() -> int:
    return max(1, int(getattr(settings, "navwarn_detail_concurrency", 5) or 5))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _parse_iso_utc(value: str) -> Optional[datetime]:
    try:
        normalized = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _age_seconds_from_iso(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    parsed = _parse_iso_utc(value)
    if parsed is None:
        return None
    return (_utc_now() - parsed).total_seconds()


def _file_mtime_age_seconds(path: Path) -> Optional[float]:
    try:
        if not path.is_file():
            return None
        return time.time() - path.stat().st_mtime
    except OSError:
        return None


def _charset_from_content_type(content_type: Optional[str]) -> Optional[str]:
    if not content_type:
        return None
    msg = Message()
    msg["content-type"] = content_type
    charset = msg.get_content_charset()
    return charset.lower() if charset else None


def decode_response_text(body: bytes, content_type: Optional[str] = None) -> str:
    """Decode HTML bytes using Content-Type charset, with windows-1252 fallback.

    NIS pages often declare UTF-8 in ``<meta>`` while serving Latin-1/Windows-1252
    bytes (French accents). Prefer the HTTP charset; if UTF-8 yields replacement
    characters, fall back to windows-1252.
    """
    preferred = _charset_from_content_type(content_type) or "utf-8"
    candidates: list[str] = []
    for encoding in (preferred, "utf-8", "windows-1252", "latin-1"):
        if encoding and encoding not in candidates:
            candidates.append(encoding)

    for encoding in candidates:
        try:
            text = body.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
        if encoding in {"utf-8", "utf8"} and "\ufffd" in text and len(body) > 0:
            # Likely wrong charset; try next candidate.
            continue
        return text

    return body.decode("utf-8", errors="replace")


def sanitize_description(raw: Any) -> str:
    """Strip HTML tags and collapse whitespace for popup-safe plain text."""
    if raw is None:
        return ""
    text = html_lib.unescape(str(raw))
    text = _HTML_TAG_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def parse_search_message_ids(html: str) -> list[int]:
    """Extract unique message IDs from search-result hrefs (order preserved)."""
    seen: set[int] = set()
    ids: list[int] = []
    for match in _MESSAGE_ID_RE.finditer(html or ""):
        message_id = int(match.group(1))
        if message_id in seen:
            continue
        seen.add(message_id)
        ids.append(message_id)
    return ids


def parse_message_features(html: str) -> list[dict[str, Any]]:
    """Parse ``var data = {...};`` features from a message detail page."""
    match = _VAR_DATA_RE.search(html or "")
    if not match:
        raise ValueError("message page missing var data = {...}")
    payload = json.loads(match.group(1))
    features = payload.get("features")
    if not isinstance(features, list):
        return []
    return [f for f in features if isinstance(f, dict)]


def normalize_js_object_literal(raw: str) -> str:
    """Convert a loose JS object/array literal into JSON text."""
    text = raw.strip()
    text = _JS_BARE_KEY_RE.sub(r'\1"\2":', text)

    def _quote_js_string(match: re.Match[str]) -> str:
        inner = match.group(1).replace(r"\'", "'").replace(r"\\", "\\")
        return json.dumps(inner)

    text = _JS_SINGLE_QUOTE_RE.sub(_quote_js_string, text)
    text = _JS_TRAILING_COMMA_RE.sub(r"\1", text)
    return text


def parse_area_features(html: str) -> list[dict[str, Any]]:
    """Parse ``var areaFeatures = [...]`` from the search page shell."""
    match = _AREA_FEATURES_RE.search(html or "")
    if not match:
        raise ValueError("search page missing var areaFeatures = [...]")
    normalized = normalize_js_object_literal(match.group(1))
    # raw_decode tolerates trailing whitespace; regex allows ``]\\s*;`` (CCG splits ] and ;).
    payload, _end = json.JSONDecoder().raw_decode(normalized)
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def parse_area_names(html: str) -> dict[int, dict[str, str]]:
    """Parse ``#messageZone`` options into areaId -> {name, level, series}."""
    # Prefer the messageZone select block when present.
    zone_start = (html or "").find('id="messageZone"')
    zone_html = html or ""
    if zone_start >= 0:
        zone_end = zone_html.find("</select>", zone_start)
        if zone_end > zone_start:
            zone_html = zone_html[zone_start:zone_end]

    result: dict[int, dict[str, str]] = {}
    for match in _MESSAGE_ZONE_OPTION_RE.finditer(zone_html):
        attrs = f"{match.group(1)} {match.group(3)}"
        area_id = int(match.group(2))
        text_match = re.search(r'data-text="([^"]*)"', attrs)
        series_match = re.search(r'data-series="([^"]*)"', attrs)
        class_match = re.search(r'class="([^"]*)"', attrs)
        name = html_lib.unescape(text_match.group(1)).strip() if text_match else ""
        series = html_lib.unescape(series_match.group(1)).strip() if series_match else ""
        level = AREA_FEATURE_LEVEL_DEFAULT
        if class_match:
            for token in class_match.group(1).split():
                if re.fullmatch(r"l[1-5]", token):
                    level = token
                    break
        display = name
        if series:
            display = f"{name} {series}".strip()
        result[area_id] = {"name": display or name or f"Area {area_id}", "level": level, "series": series}
    return result


def message_source_url(message_id: int) -> str:
    return f"{NAVWARN_BASE_URL}{NAVWARN_MESSAGE_PATH.format(message_id=message_id)}"


def _close_ring(coords: list[list[float]]) -> list[list[float]]:
    if len(coords) < 3:
        return coords
    if coords[0] != coords[-1]:
        return coords + [coords[0]]
    return coords


def navwarn_feature_to_geojson(feature: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Convert one NIS feature dict into a GeoJSON Feature."""
    geometry_type = str(feature.get("type") or "").upper()
    raw_coords = feature.get("coordinates")
    if not isinstance(raw_coords, list) or not raw_coords:
        return None

    try:
        message_id = int(feature.get("messageId"))
    except (TypeError, ValueError):
        return None

    coords: list[list[float]] = []
    for pair in raw_coords:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        try:
            coords.append([float(pair[0]), float(pair[1])])
        except (TypeError, ValueError):
            continue
    if not coords:
        return None

    if geometry_type == "POINT":
        geometry = {"type": "Point", "coordinates": coords[0]}
    elif geometry_type == "POLYLINE":
        if len(coords) < 2:
            return None
        geometry = {"type": "LineString", "coordinates": coords}
    elif geometry_type == "POLYGON":
        ring = _close_ring(coords)
        if len(ring) < 4:
            return None
        geometry = {"type": "Polygon", "coordinates": [ring]}
    else:
        logger.debug("Skipping unsupported NAVWARN geometry type %s", geometry_type)
        return None

    radius = feature.get("radius")
    try:
        radius_val = float(radius) if radius is not None else None
    except (TypeError, ValueError):
        radius_val = None

    properties = {
        "messageId": message_id,
        "seriesId": str(feature.get("seriesId") or ""),
        "title": sanitize_description(feature.get("title")),
        "description": sanitize_description(feature.get("description")),
        "date": str(feature.get("date") or ""),
        "charts": str(feature.get("charts") or ""),
        "status": str(feature.get("status") or ""),
        "source_url": message_source_url(message_id),
        "geometry_type": geometry_type,
        "radius": radius_val,
        "source": "ccg_navwarn_active",
    }
    return {
        "type": "Feature",
        "geometry": geometry,
        "properties": properties,
    }


def areas_to_geojson(
    area_features: list[dict[str, Any]],
    area_names: dict[int, dict[str, str]],
    *,
    exclude_root: bool = True,
) -> dict[str, Any]:
    """Build a FeatureCollection of NAVWARN area reference polygons."""
    features: list[dict[str, Any]] = []
    for item in area_features:
        try:
            area_id = int(item.get("areaId"))
        except (TypeError, ValueError):
            continue
        if exclude_root and area_id == ROOT_CANADA_AREA_ID:
            continue
        if str(item.get("type") or "").upper() != "POLYGON":
            continue
        raw_coords = item.get("coordinates")
        if not isinstance(raw_coords, list) or not raw_coords:
            continue
        ring: list[list[float]] = []
        for pair in raw_coords:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                continue
            try:
                ring.append([float(pair[0]), float(pair[1])])
            except (TypeError, ValueError):
                continue
        ring = _close_ring(ring)
        if len(ring) < 4:
            continue
        meta = area_names.get(area_id) or {}
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {
                    "areaId": area_id,
                    "name": meta.get("name") or f"Area {area_id}",
                    "level": meta.get("level") or AREA_FEATURE_LEVEL_DEFAULT,
                    "series": meta.get("series") or "",
                    "source": "ccg_navwarn_area",
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source": "ccg_navwarn_areas",
            "fetched_at": _utc_now_iso(),
            "feature_count": len(features),
            "attribution": "Canadian Coast Guard / NAVWARN (nis.ccg-gcc.gc.ca)",
        },
    }


def build_active_feature_collection(
    geo_features: list[dict[str, Any]],
    *,
    fetched_at: Optional[str] = None,
    message_ids: Optional[list[int]] = None,
    truncated: bool = False,
) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": geo_features,
        "metadata": {
            "source": "ccg_navwarn_active",
            "fetched_at": fetched_at or _utc_now_iso(),
            "feature_count": len(geo_features),
            "message_ids": message_ids or sorted(
                {
                    int(f["properties"]["messageId"])
                    for f in geo_features
                    if isinstance(f.get("properties"), dict)
                    and f["properties"].get("messageId") is not None
                }
            ),
            "truncated": truncated,
            "attribution": "Canadian Coast Guard / NAVWARN (nis.ccg-gcc.gc.ca)",
        },
    }


def _atomic_write_json(path: Path, payload: Any) -> None:
    _ensure_cache_dir()
    path = Path(path)
    tmp_path = unique_sibling_tmp_path(path)
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
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


def _read_json_file(path: Path) -> Optional[Any]:
    if not path.is_file():
        promote_orphan_tmp_file(path)
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return None


def _read_meta() -> dict[str, Any]:
    payload = _read_json_file(_meta_path())
    return payload if isinstance(payload, dict) else {}


def _write_meta(payload: dict[str, Any]) -> None:
    _atomic_write_json(_meta_path(), payload)


def _read_rate_limit() -> dict[str, Any]:
    payload = _read_json_file(_rate_limit_path())
    return payload if isinstance(payload, dict) else {}


def _write_rate_limit(payload: dict[str, Any]) -> None:
    _atomic_write_json(_rate_limit_path(), payload)


def _claim_upstream_slot() -> bool:
    """Persistent min-interval gate between upstream refresh cycles."""
    state = _read_rate_limit()
    last_at = state.get("last_contact_at")
    age = _age_seconds_from_iso(last_at) if last_at else None
    if age is not None and age < _min_interval_seconds():
        return False
    _write_rate_limit({"last_contact_at": _utc_now_iso()})
    return True


def _collection_is_truncated(collection: Optional[dict[str, Any]]) -> bool:
    if not isinstance(collection, dict):
        return False
    meta = collection.get("metadata") if isinstance(collection.get("metadata"), dict) else {}
    return bool(meta.get("truncated"))


def _is_active_fresh(collection: Optional[dict[str, Any]]) -> bool:
    if not isinstance(collection, dict):
        return False
    meta = collection.get("metadata") if isinstance(collection.get("metadata"), dict) else {}
    # Incomplete crawls must not satisfy freshness — force a re-page.
    if meta.get("truncated"):
        return False
    age = _age_seconds_from_iso(meta.get("fetched_at"))
    if age is None:
        age = _file_mtime_age_seconds(_active_path())
    return age is not None and age <= _ttl_seconds()


def _is_areas_fresh(collection: Optional[dict[str, Any]]) -> bool:
    if not isinstance(collection, dict):
        return False
    meta = collection.get("metadata") if isinstance(collection.get("metadata"), dict) else {}
    age = _age_seconds_from_iso(meta.get("fetched_at"))
    if age is None:
        age = _file_mtime_age_seconds(_areas_path())
    return age is not None and age <= _areas_ttl_seconds()


def _read_active_collection() -> Optional[dict[str, Any]]:
    payload = _read_json_file(_active_path())
    if isinstance(payload, dict) and payload.get("type") == "FeatureCollection":
        return payload
    return None


def _read_areas_collection() -> Optional[dict[str, Any]]:
    payload = _read_json_file(_areas_path())
    if isinstance(payload, dict) and payload.get("type") == "FeatureCollection":
        return payload
    return None


def _feature_message_id(feature: dict[str, Any]) -> Optional[int]:
    props = feature.get("properties")
    if not isinstance(props, dict):
        return None
    try:
        return int(props.get("messageId"))
    except (TypeError, ValueError):
        return None


def _index_features_by_message_id(
    collection: Optional[dict[str, Any]],
) -> dict[int, list[dict[str, Any]]]:
    indexed: dict[int, list[dict[str, Any]]] = {}
    if not collection:
        return indexed
    for feature in collection.get("features") or []:
        if not isinstance(feature, dict):
            continue
        message_id = _feature_message_id(feature)
        if message_id is None:
            continue
        indexed.setdefault(message_id, []).append(feature)
    return indexed


def _search_max_pages() -> int:
    return max(1, int(getattr(settings, "navwarn_search_max_pages", 100) or 100))


def _search_url(*, max_hits: Optional[int] = None, page: int = 1) -> str:
    """Build NIS search URL. Pagination uses ``page`` (1-based); ``startIndex`` is ignored upstream."""
    params = {
        "status": "PUBLISHED",
        "maxHits": int(max_hits if max_hits is not None else _OBSERVED_PAGE_CAP),
        "sortBy": "DATE",
        "page": max(1, int(page)),
    }
    return f"{NAVWARN_BASE_URL}{NAVWARN_SEARCH_PATH}?{urlencode(params)}"


async def _fetch_html(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(url, headers=_HTTP_HEADERS, follow_redirects=True)
    response.raise_for_status()
    return decode_response_text(response.content, response.headers.get("content-type"))


async def _fetch_all_published_message_ids(
    client: httpx.AsyncClient,
    *,
    max_pages: Optional[int] = None,
) -> tuple[list[int], bool]:
    """Fetch published message IDs by walking ``page=1..N`` until empty / no new IDs.

    NIS returns at most ~50 unique messages per page regardless of ``maxHits``.
    ``startIndex`` does not advance results; ``page`` does.

    When ``max_pages`` is set (e.g. 1 for incremental), stop after that many pages
    without treating a full last page as catalog truncation.
    """
    page_size = _OBSERVED_PAGE_CAP
    max_total = _search_max_hits()
    page_cap = max(1, int(max_pages)) if max_pages is not None else _search_max_pages()
    full_crawl = max_pages is None
    all_ids: list[int] = []
    seen: set[int] = set()
    truncated = False
    page = 1

    while page <= page_cap and len(all_ids) < max_total:
        url = _search_url(max_hits=page_size, page=page)
        html = await _fetch_html(client, url)
        page_ids = parse_search_message_ids(html)
        new_on_page = 0
        for message_id in page_ids:
            if message_id in seen:
                continue
            if len(all_ids) >= max_total:
                truncated = True
                break
            seen.add(message_id)
            all_ids.append(message_id)
            new_on_page += 1

        logger.info(
            "NAVWARN search page=%s unique_on_page=%s new=%s total=%s max_pages=%s",
            page,
            len(page_ids),
            new_on_page,
            len(all_ids),
            page_cap,
        )

        if truncated:
            break

        if not page_ids or new_on_page == 0:
            break

        if len(page_ids) < page_size:
            break

        page += 1
    else:
        # Exhausted page_cap without an empty/short page.
        if full_crawl:
            truncated = True

    if truncated:
        logger.warning(
            "NAVWARN published ID list may be truncated (count=%s, max_hits=%s, max_pages=%s, last_page=%s)",
            len(all_ids),
            max_total,
            page_cap,
            page,
        )
    else:
        logger.info(
            "NAVWARN published ID list complete (count=%s, pages_scanned=%s, full_crawl=%s)",
            len(all_ids),
            page,
            full_crawl,
        )
    return all_ids, truncated


async def _fetch_message_geo_features(
    client: httpx.AsyncClient,
    message_id: int,
    semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    async with semaphore:
        url = message_source_url(message_id)
        html = await _fetch_html(client, url)
        _stats["detail_fetches"] += 1
        raw_features = parse_message_features(html)
        geo_features: list[dict[str, Any]] = []
        for raw in raw_features:
            converted = navwarn_feature_to_geojson(raw)
            if converted is not None:
                geo_features.append(converted)
        return geo_features


REFRESH_MODE_INCREMENTAL = "incremental"
REFRESH_MODE_RECONCILE = "reconcile"


def _normalize_refresh_mode(
    *,
    mode: Optional[str] = None,
    force_full: bool = False,
) -> str:
    """Resolve refresh mode; ``force_full=True`` aliases reconcile for callers/tests."""
    if force_full:
        return REFRESH_MODE_RECONCILE
    normalized = str(mode or REFRESH_MODE_RECONCILE).strip().lower()
    if normalized == REFRESH_MODE_INCREMENTAL:
        return REFRESH_MODE_INCREMENTAL
    return REFRESH_MODE_RECONCILE


async def _refresh_locked(
    *,
    mode: str = REFRESH_MODE_RECONCILE,
    force_full: bool = False,
) -> dict[str, Any]:
    """Refresh active warnings (and areas if stale). Caller must hold ``_fetch_lock``.

    Modes:
    - ``incremental``: search page 1 only; fetch details for new IDs; never prune.
    - ``reconcile``: full page walk; fetch details for new IDs only; drop IDs absent
      from the published catalog. ``force_full=True`` aliases this mode.
    """
    refresh_mode = _normalize_refresh_mode(mode=mode, force_full=force_full)
    cached_active = _read_active_collection()
    cached_areas = _read_areas_collection()
    previous_by_id = _index_features_by_message_id(cached_active)
    cache_empty = len(previous_by_id) == 0
    was_truncated = _collection_is_truncated(cached_active)

    effective_mode = refresh_mode
    escalate_reason = ""
    if refresh_mode == REFRESH_MODE_INCREMENTAL and (cache_empty or was_truncated):
        effective_mode = REFRESH_MODE_RECONCILE
        escalate_reason = "empty_cache" if cache_empty else "truncated_cache"

    need_active = force_full or not _is_active_fresh(cached_active)
    need_areas = not _is_areas_fresh(cached_areas)

    if not need_active and not need_areas:
        _stats["cache_hits"] += 1
        return {
            "active": cached_active,
            "areas": cached_areas,
            "cache_hit": True,
            "refreshed_active": False,
            "refreshed_areas": False,
            "refresh_mode": effective_mode,
            "requested_mode": refresh_mode,
        }

    # Incomplete crawls / forced reconcile bypass the min-interval gate.
    bypass_rate_gate = was_truncated or cache_empty or force_full or bool(escalate_reason)
    if bypass_rate_gate:
        _write_rate_limit({"last_contact_at": _utc_now_iso()})
        claimed = True
    else:
        claimed = _claim_upstream_slot()

    if not claimed:
        _stats["upstream_blocked_by_rate_limit"] += 1
        _stats["cache_hits"] += 1
        if cached_active is None and need_active:
            raise RuntimeError(
                "NAVWARN cache empty and upstream is rate-limited for this interval"
            )
        return {
            "active": cached_active,
            "areas": cached_areas,
            "cache_hit": True,
            "stale": True,
            "rate_limit_reason": "upstream_ttl_gate",
            "refreshed_active": False,
            "refreshed_areas": False,
            "refresh_mode": effective_mode,
            "requested_mode": refresh_mode,
        }

    _stats["cache_misses"] += 1
    _stats["upstream_fetches"] += 1
    timeout = httpx.Timeout(_http_timeout())
    semaphore = asyncio.Semaphore(_detail_concurrency())

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            search_html = await _fetch_html(client, _search_url())
            message_ids: list[int] = []
            truncated = False
            if need_active:
                page_limit = (
                    1 if effective_mode == REFRESH_MODE_INCREMENTAL else None
                )
                message_ids, truncated = await _fetch_all_published_message_ids(
                    client, max_pages=page_limit
                )
                if not message_ids:
                    message_ids = parse_search_message_ids(search_html)
                    if len(message_ids) >= _OBSERVED_PAGE_CAP:
                        truncated = effective_mode == REFRESH_MODE_RECONCILE
                        logger.warning(
                            "NAVWARN search returned exactly %s IDs (possible page cap)",
                            len(message_ids),
                        )
                # Page-1-only never marks the disk cache as truncated.
                if effective_mode == REFRESH_MODE_INCREMENTAL:
                    truncated = False

            if need_areas:
                area_features = parse_area_features(search_html)
                area_names = parse_area_names(search_html)
                areas_collection = areas_to_geojson(area_features, area_names)
                _atomic_write_json(_areas_path(), areas_collection)
                cached_areas = areas_collection
                _stats["area_count"] = len(areas_collection.get("features") or [])

            active_collection = cached_active
            if need_active:
                published_set = set(message_ids)
                fetch_ids = [mid for mid in message_ids if mid not in previous_by_id]

                new_features: list[dict[str, Any]] = []
                failed_ids: list[int] = []
                if fetch_ids:
                    tasks = [
                        _fetch_message_geo_features(client, mid, semaphore)
                        for mid in fetch_ids
                    ]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for mid, result in zip(fetch_ids, results):
                        if isinstance(result, Exception):
                            logger.warning(
                                "NAVWARN detail fetch failed for %s: %s", mid, result
                            )
                            failed_ids.append(mid)
                            continue
                        new_features.extend(result)

                feature_map = dict(previous_by_id)
                fetched_by_id = _index_features_by_message_id(
                    {"type": "FeatureCollection", "features": new_features}
                )
                feature_map.update(fetched_by_id)

                if effective_mode == REFRESH_MODE_RECONCILE:
                    order_ids = list(message_ids)
                    removed_ids = sorted(set(previous_by_id.keys()) - published_set)
                else:
                    prev_meta_ids = (
                        ((cached_active or {}).get("metadata") or {}).get("message_ids")
                        if isinstance(cached_active, dict)
                        else None
                    )
                    if isinstance(prev_meta_ids, list) and prev_meta_ids:
                        order_ids = []
                        for raw_id in prev_meta_ids:
                            try:
                                order_ids.append(int(raw_id))
                            except (TypeError, ValueError):
                                continue
                    else:
                        order_ids = sorted(previous_by_id.keys())
                    seen_order = set(order_ids)
                    for mid in message_ids:
                        if mid not in seen_order:
                            order_ids.append(mid)
                            seen_order.add(mid)
                    removed_ids = []

                ordered: list[dict[str, Any]] = []
                for mid in order_ids:
                    ordered.extend(feature_map.get(mid) or [])

                active_collection = build_active_feature_collection(
                    ordered,
                    message_ids=order_ids,
                    truncated=truncated,
                )
                active_collection["metadata"]["refresh_mode"] = effective_mode
                active_collection["metadata"]["requested_mode"] = refresh_mode
                if escalate_reason:
                    active_collection["metadata"]["escalated_from_incremental"] = True
                    active_collection["metadata"]["escalate_reason"] = escalate_reason
                if removed_ids:
                    active_collection["metadata"]["removed_ids"] = removed_ids
                if fetch_ids:
                    active_collection["metadata"]["added_ids"] = list(fetch_ids)
                if failed_ids:
                    active_collection["metadata"]["failed_detail_ids"] = failed_ids
                _atomic_write_json(_active_path(), active_collection)
                cached_active = active_collection
                _stats["active_warning_count"] = len(ordered)

        meta = _read_meta()
        meta.update(
            {
                "last_fetch_at": _utc_now_iso(),
                "last_fetch_ok": True,
                "last_error": None,
                "active_warning_count": len((cached_active or {}).get("features") or []),
                "area_count": len((cached_areas or {}).get("features") or []),
                "truncated": bool(
                    ((cached_active or {}).get("metadata") or {}).get("truncated")
                ),
                "refresh_mode": effective_mode,
                "requested_mode": refresh_mode,
                "escalated_from_incremental": bool(escalate_reason),
                "escalate_reason": escalate_reason or None,
                "force_full": bool(force_full),
            }
        )
        _write_meta(meta)
        _stats["last_fetch_at"] = meta["last_fetch_at"]
        _stats["last_fetch_ok"] = True
        _stats["last_error"] = None
        logger.info(
            "NAVWARN refresh complete (active=%s, areas=%s, mode=%s, requested=%s, "
            "truncated=%s, escalate=%s)",
            meta.get("active_warning_count"),
            meta.get("area_count"),
            effective_mode,
            refresh_mode,
            meta.get("truncated"),
            escalate_reason or "-",
        )
        return {
            "active": cached_active,
            "areas": cached_areas,
            "cache_hit": False,
            "refreshed_active": need_active,
            "refreshed_areas": need_areas,
            "refresh_mode": effective_mode,
            "requested_mode": refresh_mode,
            "force_full": bool(force_full),
            "escalated_from_incremental": bool(escalate_reason),
            "escalate_reason": escalate_reason or None,
        }
    except Exception as exc:
        _stats["last_fetch_ok"] = False
        _stats["last_error"] = str(exc)
        meta = _read_meta()
        meta.update(
            {
                "last_fetch_at": _utc_now_iso(),
                "last_fetch_ok": False,
                "last_error": str(exc),
            }
        )
        _write_meta(meta)
        logger.error("NAVWARN upstream refresh failed: %s", exc, exc_info=True)
        if cached_active is None and need_active:
            raise
        return {
            "active": cached_active,
            "areas": cached_areas,
            "cache_hit": True,
            "stale": True,
            "upstream_error": str(exc),
            "refreshed_active": False,
            "refreshed_areas": False,
            "refresh_mode": effective_mode,
            "requested_mode": refresh_mode,
        }


async def ensure_navwarn_cache(
    *,
    mode: Optional[str] = None,
    force_full: bool = False,
) -> dict[str, Any]:
    """Ensure disk cache is fresh enough; refresh under a single-flight lock.

    Default mode is reconcile (safe for on-demand API refresh when stale).
    Prefetch should pass ``mode='incremental'``. ``force_full=True`` aliases
    reconcile and bypasses the freshness short-circuit.
    """
    refresh_mode = _normalize_refresh_mode(mode=mode, force_full=force_full)
    cached_active = _read_active_collection()
    cached_areas = _read_areas_collection()
    if (
        not force_full
        and _is_active_fresh(cached_active)
        and _is_areas_fresh(cached_areas)
    ):
        _stats["cache_hits"] += 1
        _stats["active_warning_count"] = len((cached_active or {}).get("features") or [])
        _stats["area_count"] = len((cached_areas or {}).get("features") or [])
        return {
            "active": cached_active,
            "areas": cached_areas,
            "cache_hit": True,
            "refreshed_active": False,
            "refreshed_areas": False,
            "refresh_mode": refresh_mode,
            "requested_mode": refresh_mode,
        }

    async with _fetch_lock:
        return await _refresh_locked(mode=refresh_mode, force_full=force_full)


def _geojson_bytes(collection: dict[str, Any]) -> tuple[bytes, str]:
    body = json.dumps(collection, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()[:16]
    etag = f'"{digest}"'
    return body, etag


async def get_active_warnings_geojson() -> tuple[bytes, str, dict[str, Any]]:
    """Return ``(body_bytes, etag, collection)`` for active NAVWARNs."""
    result = await ensure_navwarn_cache()
    collection = result.get("active")
    if not isinstance(collection, dict):
        raise RuntimeError("NAVWARN active warnings cache is empty")
    body, etag = _geojson_bytes(collection)
    return body, etag, collection


async def get_areas_geojson() -> tuple[bytes, str, dict[str, Any]]:
    """Return ``(body_bytes, etag, collection)`` for area reference polygons."""
    result = await ensure_navwarn_cache()
    collection = result.get("areas")
    if not isinstance(collection, dict):
        raise RuntimeError("NAVWARN areas cache is empty")
    body, etag = _geojson_bytes(collection)
    return body, etag, collection


async def prefetch_navwarn_cache(*, force_full: bool = False) -> dict[str, Any]:
    """Leader job: incremental warm by default; ``force_full`` runs reconcile."""
    if not is_feature_enabled("navwarn_map_layer"):
        summary = {"skipped": True, "reason": "feature_disabled"}
        _stats["last_prefetch_at"] = _utc_now_iso()
        _stats["last_prefetch_summary"] = summary
        logger.info("NAVWARN prefetch skipped: navwarn_map_layer disabled")
        return summary

    if not bool(getattr(settings, "navwarn_prefetch_enabled", True)):
        summary = {"skipped": True, "reason": "prefetch_disabled"}
        _stats["last_prefetch_at"] = _utc_now_iso()
        _stats["last_prefetch_summary"] = summary
        logger.info("NAVWARN prefetch skipped: navwarn_prefetch_enabled=false")
        return summary

    refresh_mode = (
        REFRESH_MODE_RECONCILE if force_full else REFRESH_MODE_INCREMENTAL
    )
    result = await ensure_navwarn_cache(mode=refresh_mode, force_full=force_full)
    active = result.get("active") or {}
    areas = result.get("areas") or {}
    summary = {
        "skipped": False,
        "force_full": force_full,
        "refresh_mode": result.get("refresh_mode") or refresh_mode,
        "requested_mode": result.get("requested_mode") or refresh_mode,
        "escalated_from_incremental": result.get("escalated_from_incremental", False),
        "cache_hit": result.get("cache_hit"),
        "stale": result.get("stale", False),
        "refreshed_active": result.get("refreshed_active"),
        "refreshed_areas": result.get("refreshed_areas"),
        "active_warning_count": len(active.get("features") or []),
        "area_count": len(areas.get("features") or []),
        "truncated": bool((active.get("metadata") or {}).get("truncated")),
        "rate_limit_reason": result.get("rate_limit_reason"),
        "upstream_error": result.get("upstream_error"),
    }
    _stats["last_prefetch_at"] = _utc_now_iso()
    _stats["last_prefetch_summary"] = summary
    logger.info("NAVWARN prefetch finished: %s", summary)
    return summary


def purge_navwarn_cache(*, force_all: bool = False) -> dict[str, Any]:
    """Remove NAVWARN cache files. force_all deletes everything; else stranded/tmp."""
    _ensure_cache_dir()
    removed_files = 0
    freed_bytes = 0
    feature_on = is_feature_enabled("navwarn_map_layer")
    paths = [_active_path(), _areas_path(), _meta_path(), _rate_limit_path()]

    for path in paths:
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
            should_remove = force_all or not feature_on
            if should_remove:
                path.unlink(missing_ok=True)
                removed_files += 1
                freed_bytes += size
        except OSError as exc:
            logger.warning("Failed to purge %s: %s", path, exc)

    for tmp in _cache_dir().glob("*.tmp"):
        try:
            size = tmp.stat().st_size
            tmp.unlink(missing_ok=True)
            removed_files += 1
            freed_bytes += size
        except OSError:
            pass

    return {
        "removed_files": removed_files,
        "freed_bytes": freed_bytes,
        "force_all": force_all,
        "feature_enabled": feature_on,
    }


async def run_navwarn_cleanup() -> dict[str, Any]:
    """Always-on cleanup: reclaim stranded temps; daily reconcile when feature on."""
    summary: dict[str, Any] = {"purge": purge_navwarn_cache(force_all=False)}
    if is_feature_enabled("navwarn_map_layer"):
        try:
            # Bypass rate gate for daily catalog reconcile by clearing the gate file.
            rate_path = _rate_limit_path()
            if rate_path.is_file():
                try:
                    rate_path.unlink()
                except OSError:
                    pass
            # Reconcile: full page walk + prune; details only for newly seen IDs.
            summary["revalidate"] = await prefetch_navwarn_cache(force_full=True)
        except Exception as exc:
            summary["revalidate_error"] = str(exc)
            logger.error("NAVWARN daily re-validate failed: %s", exc, exc_info=True)
    _stats["last_cleanup_at"] = _utc_now_iso()
    _stats["last_cleanup_summary"] = summary
    logger.debug("NAVWARN cache cleanup complete: %s", summary)
    return summary


def get_cache_status() -> dict[str, Any]:
    """Return disk cache statistics for debugging / admin UI."""
    active = _read_active_collection()
    areas = _read_areas_collection()
    meta = _read_meta()
    rate = _read_rate_limit()
    active_age = None
    if isinstance(active, dict):
        active_age = _age_seconds_from_iso(
            ((active.get("metadata") or {}).get("fetched_at"))
        )
    areas_age = None
    if isinstance(areas, dict):
        areas_age = _age_seconds_from_iso(
            ((areas.get("metadata") or {}).get("fetched_at"))
        )
    last_contact = rate.get("last_contact_at")
    last_contact_age = _age_seconds_from_iso(last_contact) if last_contact else None
    upstream_allowed = (
        last_contact_age is None or last_contact_age >= _min_interval_seconds()
    )
    return {
        "feature_enabled": is_feature_enabled("navwarn_map_layer"),
        "cache_dir": str(_cache_dir()),
        "active_is_fresh": _is_active_fresh(active),
        "areas_is_fresh": _is_areas_fresh(areas),
        "active_age_seconds": active_age,
        "areas_age_seconds": areas_age,
        "active_warning_count": len((active or {}).get("features") or []),
        "area_count": len((areas or {}).get("features") or []),
        "truncated": bool(((active or {}).get("metadata") or {}).get("truncated")),
        "ttl_seconds": _ttl_seconds(),
        "areas_ttl_seconds": _areas_ttl_seconds(),
        "upstream_min_interval_seconds": _min_interval_seconds(),
        "upstream_allowed": upstream_allowed,
        "last_contact_at": last_contact,
        "meta": meta,
        "stats": dict(_stats),
        "files": {
            "active_warnings": _active_path().is_file(),
            "areas": _areas_path().is_file(),
            "meta": _meta_path().is_file(),
            "upstream_rate_limit": _rate_limit_path().is_file(),
        },
    }
