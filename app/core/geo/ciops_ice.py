"""MSC GeoMet CIOPS-East sea-ice concentration WMS proxy.

Upstream: GeoMet-Weather WMS layer CIOPS-East_2km_SeaIceAreaFraction (hourly
48 h forecast). Browser requests go through FastAPI for auth + allowlist.
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from ...config import settings

logger = logging.getLogger(__name__)

OPEN_DATA_URL = (
    "https://open.canada.ca/data/en/dataset/bfe44cce-a9c4-467f-9172-c8800b32e4ec"
)

DEFAULT_LAYER = "CIOPS-East_2km_SeaIceAreaFraction"
DEFAULT_STYLE = "SEA_ICECONC-CIS"
ALLOWED_STYLES: frozenset[str] = frozenset(
    {
        "SEA_ICECONC-CIS",
        "SEA_ICECONC-LINEAR",
        "SEA_ICECONC",
        "SeaIceAreaFraction_Dis",
    }
)

MAX_EXPORT_SIZE = 512
MIN_EXPORT_SIZE = 64
BBOX_ROUND_DECIMALS = 4

# In-memory GetCapabilities cache: (expires_monotonic, payload_dict)
_capabilities_cache: Optional[tuple[float, dict[str, Any]]] = None

_ISO_Z_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?Z$"
)


def get_geomet_url() -> str:
    url = getattr(settings, "ciops_geomet_url", None) or "https://geo.weather.gc.ca/geomet"
    return str(url).rstrip("?")


def get_layer_name() -> str:
    return str(getattr(settings, "ciops_ice_layer", None) or DEFAULT_LAYER)


def get_default_style() -> str:
    style = str(getattr(settings, "ciops_ice_default_style", None) or DEFAULT_STYLE)
    if style not in ALLOWED_STYLES:
        return DEFAULT_STYLE
    return style


def get_cache_dir() -> Path:
    path = Path(settings.ciops_ice_cache_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_cache_ttl_seconds() -> int:
    return int(getattr(settings, "ciops_ice_cache_ttl_seconds", 3600) or 3600)


def get_capabilities_ttl_seconds() -> int:
    return int(getattr(settings, "ciops_ice_capabilities_ttl_seconds", 600) or 600)


def get_http_timeout_seconds() -> float:
    return float(getattr(settings, "ciops_ice_http_timeout_seconds", 45.0) or 45.0)


def assert_allowed_style(style: str) -> str:
    if style not in ALLOWED_STYLES:
        raise ValueError(f"style not allowlisted: {style}")
    return style


def parse_iso8601_z(value: str) -> datetime:
    """Parse GeoMet ISO8601 UTC timestamps (…Z) to aware datetime."""
    text = (value or "").strip()
    match = _ISO_Z_RE.match(text)
    if not match:
        raise ValueError(f"invalid ISO8601 time: {value!r}")
    date_part = match.group(1)
    year_s, month_s, day_s = date_part.split("-")
    hour = int(match.group(2))
    minute = int(match.group(3))
    second = int(match.group(4) or 0)
    return datetime(
        int(year_s),
        int(month_s),
        int(day_s),
        hour,
        minute,
        second,
        tzinfo=timezone.utc,
    )


def format_iso8601_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def expand_time_dimension(dimension_text: str) -> list[str]:
    """Expand a WMS Dimension time value into hourly ISO8601 Z strings.

    Supports:
    - ``start/end/PT1H`` (and PT1H with optional leading P)
    - comma-separated discrete times
    """
    text = (dimension_text or "").strip()
    if not text:
        return []

    if "/" in text:
        parts = text.split("/")
        if len(parts) != 3:
            raise ValueError(f"unsupported time dimension interval: {text!r}")
        start = parse_iso8601_z(parts[0])
        end = parse_iso8601_z(parts[1])
        step_raw = parts[2].upper().replace(" ", "")
        if step_raw not in {"PT1H", "P1H"}:
            raise ValueError(f"unsupported time step (expected PT1H): {parts[2]!r}")
        if end < start:
            raise ValueError(f"time dimension end before start: {text!r}")
        times: list[str] = []
        cursor = start
        # Cap runaway axes (48 h forecast + a little headroom)
        for _ in range(200):
            times.append(format_iso8601_z(cursor))
            if cursor >= end:
                break
            cursor = cursor + timedelta(hours=1)
        return times

    times = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        times.append(format_iso8601_z(parse_iso8601_z(token)))
    return times


def pick_default_time(times: list[str], *, now: Optional[datetime] = None) -> str:
    """Last available hour ≤ now UTC; else first available."""
    if not times:
        raise ValueError("no forecast times available")
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)

    chosen = times[0]
    for iso in times:
        dt = parse_iso8601_z(iso)
        if dt <= now_utc:
            chosen = iso
        else:
            break
    return chosen


def wms13_bbox_4326(west: float, south: float, east: float, north: float) -> str:
    """WMS 1.3.0 EPSG:4326 axis order: south,west,north,east."""
    return f"{south},{west},{north},{east}"


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _find_dimension_text(root: ET.Element, name: str) -> Optional[str]:
    target = name.lower()
    for elem in root.iter():
        if _local_name(elem.tag) != "Dimension":
            continue
        dim_name = (elem.attrib.get("name") or "").lower()
        if dim_name != target:
            continue
        text = (elem.text or "").strip()
        if text:
            return text
        # Some servers put the extent in an attribute
        extent = (elem.attrib.get("default") or "").strip()
        return extent or None
    return None


def _find_layer_bbox(root: ET.Element) -> Optional[dict[str, float]]:
    """Return geographic bbox for the named ice layer if present."""
    layer_name = get_layer_name()
    for layer in root.iter():
        if _local_name(layer.tag) != "Layer":
            continue
        name_el = None
        for child in list(layer):
            if _local_name(child.tag) == "Name" and (child.text or "").strip() == layer_name:
                name_el = child
                break
        if name_el is None:
            continue
        for child in list(layer):
            if _local_name(child.tag) != "EX_GeographicBoundingBox":
                continue
            west = south = east = north = None
            for box_child in list(child):
                ln = _local_name(box_child.tag)
                val = (box_child.text or "").strip()
                if not val:
                    continue
                try:
                    num = float(val)
                except ValueError:
                    continue
                if ln == "westBoundLongitude":
                    west = num
                elif ln == "eastBoundLongitude":
                    east = num
                elif ln == "southBoundLatitude":
                    south = num
                elif ln == "northBoundLatitude":
                    north = num
            if None not in (west, south, east, north):
                return {
                    "west": float(west),
                    "south": float(south),
                    "east": float(east),
                    "north": float(north),
                }
    return None


def parse_capabilities_xml(xml_text: str) -> dict[str, Any]:
    """Parse layer-scoped GetCapabilities into times, reference_time, domain."""
    root = ET.fromstring(xml_text)
    time_dim = _find_dimension_text(root, "time")
    if not time_dim:
        raise ValueError("GetCapabilities missing time Dimension")
    times = expand_time_dimension(time_dim)
    if not times:
        raise ValueError("GetCapabilities time Dimension expanded to empty list")

    ref_dim = _find_dimension_text(root, "reference_time")
    reference_times: list[str] = []
    if ref_dim:
        if "/" in ref_dim:
            # Rare for reference_time; treat as discrete start if interval
            try:
                reference_times = expand_time_dimension(ref_dim)
            except ValueError:
                reference_times = [format_iso8601_z(parse_iso8601_z(ref_dim.split("/")[0]))]
        else:
            for token in ref_dim.split(","):
                token = token.strip()
                if token:
                    reference_times.append(format_iso8601_z(parse_iso8601_z(token)))

    domain = _find_layer_bbox(root) or {
        "west": -77.015,
        "south": 34.87,
        "east": -37.025,
        "north": 54.47,
    }

    return {
        "times": times,
        "reference_times": reference_times,
        "reference_time": reference_times[-1] if reference_times else None,
        "domain": domain,
        "time_dimension_raw": time_dim,
    }


def _parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    parts = [p.strip() for p in bbox.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must be west,south,east,north")
    west, south, east, north = (float(p) for p in parts)
    if not (west < east and south < north):
        raise ValueError("bbox requires west<east and south<north")
    if abs(east - west) > 80 or abs(north - south) > 80:
        raise ValueError("bbox span too large")
    return west, south, east, north


def _parse_size(size: str) -> tuple[int, int]:
    parts = [p.strip() for p in size.split(",")]
    if len(parts) != 2:
        raise ValueError("size must be width,height")
    width, height = int(parts[0]), int(parts[1])
    if width < MIN_EXPORT_SIZE or height < MIN_EXPORT_SIZE:
        raise ValueError(f"size must be at least {MIN_EXPORT_SIZE}")
    if width > MAX_EXPORT_SIZE or height > MAX_EXPORT_SIZE:
        raise ValueError(f"size must be at most {MAX_EXPORT_SIZE}")
    return width, height


def _rounded_bbox_key(west: float, south: float, east: float, north: float) -> str:
    nd = BBOX_ROUND_DECIMALS
    return f"{west:.{nd}f}_{south:.{nd}f}_{east:.{nd}f}_{north:.{nd}f}"


def _cache_path(kind: str, digest_src: str) -> Path:
    digest = hashlib.sha256(digest_src.encode("utf-8")).hexdigest()[:40]
    return get_cache_dir() / f"{kind}_{digest}.png"


def _read_fresh_cache(path: Path) -> Optional[bytes]:
    if not path.is_file():
        return None
    age = time.time() - path.stat().st_mtime
    if age > get_cache_ttl_seconds():
        return None
    try:
        return path.read_bytes()
    except OSError as exc:
        logger.warning("CIOPS ice cache read failed (%s): %s", path, exc)
        return None


def _write_cache(path: Path, body: bytes) -> None:
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)
    except OSError as exc:
        logger.warning("CIOPS ice cache write failed (%s): %s", path, exc)


def build_getmap_url(
    *,
    west: float,
    south: float,
    east: float,
    north: float,
    width: int,
    height: int,
    time_iso: str,
    style: str,
) -> str:
    layer = get_layer_name()
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetMap",
        "LAYERS": layer,
        "STYLES": style,
        "CRS": "EPSG:4326",
        "BBOX": wms13_bbox_4326(west, south, east, north),
        "WIDTH": str(width),
        "HEIGHT": str(height),
        "FORMAT": "image/png",
        "TRANSPARENT": "TRUE",
        "TIME": time_iso,
    }
    base = get_geomet_url()
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}{urlencode(params)}"


def build_legend_url(*, style: str) -> str:
    layer = get_layer_name()
    params = {
        "version": "1.3.0",
        "service": "WMS",
        "request": "GetLegendGraphic",
        "sld_version": "1.1.0",
        "layer": layer,
        "format": "image/png",
        "STYLE": style,
    }
    base = get_geomet_url()
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}{urlencode(params)}"


def clear_capabilities_cache() -> None:
    global _capabilities_cache
    _capabilities_cache = None


async def fetch_capabilities(*, force_refresh: bool = False) -> dict[str, Any]:
    """Return parsed capabilities, using an in-memory TTL cache."""
    global _capabilities_cache
    now_mono = time.monotonic()
    if not force_refresh and _capabilities_cache is not None:
        expires, payload = _capabilities_cache
        if now_mono < expires:
            return payload

    layer = get_layer_name()
    params = {
        "service": "WMS",
        "version": "1.3.0",
        "request": "GetCapabilities",
        "layer": layer,
    }
    base = get_geomet_url()
    sep = "&" if "?" in base else "?"
    url = f"{base}{sep}{urlencode(params)}"
    timeout = get_http_timeout_seconds()
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": "GliderBuddyCiopsIce/1.0"},
        follow_redirects=True,
    ) as client:
        response = await client.get(url)
        if response.status_code >= 400:
            snippet = (response.text or "")[:200]
            raise RuntimeError(
                f"Upstream GetCapabilities HTTP {response.status_code}: {snippet}"
            )
        xml_text = response.text

    parsed = parse_capabilities_xml(xml_text)
    _capabilities_cache = (now_mono + get_capabilities_ttl_seconds(), parsed)
    return parsed


async def build_meta() -> dict[str, Any]:
    caps = await fetch_capabilities()
    times: list[str] = list(caps["times"])
    default_time = pick_default_time(times)
    style = get_default_style()
    return {
        "title": "CIOPS-East sea ice",
        "description": (
            "MSC Coastal Ice-Ocean Prediction System (CIOPS-East) sea ice area "
            "fraction — 48-hour hourly model forecast at ~2 km. Forecast "
            "concentration, not CIS observed ice charts. Domain covers the "
            "Gulf of St. Lawrence, Maritimes, and NW Atlantic (not Arctic or Pacific)."
        ),
        "attribution": (
            "Government of Canada; Environment and Climate Change Canada; "
            "Meteorological Service of Canada"
        ),
        "open_data_url": OPEN_DATA_URL,
        "geomet_url": get_geomet_url(),
        "layer": get_layer_name(),
        "style": style,
        "styles": sorted(ALLOWED_STYLES),
        "times": times,
        "default_time": default_time,
        "reference_time": caps.get("reference_time"),
        "reference_times": caps.get("reference_times") or [],
        "domain": caps.get("domain"),
        "opacity_default": 0.65,
        "note": (
            "Model concentration often near 0 in summer over much of the domain. "
            "East coast only."
        ),
    }


async def fetch_map_png(
    *,
    bbox: str,
    size: str = "256,256",
    time: str,
    style: Optional[str] = None,
) -> tuple[bytes, str]:
    """Return (png_bytes, cache_status) for a WMS GetMap tile."""
    style = assert_allowed_style(style or get_default_style())
    west, south, east, north = _parse_bbox(bbox)
    width, height = _parse_size(size)

    caps = await fetch_capabilities()
    allowed_times = set(caps["times"])
    time_iso = format_iso8601_z(parse_iso8601_z(time))
    if time_iso not in allowed_times:
        raise ValueError(f"time not in current forecast window: {time_iso}")

    bbox_key = _rounded_bbox_key(west, south, east, north)
    cache_file = _cache_path(
        "map",
        f"{get_layer_name()}|{style}|{time_iso}|{bbox_key}|{width}x{height}",
    )
    cached = _read_fresh_cache(cache_file)
    if cached is not None:
        return cached, "hit"

    url = build_getmap_url(
        west=west,
        south=south,
        east=east,
        north=north,
        width=width,
        height=height,
        time_iso=time_iso,
        style=style,
    )
    timeout = get_http_timeout_seconds()
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": "GliderBuddyCiopsIce/1.0"},
        follow_redirects=True,
    ) as client:
        response = await client.get(url)
        if response.status_code >= 400:
            snippet = (response.text or "")[:200]
            raise RuntimeError(
                f"Upstream GetMap HTTP {response.status_code}: {snippet}"
            )
        content_type = (response.headers.get("content-type") or "").lower()
        body = response.content
        if "png" not in content_type and not body.startswith(b"\x89PNG"):
            snippet = body[:200]
            raise RuntimeError(
                f"Upstream GetMap did not return PNG (content-type={content_type!r}): {snippet!r}"
            )

    _write_cache(cache_file, body)
    return body, "miss"


async def fetch_legend_png(*, style: Optional[str] = None) -> tuple[bytes, str]:
    """Return (png_bytes, cache_status) for GetLegendGraphic."""
    style = assert_allowed_style(style or get_default_style())
    cache_file = _cache_path("legend", f"{get_layer_name()}|{style}")
    cached = _read_fresh_cache(cache_file)
    if cached is not None:
        return cached, "hit"

    url = build_legend_url(style=style)
    timeout = get_http_timeout_seconds()
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": "GliderBuddyCiopsIce/1.0"},
        follow_redirects=True,
    ) as client:
        response = await client.get(url)
        if response.status_code >= 400:
            snippet = (response.text or "")[:200]
            raise RuntimeError(
                f"Upstream GetLegendGraphic HTTP {response.status_code}: {snippet}"
            )
        content_type = (response.headers.get("content-type") or "").lower()
        body = response.content
        if "png" not in content_type and not body.startswith(b"\x89PNG"):
            snippet = body[:200]
            raise RuntimeError(
                f"Upstream legend did not return PNG (content-type={content_type!r}): {snippet!r}"
            )

    _write_cache(cache_file, body)
    return body, "miss"
