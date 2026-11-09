"""
Slocum lifetime mission aggregates (mission track distance).

Leader daily job and weekly-report builds refresh these from the authoritative
full-history dashboard track (overage/report context), never the 72h mirror alone.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

import pandas as pd
from sqlmodel import Session

from app.core.infra.db import sqlite_engine
from app.core.infra.logging_config import get_request_id
from app.core.mission_aliases import (
    resolve_slocum_dataset_id,
    resolved_slocum_mission_key,
)
from app.core.models.database import SlocumMissionMetrics
from app.core.reporting.builder import calculate_telemetry_summary
from app.platforms.slocum.deployment_service import resolve_deployment_for_dataset
from app.platforms.slocum.mirror_service import (
    dashboard_df_to_track_df,
    read_mirror_meta,
)

logger = logging.getLogger(__name__)

CALCULATION_VERSION = 1
DISTANCE_METHOD = "great_circle"


def compute_slocum_total_distance_km(track_df: Optional[pd.DataFrame]) -> Optional[float]:
    """Mission peak distance (km) from a normalized report track DataFrame."""
    if track_df is None or track_df.empty:
        return None
    summary = calculate_telemetry_summary(track_df)
    value = summary.get("total_distance_km")
    if value is None:
        return None
    try:
        km = float(value)
    except (TypeError, ValueError):
        return None
    if km < 0:
        return None
    return km


def _parse_iso_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        ts = pd.Timestamp(value)
        if pd.isna(ts):
            return None
        dt = ts.to_pydatetime()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _extract_track_through_ts(track_df: Optional[pd.DataFrame]) -> Optional[datetime]:
    if track_df is None or track_df.empty:
        return None
    col = "lastLocationFix" if "lastLocationFix" in track_df.columns else "Timestamp"
    if col not in track_df.columns:
        return None
    try:
        series = pd.to_datetime(track_df[col], utc=True, errors="coerce")
        max_ts = series.max()
        if pd.isna(max_ts):
            return None
        dt = pd.Timestamp(max_ts).to_pydatetime()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _mirror_dashboard_last_ts(dataset_id: str) -> Optional[datetime]:
    meta = read_mirror_meta(dataset_id)
    bundles = meta.get("bundles") if isinstance(meta, dict) else None
    if isinstance(bundles, dict):
        dash = bundles.get("dashboard") or {}
        if isinstance(dash, dict):
            parsed = _parse_iso_timestamp(dash.get("last_data_timestamp"))
            if parsed is not None:
                return parsed
    if isinstance(meta, dict):
        return _parse_iso_timestamp(meta.get("last_data_timestamp"))
    return None


def _timestamps_close(
    stored: Optional[datetime],
    current: Optional[datetime],
) -> bool:
    if stored is None or current is None:
        return False
    return abs((stored - current).total_seconds()) < 1.0


def get_mission_metrics(
    session: Session,
    mission_key: str,
) -> Optional[SlocumMissionMetrics]:
    if not mission_key:
        return None
    return session.get(SlocumMissionMetrics, mission_key)


def ensure_mission_metrics_row(
    session: Session,
    mission_key: str,
) -> SlocumMissionMetrics:
    row = session.get(SlocumMissionMetrics, mission_key)
    if row is not None:
        return row
    row = SlocumMissionMetrics(mission_key=mission_key)
    session.add(row)
    session.flush()
    return row


def upsert_from_track_frame(
    session: Session,
    *,
    mission_key: str,
    dataset_id: str,
    track_df: pd.DataFrame,
    dashboard_last_data_timestamp: Optional[datetime] = None,
) -> SlocumMissionMetrics:
    """
    Persist mission distance from an already-loaded full-history track frame.

    Used by weekly reports to avoid a second ERDDAP round-trip.
    """
    row = ensure_mission_metrics_row(session, mission_key)
    distance_km = compute_slocum_total_distance_km(track_df)
    row.total_distance_km = distance_km
    row.distance_method = DISTANCE_METHOD if distance_km is not None else None
    row.track_data_through_ts = _extract_track_through_ts(track_df)
    row.source_erddap_dataset_id = resolve_slocum_dataset_id(dataset_id)
    row.dashboard_last_data_timestamp = (
        dashboard_last_data_timestamp or _mirror_dashboard_last_ts(dataset_id)
    )
    row.calculation_version = CALCULATION_VERSION
    row.computed_at_utc = datetime.now(timezone.utc)
    session.add(row)
    session.commit()
    session.refresh(row)
    logger.info(
        "SLOCUM_MISSION_METRICS mission_key=%s dataset=%s distance_km=%s "
        "source=track_frame pid=%s request_id=%s",
        mission_key,
        row.source_erddap_dataset_id,
        row.total_distance_km,
        os.getpid(),
        get_request_id(),
    )
    return row


async def load_mission_track_dataframe(
    session: Session,
    dataset_id: str,
) -> pd.DataFrame:
    """Load the authoritative full-mission track via the report/overage path."""
    from app.platforms.slocum.reports import (
        load_slocum_report_dataframes,
        normalize_slocum_track_for_report,
        resolve_mission_track_start_date,
    )

    dataset_id = resolve_slocum_dataset_id(dataset_id)
    deployment = resolve_deployment_for_dataset(
        session, dataset_id, include_inactive=True, allow_create=False
    )
    end_date = datetime.now(timezone.utc).date()
    mission_start = resolve_mission_track_start_date(
        dataset_id=dataset_id,
        deployment=deployment,
        period_start=end_date - timedelta(days=7),
    )
    # Period window is unused for mission distance; load_slocum_report_dataframes
    # still needs a period range for the parallel period fetch.
    period_start = max(mission_start, end_date - timedelta(days=7))
    frames = await load_slocum_report_dataframes(
        dataset_id,
        period_start,
        end_date,
        mission_start_date=mission_start,
    )
    mission_track = frames.get("mission_track")
    if mission_track is None or mission_track.empty:
        mission_dash = frames.get("mission_dashboard")
        if mission_dash is not None and not mission_dash.empty:
            mission_track = dashboard_df_to_track_df(mission_dash)
    return normalize_slocum_track_for_report(
        mission_track if mission_track is not None else pd.DataFrame()
    )


async def refresh_slocum_mission_metrics(
    dataset_id: str,
    *,
    session: Optional[Session] = None,
    force: bool = False,
) -> Optional[SlocumMissionMetrics]:
    """
    Recompute mission distance when mirror tail, dataset identity, or formula version changed.
    """
    dataset_id = resolve_slocum_dataset_id(dataset_id)
    mission_key = resolved_slocum_mission_key(dataset_id)
    if not mission_key:
        logger.warning("SLOCUM_MISSION_METRICS skip dataset=%s: no mission_key", dataset_id)
        return None

    owns_session = session is None
    if owns_session:
        session = Session(sqlite_engine)

    started = time.monotonic()
    try:
        row = ensure_mission_metrics_row(session, mission_key)
        mirror_tail = _mirror_dashboard_last_ts(dataset_id)
        needs_version = (row.calculation_version or 0) < CALCULATION_VERSION
        dataset_changed = (
            row.source_erddap_dataset_id is not None
            and row.source_erddap_dataset_id != dataset_id
        )
        if (
            not force
            and not needs_version
            and not dataset_changed
            and row.total_distance_km is not None
            and _timestamps_close(row.dashboard_last_data_timestamp, mirror_tail)
        ):
            logger.info(
                "SLOCUM_MISSION_METRICS mission_key=%s dataset=%s skipped=unchanged_tail "
                "distance_km=%s duration=%.2fs pid=%s request_id=%s",
                mission_key,
                dataset_id,
                row.total_distance_km,
                time.monotonic() - started,
                os.getpid(),
                get_request_id(),
            )
            return row

        track_df = await load_mission_track_dataframe(session, dataset_id)
        row = upsert_from_track_frame(
            session,
            mission_key=mission_key,
            dataset_id=dataset_id,
            track_df=track_df,
            dashboard_last_data_timestamp=mirror_tail,
        )
        logger.info(
            "SLOCUM_MISSION_METRICS mission_key=%s dataset=%s duration=%.2fs "
            "distance_km=%s pid=%s request_id=%s",
            mission_key,
            dataset_id,
            time.monotonic() - started,
            row.total_distance_km,
            os.getpid(),
            get_request_id(),
        )
        return row
    except Exception:
        session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


def resolve_slocum_mission_distance_km(
    session: Session,
    dataset_id: str,
) -> Optional[float]:
    """DB-only read of persisted mission distance for dashboard request paths."""
    mission_key = resolved_slocum_mission_key(dataset_id)
    if not mission_key:
        return None
    row = get_mission_metrics(session, mission_key)
    if row is None:
        return None
    return row.total_distance_km


async def refresh_active_slocum_mission_metrics(
    *,
    dataset_ids: Optional[Sequence[str]] = None,
) -> dict[str, int]:
    """Refresh metrics for active deployments sequentially (leader daily job)."""
    from app.core.mission_catalog.enablement import resolve_active_slocum_dataset_ids

    refreshed = 0
    skipped = 0
    errors = 0
    if dataset_ids is not None:
        ids = list(dataset_ids)
    else:
        with Session(sqlite_engine) as session:
            ids = list(resolve_active_slocum_dataset_ids(session))
    for dataset_id in ids:
        try:
            before = None
            with Session(sqlite_engine) as session:
                key = resolved_slocum_mission_key(dataset_id)
                if key:
                    before = get_mission_metrics(session, key)
                    before_ts = before.computed_at_utc if before else None
                else:
                    before_ts = None
            row = await refresh_slocum_mission_metrics(dataset_id, force=False)
            if row is None:
                skipped += 1
            elif before_ts is not None and row.computed_at_utc == before_ts:
                skipped += 1
            else:
                refreshed += 1
        except Exception as exc:
            errors += 1
            logger.warning(
                "SLOCUM_MISSION_METRICS_JOB_FAIL dataset=%s err=%s",
                dataset_id,
                exc,
            )
    return {"refreshed": refreshed, "skipped": skipped, "errors": errors, "total": len(ids)}


def compute_distance_24h_km_from_dashboard(
    dashboard_df: Optional[pd.DataFrame],
) -> Optional[float]:
    """Period distance from the latest 24h of a (mirror) dashboard frame."""
    if dashboard_df is None or dashboard_df.empty or "Timestamp" not in dashboard_df.columns:
        return None
    working = dashboard_df.copy()
    working["Timestamp"] = pd.to_datetime(working["Timestamp"], utc=True, errors="coerce")
    working = working.dropna(subset=["Timestamp"])
    if working.empty:
        return None
    last_ts = working["Timestamp"].max()
    window = working[working["Timestamp"] > (last_ts - pd.Timedelta(hours=24))]
    track = dashboard_df_to_track_df(window)
    from app.platforms.slocum.reports import normalize_slocum_track_for_report

    normalized = normalize_slocum_track_for_report(track)
    return compute_slocum_total_distance_km(normalized)
