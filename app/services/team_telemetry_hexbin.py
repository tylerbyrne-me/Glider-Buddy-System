"""Wave Glider telemetry hexbin coverage maps for Team (and CLI shim).

Moved from tests/oneoff_telemetry_hexbin.py. Cache/outputs live under data_store/.
Track sources are discovered from the mission catalog (WGMS realtime + past,
and ERDDAP) so active missions appear alongside historical coverage.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import httpx
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LogNorm

import cartopy.crs as ccrs
import cartopy.feature as cfeature
from cartopy.mpl.gridliner import LATITUDE_FORMATTER, LONGITUDE_FORMATTER

from app.config import settings
from app.core.data.loaders import load_report
from app.core.data.processors import preprocess_telemetry_df
from app.core.geo.bathymetry import fetch_etopo_bathymetry, nice_contour_levels
from app.core.models.enums import (
    CatalogMatchStatus,
    CatalogOperationalState,
    CatalogSourceKind,
)
from app.core.models.schemas import TelemetryHexbinResult
from app.core.plotting import (
    OVERLAY_STRIP_MIN_FRACTION,
    _add_report_regional_inset,
    _regional_inset_extent,
)

logger = logging.getLogger("team_telemetry_hexbin")

TELEMETRY_FILENAME = "Telemetry 6 Report by WGMS Datetime.csv"
DEFAULT_CENTER_LAT = 44.04
DEFAULT_CENTER_LON = -60.32
DEFAULT_SIZE_KM = 150.0
DEFAULT_GRIDSIZE = 60
DEFAULT_MAX_MISSIONS = 40
DEFAULT_TIME_BUDGET_S = 150.0
DEFAULT_SOURCE_FILTER = "all"

OCEAN_COLOR = "#B8D4E8"
LAND_COLOR = "#C4A882"
KM_PER_DEG_LAT = 111.32

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = _PROJECT_ROOT / "data_store" / "team_hexbin_cache"
OUTPUT_DIR = _PROJECT_ROOT / "data_store" / "team_hexbin_outputs"

_STATE_RANK = {
    CatalogOperationalState.ACTIVE.value: 0,
    CatalogOperationalState.COMPLETED.value: 1,
    CatalogOperationalState.PLANNED.value: 2,
    CatalogOperationalState.ARCHIVED.value: 3,
}


@dataclass(frozen=True)
class HexbinTrackSource:
    """One catalog-backed track location to pull for hexbin coverage."""

    mission_id: str
    deployment_number: Optional[int]
    operational_state: str
    source_kind: str
    collection: str
    external_ref: str
    source_variant: str
    provider_key: str = ""

    @property
    def label(self) -> str:
        if self.source_kind == CatalogSourceKind.WGMS_REMOTE.value:
            collection = self.collection or "wgms"
            return f"{self.external_ref}@{collection}"
        return self.external_ref


def _km_box_extent(
    center_lat: float,
    center_lon: float,
    size_km: float,
) -> Tuple[float, float, float, float]:
    if size_km <= 0:
        raise ValueError(f"size_km must be positive, got {size_km}")
    half_km = size_km / 2.0
    dlat = half_km / KM_PER_DEG_LAT
    cos_lat = max(math.cos(math.radians(center_lat)), 1e-6)
    dlon = half_km / (KM_PER_DEG_LAT * cos_lat)
    return (
        center_lon - dlon,
        center_lon + dlon,
        center_lat - dlat,
        center_lat + dlat,
    )


def _extent_center_and_size_km(
    extent: Tuple[float, float, float, float],
) -> Tuple[float, float, float]:
    lon_min, lon_max, lat_min, lat_max = extent
    center_lat = (lat_min + lat_max) / 2.0
    center_lon = (lon_min + lon_max) / 2.0
    lat_span_km = (lat_max - lat_min) * KM_PER_DEG_LAT
    cos_lat = max(math.cos(math.radians(center_lat)), 1e-6)
    lon_span_km = (lon_max - lon_min) * KM_PER_DEG_LAT * cos_lat
    size_km = (lat_span_km + lon_span_km) / 2.0
    return center_lat, center_lon, size_km


def resolve_extent(
    *,
    center_lat: Optional[float],
    center_lon: Optional[float],
    size_km: float,
    lon_min: Optional[float],
    lon_max: Optional[float],
    lat_min: Optional[float],
    lat_max: Optional[float],
) -> Tuple[Tuple[float, float, float, float], float, float, float]:
    """Return (extent, center_lat, center_lon, size_km)."""
    if None not in (lon_min, lon_max, lat_min, lat_max):
        if lon_min >= lon_max or lat_min >= lat_max:
            raise ValueError("bbox requires lon_min < lon_max and lat_min < lat_max")
        extent = (float(lon_min), float(lon_max), float(lat_min), float(lat_max))
        clat, clon, size = _extent_center_and_size_km(extent)
        return extent, clat, clon, size
    clat = DEFAULT_CENTER_LAT if center_lat is None else float(center_lat)
    clon = DEFAULT_CENTER_LON if center_lon is None else float(center_lon)
    if not (-90.0 <= clat <= 90.0):
        raise ValueError(f"Latitude out of range: {clat}")
    if not (-180.0 <= clon <= 180.0):
        raise ValueError(f"Longitude out of range: {clon}")
    size = float(size_km) if size_km else DEFAULT_SIZE_KM
    extent = _km_box_extent(clat, clon, size)
    return extent, clat, clon, size


def safe_output_filename(name: str) -> Optional[str]:
    """Basename-only guard for download routes."""
    if not name or name != Path(name).name:
        return None
    if ".." in name or "/" in name or "\\" in name:
        return None
    if not re.fullmatch(r"telemetry_hexbin_\d{8}T\d{6}Z_[\w.\-]+\.png", name):
        return None
    return name


def output_path_for(filename: str) -> Path:
    return OUTPUT_DIR / filename


def _parse_capabilities(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if item]


def _source_has_track_capability(capabilities_json: Optional[str]) -> bool:
    caps = _parse_capabilities(capabilities_json)
    if not caps:
        return True
    return "track" in caps or "telemetry" in caps


def _is_usable_source(source) -> bool:
    if not getattr(source, "enabled", False):
        return False
    status = (getattr(source, "match_status", "") or "").lower()
    if status in {
        CatalogMatchStatus.STALE.value,
        CatalogMatchStatus.CONFLICT.value,
        CatalogMatchStatus.UNMATCHED.value,
    }:
        return False
    if not _source_has_track_capability(getattr(source, "capabilities_json", None)):
        return False
    ref = (getattr(source, "external_ref", "") or "").strip()
    return bool(ref)


def _mission_sort_key(mission) -> Tuple[int, int, str]:
    state = (getattr(mission, "operational_state", "") or "").lower()
    state_rank = _STATE_RANK.get(state, 9)
    deployment = getattr(mission, "deployment_number", None)
    # Newest first within the same lifecycle bucket.
    dep_rank = -(int(deployment) if deployment is not None else -1)
    return (state_rank, dep_rank, str(getattr(mission, "id", "")))


def _source_sort_key(source: HexbinTrackSource) -> Tuple[int, int, str]:
    # Prefer realtime WGMS, then past WGMS, then ERDDAP.
    kind_rank = {
        CatalogSourceKind.WGMS_REMOTE.value: 0,
        CatalogSourceKind.ERDDAP.value: 1,
    }.get(source.source_kind, 9)
    realtime_rank = 0 if "realtime" in (source.collection or "").lower() else 1
    if source.source_variant == "realtime":
        realtime_rank = 0
    return (kind_rank, realtime_rank, source.external_ref.lower())


def _looks_like_erddap_id(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    return text.endswith(("_realtime", "_delayed")) or (
        "_" in text and not text.lower().startswith("m")
    )


def list_catalog_hexbin_sources(
    session,
    *,
    source_filter: str = DEFAULT_SOURCE_FILTER,
    max_missions: int = DEFAULT_MAX_MISSIONS,
    explicit_refs: Optional[Sequence[str]] = None,
) -> List[HexbinTrackSource]:
    """Return usable Wave Glider track sources from the catalog.

    ``max_missions`` caps *missions* (active first, then newest). Every usable
    source belonging to an included mission is retained (all-sources policy).
    """
    from app.core.models.database import (
        CatalogMission,
        CatalogMissionSource,
        CatalogPlatform,
    )
    from sqlmodel import select

    source_mode = (source_filter or DEFAULT_SOURCE_FILTER).strip().lower()
    wanted_kinds: set[str] = set()
    if source_mode in {"wgms", "all"}:
        wanted_kinds.add(CatalogSourceKind.WGMS_REMOTE.value)
    if source_mode in {"erddap", "all"}:
        wanted_kinds.add(CatalogSourceKind.ERDDAP.value)
    if not wanted_kinds:
        return []

    platforms = {
        p.id: p
        for p in session.exec(select(CatalogPlatform)).all()
        if p.id is not None and (p.platform_family or "") == "wave_glider"
    }
    if not platforms:
        return []

    missions = [
        m
        for m in session.exec(select(CatalogMission)).all()
        if m.platform_id in platforms
    ]
    missions.sort(key=_mission_sort_key)

    explicit = {m.strip() for m in (explicit_refs or []) if m and str(m).strip()}
    selected_mission_ids: List[str] = []
    for mission in missions:
        if not mission.id:
            continue
        if explicit:
            # Defer mission selection until we know it has a matching source.
            continue
        selected_mission_ids.append(mission.id)
        if len(selected_mission_ids) >= max(1, int(max_missions)):
            break

    mission_by_id = {m.id: m for m in missions if m.id}
    allowed_mission_ids = set(selected_mission_ids) if not explicit else set(mission_by_id)

    sources = list(session.exec(select(CatalogMissionSource)).all())

    by_mission: dict[str, List[HexbinTrackSource]] = {}
    for source in sources:
        mission_id = source.mission_id
        if not mission_id or mission_id not in allowed_mission_ids:
            continue
        if source.source_kind not in wanted_kinds:
            continue
        if not _is_usable_source(source):
            continue
        mission = mission_by_id.get(mission_id)
        if mission is None:
            continue
        if explicit and source.external_ref not in explicit:
            continue
        item = HexbinTrackSource(
            mission_id=mission_id,
            deployment_number=mission.deployment_number,
            operational_state=mission.operational_state,
            source_kind=source.source_kind,
            collection=(source.collection or "").strip(),
            external_ref=source.external_ref.strip(),
            source_variant=(source.source_variant or "").strip(),
            provider_key=(source.provider_key or "").strip(),
        )
        by_mission.setdefault(mission_id, []).append(item)

    if explicit:
        # Cap matching missions with the same active-first / newest ordering.
        matched_missions = [
            mission_by_id[mid]
            for mid in by_mission
            if mid in mission_by_id
        ]
        matched_missions.sort(key=_mission_sort_key)
        keep = {m.id for m in matched_missions[: max(1, int(max_missions))]}
        by_mission = {mid: items for mid, items in by_mission.items() if mid in keep}
        ordered_ids = [m.id for m in matched_missions if m.id in keep]
    else:
        ordered_ids = selected_mission_ids

    result: List[HexbinTrackSource] = []
    for mission_id in ordered_ids:
        items = by_mission.get(mission_id) or []
        items.sort(key=_source_sort_key)
        result.extend(items)
    return result


def _safe_cache_token(value: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "_", (value or "").strip())
    return cleaned or "unknown"


def _cache_csv_path(source: HexbinTrackSource) -> Path:
    """Namespace cache by kind/collection so realtime vs past never collide."""
    kind = _safe_cache_token(source.source_kind)
    collection = _safe_cache_token(source.collection or "default")
    ref = _safe_cache_token(source.external_ref)
    return CACHE_DIR / kind / collection / ref / TELEMETRY_FILENAME


def _wgms_base_url(collection: str) -> str:
    base = settings.remote_data_url.rstrip("/")
    folder = (collection or "output_past_missions").strip().strip("/")
    if folder not in {"output_realtime_missions", "output_past_missions"}:
        # Defensive fallback: unknown collections still resolve under remote root.
        folder = "output_past_missions"
    return f"{base}/{folder}"


async def load_telemetry_for_wgms_source(
    source: HexbinTrackSource,
    client: httpx.AsyncClient,
    *,
    refresh: bool,
) -> Optional[pd.DataFrame]:
    cache_path = _cache_csv_path(source)
    if cache_path.exists() and not refresh:
        try:
            df = await asyncio.to_thread(pd.read_csv, cache_path)
            logger.info("Cache hit: %s (%d rows)", source.label, len(df))
            return df
        except Exception as exc:
            logger.warning(
                "Failed reading cache for %s: %s; re-fetching", source.label, exc
            )

    base_url = _wgms_base_url(source.collection)
    df, _mtime = await load_report(
        "telemetry",
        source.external_ref,
        base_url=base_url,
        client=client,
    )
    if df is None or df.empty:
        logger.warning("No telemetry for %s (missing or empty); skipping", source.label)
        return None

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(df.to_csv, cache_path, index=False)
    logger.info("Fetched + cached %s (%d rows)", source.label, len(df))
    return df


def preprocess_and_filter(
    raw_df: pd.DataFrame,
    extent: Tuple[float, float, float, float],
    source: HexbinTrackSource,
) -> pd.DataFrame:
    tele = preprocess_telemetry_df(raw_df)
    if tele.empty:
        return tele

    required = {"Latitude", "Longitude"}
    missing = required - set(tele.columns)
    if missing:
        logger.warning(
            "%s missing columns %s after preprocess; skipping", source.label, missing
        )
        return pd.DataFrame()

    lon_min, lon_max, lat_min, lat_max = extent
    mask = (
        tele["Longitude"].between(lon_min, lon_max)
        & tele["Latitude"].between(lat_min, lat_max)
        & tele["Latitude"].notna()
        & tele["Longitude"].notna()
    )
    filtered = tele.loc[mask, ["Timestamp", "Latitude", "Longitude"]].copy()
    filtered["mission_folder"] = source.external_ref
    filtered["source_kind"] = source.source_kind
    filtered["source_label"] = source.label
    return filtered


def _normalize_erddap_track(df: pd.DataFrame) -> pd.DataFrame:
    rename: dict[str, str] = {}
    for col in df.columns:
        key = str(col).strip().lower().split(" ")[0]
        if key in {"time", "latitude", "longitude"} and key not in rename.values():
            rename[col] = key
    out = df.rename(columns=rename)
    keep = [c for c in ("time", "latitude", "longitude") if c in out.columns]
    return out.loc[:, keep].copy()


def _empty_points_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "Timestamp",
            "Latitude",
            "Longitude",
            "mission_folder",
            "source_kind",
            "source_label",
        ]
    )


async def collect_points_from_catalog_sources(
    sources: Sequence[HexbinTrackSource],
    extent: Tuple[float, float, float, float],
    *,
    refresh: bool,
    deadline: float,
) -> Tuple[pd.DataFrame, List[str], List[str], bool]:
    """Fetch and filter points for every selected catalog track source."""
    from app.core.data.erddap_tabledap import fetch_tabledap_track

    contributed: List[str] = []
    skipped: List[str] = []
    frames: List[pd.DataFrame] = []
    timed_out = False
    lon_min, lon_max, lat_min, lat_max = extent

    wgms_sources = [
        s for s in sources if s.source_kind == CatalogSourceKind.WGMS_REMOTE.value
    ]
    erddap_sources = [
        s for s in sources if s.source_kind == CatalogSourceKind.ERDDAP.value
    ]

    if wgms_sources:
        timeout = httpx.Timeout(60.0, connect=15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for source in wgms_sources:
                if time.monotonic() > deadline:
                    timed_out = True
                    logger.warning("Time budget exceeded before finishing all sources")
                    break
                try:
                    raw = await load_telemetry_for_wgms_source(
                        source, client, refresh=refresh
                    )
                except Exception as exc:
                    logger.warning("Error loading %s: %s; skipping", source.label, exc)
                    skipped.append(source.label)
                    continue
                if raw is None:
                    skipped.append(source.label)
                    continue
                try:
                    filtered = preprocess_and_filter(raw, extent, source)
                except Exception as exc:
                    logger.warning(
                        "Error preprocessing %s: %s; skipping", source.label, exc
                    )
                    skipped.append(source.label)
                    continue
                if filtered.empty:
                    logger.info("%s: 0 points in box", source.label)
                    continue
                contributed.append(source.label)
                frames.append(filtered)
                logger.info("%s: %d points in box", source.label, len(filtered))

    for source in erddap_sources:
        if time.monotonic() > deadline:
            timed_out = True
            break
        try:
            raw = await asyncio.to_thread(fetch_tabledap_track, source.external_ref)
        except Exception as exc:
            logger.warning("ERDDAP track failed for %s: %s", source.label, exc)
            skipped.append(source.label)
            continue
        if raw is None or raw.empty:
            skipped.append(source.label)
            continue
        track = _normalize_erddap_track(raw)
        if track.empty or "latitude" not in track.columns or "longitude" not in track.columns:
            skipped.append(source.label)
            continue
        track = track.dropna(subset=["latitude", "longitude"])
        mask = (
            track["longitude"].between(lon_min, lon_max)
            & track["latitude"].between(lat_min, lat_max)
        )
        filtered = track.loc[mask].copy()
        if filtered.empty:
            continue
        filtered = filtered.rename(
            columns={
                "time": "Timestamp",
                "latitude": "Latitude",
                "longitude": "Longitude",
            }
        )
        filtered["mission_folder"] = source.external_ref
        filtered["source_kind"] = source.source_kind
        filtered["source_label"] = source.label
        contributed.append(source.label)
        frames.append(
            filtered[
                [
                    "Timestamp",
                    "Latitude",
                    "Longitude",
                    "mission_folder",
                    "source_kind",
                    "source_label",
                ]
            ]
        )
        logger.info("%s: %d ERDDAP points in box", source.label, len(filtered))

    if not frames:
        return _empty_points_frame(), contributed, skipped, timed_out
    return pd.concat(frames, ignore_index=True), contributed, skipped, timed_out


async def collect_points_erddap(
    extent: Tuple[float, float, float, float],
    *,
    deadline: float,
    max_missions: int,
    dataset_ids: Optional[Sequence[str]] = None,
) -> Tuple[pd.DataFrame, List[str], List[str], bool]:
    """Compatibility wrapper: catalog ERDDAP sources (or explicit dataset ids)."""
    from app.core.infra.db import sqlite_engine
    from sqlmodel import Session

    if dataset_ids:
        synthetic = [
            HexbinTrackSource(
                mission_id=f"explicit:{dataset_id}",
                deployment_number=None,
                operational_state=CatalogOperationalState.COMPLETED.value,
                source_kind=CatalogSourceKind.ERDDAP.value,
                collection="tabledap",
                external_ref=str(dataset_id).strip(),
                source_variant="",
            )
            for dataset_id in dataset_ids
            if dataset_id and str(dataset_id).strip()
        ][:max_missions]
        return await collect_points_from_catalog_sources(
            synthetic, extent, refresh=False, deadline=deadline
        )

    with Session(sqlite_engine) as session:
        sources = list_catalog_hexbin_sources(
            session,
            source_filter="erddap",
            max_missions=max_missions,
        )
    return await collect_points_from_catalog_sources(
        sources, extent, refresh=False, deadline=deadline
    )


def _discover_past_mission_folders(listing_html: str) -> List[str]:
    """Legacy HTML scrape helper (fallback when catalog has no WGMS sources)."""
    patterns = [
        r"<([mM]\d+-[A-Z0-9]+)/?>",
        r"<([mM]\d+-[^>]+)/?>",
        r"<([mM]\d+[^>]*)/?>",
        r'href=["\']([mM]\d+[^"\']*)["\']',
    ]
    excluded = {"parent", "directory", "index", "..", ".", "", "private"}
    folders: set[str] = set()
    for pattern in patterns:
        for match in re.findall(pattern, listing_html, re.IGNORECASE):
            folder_name = match.strip().rstrip("/")
            if folder_name.lower() in excluded:
                continue
            if re.match(r"^m\d+", folder_name, re.IGNORECASE):
                folders.add(folder_name)

    def sort_key(name: str) -> Tuple[int, str]:
        m = re.match(r"^m(\d+)", name, re.IGNORECASE)
        return (int(m.group(1)) if m else 9999, name.lower())

    return sorted(folders, key=sort_key)


async def discover_past_mission_folders(client: httpx.AsyncClient) -> List[str]:
    base = settings.remote_data_url.rstrip("/")
    url = f"{base}/output_past_missions/"
    logger.info("Discovering past missions at %s", url)
    response = await client.get(url, timeout=30.0)
    response.raise_for_status()
    folders = _discover_past_mission_folders(response.text)
    logger.info("Found %d past mission folders", len(folders))
    return folders


async def _fallback_past_wgms_sources(
    *,
    explicit: Sequence[str],
    max_missions: int,
) -> List[HexbinTrackSource]:
    """Legacy scrape of output_past_missions when catalog inventory is empty."""
    timeout = httpx.Timeout(60.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if explicit:
            folders = [m for m in explicit if not _looks_like_erddap_id(m)]
        else:
            folders = await discover_past_mission_folders(client)
            if len(folders) > max_missions:
                folders = folders[-max_missions:]
    return [
        HexbinTrackSource(
            mission_id=f"legacy:{folder}",
            deployment_number=None,
            operational_state=CatalogOperationalState.COMPLETED.value,
            source_kind=CatalogSourceKind.WGMS_REMOTE.value,
            collection="output_past_missions",
            external_ref=folder,
            source_variant="",
            provider_key="legacy_scrape",
        )
        for folder in folders
    ]


def add_bathymetry_contours(ax, extent: Tuple[float, float, float, float]) -> None:
    extent_list = list(extent)
    try:
        grid = fetch_etopo_bathymetry(extent_list)
    except Exception as exc:
        logger.warning("Bathymetry fetch failed: %s", exc)
        return

    if grid is None or grid.z.size == 0:
        logger.warning("No bathymetry grid returned for extent %s", extent_list)
        return

    z_ocean = np.ma.masked_where(grid.z >= 0, grid.z)
    if z_ocean.count() == 0:
        logger.warning("Bathymetry grid has no ocean depths for extent %s", extent_list)
        return

    valid_z = z_ocean.compressed()
    levels = nice_contour_levels(float(np.min(valid_z)), float(np.max(valid_z)))
    if not levels:
        return

    try:
        contour_set = ax.contour(
            grid.longitude,
            grid.latitude,
            z_ocean,
            levels=levels,
            colors="#1E3A5F",
            linewidths=0.5,
            alpha=0.75,
            transform=ccrs.PlateCarree(),
            zorder=1.5,
        )
        ax.clabel(
            contour_set,
            inline=True,
            fontsize=6,
            fmt=lambda value: f"{abs(int(value))} m",
        )
    except Exception as exc:
        logger.warning("Skipping bathymetry contours: %s", exc)


def plot_hexbin(
    df: pd.DataFrame,
    extent: Tuple[float, float, float, float],
    *,
    gridsize: int,
    output_path: Path,
    title: str,
    include_bathymetry: bool = True,
    include_regional_inset: bool = True,
) -> None:
    lon_min, lon_max, lat_min, lat_max = extent
    main_extent = [lon_min, lon_max, lat_min, lat_max]
    fig = plt.figure(figsize=(10, 9))
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
    ax.set_extent(main_extent, crs=ccrs.PlateCarree())
    ax.add_feature(cfeature.OCEAN, facecolor=OCEAN_COLOR, zorder=0)
    ax.add_feature(cfeature.LAND, facecolor=LAND_COLOR, zorder=1)
    if include_bathymetry:
        add_bathymetry_contours(ax, extent)
    ax.coastlines(resolution="10m", zorder=2)
    ax.add_feature(cfeature.BORDERS, linestyle=":", zorder=2)

    hb = ax.hexbin(
        df["Longitude"].to_numpy(dtype=float),
        df["Latitude"].to_numpy(dtype=float),
        gridsize=gridsize,
        cmap="viridis",
        mincnt=1,
        norm=LogNorm(),
        transform=ccrs.PlateCarree(),
        zorder=3,
        linewidths=0.15,
        edgecolors="none",
    )
    cbar = fig.colorbar(hb, ax=ax, shrink=0.82, pad=0.02)
    cbar.set_label("Total telemetry fixes (log scale)")

    gl = ax.gridlines(
        draw_labels=True, linewidth=0.25, color="gray", alpha=0.5, linestyle="--"
    )
    gl.top_labels = False
    gl.right_labels = False
    gl.xlabel_style = {"size": 10}
    gl.ylabel_style = {"size": 10}
    gl.xformatter = LONGITUDE_FORMATTER
    gl.yformatter = LATITUDE_FORMATTER

    ax.set_title(title, fontsize=13, pad=12)
    # Layout first so the regional inset can anchor to the final axes position
    # (same order as report telemetry maps).
    fig.tight_layout()
    if include_regional_inset:
        regional_extent = _regional_inset_extent(main_extent)
        _add_report_regional_inset(
            fig,
            ax,
            main_extent,
            regional_extent,
            OVERLAY_STRIP_MIN_FRACTION,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Wrote %s", output_path)


def _format_date_range(timestamps: pd.Series) -> str:
    ts = pd.to_datetime(timestamps, utc=True, errors="coerce").dropna()
    if ts.empty:
        return "unknown dates"
    start = ts.min().strftime("%Y-%m-%d")
    end = ts.max().strftime("%Y-%m-%d")
    return f"{start} - {end}"


def _make_output_filename(center_lat: float, center_lon: float, size_km: float) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lat_tag = f"{center_lat:.2f}".replace(".", "p")
    lon_tag = f"{center_lon:.2f}".replace(".", "p").replace("-", "m")
    size_tag = f"{size_km:.0f}km"
    return f"telemetry_hexbin_{stamp}_{lat_tag}_{lon_tag}_{size_tag}.png"


async def async_generate_hexbin(
    *,
    center_lat: Optional[float] = None,
    center_lon: Optional[float] = None,
    size_km: float = DEFAULT_SIZE_KM,
    lon_min: Optional[float] = None,
    lon_max: Optional[float] = None,
    lat_min: Optional[float] = None,
    lat_max: Optional[float] = None,
    gridsize: int = DEFAULT_GRIDSIZE,
    missions: Optional[str] = None,
    refresh: bool = False,
    include_bathymetry: bool = True,
    max_missions: int = DEFAULT_MAX_MISSIONS,
    time_budget_s: float = DEFAULT_TIME_BUDGET_S,
    source_filter: str = DEFAULT_SOURCE_FILTER,
) -> TelemetryHexbinResult:
    started = time.perf_counter()
    deadline = time.monotonic() + max(30.0, float(time_budget_s))
    try:
        extent, clat, clon, size = resolve_extent(
            center_lat=center_lat,
            center_lon=center_lon,
            size_km=size_km,
            lon_min=lon_min,
            lon_max=lon_max,
            lat_min=lat_min,
            lat_max=lat_max,
        )
    except ValueError as exc:
        return TelemetryHexbinResult(
            success=False,
            error=str(exc),
            summary=f"Error: {exc}",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    source_mode = (source_filter or DEFAULT_SOURCE_FILTER).strip().lower()
    if source_mode not in {"wgms", "erddap", "all"}:
        return TelemetryHexbinResult(
            success=False,
            error=f"Invalid source_filter={source_filter!r}; use wgms|erddap|all",
            summary="Error: invalid source_filter",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    explicit = [m.strip() for m in missions.split(",")] if missions else []
    explicit = [m for m in explicit if m]

    from app.core.infra.db import sqlite_engine
    from sqlmodel import Session

    with Session(sqlite_engine) as session:
        catalog_sources = list_catalog_hexbin_sources(
            session,
            source_filter=source_mode,
            max_missions=max_missions,
            explicit_refs=explicit or None,
        )

    # Fallback: if catalog has no WGMS rows for a wgms/all request, scrape past folders.
    want_wgms = source_mode in {"wgms", "all"}
    have_wgms = any(
        s.source_kind == CatalogSourceKind.WGMS_REMOTE.value for s in catalog_sources
    )
    if want_wgms and not have_wgms:
        logger.warning(
            "Catalog returned no WGMS hexbin sources; falling back to past-folder scrape"
        )
        catalog_sources = list(catalog_sources) + await _fallback_past_wgms_sources(
            explicit=explicit,
            max_missions=max_missions,
        )

    # Explicit ERDDAP ids not found in catalog still get pulled when requested.
    if explicit and source_mode in {"erddap", "all"}:
        known = {s.external_ref for s in catalog_sources}
        for ref in explicit:
            if ref in known:
                continue
            if source_mode == "erddap" or _looks_like_erddap_id(ref):
                catalog_sources.append(
                    HexbinTrackSource(
                        mission_id=f"explicit:{ref}",
                        deployment_number=None,
                        operational_state=CatalogOperationalState.COMPLETED.value,
                        source_kind=CatalogSourceKind.ERDDAP.value,
                        collection="tabledap",
                        external_ref=ref,
                        source_variant="",
                        provider_key="explicit",
                    )
                )

    if not catalog_sources:
        return TelemetryHexbinResult(
            success=False,
            error="No catalog track sources matched the request",
            summary="Error: no catalog track sources matched",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    combined, contributed, skipped, timed_out = await collect_points_from_catalog_sources(
        catalog_sources,
        extent,
        refresh=refresh,
        deadline=deadline,
    )

    source_counts = {
        "wgms_remote": int((combined["source_kind"] == "wgms_remote").sum())
        if not combined.empty
        else 0,
        "erddap": int((combined["source_kind"] == "erddap").sum())
        if not combined.empty
        else 0,
    }

    if timed_out and combined.empty:
        return TelemetryHexbinResult(
            success=False,
            error="Time budget exceeded before any in-box points were collected",
            summary="Error: time budget exceeded (narrow bbox or set missions=)",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
    if combined.empty:
        return TelemetryHexbinResult(
            success=False,
            error="No telemetry points inside the box",
            summary="Error: no telemetry points inside the box",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    filename = _make_output_filename(clat, clon, size)
    output_path = output_path_for(filename)
    date_range = _format_date_range(combined["Timestamp"])
    title = (
        f"Wave Glider Coverage: {date_range}\n"
        f"Center {clat:.2f}°, {clon:.2f}° · ~{size:.0f} km box · sources={source_mode}"
    )
    plot_hexbin(
        combined,
        extent,
        gridsize=gridsize,
        output_path=output_path,
        title=title,
        include_bathymetry=include_bathymetry,
    )
    duration_ms = int((time.perf_counter() - started) * 1000)
    mission_count = len({s.mission_id for s in catalog_sources if s.mission_id})
    # Prefer contributed mission folders when available.
    if contributed:
        mission_count = len(set(contributed))
    summary_parts = [
        f"Wrote {filename}",
        f"{len(combined)} points from {mission_count} sources",
        f"skipped={len(skipped)}",
        f"wgms={source_counts['wgms_remote']}",
        f"erddap={source_counts['erddap']}",
        f"duration_ms={duration_ms}",
    ]
    if timed_out:
        summary_parts.append("NOTE: time budget hit; result may be partial")
    return TelemetryHexbinResult(
        success=True,
        output_url=f"/api/team/telemetry-hexbin/outputs/{filename}",
        filename=filename,
        point_count=len(combined),
        mission_count=mission_count,
        duration_ms=duration_ms,
        summary="; ".join(summary_parts),
        source_counts=source_counts,
    )


def generate_hexbin_sync(**kwargs) -> TelemetryHexbinResult:
    """Sync entrypoint for Team threadpool / CLI."""
    return asyncio.run(async_generate_hexbin(**kwargs))
