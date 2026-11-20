"""Unit tests for offload mission-ID audit classification and apply helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pandas as pd
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from app.core.models.database import OffloadLog, StationMetadata
from app.core.offload_comments import STATION_OFFLOAD_SHEET_MARKER, mission_id_from_offload_log
from app.services.offload_mission_audit import (
    apply_mission_audit_fixes,
    audit_mission_vm4_sessions,
    classify_matched_log,
    missions_compatible,
)


def test_missions_compatible_aliases():
    assert missions_compatible("m227-SV3-1071", "m227-SV3-1071")
    assert missions_compatible("m227-SV3-1071", "m227")
    assert not missions_compatible("m227-SV3-1071", "m230-SV3-1070")
    assert not missions_compatible("m227-SV3-1071", None)


def test_classify_mismatch_and_failed_with_vrl():
    log = SimpleNamespace(
        id=853,
        station_id="HFX231",
        parser_session_ref=f"m230-SV3-1070{STATION_OFFLOAD_SHEET_MARKER}HFX231",
        parser_run_id=None,
        was_offloaded=False,
        vrl_file_name="VR4-UWM_250644_20261102234350.vrl",
        offload_end_time_utc=None,
        offload_start_time_utc=datetime(2026, 11, 2, 23, 46, tzinfo=timezone.utc),
        time_first_command_sent_utc=None,
        arrival_date=None,
        log_timestamp_utc=datetime(2026, 11, 2, 23, 46, tzinfo=timezone.utc),
        created_by_source="user",
    )
    findings = classify_matched_log(
        expected_mission_id="m227-SV3-1071",
        log=log,
        session_payload={
            "serial_number": "250644",
            "vrl_file_name": "VR4-UWM_250644_20261102234350.vrl",
        },
        reference_ts=datetime(2026, 11, 2, 23, 43, 50, tzinfo=timezone.utc),
    )
    reasons = {f.reason for f in findings}
    assert "mission_mismatch" in reasons
    assert "failed_with_vrl" in reasons
    mismatch = next(f for f in findings if f.reason == "mission_mismatch")
    assert mismatch.can_apply is True
    assert mismatch.actual_mission_id == "m230-SV3-1070"


def test_classify_missing_and_locked_parser_ref():
    blank = SimpleNamespace(
        id=1,
        station_id="HFX231",
        parser_session_ref=None,
        parser_run_id=None,
        was_offloaded=True,
        vrl_file_name="ok.vrl",
        offload_end_time_utc=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
        offload_start_time_utc=None,
        time_first_command_sent_utc=None,
        arrival_date=None,
        log_timestamp_utc=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
        created_by_source="user",
    )
    missing = classify_matched_log(
        expected_mission_id="m219-SV3-1121",
        log=blank,
        session_payload={"serial_number": "1", "vrl_file_name": "ok.vrl"},
        reference_ts=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
    )
    assert [f.reason for f in missing] == ["mission_missing"]
    assert missing[0].can_apply is True

    locked = SimpleNamespace(
        id=2,
        station_id="HFX231",
        parser_session_ref="m230-SV3-1070:250644:2026-11-02T23:43:50+00:00",
        parser_run_id=None,
        was_offloaded=True,
        vrl_file_name="ok.vrl",
        offload_end_time_utc=datetime(2026, 11, 2, 23, 46, tzinfo=timezone.utc),
        offload_start_time_utc=None,
        time_first_command_sent_utc=None,
        arrival_date=None,
        log_timestamp_utc=datetime(2026, 11, 2, 23, 46, tzinfo=timezone.utc),
        created_by_source="parser",
    )
    locked_findings = classify_matched_log(
        expected_mission_id="m227-SV3-1071",
        log=locked,
        session_payload={"serial_number": "250644", "vrl_file_name": "ok.vrl"},
        reference_ts=datetime(2026, 11, 2, 23, 43, 50, tzinfo=timezone.utc),
    )
    assert [f.reason for f in locked_findings] == ["locked_parser_ref"]
    assert locked_findings[0].can_apply is False


def _session() -> Session:
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    SQLModel.metadata.create_all(
        engine,
        tables=[StationMetadata.__table__, OffloadLog.__table__],
    )
    return Session(engine)


def _nov_vrl_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "timeStamp": "2026-11-02 23:40:00",
                "latitude": 44.5,
                "longitude": -63.5,
                "payload Data": "Connecting to remote VR4-250644",
            },
            {
                "timeStamp": "2026-11-02 23:43:50",
                "latitude": 44.5,
                "longitude": -63.5,
                "payload Data": (
                    "Completed remote offload: "
                    "/data/VR4-UWM_250644_20261102234350.vrl"
                ),
            },
        ]
    )


def test_audit_and_apply_sheet_mismatch_and_blank():
    session = _session()
    station = StationMetadata(
        station_id="HFX231",
        serial_number="250644",
        last_offload_by_glider="m230-SV3-1070",
    )
    session.add(station)
    wrong = OffloadLog(
        station_id="HFX231",
        logged_by_username="pilot",
        log_timestamp_utc=datetime(2026, 11, 2, 23, 46, tzinfo=timezone.utc),
        offload_start_time_utc=datetime(2026, 11, 2, 23, 40, tzinfo=timezone.utc),
        was_offloaded=True,
        vrl_file_name="VR4-UWM_250644_20261102234350.vrl",
        parser_session_ref=f"m230-SV3-1070{STATION_OFFLOAD_SHEET_MARKER}HFX231",
        created_by_source="user",
    )
    session.add(wrong)
    session.commit()
    session.refresh(wrong)

    findings = audit_mission_vm4_sessions(
        session,
        "m227-SV3-1071",
        vm4_df=_nov_vrl_dataframe(),
    )
    reasons = {f.reason for f in findings}
    assert "mission_mismatch" in reasons
    mismatch = next(f for f in findings if f.reason == "mission_mismatch")
    assert mismatch.log_id == wrong.id
    assert mismatch.can_apply is True

    result = apply_mission_audit_fixes(session, findings)
    assert result["updated"] == 1
    session.refresh(wrong)
    session.refresh(station)
    assert mission_id_from_offload_log(wrong) == "m227-SV3-1071"
    assert station.last_offload_by_glider == "m227-SV3-1071"
    assert "MISSION_AUDIT_SET" in (wrong.parser_notes or "")
