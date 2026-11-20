"""Audit offload_logs mission attribution against WG-VM4 sessions per mission folder."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

import pandas as pd
from sqlmodel import select

from app.config import settings
from app.core import models, utils
from app.core.data.data_service import resolve_synced_mission_dir
from app.core.data.processors import preprocess_wg_vm4_info_df
from app.core.infra.db import SQLModelSession
from app.core.offload_comments import (
    apply_mission_id_to_offload_log,
    is_station_offload_sheet_session_ref,
    mission_id_from_offload_log,
)
from app.core.stations.vrl_filename import log_reference_timestamp
from app.core.stations.wg_vm4_payload_parser import parse_wg_vm4_info_data
from app.core.stations.wg_vm4_station_service import (
    WgVm4StationService,
    _find_matching_log_for_enrichment,
    _normalize_utc_timestamp,
)

logger = logging.getLogger(__name__)

VM4_INFO_FILENAME = "Vemco VM4 Information.csv"
DEFAULT_MATCH_WINDOW_MINUTES = 30

APPLYABLE_REASONS = frozenset({"mission_mismatch", "mission_missing"})


@dataclass(frozen=True)
class MissionAuditFinding:
    expected_mission_id: str
    reason: str
    station_id: Optional[str]
    log_id: Optional[int]
    actual_mission_id: Optional[str]
    vrl_file_name: Optional[str]
    was_offloaded: Optional[bool]
    session_ref_utc: Optional[str]
    log_ref_utc: Optional[str]
    serial_number: Optional[str]
    can_apply: bool
    parser_session_ref: Optional[str] = None
    created_by_source: Optional[str] = None

    def as_dict(self) -> dict:
        return asdict(self)


def list_local_vm4_mission_ids() -> list[str]:
    """Mission folder names under local_data_base_path that have VM4 info CSV."""
    base = settings.local_data_base_path
    if not base.is_dir():
        return []
    results: list[str] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        if (child / VM4_INFO_FILENAME).is_file():
            results.append(child.name)
    return results


def load_vm4_info_dataframe(mission_id: str) -> Optional[pd.DataFrame]:
    """Load and preprocess VM4 info CSV for a mission folder (sync)."""
    mission_dir = resolve_synced_mission_dir(mission_id)
    if mission_dir is None:
        logger.warning("No synced mission dir for %s", mission_id)
        return None
    path = mission_dir / VM4_INFO_FILENAME
    if not path.is_file():
        logger.warning("No %s under %s", VM4_INFO_FILENAME, mission_dir)
        return None
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        logger.warning("Failed reading %s: %s", path, exc)
        return None
    return preprocess_wg_vm4_info_df(df)


def _alias_set(mission_id: Optional[str]) -> set[str]:
    if not mission_id:
        return set()
    return {a.lower() for a in utils.mission_ids_for_offload_parser_trace_matching(mission_id)}


def missions_compatible(expected: str, actual: Optional[str]) -> bool:
    """True when actual is empty-incompatible or shares an alias with expected."""
    if not actual:
        return False
    return bool(_alias_set(expected) & _alias_set(actual))


def _can_rewrite_mission_ref(log: Any) -> bool:
    ref = (getattr(log, "parser_session_ref", None) or "").strip()
    return (not ref) or is_station_offload_sheet_session_ref(ref)


def _offload_sort_key(log: models.OffloadLog) -> datetime:
    ts = log.offload_end_time_utc or log.offload_start_time_utc or log.log_timestamp_utc
    if ts is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def classify_matched_log(
    *,
    expected_mission_id: str,
    log: Any,
    session_payload: dict,
    reference_ts: datetime,
) -> list[MissionAuditFinding]:
    """
    Classify a time-matched log against the expected mission folder.

    May return multiple findings (e.g. mission_mismatch + failed_with_vrl).
    """
    station_id = str(getattr(log, "station_id"))
    actual = mission_id_from_offload_log(log)
    vrl = session_payload.get("vrl_file_name") or getattr(log, "vrl_file_name", None)
    vrl_name = str(vrl).strip() if vrl else None
    was_offloaded = getattr(log, "was_offloaded", None)
    log_ts = log_reference_timestamp(log)
    ref = (getattr(log, "parser_session_ref", None) or "").strip() or None
    can_rewrite = _can_rewrite_mission_ref(log)
    findings: list[MissionAuditFinding] = []

    def _row(reason: str, *, can_apply: bool) -> MissionAuditFinding:
        return MissionAuditFinding(
            expected_mission_id=expected_mission_id,
            reason=reason,
            station_id=station_id,
            log_id=int(getattr(log, "id")) if getattr(log, "id", None) is not None else None,
            actual_mission_id=actual,
            vrl_file_name=vrl_name,
            was_offloaded=was_offloaded,
            session_ref_utc=reference_ts.isoformat(),
            log_ref_utc=log_ts.isoformat() if log_ts else None,
            serial_number=str(session_payload.get("serial_number") or "").strip() or None,
            can_apply=can_apply,
            parser_session_ref=ref,
            created_by_source=getattr(log, "created_by_source", None),
        )

    if missions_compatible(expected_mission_id, actual):
        pass
    elif not actual:
        findings.append(_row("mission_missing", can_apply=can_rewrite))
    elif not can_rewrite:
        findings.append(_row("locked_parser_ref", can_apply=False))
    else:
        findings.append(_row("mission_mismatch", can_apply=True))

    if was_offloaded is False and vrl_name:
        findings.append(_row("failed_with_vrl", can_apply=False))

    return findings


def audit_mission_vm4_sessions(
    session: SQLModelSession,
    expected_mission_id: str,
    *,
    station_id: Optional[str] = None,
    time_window_minutes: int = DEFAULT_MATCH_WINDOW_MINUTES,
    vm4_df: Optional[pd.DataFrame] = None,
) -> list[MissionAuditFinding]:
    """
    Parse VM4 sessions for ``expected_mission_id`` and compare matched logs' mission IDs.
    """
    df = vm4_df if vm4_df is not None else load_vm4_info_dataframe(expected_mission_id)
    if df is None or df.empty:
        return []

    _events, sessions = parse_wg_vm4_info_data(df)
    service = WgVm4StationService(session)
    findings: list[MissionAuditFinding] = []

    for session_payload in sessions:
        vrl_file_name = session_payload.get("vrl_file_name")
        if not vrl_file_name or not str(vrl_file_name).strip():
            continue

        serial = str(session_payload.get("serial_number", "")).strip()
        reference_ts = _normalize_utc_timestamp(
            session_payload.get("end_time") or session_payload.get("start_time")
        )
        if not serial or reference_ts is None:
            findings.append(
                MissionAuditFinding(
                    expected_mission_id=expected_mission_id,
                    reason="no_matching_log",
                    station_id=None,
                    log_id=None,
                    actual_mission_id=None,
                    vrl_file_name=str(vrl_file_name).strip(),
                    was_offloaded=None,
                    session_ref_utc=None,
                    log_ref_utc=None,
                    serial_number=serial or None,
                    can_apply=False,
                )
            )
            continue

        station = service.find_station_by_serial(serial)
        if not station:
            # When auditing one station, skip unrelated/unknown serials.
            if station_id:
                continue
            findings.append(
                MissionAuditFinding(
                    expected_mission_id=expected_mission_id,
                    reason="no_station",
                    station_id=None,
                    log_id=None,
                    actual_mission_id=None,
                    vrl_file_name=str(vrl_file_name).strip(),
                    was_offloaded=None,
                    session_ref_utc=reference_ts.isoformat(),
                    log_ref_utc=None,
                    serial_number=serial,
                    can_apply=False,
                )
            )
            continue

        if station_id and station.station_id != station_id:
            continue

        start_window = reference_ts - timedelta(minutes=time_window_minutes)
        end_window = reference_ts + timedelta(minutes=time_window_minutes)
        log = _find_matching_log_for_enrichment(
            session=session,
            station_id=station.station_id,
            reference_ts=reference_ts,
            start_window=start_window,
            end_window=end_window,
            prefer_blank_vrl=False,
        )
        if not log:
            findings.append(
                MissionAuditFinding(
                    expected_mission_id=expected_mission_id,
                    reason="no_matching_log",
                    station_id=station.station_id,
                    log_id=None,
                    actual_mission_id=None,
                    vrl_file_name=str(vrl_file_name).strip(),
                    was_offloaded=None,
                    session_ref_utc=reference_ts.isoformat(),
                    log_ref_utc=None,
                    serial_number=serial,
                    can_apply=False,
                )
            )
            continue

        findings.extend(
            classify_matched_log(
                expected_mission_id=expected_mission_id,
                log=log,
                session_payload=session_payload,
                reference_ts=reference_ts,
            )
        )

    return findings


def audit_missions(
    session: SQLModelSession,
    mission_ids: Iterable[str],
    *,
    station_id: Optional[str] = None,
    time_window_minutes: int = DEFAULT_MATCH_WINDOW_MINUTES,
) -> list[MissionAuditFinding]:
    """Run mission audit for multiple mission folders; dedupe by (log_id, reason, expected)."""
    all_findings: list[MissionAuditFinding] = []
    for mid in mission_ids:
        mid = (mid or "").strip()
        if not mid:
            continue
        all_findings.extend(
            audit_mission_vm4_sessions(
                session,
                mid,
                station_id=station_id,
                time_window_minutes=time_window_minutes,
            )
        )

    seen: set[tuple] = set()
    unique: list[MissionAuditFinding] = []
    for row in all_findings:
        key = (row.expected_mission_id, row.log_id, row.reason, row.serial_number, row.session_ref_utc)
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    unique.sort(
        key=lambda r: (
            r.reason,
            r.station_id or "",
            r.log_id or 0,
            r.expected_mission_id,
        )
    )
    return unique


def apply_mission_audit_fixes(
    session: SQLModelSession,
    findings: Iterable[MissionAuditFinding],
    *,
    reasons: Optional[set[str]] = None,
) -> dict[str, Any]:
    """
    Rewrite blank/sheet mission refs for applyable findings.

    Syncs station ``last_offload_by_glider`` when the corrected log is the latest attempt.
    """
    allowed = reasons if reasons is not None else set(APPLYABLE_REASONS)
    now = datetime.now(timezone.utc)
    updated = 0
    skipped = 0
    stations: set[str] = set()

    for row in findings:
        if row.reason not in allowed or not row.can_apply or row.log_id is None:
            skipped += 1
            continue
        log = session.get(models.OffloadLog, row.log_id)
        if not log or log.station_id != row.station_id:
            skipped += 1
            continue
        if not _can_rewrite_mission_ref(log):
            skipped += 1
            continue

        before = mission_id_from_offload_log(log)
        apply_mission_id_to_offload_log(
            log,
            row.expected_mission_id,
            station_id=log.station_id,
        )
        note = (
            f"[MISSION_AUDIT_SET {now.isoformat()}] "
            f"expected={row.expected_mission_id!r} previous={before!r} reason={row.reason}"
        )
        existing = (log.parser_notes or "").strip()
        log.parser_notes = f"{existing}\n{note}".strip() if existing else note
        log.updated_by_source = "mission_audit"
        log.updated_at_utc = now
        session.add(log)

        all_logs = list(
            session.exec(
                select(models.OffloadLog).where(
                    models.OffloadLog.station_id == log.station_id
                )
            ).all()
        )
        if all_logs:
            latest = max(all_logs, key=_offload_sort_key)
            if latest.id == log.id:
                station = session.get(models.StationMetadata, log.station_id)
                if station:
                    station.last_offload_by_glider = row.expected_mission_id
                    session.add(station)

        updated += 1
        stations.add(log.station_id)

    if updated:
        session.commit()
    return {"updated": updated, "skipped": skipped, "stations": sorted(stations)}
