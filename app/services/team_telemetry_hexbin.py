"""Wave Glider telemetry hexbin coverage maps for Team (and CLI shim).

Moved from tests/oneoff_telemetry_hexbin.py. Cache/outputs live under data_store/.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
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
from app.core.models.schemas import TelemetryHexbinResult

logger = logging.getLogger("team_telemetry_hexbin")

TELEMETRY_FILENAME = "Telemetry 6 Report by WGMS Datetime.csv"
DEFAULT_CENTER_LAT = 44.04
DEFAULT_CENTER_LON = -60.32
DEFAULT_SIZE_KM = 150.0
DEFAULT_GRIDSIZE = 60
DEFAULT_MAX_MISSIONS = 40
DEFAULT_TIME_BUDGET_S = 150.0

OCEAN_COLOR = "#B8D4E8"
LAND_COLOR = "#C4A882"
KM_PER_DEG_LAT = 111.32

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = _PROJECT_ROOT / "data_store" / "team_hexbin_cache"
OUTPUT_DIR = _PROJECT_ROOT / "data_store" / "team_hexbin_outputs"


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


def _discover_past_mission_folders(listing_html: str) -> List[str]:
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


def _cache_csv_path(folder: str) -> Path:
    return CACHE_DIR / folder / TELEMETRY_FILENAME


async def load_telemetry_for_folder(
    folder: str,
    past_base_url: str,
    client: httpx.AsyncClient,
    *,
    refresh: bool,
) -> Optional[pd.DataFrame]:
    cache_path = _cache_csv_path(folder)
    if cache_path.exists() and not refresh:
        try:
            df = await asyncio.to_thread(pd.read_csv, cache_path)
            logger.info("Cache hit: %s (%d rows)", folder, len(df))
            return df
        except Exception as exc:
            logger.warning("Failed reading cache for %s: %s; re-fetching", folder, exc)

    df, _mtime = await load_report(
        "telemetry",
        folder,
        base_url=past_base_url,
        client=client,
    )
    if df is None or df.empty:
        logger.warning("No telemetry for %s (missing or empty); skipping", folder)
        return None

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(df.to_csv, cache_path, index=False)
    logger.info("Fetched + cached %s (%d rows)", folder, len(df))
    return df


def preprocess_and_filter(
    raw_df: pd.DataFrame,
    extent: Tuple[float, float, float, float],
    folder: str,
) -> pd.DataFrame:
    tele = preprocess_telemetry_df(raw_df)
    if tele.empty:
        return tele

    required = {"Latitude", "Longitude"}
    missing = required - set(tele.columns)
    if missing:
        logger.warning("%s missing columns %s after preprocess; skipping", folder, missing)
        return pd.DataFrame()

    lon_min, lon_max, lat_min, lat_max = extent
    mask = (
        tele["Longitude"].between(lon_min, lon_max)
        & tele["Latitude"].between(lat_min, lat_max)
        & tele["Latitude"].notna()
        & tele["Longitude"].notna()
    )
    filtered = tele.loc[mask, ["Timestamp", "Latitude", "Longitude"]].copy()
    filtered["mission_folder"] = folder
    return filtered


async def collect_points(
    folders: Sequence[str],
    extent: Tuple[float, float, float, float],
    *,
    refresh: bool,
    deadline: float,
) -> Tuple[pd.DataFrame, List[str], List[str], bool]:
    past_base = f"{settings.remote_data_url.rstrip('/')}/output_past_missions"
    contributed: List[str] = []
    skipped: List[str] = []
    frames: List[pd.DataFrame] = []
    timed_out = False

    timeout = httpx.Timeout(60.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for folder in folders:
            if time.monotonic() > deadline:
                timed_out = True
                logger.warning("Time budget exceeded before finishing all missions")
                break
            try:
                raw = await load_telemetry_for_folder(
                    folder, past_base, client, refresh=refresh
                )
            except Exception as exc:
                logger.warning("Error loading %s: %s; skipping", folder, exc)
                skipped.append(folder)
                continue

            if raw is None:
                skipped.append(folder)
                continue

            try:
                filtered = preprocess_and_filter(raw, extent, folder)
            except Exception as exc:
                logger.warning("Error preprocessing %s: %s; skipping", folder, exc)
                skipped.append(folder)
                continue

            if filtered.empty:
                logger.info("%s: 0 points in box", folder)
                continue

            contributed.append(folder)
            frames.append(filtered)
            logger.info("%s: %d points in box", folder, len(filtered))

    if not frames:
        empty = pd.DataFrame(columns=["Timestamp", "Latitude", "Longitude", "mission_folder"])
        return empty, contributed, skipped, timed_out

    combined = pd.concat(frames, ignore_index=True)
    return combined, contributed, skipped, timed_out


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
) -> None:
    lon_min, lon_max, lat_min, lat_max = extent
    fig = plt.figure(figsize=(10, 9))
    ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
    ax.set_extent([lon_min, lon_max, lat_min, lat_max], crs=ccrs.PlateCarree())
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
    fig.tight_layout()
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

    timeout = httpx.Timeout(60.0, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if missions:
            folders = [m.strip() for m in missions.split(",") if m.strip()]
        else:
            folders = await discover_past_mission_folders(client)
            if len(folders) > max_missions:
                logger.info(
                    "Capping discovered missions from %d to %d (pass missions= to override)",
                    len(folders),
                    max_missions,
                )
                folders = folders[-max_missions:]

    if not folders:
        return TelemetryHexbinResult(
            success=False,
            error="No past mission folders to process",
            summary="Error: no past mission folders",
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    combined, contributed, skipped, timed_out = await collect_points(
        folders, extent, refresh=refresh, deadline=deadline
    )
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
        f"Center {clat:.2f}°, {clon:.2f}° · ~{size:.0f} km box"
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
    summary_parts = [
        f"Wrote {filename}",
        f"{len(combined)} points from {len(contributed)} missions",
        f"skipped={len(skipped)}",
        f"duration_ms={duration_ms}",
    ]
    if timed_out:
        summary_parts.append("NOTE: time budget hit; result may be partial")
    return TelemetryHexbinResult(
        success=True,
        output_url=f"/api/team/telemetry-hexbin/outputs/{filename}",
        filename=filename,
        point_count=len(combined),
        mission_count=len(contributed),
        duration_ms=duration_ms,
        summary="; ".join(summary_parts),
    )


def generate_hexbin_sync(**kwargs) -> TelemetryHexbinResult:
    """Sync entrypoint for Team threadpool / CLI."""
    return asyncio.run(async_generate_hexbin(**kwargs))
