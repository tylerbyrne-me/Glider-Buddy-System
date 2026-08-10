"""DFO NW Atlantic AIS vessel-density MapServer proxy (monthly rasters).

Upstream: egisp MapServer raster layers 7–18 (All vessel types, Jan–Dec 2025).
Browser requests go through FastAPI to avoid CORS and enforce auth + allowlist.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from ...config import settings

logger = logging.getLogger(__name__)

DEFAULT_MAPSERVER_URL = (
    "https://egisp.dfo-mpo.gc.ca/arcgis/rest/services/"
    "open_data_donnees_ouvertes/"
    "nw_atlantic_vessel_density_2025_ais_densite_des_navires_nw_atlantique_2025_sia/"
    "MapServer"
)

OPEN_DATA_URL = "https://open.canada.ca/data/en/dataset/eac8e835-e7c8-450d-96b0-ff42d416c815"

# Calendar month 1–12 → MapServer layer id (All vessel types, 2025).
MONTH_TO_LAYER_ID: dict[int, int] = {
    1: 7,
    2: 8,
    3: 9,
    4: 10,
    5: 11,
    6: 12,
    7: 13,
    8: 14,
    9: 15,
    10: 16,
    11: 17,
    12: 18,
}

ALLOWED_LAYER_IDS: frozenset[int] = frozenset(MONTH_TO_LAYER_ID.values())

MONTH_LABELS: dict[int, str] = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}

MAX_EXPORT_SIZE = 512
MIN_EXPORT_SIZE = 64
BBOX_ROUND_DECIMALS = 4


def get_mapserver_url() -> str:
    url = getattr(settings, "vessel_density_mapserver_url", None) or DEFAULT_MAPSERVER_URL
    return str(url).rstrip("/")


def get_cache_dir() -> Path:
    path = Path(settings.vessel_density_cache_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_cache_ttl_seconds() -> int:
    return int(getattr(settings, "vessel_density_cache_ttl_seconds", 3600) or 3600)


def get_http_timeout_seconds() -> float:
    return float(getattr(settings, "vessel_density_http_timeout_seconds", 45.0) or 45.0)


def default_month_utc() -> int:
    """Calendar month 1–12 for 'today' UTC (maps onto 2025 monthly rasters)."""
    return datetime.now(timezone.utc).month


def layer_id_for_month(month: int) -> int:
    if month not in MONTH_TO_LAYER_ID:
        raise ValueError(f"month must be 1–12, got {month}")
    return MONTH_TO_LAYER_ID[month]


def assert_allowed_layer_id(layer_id: int) -> int:
    if layer_id not in ALLOWED_LAYER_IDS:
        raise ValueError(f"layer_id not allowlisted: {layer_id}")
    return layer_id


def build_meta() -> dict[str, Any]:
    default_month = default_month_utc()
    months = [
        {
            "month": m,
            "label": MONTH_LABELS[m],
            "layer_id": MONTH_TO_LAYER_ID[m],
        }
        for m in range(1, 13)
    ]
    return {
        "year": 2025,
        "title": "AIS vessel density (2025)",
        "description": (
            "DFO Northwest Atlantic AIS vessel density — all vessel types, "
            "daily average by month (2025). Cartographic reference only."
        ),
        "attribution": (
            "Government of Canada; Fisheries and Oceans Canada; "
            "Marine Planning and Conservation"
        ),
        "open_data_url": OPEN_DATA_URL,
        "mapserver_url": get_mapserver_url(),
        "default_month": default_month,
        "default_layer_id": MONTH_TO_LAYER_ID[default_month],
        "months": months,
        "opacity_default": 0.55,
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
    return (
        f"{west:.{nd}f}_{south:.{nd}f}_{east:.{nd}f}_{north:.{nd}f}"
    )


def _cache_path(layer_id: int, bbox_key: str, width: int, height: int) -> Path:
    digest = hashlib.sha256(
        f"{layer_id}|{bbox_key}|{width}x{height}".encode("utf-8")
    ).hexdigest()[:40]
    return get_cache_dir() / f"export_{layer_id}_{digest}.png"


def _read_fresh_cache(path: Path) -> Optional[bytes]:
    if not path.is_file():
        return None
    age = time.time() - path.stat().st_mtime
    if age > get_cache_ttl_seconds():
        return None
    try:
        return path.read_bytes()
    except OSError as exc:
        logger.warning("Vessel density cache read failed (%s): %s", path, exc)
        return None


def _write_cache(path: Path, body: bytes) -> None:
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)
    except OSError as exc:
        logger.warning("Vessel density cache write failed (%s): %s", path, exc)


def build_export_url(
    *,
    layer_id: int,
    west: float,
    south: float,
    east: float,
    north: float,
    width: int,
    height: int,
) -> str:
    params = {
        "bbox": f"{west},{south},{east},{north}",
        "bboxSR": "4326",
        "imageSR": "3857",
        "size": f"{width},{height}",
        "dpi": "96",
        "format": "png32",
        "transparent": "true",
        "layers": f"show:{layer_id}",
        "f": "image",
    }
    return f"{get_mapserver_url()}/export?{urlencode(params)}"


async def fetch_export_png(
    *,
    layer_id: int,
    bbox: str,
    size: str = "256,256",
) -> tuple[bytes, str]:
    """Return (png_bytes, cache_status) where cache_status is 'hit' or 'miss'."""
    layer_id = assert_allowed_layer_id(int(layer_id))
    west, south, east, north = _parse_bbox(bbox)
    width, height = _parse_size(size)
    bbox_key = _rounded_bbox_key(west, south, east, north)
    cache_file = _cache_path(layer_id, bbox_key, width, height)
    cached = _read_fresh_cache(cache_file)
    if cached is not None:
        return cached, "hit"

    url = build_export_url(
        layer_id=layer_id,
        west=west,
        south=south,
        east=east,
        north=north,
        width=width,
        height=height,
    )
    timeout = get_http_timeout_seconds()
    async with httpx.AsyncClient(
        timeout=timeout,
        headers={"User-Agent": "GliderBuddyVesselDensity/1.0"},
        follow_redirects=True,
    ) as client:
        response = await client.get(url)
        if response.status_code >= 400:
            snippet = (response.text or "")[:200]
            raise RuntimeError(
                f"Upstream export HTTP {response.status_code}: {snippet}"
            )
        content_type = (response.headers.get("content-type") or "").lower()
        body = response.content
        if "png" not in content_type and not body.startswith(b"\x89PNG"):
            snippet = body[:200]
            raise RuntimeError(
                f"Upstream export did not return PNG (content-type={content_type!r}): {snippet!r}"
            )

    _write_cache(cache_file, body)
    return body, "miss"
