"""Slocum glider weekly PDF report generation."""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional, Sequence

import matplotlib.pyplot as plt
import pandas as pd
from PIL import Image as PILImage
from reportlab.lib.units import mm
from reportlab.platypus import Image, NextPageTemplate, PageBreak, Paragraph, Spacer
from sqlmodel import Session as SQLModelSession, select

from .. import models, utils
from ..geo.coordinates import drop_null_island_rows
from ..plotting import report_pdf_rc_context
from ..slocum_cache_service import get_cached_or_fetch_bundle_df, slice_processed_df
from ..slocum_deployment_service import get_or_create_deployment_for_dataset
from ..slocum_mirror_service import dashboard_df_to_track_df
from ..slocum_overage_cache import OverageResult
from ..utils import slocum_mission_key
from . import sections
from .builder import (
    build_mission_note_annotations,
    calculate_telemetry_summary,
    load_instrument_blocks,
    mission_blocks_from_deployment,
)
from .common import build_platform_cover_flowables, get_report_logo_path, get_report_paragraph_styles
from .constants import REPORTS_ROOT
from .styling import WeeklyReportDocTemplate

logger = logging.getLogger(__name__)

SLOCUM_WEEKLY_REPORT_VARIABLE_GROUPS = {
    "track": ["time", "latitude", "longitude", "depth"],
    "dashboard": None,
    "ctd": None,
}


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


async def load_slocum_report_dataframes(
    dataset_id: str,
    start_date: date,
    end_date: date,
) -> dict[str, pd.DataFrame]:
    time_start, time_end = _iso_window(start_date, end_date)
    hours_back = max(1, int((end_date - start_date).total_seconds() / 3600) + 24)

    async def _load(bundle: str) -> pd.DataFrame:
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

    dash_raw, ctd_raw = await asyncio.gather(_load("dashboard"), _load("ctd"))
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
    return {
        "track": dashboard_df_to_track_df(dashboard),
        "dashboard": dashboard,
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
    parsed = utils.parse_slocum_dataset_id(dataset_id)
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


def compute_slocum_report_summaries(
    *,
    telemetry_df: pd.DataFrame,
    dashboard_df: pd.DataFrame,
    ctd_df: pd.DataFrame,
) -> dict[str, Any]:
    """Period KPIs for the Slocum weekly summary section."""
    telemetry_summary = calculate_telemetry_summary(telemetry_df)

    depth_summary = None
    if not telemetry_df.empty and "depth" in telemetry_df.columns:
        depth_summary = _numeric_stat_summary(telemetry_df["depth"])
    elif not dashboard_df.empty and "MDepth" in dashboard_df.columns:
        depth_summary = _numeric_stat_summary(dashboard_df["MDepth"])

    battery_summary = None
    if not dashboard_df.empty and "MBattery" in dashboard_df.columns:
        battery_summary = _numeric_stat_summary(dashboard_df["MBattery"])

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
        "depth": depth_summary,
        "battery": battery_summary,
        "ctd": ctd_summary,
    }


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


def _line_chart_image(df: pd.DataFrame, y_col: str, title: str, *, max_width_pt: float) -> Optional[Image]:
    if df.empty or "Timestamp" not in df.columns or y_col not in df.columns:
        return None
    series = df.set_index("Timestamp")[y_col].astype(float).dropna()
    if series.empty:
        return None
    with report_pdf_rc_context():
        fig, ax = plt.subplots(figsize=(8.27, 3.5))
        ax.plot(series.index, series.values, linewidth=1.2)
        ax.set_title(title)
        ax.grid(True, alpha=0.3)
        fig.autofmt_xdate()
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
) -> Path:
    styles = get_report_paragraph_styles()
    max_width = 180 * mm
    generated_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    date_range = f"{start_date.isoformat()} to {end_date.isoformat()}"

    telemetry_df = normalize_slocum_track_for_report(data_frames.get("track", pd.DataFrame()))
    dashboard_df = data_frames.get("dashboard", pd.DataFrame())
    ctd_df = data_frames.get("ctd", pd.DataFrame())
    summaries = compute_slocum_report_summaries(
        telemetry_df=telemetry_df,
        dashboard_df=dashboard_df,
        ctd_df=ctd_df,
    )

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
            depth_summary=summaries["depth"],
            battery_summary=summaries["battery"],
            ctd_summary=summaries["ctd"],
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
        color_by="depth",
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

    dash_charts: list[Any] = []
    for y_col, title in (
        ("MDepth", "Measured depth (m)"),
        ("MAltitude", "Altitude (m)"),
        ("MBattery", "Battery (V)"),
        ("CPitch", "Commanded pitch (deg)"),
    ):
        img = _line_chart_image(dashboard_df, y_col, title, max_width_pt=max_width)
        if img:
            dash_charts.append(Paragraph(title, styles["Heading3"]))
            dash_charts.append(img)
            dash_charts.append(Spacer(1, 8))

    ctd_charts: list[Any] = []
    for y_col, title in (
        ("Temperature", "CTD temperature"),
        ("Salinity", "CTD salinity"),
        ("Density", "CTD density"),
    ):
        img = _line_chart_image(ctd_df, y_col, title, max_width_pt=max_width)
        if img:
            ctd_charts.append(Paragraph(title, styles["Heading3"]))
            ctd_charts.append(img)
            ctd_charts.append(Spacer(1, 8))

    if dash_charts:
        story.append(Paragraph("Dashboard sensors", styles["Heading1"]))
        story.extend(dash_charts)
        if ctd_charts:
            story.append(PageBreak())
    if ctd_charts:
        story.append(Paragraph("CTD sensors", styles["Heading1"]))
        story.extend(ctd_charts)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc.multiBuild(story)
    return output_path


async def create_and_save_slocum_weekly_report(dataset_id: str, session: SQLModelSession) -> Optional[str]:
    start_date, end_date = default_slocum_weekly_date_window()
    data_frames = await load_slocum_report_dataframes(dataset_id, start_date, end_date)
    if all(df.empty for df in data_frames.values()):
        logger.warning("No Slocum report data for dataset %s", dataset_id)
        return None

    deployment = get_or_create_deployment_for_dataset(
        session,
        dataset_id,
        created_by_username="system",
    )
    deployment_id = deployment.id if deployment else 0
    goals = load_slocum_goals_for_report(session, deployment_id) if deployment_id else []
    notes = load_slocum_notes_for_report(session, deployment_id) if deployment_id else []
    sensor_tracker_deployment = load_slocum_sensor_tracker_deployment(session, dataset_id)

    mission_key = slocum_mission_key(dataset_id) or dataset_id
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
    )
    return f"/static/mission_reports/slocum/{safe_id}/{filename}"
