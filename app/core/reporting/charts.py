"""Render matplotlib report figures to ReportLab Image flowables.

Sizing uses ``LANDSCAPE_CONTENT_*`` / portrait helpers from ``styling``; ``pad_inches`` and
``tight_layout`` rects control whitespace inside the PNG, not the PDF margins.

Dense time-series frames are stride-downsampled before matplotlib draw so long
end-of-mission week loops stay within gunicorn/proxy budgets (summaries still
use full frames in the builder).
"""

from __future__ import annotations

import io
import math
from typing import Any, Dict, List, Optional

import matplotlib.pyplot as plt
import pandas as pd
from PIL import Image as PILImage
from reportlab.platypus import Image

from ..plotting import (
    plot_c3_for_report,
    plot_ctd_for_report,
    plot_power_for_report,
    plot_slocum_battery_for_report,
    plot_telemetry_page_with_notes,
    plot_wave_for_report,
    plot_weather_for_report,
    report_pdf_rc_context,
)

DEFAULT_DPI = 200
# Cap chart vertices so EOM multi-week matplotlib stays interactive-request friendly.
# ~5k points is visually dense at report DPI; stride keeps temporal coverage.
REPORT_CHART_MAX_POINTS = 5000


def _limit_chart_rows(
    df: pd.DataFrame,
    *,
    max_points: int = REPORT_CHART_MAX_POINTS,
) -> pd.DataFrame:
    """Evenly stride-downsample ``df`` when it exceeds ``max_points`` (plot path only)."""
    if df is None or df.empty:
        return df
    n = len(df)
    if n <= max_points:
        return df
    # ceil so e.g. 13626 → step 3 (~4.5k), not step 2 (~6.8k still over the cap).
    step = max(1, int(math.ceil(n / float(max_points))))
    out = df.iloc[::step].copy()
    if len(out) > max_points:
        out = out.iloc[:max_points].copy()
    return out


def _fig_to_image(
    fig: Any,
    *,
    dpi: int = DEFAULT_DPI,
    max_width_pt: float,
    max_height_pt: float | None = None,
) -> Image:
    buf = io.BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", pad_inches=0.04, facecolor="white")
    finally:
        plt.close(fig)
    buf.seek(0)
    pil = PILImage.open(buf)
    px_w, px_h = pil.size
    aspect = px_h / max(px_w, 1)
    width_pt = max_width_pt
    height_pt = width_pt * aspect
    if max_height_pt is not None and height_pt > max_height_pt:
        height_pt = max_height_pt
        width_pt = height_pt / aspect
    if width_pt > max_width_pt:
        width_pt = max_width_pt
        height_pt = width_pt * aspect
    buf.seek(0)
    return Image(buf, width=width_pt, height=height_pt)


def chart_telemetry_image(
    telemetry_df: pd.DataFrame,
    note_annotations: Optional[List[Dict[str, Any]]],
    *,
    max_width_pt: float,
    max_height_pt: float | None = None,
    dpi: int = DEFAULT_DPI,
    color_by: str = "sog",
    include_bathymetry: bool = True,
) -> Image:
    plot_df = _limit_chart_rows(telemetry_df)
    with report_pdf_rc_context():
        fig = plt.figure(figsize=(8.27, 11.69))
        plot_telemetry_page_with_notes(
            fig,
            plot_df,
            note_annotations=note_annotations or [],
            color_by=color_by,
            include_bathymetry=include_bathymetry,
        )
    return _fig_to_image(fig, dpi=dpi, max_width_pt=max_width_pt, max_height_pt=max_height_pt)


def chart_power_image(
    power_df: pd.DataFrame,
    solar_df: Optional[pd.DataFrame] = None,
    *,
    battery_max_wh: float = 2940.0,
    max_width_pt: float,
    max_height_pt: float | None = None,
    dpi: int = DEFAULT_DPI,
) -> Image:
    plot_power = _limit_chart_rows(power_df)
    plot_solar = _limit_chart_rows(solar_df) if solar_df is not None else None
    with report_pdf_rc_context():
        fig = plt.figure(figsize=(11.69, 8.27))
        plot_power_for_report(
            fig,
            plot_power,
            plot_solar,
            battery_max_wh=battery_max_wh,
        )
        fig.tight_layout(rect=[0, 0.02, 1, 0.96])
    return _fig_to_image(fig, dpi=dpi, max_width_pt=max_width_pt, max_height_pt=max_height_pt)


def chart_ctd_image(
    ctd_df: pd.DataFrame,
    *,
    max_width_pt: float,
    max_height_pt: float | None = None,
    dpi: int = DEFAULT_DPI,
) -> Image:
    plot_df = _limit_chart_rows(ctd_df)
    with report_pdf_rc_context():
        fig = plt.figure(figsize=(11.69, 8.27))
        plot_ctd_for_report(fig, plot_df)
        fig.tight_layout(rect=[0, 0.02, 1, 0.97])
    return _fig_to_image(fig, dpi=dpi, max_width_pt=max_width_pt, max_height_pt=max_height_pt)


def chart_weather_image(
    weather_df: pd.DataFrame,
    *,
    max_width_pt: float,
    max_height_pt: float | None = None,
    dpi: int = DEFAULT_DPI,
) -> Image:
    plot_df = _limit_chart_rows(weather_df)
    with report_pdf_rc_context():
        fig = plt.figure(figsize=(11.69, 8.27))
        plot_weather_for_report(fig, plot_df)
        fig.tight_layout(rect=[0, 0.02, 1, 0.97])
    return _fig_to_image(fig, dpi=dpi, max_width_pt=max_width_pt, max_height_pt=max_height_pt)


def chart_wave_image(
    wave_df: pd.DataFrame,
    *,
    max_width_pt: float,
    max_height_pt: float | None = None,
    dpi: int = DEFAULT_DPI,
) -> Image:
    plot_df = _limit_chart_rows(wave_df)
    with report_pdf_rc_context():
        fig = plt.figure(figsize=(11.69, 8.27))
        plot_wave_for_report(fig, plot_df)
        fig.tight_layout(rect=[0, 0.02, 1, 0.97])
    return _fig_to_image(fig, dpi=dpi, max_width_pt=max_width_pt, max_height_pt=max_height_pt)


def chart_c3_image(
    fluorometer_df: pd.DataFrame,
    *,
    channel_map: dict | None = None,
    max_width_pt: float,
    max_height_pt: float | None = None,
    dpi: int = DEFAULT_DPI,
) -> Image:
    plot_df = _limit_chart_rows(fluorometer_df)
    with report_pdf_rc_context():
        fig = plt.figure(figsize=(11.69, 8.27))
        plot_c3_for_report(fig, plot_df, channel_map=channel_map)
        fig.tight_layout(rect=[0, 0.02, 1, 0.97])
    return _fig_to_image(fig, dpi=dpi, max_width_pt=max_width_pt, max_height_pt=max_height_pt)


def chart_slocum_battery_image(
    daily_df: pd.DataFrame,
    *,
    max_width_pt: float,
    max_height_pt: float | None = None,
    dpi: int = DEFAULT_DPI,
    title: str = "Daily amp-hour consumption",
) -> Image:
    with report_pdf_rc_context():
        fig = plt.figure(figsize=(8.27, 4.8))
        plot_slocum_battery_for_report(fig, daily_df, title=title)
        fig.tight_layout(rect=[0, 0.02, 1, 0.96])
    return _fig_to_image(fig, dpi=dpi, max_width_pt=max_width_pt, max_height_pt=max_height_pt)
