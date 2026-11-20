"""VRL attach must time-match logs; never paint a new VRL onto older blank attempts."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.models.database import OffloadLog, StationMetadata
from app.core.stations.wg_vm4_station_service import attach_vrl_file_names_to_offload_logs


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
                "timeStamp": "2026-11-09 19:01:00",
                "latitude": 44.5,
                "longitude": -63.5,
                "payload Data": "Connecting to remote VR4-250866",
            },
            {
                "timeStamp": "2026-11-09 19:03:00",
                "latitude": 44.5,
                "longitude": -63.5,
                "payload Data": (
                    "Completed remote offload: "
                    "/data/VR4-UWM_250866_20261109190155.vrl"
                ),
            },
        ]
    )


def test_attach_vrl_does_not_fill_older_blank_log():
    session = _session()
    station = StationMetadata(station_id="HFX273", serial_number="250866")
    session.add(station)
    session.commit()

    april = OffloadLog(
        station_id="HFX273",
        logged_by_username="pilot",
        log_timestamp_utc=datetime(2026, 4, 24, 22, 51, tzinfo=timezone.utc),
        offload_start_time_utc=datetime(2026, 4, 24, 22, 40, tzinfo=timezone.utc),
        was_offloaded=False,
        vrl_file_name=None,
        created_by_source="user",
    )
    november = OffloadLog(
        station_id="HFX273",
        logged_by_username="pilot",
        log_timestamp_utc=datetime(2026, 11, 9, 19, 8, tzinfo=timezone.utc),
        offload_start_time_utc=datetime(2026, 11, 9, 19, 1, tzinfo=timezone.utc),
        was_offloaded=True,
        vrl_file_name=None,
        created_by_source="user",
    )
    session.add(april)
    session.add(november)
    session.commit()
    session.refresh(april)
    session.refresh(november)

    stats = attach_vrl_file_names_to_offload_logs(session, _nov_vrl_dataframe())
    assert stats["logs_updated"] == 1

    session.refresh(april)
    session.refresh(november)
    assert april.vrl_file_name is None
    assert november.vrl_file_name == "VR4-UWM_250866_20261109190155.vrl"


def test_attach_vrl_does_not_overwrite_existing_filename():
    session = _session()
    station = StationMetadata(station_id="HFX273", serial_number="250866")
    session.add(station)
    session.commit()

    existing = OffloadLog(
        station_id="HFX273",
        logged_by_username="pilot",
        log_timestamp_utc=datetime(2026, 11, 9, 19, 8, tzinfo=timezone.utc),
        offload_start_time_utc=datetime(2026, 11, 9, 19, 1, tzinfo=timezone.utc),
        was_offloaded=True,
        vrl_file_name="KEEP_ME.vrl",
        created_by_source="user",
    )
    session.add(existing)
    session.commit()
    session.refresh(existing)

    stats = attach_vrl_file_names_to_offload_logs(session, _nov_vrl_dataframe())
    assert stats["logs_updated"] == 0
    assert stats["already_had_vrl"] == 1

    session.refresh(existing)
    assert existing.vrl_file_name == "KEEP_ME.vrl"


def test_attach_vrl_skips_when_no_time_nearby_log():
    session = _session()
    station = StationMetadata(station_id="HFX273", serial_number="250866")
    session.add(station)
    session.commit()

    april_only = OffloadLog(
        station_id="HFX273",
        logged_by_username="pilot",
        log_timestamp_utc=datetime(2026, 4, 24, 22, 51, tzinfo=timezone.utc),
        offload_start_time_utc=datetime(2026, 4, 24, 22, 40, tzinfo=timezone.utc),
        was_offloaded=False,
        vrl_file_name=None,
        created_by_source="user",
    )
    session.add(april_only)
    session.commit()
    session.refresh(april_only)

    stats = attach_vrl_file_names_to_offload_logs(session, _nov_vrl_dataframe())
    assert stats["logs_updated"] == 0
    assert stats["no_matching_log"] >= 1

    session.refresh(april_only)
    assert april_only.vrl_file_name is None


def test_attach_vrl_picks_closest_log_in_primary_window():
    """Two same-day attempts within ±30m: VRL goes to the nearer one, not the newer-edited."""
    session = _session()
    station = StationMetadata(station_id="HFX273", serial_number="250866")
    session.add(station)
    session.commit()

    earlier = OffloadLog(
        station_id="HFX273",
        logged_by_username="pilot",
        log_timestamp_utc=datetime(2026, 11, 9, 18, 50, tzinfo=timezone.utc),
        offload_start_time_utc=datetime(2026, 11, 9, 18, 50, tzinfo=timezone.utc),
        was_offloaded=False,
        vrl_file_name=None,
        created_by_source="user",
        updated_at_utc=datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc),
    )
    nearer = OffloadLog(
        station_id="HFX273",
        logged_by_username="pilot",
        log_timestamp_utc=datetime(2026, 11, 9, 19, 2, tzinfo=timezone.utc),
        offload_start_time_utc=datetime(2026, 11, 9, 19, 2, tzinfo=timezone.utc),
        was_offloaded=True,
        vrl_file_name=None,
        created_by_source="user",
        updated_at_utc=datetime(2026, 11, 9, 19, 10, tzinfo=timezone.utc),
    )
    session.add(earlier)
    session.add(nearer)
    session.commit()
    session.refresh(earlier)
    session.refresh(nearer)

    stats = attach_vrl_file_names_to_offload_logs(session, _nov_vrl_dataframe())
    assert stats["logs_updated"] == 1
    session.refresh(earlier)
    session.refresh(nearer)
    assert nearer.vrl_file_name == "VR4-UWM_250866_20261109190155.vrl"
    assert earlier.vrl_file_name is None


def test_attach_vrl_refills_blank_after_audit_clear():
    """HFX031-style: cleared wrong VRL, correct session still in full CSV → re-attach."""
    session = _session()
    station = StationMetadata(station_id="HFX031", serial_number="250515")
    session.add(station)
    session.commit()

    log = OffloadLog(
        station_id="HFX031",
        logged_by_username="tester",
        was_offloaded=True,
        vrl_file_name=None,
        offload_start_time_utc=datetime(2026, 11, 12, 3, 55, tzinfo=timezone.utc),
        offload_end_time_utc=datetime(2026, 11, 12, 3, 56, tzinfo=timezone.utc),
        created_by_source="user",
        updated_by_source="vrl_audit",
        parser_notes=(
            "[VRL_AUDIT_CLEARED] removed mis-attached "
            "vrl_file_name='VR4-UWM_250515_20260709185810.vrl'"
        ),
    )
    session.add(log)
    session.commit()
    session.refresh(log)

    df = pd.DataFrame(
        [
            {
                "timeStamp": "2026-11-12 03:55:00",
                "latitude": 44.302,
                "longitude": -63.334,
                "payload Data": "Connecting to remote VR4-250515",
            },
            {
                "timeStamp": "2026-11-12 03:56:45",
                "latitude": 44.302,
                "longitude": -63.335,
                "payload Data": (
                    "Completed remote offload: "
                    "/data/VR4-UWM_250515_20261112035532.vrl"
                ),
            },
        ]
    )
    stats = attach_vrl_file_names_to_offload_logs(session, df)
    session.refresh(log)
    assert stats["logs_updated"] == 1
    assert log.vrl_file_name == "VR4-UWM_250515_20261112035532.vrl"
