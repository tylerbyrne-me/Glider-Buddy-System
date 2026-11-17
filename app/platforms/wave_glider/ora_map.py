"""Operations-area map for the Wave Glider ORA PDF.

Draws the coordinate table on the weekly-report Cartopy base (land/ocean,
optional ETOPO contours, compass, scale bar, regional inset). Points are
numbered in table order; the course is one line through every point, and each
``Box NW/NE/SE/SW`` run (what the ORA page's Box tool writes) is filled.
"""

from __future__ import annotations

import io
import math
from typing import Any, Optional, Sequence

import cartopy.crs as ccrs
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import to_rgba  # noqa: E402
from matplotlib.patches import Polygon  # noqa: E402

from app.core.plotting import (  # noqa: E402
    _add_report_bathymetry_contours,
    _add_report_map_scale_and_compass,
    _add_report_regional_inset,
    _compute_overlay_strip_extent,
    _pad_extent_to_aspect,
    _regional_inset_extent,
    _resolve_overlay_strip_fraction,
    _setup_report_map,
    _track_bounding_extent,
    report_pdf_rc_context,
)

BOX_COMMENTS = ("Box NW", "Box NE", "Box SE", "Box SW")
HOLD_COMMENT = "hold station"
LINE_COLOR = "#0B3A5B"
HOLD_COLOR = "#C2410C"
# A lone hold station still needs coastline context around it.
MIN_SPAN_DEG = 0.25
PADDING_FRACTION = 0.25
FIGSIZE_IN = (7.3, 5.8)
DPI = 200


def _finite_pair(point: Any) -> Optional[tuple[float, float]]:
    lat, lon = point.lat, point.lon
    if lat is None or lon is None:
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    return float(lat), float(lon)


def _box_groups(points: Sequence[Any]) -> list[list[tuple[float, float]]]:
    groups = []
    index = 0
    while index + len(BOX_COMMENTS) <= len(points):
        run = points[index : index + len(BOX_COMMENTS)]
        corners = [_finite_pair(point) for point in run]
        is_box = all(
            (point.comment or "").strip() == expected
            for point, expected in zip(run, BOX_COMMENTS)
        )
        if is_box and all(corners):
            groups.append(corners)
            index += len(BOX_COMMENTS)
            continue
        index += 1
    return groups


def _is_hold_station(point: Any) -> bool:
    return (point.comment or "").strip().lower() == HOLD_COMMENT


def plot_ora_area_map(fig, points: Sequence[Any]) -> bool:
    """Draw numbered ``points`` (label/lat/lon/comment) on ``fig``.

    Returns False without drawing when no point has a usable lat/lon.
    """
    numbered = [
        (number, pair, point)
        for number, point in enumerate(points, start=1)
        if (pair := _finite_pair(point)) is not None
    ]
    if not numbered:
        return False

    lats = [pair[0] for _, pair, _ in numbered]
    lons = [pair[1] for _, pair, _ in numbered]
    extent = _track_bounding_extent(
        lons,
        lats,
        padding_fraction=PADDING_FRACTION,
        min_span_deg=MIN_SPAN_DEG,
    )
    map_ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
    fig_w, fig_h = fig.get_size_inches()
    strip_extent, strip_deg = _compute_overlay_strip_extent(extent)
    padded_extent = _pad_extent_to_aspect(strip_extent, fig_w / max(fig_h - 0.6, 1e-3))
    strip_fraction = _resolve_overlay_strip_fraction(strip_deg, padded_extent)
    _setup_report_map(map_ax, padded_extent)
    _add_report_bathymetry_contours(map_ax, padded_extent)

    for corners in _box_groups(points):
        map_ax.add_patch(
            Polygon(
                [(lon, lat) for lat, lon in corners],
                closed=True,
                facecolor=to_rgba(LINE_COLOR, 0.15),
                edgecolor=LINE_COLOR,
                linewidth=1.6,
                transform=ccrs.PlateCarree(),
                zorder=3,
            )
        )
    if len(numbered) >= 2:
        map_ax.plot(
            lons,
            lats,
            color=LINE_COLOR,
            linewidth=1.6,
            transform=ccrs.PlateCarree(),
            zorder=4,
        )
    for number, (lat, lon), point in numbered:
        is_hold = _is_hold_station(point)
        map_ax.plot(
            lon,
            lat,
            marker="*" if is_hold else "o",
            markersize=13 if is_hold else 7,
            color=HOLD_COLOR if is_hold else LINE_COLOR,
            markeredgecolor="white",
            markeredgewidth=0.8,
            transform=ccrs.PlateCarree(),
            zorder=6,
        )
        map_ax.annotate(
            str(number),
            xy=(lon, lat),
            xycoords="data",
            xytext=(6, 6),
            textcoords="offset points",
            fontsize=8,
            fontweight="bold",
            color="black",
            bbox=dict(boxstyle="round,pad=0.2", facecolor="white", edgecolor="#9CA3AF", alpha=0.9),
            zorder=7,
        )

    _add_report_map_scale_and_compass(map_ax, padded_extent, strip_fraction)
    map_ax.set_title("Operations area")
    fig.tight_layout(pad=1.0)
    _add_report_regional_inset(
        fig, map_ax, padded_extent, _regional_inset_extent(padded_extent), strip_fraction
    )
    return True


def render_ora_area_map_png(points: Sequence[Any]) -> Optional[bytes]:
    """PNG bytes of the operations-area map, or None when there is nothing to plot."""
    with report_pdf_rc_context():
        fig = plt.figure(figsize=FIGSIZE_IN)
        try:
            if not plot_ora_area_map(fig, points):
                return None
            buffer = io.BytesIO()
            fig.savefig(buffer, format="png", dpi=DPI, bbox_inches="tight", pad_inches=0.04, facecolor="white")
            return buffer.getvalue()
        finally:
            plt.close(fig)
