"""
Wave Glider lifetime mission aggregates (distance, observed max power).

Leader sync refreshes these from trusted synced CSVs so dashboards can use
bounded recent windows for cards/charts while still showing mission totals.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence, Tuple

import pandas as pd
from sqlmodel import Session

from app.core.data import summaries as core_summaries
from app.core.data.data_service import resolve_synced_mission_dir
from app.core.data.loaders import load_report
from app.core.data.processors import preprocess_power_df, preprocess_telemetry_df
from app.core.infra.db import sqlite_engine
from app.core.infra.logging_config import get_request_id
from app.core.models.database import WaveGliderMissionMetrics

logger = logging.getLogger(__name__)

CALCULATION_VERSION = 1
METRIC_REPORT_TYPES = frozenset({"telemetry", "power"})


def compute_total_distance_nm(
    df: Optional[pd.DataFrame],
) -> Tuple[Optional[float], Optional[str]]:
    """
    Prefer vehicle incremental odometer; else great-circle track length.

    Returns ``(nm, method)`` where method is ``odometer`` or ``great_circle``.
    """
    if df is None or df.empty:
        return None, None
    try:
        processed = preprocess_telemetry_df(df)
    except Exception as exc:
        logger.warning("Mission metrics: telemetry preprocess failed: %s", exc)
        return None, None
    if processed is None or processed.empty:
        return None, None

    if "Timestamp" in processed.columns:
        processed = (
            processed.dropna(subset=["Timestamp"])
            .sort_values("Timestamp")
            .drop_duplicates(subset=["Timestamp"], keep="last")
        )

    incremental = core_summaries._incremental_odometer_nm(processed)
    if incremental is not None:
        return float(incremental), "odometer"
    track = core_summaries._track_length_nautical_miles(processed)
    if track is not None:
        return float(track), "great_circle"
    return None, None


def compute_observed_max_battery_wh(
    df: Optional[pd.DataFrame],
) -> Optional[float]:
    """Mission peak BatteryWattHours from a power DataFrame."""
    if df is None or df.empty:
        return None
    try:
        processed = preprocess_power_df(df)
    except Exception as exc:
        logger.warning("Mission metrics: power preprocess failed: %s", exc)
        return None
    if processed is None or processed.empty:
        return None
    if "BatteryWattHours" not in processed.columns:
        return None
    series = pd.to_numeric(processed["BatteryWattHours"], errors="coerce")
    series = series[series.notna() & (series > 0)]
    if series.empty:
        return None
    return float(series.max())


def _extract_data_through_ts(df: Optional[pd.DataFrame]) -> Optional[datetime]:
    if df is None or df.empty or "Timestamp" not in df.columns:
        return None
    try:
        processed = df
        if not pd.api.types.is_datetime64_any_dtype(processed["Timestamp"]):
            processed = processed.copy()
            processed["Timestamp"] = pd.to_datetime(processed["Timestamp"], utc=True, errors="coerce")
        max_ts = processed["Timestamp"].max()
        if pd.isna(max_ts):
            return None
        ts = pd.Timestamp(max_ts).to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except Exception:
        return None


def _mtime_unchanged(
    stored: Optional[datetime],
    current: Optional[datetime],
) -> bool:
    if stored is None or current is None:
        return False
    # Compare at second resolution (filesystem / header precision).
    return abs((stored - current).total_seconds()) < 1.0


async def _load_synced_report(
    report_type: str,
    mission_id: str,
) -> Tuple[Optional[pd.DataFrame], Optional[datetime], Optional[str]]:
    mission_dir = resolve_synced_mission_dir(mission_id)
    if mission_dir is None:
        return None, None, None
    from app.config import settings

    base = settings.local_data_base_path.resolve()
    folder_name = mission_dir.name
    try:
        df, file_mtime = await load_report(report_type, folder_name, base_path=base)
        if df is None or df.empty:
            return None, file_mtime, str(mission_dir)
        return df, file_mtime, str(mission_dir)
    except FileNotFoundError:
        return None, None, str(mission_dir)
    except Exception as exc:
        logger.warning(
            "Mission metrics: failed loading synced %s for %s: %s",
            report_type,
            mission_id,
            exc,
        )
        return None, None, str(mission_dir)


def get_mission_metrics(
    session: Session,
    mission_id: str,
) -> Optional[WaveGliderMissionMetrics]:
    if not mission_id:
        return None
    return session.get(WaveGliderMissionMetrics, mission_id)


def ensure_mission_metrics_row(
    session: Session,
    mission_id: str,
) -> WaveGliderMissionMetrics:
    row = session.get(WaveGliderMissionMetrics, mission_id)
    if row is not None:
        return row
    row = WaveGliderMissionMetrics(mission_id=mission_id)
    session.add(row)
    session.flush()
    return row


async def refresh_mission_metrics_for_reports(
    mission_id: str,
    report_types: Optional[Sequence[str]] = None,
    *,
    session: Optional[Session] = None,
    force: bool = False,
) -> WaveGliderMissionMetrics:
    """
    Recompute lifetime metrics from synced CSVs when mtime or formula version changed.

    Telemetry and power fields update independently. Safe to call after sync or as
    a one-time lazy bootstrap when a snapshot row is missing.
    """
    types = [
        rt
        for rt in (report_types or sorted(METRIC_REPORT_TYPES))
        if rt in METRIC_REPORT_TYPES
    ]
    owns_session = session is None
    if owns_session:
        session = Session(sqlite_engine)

    started = time.monotonic()
    try:
        row = ensure_mission_metrics_row(session, mission_id)
        needs_version_rebuild = (row.calculation_version or 0) < CALCULATION_VERSION

        if "telemetry" in types:
            await _refresh_telemetry_metrics(
                session, row, mission_id, force=force or needs_version_rebuild
            )
        if "power" in types:
            await _refresh_power_metrics(
                session, row, mission_id, force=force or needs_version_rebuild
            )

        row.calculation_version = CALCULATION_VERSION
        row.computed_at_utc = datetime.now(timezone.utc)
        session.add(row)
        session.commit()
        session.refresh(row)
        logger.info(
            "WG_MISSION_METRICS mission=%s reports=%s duration=%.2fs "
            "distance_nm=%s method=%s max_wh=%s pid=%s request_id=%s",
            mission_id,
            ",".join(types),
            time.monotonic() - started,
            row.total_distance_nm,
            row.distance_method,
            row.observed_max_battery_wh,
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


async def _refresh_telemetry_metrics(
    session: Session,
    row: WaveGliderMissionMetrics,
    mission_id: str,
    *,
    force: bool,
) -> None:
    df, file_mtime, _path = await _load_synced_report("telemetry", mission_id)
    if df is None:
        return
    if (
        not force
        and row.total_distance_nm is not None
        and _mtime_unchanged(row.telemetry_source_mtime, file_mtime)
    ):
        return

    distance_nm, method = compute_total_distance_nm(df)
    # Prefer processed timestamps when available.
    try:
        processed = preprocess_telemetry_df(df)
        data_through = _extract_data_through_ts(processed)
    except Exception:
        data_through = _extract_data_through_ts(df)

    row.total_distance_nm = distance_nm
    row.distance_method = method
    row.telemetry_data_through_ts = data_through
    row.telemetry_source_mtime = file_mtime
    session.add(row)


async def _refresh_power_metrics(
    session: Session,
    row: WaveGliderMissionMetrics,
    mission_id: str,
    *,
    force: bool,
) -> None:
    df, file_mtime, _path = await _load_synced_report("power", mission_id)
    if df is None:
        return
    if (
        not force
        and row.observed_max_battery_wh is not None
        and _mtime_unchanged(row.power_source_mtime, file_mtime)
    ):
        return

    max_wh = compute_observed_max_battery_wh(df)
    try:
        processed = preprocess_power_df(df)
        data_through = _extract_data_through_ts(processed)
    except Exception:
        data_through = _extract_data_through_ts(df)

    row.observed_max_battery_wh = max_wh
    row.power_data_through_ts = data_through
    row.power_source_mtime = file_mtime
    session.add(row)


async def bootstrap_mission_metrics_if_needed(
    session: Session,
    mission_id: str,
) -> Optional[WaveGliderMissionMetrics]:
    """
    One-time lazy bootstrap when a dashboard needs lifetime totals and none exist.

    Does not re-parse on every request once a row is present.
    """
    existing = get_mission_metrics(session, mission_id)
    if existing is not None and (
        existing.total_distance_nm is not None or existing.observed_max_battery_wh is not None
    ):
        return existing
    if existing is not None and existing.calculation_version >= CALCULATION_VERSION:
        # Row exists but both metrics null (no synced files yet) — avoid repeated full parses.
        if existing.telemetry_source_mtime is not None or existing.power_source_mtime is not None:
            return existing
    try:
        return await refresh_mission_metrics_for_reports(
            mission_id, session=session, force=True
        )
    except Exception as exc:
        logger.warning(
            "WG_MISSION_METRICS_BOOTSTRAP_FAIL mission=%s err=%s",
            mission_id,
            exc,
        )
        return get_mission_metrics(session, mission_id)


async def refresh_after_sync(
    mission_id: str,
    report_types: Iterable[str],
) -> None:
    """Hook for sync_service: refresh only metric-relevant report types."""
    relevant = [rt for rt in report_types if rt in METRIC_REPORT_TYPES]
    if not relevant:
        # Still bootstrap missing snapshots after a full mission sync that
        # may have skipped telemetry/power only because they were up-to-date.
        with Session(sqlite_engine) as session:
            existing = get_mission_metrics(session, mission_id)
            if existing is None:
                relevant = list(METRIC_REPORT_TYPES)
            else:
                return
    try:
        await refresh_mission_metrics_for_reports(mission_id, relevant)
    except Exception as exc:
        logger.warning(
            "WG_MISSION_METRICS_SYNC_HOOK_FAIL mission=%s reports=%s err=%s",
            mission_id,
            relevant,
            exc,
        )
