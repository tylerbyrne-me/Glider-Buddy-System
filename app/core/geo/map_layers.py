"""Static vector map layers (GeoJSON) served from config/map_layers/."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from ...config import settings

logger = logging.getLogger(__name__)

LAYER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class MapLayerStyle(BaseModel):
    color: str = "#3388ff"
    weight: float = 2
    opacity: float = 0.9
    fillColor: str = "#3388ff"
    fillOpacity: float = 0.15


class MapLayerEntry(BaseModel):
    id: str
    name: str
    description: str = ""
    platforms: list[str] = Field(default_factory=list)
    path: str
    style: MapLayerStyle = Field(default_factory=MapLayerStyle)
    bounds: Optional[list[float]] = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not LAYER_ID_PATTERN.fullmatch(value):
            raise ValueError(f"Invalid layer id: {value!r}")
        return value

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/").strip().lstrip("/")
        if not normalized or ".." in normalized.split("/"):
            raise ValueError(f"Unsafe layer path: {value!r}")
        if not normalized.startswith("published/"):
            raise ValueError(f"Layer path must be under published/: {value!r}")
        if not normalized.lower().endswith(".geojson"):
            raise ValueError(f"Layer path must end with .geojson: {value!r}")
        return normalized

    @field_validator("bounds")
    @classmethod
    def validate_bounds(cls, value: Optional[list[float]]) -> Optional[list[float]]:
        if value is None:
            return None
        if len(value) != 4:
            raise ValueError("bounds must be [west, south, east, north]")
        return [float(v) for v in value]


class MapLayerManifest(BaseModel):
    layers: list[MapLayerEntry] = Field(default_factory=list)


def get_map_layers_dir() -> Path:
    return Path(settings.map_layers_dir)


def _manifest_path() -> Path:
    return get_map_layers_dir() / "manifest.json"


def load_manifest() -> MapLayerManifest:
    """Load and validate config/map_layers/manifest.json."""
    path = _manifest_path()
    if not path.is_file():
        logger.warning("Map layers manifest missing: %s", path)
        return MapLayerManifest()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return MapLayerManifest.model_validate(raw)
    except Exception as exc:
        logger.error("Failed to load map layers manifest %s: %s", path, exc)
        raise


def get_layer_catalog(*, platform: Optional[str] = None) -> list[dict[str, Any]]:
    """
    Return catalog entries (no geometry).

    Empty ``platforms`` on a layer means available to all platforms.
    """
    manifest = load_manifest()
    platform_key = (platform or "").strip().lower() or None
    catalog: list[dict[str, Any]] = []
    for layer in manifest.layers:
        allowed = [p.strip().lower() for p in layer.platforms if p and str(p).strip()]
        if allowed and platform_key and platform_key not in allowed:
            continue
        catalog.append(
            {
                "id": layer.id,
                "name": layer.name,
                "description": layer.description,
                "platforms": list(layer.platforms),
                "style": layer.style.model_dump(),
                "bounds": layer.bounds,
            }
        )
    return catalog


def get_layer_entry(layer_id: str) -> MapLayerEntry:
    if not LAYER_ID_PATTERN.fullmatch(layer_id):
        raise KeyError(layer_id)
    for layer in load_manifest().layers:
        if layer.id == layer_id:
            return layer
    raise KeyError(layer_id)


def resolve_layer_file(layer: MapLayerEntry) -> Path:
    """Resolve a published GeoJSON path under map_layers_dir (no path traversal)."""
    root = get_map_layers_dir().resolve()
    candidate = (root / layer.path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Layer path escapes map_layers_dir: {layer.path}") from exc
    if not candidate.is_file():
        raise FileNotFoundError(f"Layer GeoJSON missing: {candidate}")
    return candidate


def read_layer_geojson(layer_id: str) -> tuple[bytes, str, float]:
    """
    Read published GeoJSON for ``layer_id``.

    Returns ``(body_bytes, etag, mtime)``.
    """
    layer = get_layer_entry(layer_id)
    path = resolve_layer_file(layer)
    body = path.read_bytes()
    mtime = path.stat().st_mtime
    digest = hashlib.sha256(body).hexdigest()[:16]
    etag = f'"{layer_id}-{digest}"'
    return body, etag, mtime
