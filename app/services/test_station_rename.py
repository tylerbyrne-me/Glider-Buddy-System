"""Station ID rename re-keys registry children without dropping history."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.models.database import (
    OffloadLog,
    StationFlagEvent,
    StationHardwareHistory,
    StationMetadata,
    StationMetadataSeasonSnapshot,
)
from app.services.station_rename_service import StationRenameError, rename_station_id


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
        tables=[
            StationMetadata.__table__,
            OffloadLog.__table__,
            StationFlagEvent.__table__,
            StationHardwareHistory.__table__,
            StationMetadataSeasonSnapshot.__table__,
        ],
    )
    return Session(engine)


def _seed_station_with_history(session: Session, station_id: str = "CBS_001") -> None:
    now = datetime.now(timezone.utc)
    session.add(
        StationMetadata(
            station_id=station_id,
            serial_number="SN-1",
            modem_address=1001,
            notes="typo id",
        )
    )
    # Flag/hardware tables have FKs but no ORM relationship; flush parent first.
    session.flush()
    session.add(
        OffloadLog(
            station_id=station_id,
            logged_by_username="pilot",
            log_timestamp_utc=now,
            was_offloaded=True,
            field_season_year=2026,
            parser_session_ref=f"wg-mission:station_offload_sheet:{station_id}",
        )
    )
    session.add(
        OffloadLog(
            station_id=station_id,
            logged_by_username="parser",
            log_timestamp_utc=now,
            was_offloaded=True,
            created_by_source="parser",
            parser_session_ref=f"wg-mission:SN-1:{now.isoformat()}",
        )
    )
    session.add(
        StationFlagEvent(
            station_id=station_id,
            field_season_year=2026,
            is_flagged=True,
            note="check battery",
            changed_by_username="pilot",
            changed_at_utc=now,
        )
    )
    session.add(
        StationHardwareHistory(
            station_id=station_id,
            serial_number="SN-1",
            modem_address=1001,
            effective_start_utc=now,
            changed_by_username="admin",
            change_source="user",
        )
    )
    session.add(
        StationMetadataSeasonSnapshot(
            field_season_year=2025,
            station_id=station_id,
            serial_number="SN-1",
            notes="closed season roster",
        )
    )
    session.commit()


def test_rename_moves_logs_and_related_rows() -> None:
    session = _session()
    _seed_station_with_history(session, "CBS_001")

    result = rename_station_id(
        session,
        old_station_id="CBS_001",
        new_station_id="CBS001",
        commit=True,
    )

    assert result.old_station_id == "CBS_001"
    assert result.new_station_id == "CBS001"
    assert result.offload_logs_moved == 2
    assert result.flag_events_moved == 1
    assert result.hardware_history_moved == 1
    assert result.season_snapshots_moved == 1
    assert result.parser_session_refs_rewritten == 1

    assert session.get(StationMetadata, "CBS_001") is None
    new_row = session.get(StationMetadata, "CBS001")
    assert new_row is not None
    assert new_row.serial_number == "SN-1"
    assert new_row.notes == "typo id"

    logs = session.exec(select(OffloadLog).where(OffloadLog.station_id == "CBS001")).all()
    assert len(logs) == 2
    sheet_refs = [log.parser_session_ref for log in logs if "station_offload_sheet" in (log.parser_session_ref or "")]
    assert sheet_refs == ["wg-mission:station_offload_sheet:CBS001"]
    parser_refs = [log.parser_session_ref for log in logs if "station_offload_sheet" not in (log.parser_session_ref or "")]
    assert len(parser_refs) == 1
    assert parser_refs[0].startswith("wg-mission:SN-1:")

    assert session.exec(
        select(StationFlagEvent).where(StationFlagEvent.station_id == "CBS001")
    ).first() is not None
    assert session.exec(
        select(StationHardwareHistory).where(StationHardwareHistory.station_id == "CBS001")
    ).first() is not None
    assert session.exec(
        select(StationMetadataSeasonSnapshot).where(
            StationMetadataSeasonSnapshot.station_id == "CBS001"
        )
    ).first() is not None
    assert session.exec(select(OffloadLog).where(OffloadLog.station_id == "CBS_001")).all() == []


def test_rename_rejects_collision() -> None:
    session = _session()
    _seed_station_with_history(session, "CBS_001")
    session.add(StationMetadata(station_id="CBS001", serial_number="OTHER"))
    session.commit()

    with pytest.raises(StationRenameError) as exc_info:
        rename_station_id(
            session,
            old_station_id="CBS_001",
            new_station_id="CBS001",
            commit=True,
        )
    assert exc_info.value.code == "conflict"
    assert session.get(StationMetadata, "CBS_001") is not None
    assert session.exec(select(OffloadLog).where(OffloadLog.station_id == "CBS_001")).all()


def test_rename_rejects_unchanged_and_missing() -> None:
    session = _session()
    _seed_station_with_history(session, "CBS001")

    with pytest.raises(StationRenameError) as unchanged:
        rename_station_id(
            session,
            old_station_id="CBS001",
            new_station_id="CBS001",
            commit=True,
        )
    assert unchanged.value.code == "unchanged"

    with pytest.raises(StationRenameError) as missing:
        rename_station_id(
            session,
            old_station_id="DOES_NOT_EXIST",
            new_station_id="CBS002",
            commit=True,
        )
    assert missing.value.code == "not_found"
