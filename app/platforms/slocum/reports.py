"""Slocum glider weekly PDF report generation."""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional, Sequence

import cmocean.cm as cmo
import matplotlib.pyplot as plt
import pandas as pd
from PIL import Image as PILImage
from reportlab.lib.units import mm
from reportlab.platypus import Image, NextPageTemplate, PageBreak, Paragraph, Spacer
from sqlmodel import Session as SQLModelSession, select

from app.core import models, utils
from app.core.mission_aliases import resolve_slocum_dataset_id, resolved_slocum_mission_key
from app.core.geo.bathymetry import fetch_etopo_bathymetry, sample_depth_m_from_grid
from app.core.geo.coordinates import drop_null_island_rows
from app.core.data.processors import filter_valid_water_depth_m
from app.core.plotting import plot_slocum_ctd_profile_for_report, report_pdf_rc_context
from app.core.sfmc_transforms import normalize_dmon_asc_files
from app.core.utils import slocum_mission_key
from app.core.reporting import sections
from app.core.reporting.builder import (
    build_mission_note_annotations,
    calculate_telemetry_summary,
    load_instrument_blocks,
    mission_blocks_from_deployment,
)
from app.core.reporting.common import build_platform_cover_flowables, get_report_logo_path, get_report_paragraph_styles
from app.core.reporting.constants import REPORTS_ROOT
from app.core.reporting.styling import WeeklyReportDocTemplate
from .battery_report import build_battery_report_context
from .cache_service import get_cached_or_fetch_bundle_df, slice_processed_df
from .checklist_autofill import (
    BATTERY_PACK_PRESETS,
    parse_checklist_reference_values,
    parse_enabled_sensor_cards,
)
from .deployment_service import get_or_create_deployment_for_dataset
from .dmon_review import (
    count_dmon_confirmed_detections,
    filter_dmon_review,
    get_cached_dmon_review,
)
from .erddap_client import fetch_dataset_time_extent
from .mirror_service import dashboard_df_to_track_df
from .overage_cache import OverageResult

logger = logging.getLogger(__name__)

SLOCUM_WEEKLY_REPORT_VARIABLE_GROUPS = {
    "track": ["time", "latitude", "longitude", "depth"],
    "dashboard": None,
    "ctd": None,
}

_ETOPO_WATER_DEPTH_MAX_SAMPLES = 48


def default_slocum_weekly_date_window() -> tuple[date, date]:
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=7)
    return start_date, end_date


def _iso_window(start_date: date, end_date: date) -> tuple[str, str]:
    start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(end_date, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc)
    return (
        start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


async def _load_bundle_window(
    dataset_id: str,
    bundle: str,
    time_start: str,
    time_end: str,
    *,
    hours_back: int,
) -> pd.DataFrame:
    result = await get_cached_or_fetch_bundle_df(
        dataset_id,
        bundle,
        time_start,
        time_end,
        hours_back=hours_back,
        context="report",
        return_metadata=True,
    )
    if isinstance(result, OverageResult):
        return result.df if result.df is not None else pd.DataFrame()
    return result if isinstance(result, pd.DataFrame) and result is not None else pd.DataFrame()


def resolve_mission_track_start_date(
    *,
    dataset_id: str,
    deployment: Optional[models.SlocumDeployment],
    period_start: date,
) -> date:
    """Earliest date to use for Distance (total) track loading."""
    if deployment and deployment.deployment_date is not None:
        dep = deployment.deployment_date
        if dep.tzinfo is None:
            return dep.date()
        return dep.astimezone(timezone.utc).date()
    try:
        min_dt, _ = fetch_dataset_time_extent(dataset_id)
    except Exception as exc:
        logger.debug("Mission start extent lookup failed for %s: %s", dataset_id, exc)
        min_dt = None
    if min_dt is not None:
        if min_dt.tzinfo is None:
            return min_dt.date()
        return min_dt.astimezone(timezone.utc).date()
    return period_start


async def load_slocum_report_dataframes(
    dataset_id: str,
    start_date: date,
    end_date: date,
    *,
    mission_start_date: Optional[date] = None,
) -> dict[str, pd.DataFrame]:
    time_start, time_end = _iso_window(start_date, end_date)
    hours_back = max(1, int((end_date - start_date).total_seconds() / 3600) + 24)

    mission_start = mission_start_date or start_date
    if mission_start > end_date:
        mission_start = start_date
    mission_time_start, mission_time_end = _iso_window(mission_start, end_date)
    mission_hours_back = max(
        hours_back,
        max(1, int((end_date - mission_start).total_seconds() / 3600) + 24),
    )

    dash_raw, ctd_raw, mission_dash_raw = await asyncio.gather(
        _load_bundle_window(dataset_id, "dashboard", time_start, time_end, hours_back=hours_back),
        _load_bundle_window(dataset_id, "ctd", time_start, time_end, hours_back=hours_back),
        _load_bundle_window(
            dataset_id,
            "dashboard",
            mission_time_start,
            mission_time_end,
            hours_back=mission_hours_back,
        ),
    )
    # Results are already window-sliced by the overage service; re-slice for safety.
    dashboard = slice_processed_df(
        dash_raw if dash_raw is not None else pd.DataFrame(),
        hours_back=hours_back,
        use_date_range=True,
        time_start_str=time_start,
        time_end_str=time_end,
    )
    ctd = slice_processed_df(
        ctd_raw if ctd_raw is not None else pd.DataFrame(),
        hours_back=hours_back,
        use_date_range=True,
        time_start_str=time_start,
        time_end_str=time_end,
    )
    mission_dashboard = slice_processed_df(
        mission_dash_raw if mission_dash_raw is not None else pd.DataFrame(),
        hours_back=mission_hours_back,
        use_date_range=True,
        time_start_str=mission_time_start,
        time_end_str=mission_time_end,
    )
    if mission_dashboard.empty and not dashboard.empty:
        mission_dashboard = dashboard
    return {
        "track": dashboard_df_to_track_df(dashboard),
        "mission_track": dashboard_df_to_track_df(mission_dashboard),
        "dashboard": dashboard,
        "mission_dashboard": mission_dashboard,
        "ctd": ctd,
    }


def load_slocum_goals_for_report(session: SQLModelSession, deployment_id: int) -> List[models.SlocumDeploymentGoal]:
    return list(
        session.exec(
            select(models.SlocumDeploymentGoal)
            .where(models.SlocumDeploymentGoal.deployment_id == deployment_id)
            .order_by(models.SlocumDeploymentGoal.created_at_utc)
        ).all()
    )


def load_slocum_notes_for_report(session: SQLModelSession, deployment_id: int) -> List[models.SlocumDeploymentNote]:
    return list(
        session.exec(
            select(models.SlocumDeploymentNote)
            .where(
                models.SlocumDeploymentNote.deployment_id == deployment_id,
                models.SlocumDeploymentNote.include_in_report == True,  # noqa: E712
            )
            .order_by(models.SlocumDeploymentNote.created_at_utc)
        ).all()
    )


def resolve_slocum_sensor_tracker_mission_code(dataset_id: str) -> Optional[str]:
    """Map ERDDAP dataset id to Sensor Tracker mission code ``m{N}``."""
    parsed = utils.parse_slocum_dataset_id(resolve_slocum_dataset_id(dataset_id))
    if not parsed:
        return None
    return f"m{parsed['deployment_number']}"


def load_slocum_sensor_tracker_deployment(
    session: SQLModelSession,
    dataset_id: str,
) -> Optional[models.SensorTrackerDeployment]:
    mission_code = resolve_slocum_sensor_tracker_mission_code(dataset_id)
    if not mission_code:
        return None
    return session.exec(
        select(models.SensorTrackerDeployment).where(
            models.SensorTrackerDeployment.mission_id == mission_code
        )
    ).first()


def normalize_slocum_track_for_report(track_df: pd.DataFrame) -> pd.DataFrame:
    """Normalize Slocum track columns to Wave Glider telemetry report shape.

    Output columns: ``latitude``, ``longitude``, ``lastLocationFix``, ``depth``.
    """
    if track_df is None or track_df.empty:
        return pd.DataFrame(columns=["latitude", "longitude", "lastLocationFix", "depth"])

    out = track_df.copy()
    rename: dict[str, str] = {}
    if "Latitude" in out.columns and "latitude" not in out.columns:
        rename["Latitude"] = "latitude"
    if "Longitude" in out.columns and "longitude" not in out.columns:
        rename["Longitude"] = "longitude"
    if "Timestamp" in out.columns and "lastLocationFix" not in out.columns:
        rename["Timestamp"] = "lastLocationFix"
    if "Depth" in out.columns and "depth" not in out.columns:
        rename["Depth"] = "depth"
    if "MDepth" in out.columns and "depth" not in out.columns and "Depth" not in out.columns:
        rename["MDepth"] = "depth"
    if rename:
        out = out.rename(columns=rename)

    required = ["latitude", "longitude", "lastLocationFix"]
    missing = [c for c in required if c not in out.columns]
    if missing:
        return pd.DataFrame(columns=["latitude", "longitude", "lastLocationFix", "depth"])

    out["lastLocationFix"] = utils.parse_timestamp_column(
        out["lastLocationFix"], errors="coerce", utc=True
    )
    out = out.dropna(subset=["latitude", "longitude", "lastLocationFix"])
    out = drop_null_island_rows(out, lat_col="latitude", lon_col="longitude")
    if "depth" not in out.columns:
        out["depth"] = pd.NA
    else:
        out["depth"] = pd.to_numeric(out["depth"], errors="coerce")
    return (
        out.loc[:, ["latitude", "longitude", "lastLocationFix", "depth"]]
        .sort_values("lastLocationFix")
        .reset_index(drop=True)
    )


def _numeric_stat_summary(series: pd.Series) -> Optional[dict]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    return {
        "avg": float(values.mean()),
        "min": float(values.min()),
        "max": float(values.max()),
    }


def resolve_battery_pack_label(deployment: Optional[models.SlocumDeployment]) -> Optional[str]:
    if deployment is None:
        return None
    refs = parse_checklist_reference_values(deployment.checklist_reference_values)
    pack_id = str(refs.get("battery_pack") or "").strip()
    if not pack_id:
        return None
    if pack_id in BATTERY_PACK_PRESETS:
        return str(BATTERY_PACK_PRESETS[pack_id].get("label") or pack_id)
    return pack_id


def compute_average_water_depth(
    *,
    dashboard_df: pd.DataFrame,
    telemetry_df: pd.DataFrame,
) -> Optional[dict[str, Any]]:
    """Prefer mean ``MWaterDepth``; else mean ETOPO 2022 depth at track fixes."""
    if not dashboard_df.empty and "MWaterDepth" in dashboard_df.columns:
        values = filter_valid_water_depth_m(dashboard_df["MWaterDepth"]).dropna()
        if not values.empty:
            return {"avg": float(values.mean()), "source": "m_water_depth"}

    if telemetry_df is None or telemetry_df.empty:
        return None
    track = telemetry_df.dropna(subset=["latitude", "longitude"]).copy()
    if track.empty:
        return None
    if len(track) > _ETOPO_WATER_DEPTH_MAX_SAMPLES:
        step = max(1, len(track) // _ETOPO_WATER_DEPTH_MAX_SAMPLES)
        track = track.iloc[::step].copy()

    lon_min = float(track["longitude"].min())
    lon_max = float(track["longitude"].max())
    lat_min = float(track["latitude"].min())
    lat_max = float(track["latitude"].max())
    pad = 0.05
    extent = [lon_min - pad, lon_max + pad, lat_min - pad, lat_max + pad]
    try:
        grid = fetch_etopo_bathymetry(extent)
    except Exception as exc:
        logger.warning("ETOPO average water depth fetch failed: %s", exc)
        grid = None
    if grid is None:
        return None

    depths: list[float] = []
    for _, row in track.iterrows():
        depth = sample_depth_m_from_grid(grid, float(row["latitude"]), float(row["longitude"]))
        if depth is not None and depth > 0:
            depths.append(float(depth))
    if not depths:
        return None
    return {"avg": float(sum(depths) / len(depths)), "source": "ETOPO 2022"}


def compute_slocum_report_summaries(
    *,
    telemetry_df: pd.DataFrame,
    mission_telemetry_df: pd.DataFrame,
    dashboard_df: pd.DataFrame,
    ctd_df: pd.DataFrame,
) -> dict[str, Any]:
    """Period KPIs for the Slocum weekly summary section."""
    telemetry_summary = calculate_telemetry_summary(telemetry_df)
    mission_telemetry_summary = calculate_telemetry_summary(mission_telemetry_df)

    battery_summary = None
    if not dashboard_df.empty and "MBattery" in dashboard_df.columns:
        battery_summary = _numeric_stat_summary(dashboard_df["MBattery"])

    water_depth_summary = compute_average_water_depth(
        dashboard_df=dashboard_df,
        telemetry_df=telemetry_df,
    )

    ctd_summary: dict[str, dict] = {}
    if not ctd_df.empty:
        for col, key in (
            ("Temperature", "Temperature"),
            ("Salinity", "Salinity"),
            ("Density", "Density"),
        ):
            if col in ctd_df.columns:
                stats = _numeric_stat_summary(ctd_df[col])
                if stats:
                    ctd_summary[key] = stats

    return {
        "telemetry": telemetry_summary,
        "mission_telemetry": mission_telemetry_summary,
        "water_depth": water_depth_summary,
        "battery": battery_summary,
        "ctd": ctd_summary,
    }


async def load_dmon_asc_payload_for_report(
    *,
    deployment: Optional[models.SlocumDeployment],
    start_date: date,
    end_date: date,
) -> Optional[dict[str, Any]]:
    """Return normalized ASC listing for the report window when DMON is enabled."""
    if deployment is None:
        return None
    cards = {c.lower() for c in parse_enabled_sensor_cards(deployment.enabled_sensor_cards)}
    if "dmon" not in cards:
        return None
    glider = (deployment.glider_name or "").strip()
    if not glider:
        return None

    window_start = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    window_end = datetime.combine(
        end_date, datetime.max.time().replace(microsecond=0), tzinfo=timezone.utc
    )
    # Ask SFMC from the report start (not only "now - hours") so early-window
    # files are included; paginate past the default 20-file page size.
    last_modified_after = window_start.strftime("%Y%m%d%H%M")
    try:
        from app.core.sfmc_client import fetch_dmon_asc_files

        entries = await fetch_dmon_asc_files(
            glider,
            last_modified_after=last_modified_after,
        )
    except Exception as exc:
        logger.warning("DMON ASC listing for weekly report failed: %s", exc)
        return {
            "files": [],
            "hours_since_last": None,
            "has_gap_over_16h": False,
            "file_count": 0,
            "summary": f"SFMC *.asc listing unavailable: {exc}",
        }
    return normalize_dmon_asc_files(
        entries,
        now=window_end,
        window_start=window_start,
    )


def load_dmon_review_for_report(
    *,
    deployment: Optional[models.SlocumDeployment],
    dataset_id: str,
    start_date: date,
    end_date: date,
) -> Optional[dict[str, Any]]:
    """Load and date-filter Robots4Whales review when DMON is enabled."""
    if deployment is None:
        return None
    cards = {c.lower() for c in parse_enabled_sensor_cards(deployment.enabled_sensor_cards)}
    if "dmon" not in cards:
        return None
    mission_key = (
        (deployment.mission_key if deployment else None)
        or resolved_slocum_mission_key(dataset_id)
        or ""
    )
    if not mission_key:
        return None
    cached = get_cached_dmon_review(mission_key)
    if not cached:
        return None
    filtered = filter_dmon_review(
        cached,
        start_date=start_date,
        end_date=end_date,
        recent_hours=None,
    )
    if deployment.robots4whales_url:
        filtered["source_url"] = deployment.robots4whales_url
        if isinstance(filtered.get("attribution"), dict):
            filtered["attribution"]["source_url"] = deployment.robots4whales_url
    return filtered


def _fig_to_image(fig: Any, *, max_width_pt: float) -> Image:
    buf = io.BytesIO()
    try:
        fig.savefig(buf, format="png", dpi=180, bbox_inches="tight", pad_inches=0.05, facecolor="white")
    finally:
        plt.close(fig)
    buf.seek(0)
    pil = PILImage.open(buf)
    px_w, px_h = pil.size
    aspect = px_h / max(px_w, 1)
    width_pt = max_width_pt
    height_pt = width_pt * aspect
    buf.seek(0)
    return Image(buf, width=width_pt, height=height_pt)


def _ctd_profile_chart_image(
    df: pd.DataFrame,
    *,
    value_col: str,
    title: str,
    cmap,
    colorbar_label: str,
    max_width_pt: float,
    water_depth_df: Optional[pd.DataFrame] = None,
) -> Optional[Image]:
    if df.empty or "Timestamp" not in df.columns or value_col not in df.columns:
        return None
    with report_pdf_rc_context():
        fig = plt.figure(figsize=(8.27, 3.8))
        plot_slocum_ctd_profile_for_report(
            fig,
            df,
            value_col=value_col,
            title=title,
            cmap=cmap,
            colorbar_label=colorbar_label,
            water_depth_df=water_depth_df,
        )
    return _fig_to_image(fig, max_width_pt=max_width_pt)


def write_slocum_weekly_pdf(
    *,
    dataset_id: str,
    data_frames: dict[str, pd.DataFrame],
    goals: Sequence[models.SlocumDeploymentGoal],
    notes: Sequence[models.SlocumDeploymentNote],
    start_date: date,
    end_date: date,
    output_path: Path,
    session: Optional[SQLModelSession] = None,
    deployment: Optional[models.SlocumDeployment] = None,
    sensor_tracker_deployment: Optional[models.SensorTrackerDeployment] = None,
    dmon_detection_counts: Optional[dict[str, int]] = None,
    dmon_review_payload: Optional[dict[str, Any]] = None,
    dmon_asc_payload: Optional[dict[str, Any]] = None,
) -> Path:
    styles = get_report_paragraph_styles()
    max_width = 180 * mm
    generated_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    date_range = f"{start_date.isoformat()} to {end_date.isoformat()}"

    telemetry_df = normalize_slocum_track_for_report(data_frames.get("track", pd.DataFrame()))
    mission_telemetry_df = normalize_slocum_track_for_report(
        data_frames.get("mission_track", data_frames.get("track", pd.DataFrame()))
    )
    dashboard_df = data_frames.get("dashboard", pd.DataFrame())
    ctd_df = data_frames.get("ctd", pd.DataFrame())
    summaries = compute_slocum_report_summaries(
        telemetry_df=telemetry_df,
        mission_telemetry_df=mission_telemetry_df,
        dashboard_df=dashboard_df,
        ctd_df=ctd_df,
    )
    battery_type = resolve_battery_pack_label(deployment)

    mission_code = resolve_slocum_sensor_tracker_mission_code(dataset_id) or dataset_id
    mission_title = (
        (sensor_tracker_deployment.title if sensor_tracker_deployment and sensor_tracker_deployment.title else None)
        or (deployment.name if deployment and deployment.name else None)
        or dataset_id
    )
    vehicle_name = (
        (sensor_tracker_deployment.platform_name if sensor_tracker_deployment else None)
        or (deployment.glider_name if deployment else None)
        or "Slocum Glider"
    )
    mission_header = f"{mission_title} · {dataset_id}"

    doc = WeeklyReportDocTemplate(
        str(output_path),
        mission_header=mission_header[:200],
        report_title="Slocum Weekly Mission Report",
        generated_utc=generated_utc,
        styles=styles,
    )

    story: list[Any] = []
    story.extend(
        build_platform_cover_flowables(
            title="Slocum Weekly Mission Report",
            platform_name="Slocum Glider",
            mission_id=dataset_id,
            mission_title=str(mission_title),
            date_range_str=date_range,
            generated_utc=generated_utc,
            logo_path=get_report_logo_path(),
        )
    )
    story.append(NextPageTemplate("portrait"))
    story.append(PageBreak())
    story.extend(sections.build_toc_intro())
    story.append(PageBreak())

    mission_blocks = mission_blocks_from_deployment(
        mission_id=mission_code,
        sensor_tracker_deployment=sensor_tracker_deployment,
        mission_goals=list(goals),
        vehicle_name=vehicle_name,
        source_path=dataset_id,
    )
    md_main = sections.build_mission_details_sections(mission_blocks[:2])
    md_pub = sections.build_mission_details_sections(mission_blocks[2:])
    if md_main or md_pub:
        story.append(Paragraph("Mission details", styles["Heading1"]))
        if md_main:
            story.extend(md_main)
        if md_pub:
            if md_main:
                story.append(PageBreak())
            story.extend(md_pub)
        story.append(PageBreak())

    if sensor_tracker_deployment and session is not None:
        blocks = load_instrument_blocks(session, mission_code)
        inst_flow = sections.build_instruments_page(blocks)
        if inst_flow:
            story.append(Paragraph("Glider instruments and sensors", styles["Heading1"]))
            story.extend(inst_flow)
            story.append(PageBreak())

    story.append(Paragraph("Mission summary statistics", styles["Heading1"]))
    story.extend(
        sections.build_slocum_summary(
            period_label=f"Report window · {date_range}",
            telemetry_summary=summaries["telemetry"],
            mission_telemetry_summary=summaries["mission_telemetry"],
            water_depth_summary=summaries["water_depth"],
            battery_summary=summaries["battery"],
            battery_type=battery_type,
            ctd_summary=summaries["ctd"],
            dmon_detection_counts=dmon_detection_counts,
            mission_goals=list(goals),
        )
    )
    story.append(PageBreak())

    note_annotations = build_mission_note_annotations(
        list(notes),
        telemetry_df,
        start_date=start_date,
        end_date=end_date,
    )
    telem_flow = sections.build_telemetry_section(
        telemetry_df,
        note_annotations,
        report_distance_km=float(summaries["telemetry"].get("total_distance_km", 0.0)),
        section_title="Telemetry",
        compact=False,
        keep_together=True,
        color_by="sfmc_sog",
    )
    if telem_flow:
        story.append(Paragraph("Telemetry", styles["Heading1"]))
        story.extend(telem_flow)
        story.append(PageBreak())

    notes_flow = sections.build_mission_notes_section(note_annotations)
    if notes_flow:
        story.extend(notes_flow)
        story.append(PageBreak())
    elif notes:
        # Notes flagged for report but none snapped into the window / track.
        story.append(Paragraph("Mission notes", styles["Heading2"]))
        story.append(
            Paragraph(
                "Notes flagged for the report could not be matched to track fixes in this window.",
                styles["Body"],
            )
        )
        story.append(PageBreak())

    mission_dashboard_df = data_frames.get("mission_dashboard", pd.DataFrame())
    if mission_dashboard_df.empty:
        mission_dashboard_df = dashboard_df
    battery_ctx = build_battery_report_context(
        period_dashboard=dashboard_df,
        mission_dashboard=mission_dashboard_df,
        checklist_reference_values=(
            deployment.checklist_reference_values if deployment is not None else None
        ),
    )
    battery_flow = sections.build_slocum_battery_section(
        battery_ctx,
        period_label=f"Report window · {date_range}",
    )
    if battery_flow:
        story.append(Paragraph("Battery", styles["Heading1"]))
        story.extend(battery_flow)
        story.append(PageBreak())

    ctd_charts: list[Any] = []
    water_depth_df = pd.DataFrame()
    if not dashboard_df.empty and "Timestamp" in dashboard_df.columns and "MWaterDepth" in dashboard_df.columns:
        water_depth_df = dashboard_df[["Timestamp", "MWaterDepth"]].copy()
    for value_col, title, cmap, cbar_label in (
        ("Temperature", "CTD temperature", cmo.thermal, "Temperature (°C)"),
        ("Salinity", "CTD salinity", cmo.haline, "Salinity (PSU)"),
        ("Density", "CTD density", cmo.dense, "Density (kg/m³)"),
    ):
        img = _ctd_profile_chart_image(
            ctd_df,
            value_col=value_col,
            title=title,
            cmap=cmap,
            colorbar_label=cbar_label,
            max_width_pt=max_width,
            water_depth_df=water_depth_df if not water_depth_df.empty else None,
        )
        if img:
            ctd_charts.append(Paragraph(title, styles["Heading3"]))
            ctd_charts.append(img)
            ctd_charts.append(Spacer(1, 8))

    if ctd_charts:
        story.append(Paragraph("CTD sensors", styles["Heading1"]))
        story.extend(ctd_charts)

    # Robots4Whales DMON analyst-review detections + ASC offload accounting.
    if dmon_review_payload:
        dmon_flow = sections.build_dmon_review_section(
            dmon_review_payload,
            period_label=f"Report window · {date_range}",
            asc_payload=dmon_asc_payload,
        )
        if dmon_flow:
            if ctd_charts:
                story.append(PageBreak())
            story.extend(dmon_flow)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.multiBuild(story)
    return output_path


async def create_and_save_slocum_weekly_report(dataset_id: str, session: SQLModelSession) -> Optional[str]:
    dataset_id = resolve_slocum_dataset_id(dataset_id)
    start_date, end_date = default_slocum_weekly_date_window()
    deployment = get_or_create_deployment_for_dataset(
        session,
        dataset_id,
        created_by_username="system",
    )
    mission_start = resolve_mission_track_start_date(
        dataset_id=dataset_id,
        deployment=deployment,
        period_start=start_date,
    )
    data_frames = await load_slocum_report_dataframes(
        dataset_id,
        start_date,
        end_date,
        mission_start_date=mission_start,
    )
    if all(
        df.empty
        for key, df in data_frames.items()
        if key in ("track", "dashboard", "ctd")
    ):
        logger.warning("No Slocum report data for dataset %s", dataset_id)
        return None

    deployment_id = deployment.id if deployment else 0
    goals = load_slocum_goals_for_report(session, deployment_id) if deployment_id else []
    notes = load_slocum_notes_for_report(session, deployment_id) if deployment_id else []
    sensor_tracker_deployment = load_slocum_sensor_tracker_deployment(session, dataset_id)
    dmon_review_payload = None
    try:
        dmon_review_payload = load_dmon_review_for_report(
            deployment=deployment,
            dataset_id=dataset_id,
            start_date=start_date,
            end_date=end_date,
        )
    except Exception as exc:
        logger.warning("Slocum weekly PDF: DMON review load skipped: %s", exc)
    dmon_detection_counts = (
        count_dmon_confirmed_detections(dmon_review_payload) if dmon_review_payload else None
    )
    dmon_asc_payload = await load_dmon_asc_payload_for_report(
        deployment=deployment,
        start_date=start_date,
        end_date=end_date,
    )

    mission_key = resolved_slocum_mission_key(dataset_id)
    safe_id = mission_key.replace("/", "_").replace("\\", "_")
    report_dir = REPORTS_ROOT / "slocum" / safe_id
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    filename = f"weekly_report_{safe_id}_{timestamp}.pdf"
    output_path = report_dir / filename
    write_slocum_weekly_pdf(
        dataset_id=dataset_id,
        data_frames=data_frames,
        goals=goals,
        notes=notes,
        start_date=start_date,
        end_date=end_date,
        output_path=output_path,
        session=session,
        deployment=deployment,
        sensor_tracker_deployment=sensor_tracker_deployment,
        dmon_detection_counts=dmon_detection_counts,
        dmon_review_payload=dmon_review_payload,
        dmon_asc_payload=dmon_asc_payload,
    )
    report_url = f"/static/mission_reports/slocum/{safe_id}/{filename}"
    if deployment is not None:
        deployment.weekly_report_url = report_url
        deployment.updated_at_utc = datetime.now(timezone.utc)
        session.add(deployment)
        session.commit()
        session.refresh(deployment)
    return report_url
