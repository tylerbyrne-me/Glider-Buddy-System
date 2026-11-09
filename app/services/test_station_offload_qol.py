"""Station Offload QOL: overview fields, skip note clear, archive, idempotent creates."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.models.database import OffloadLog, StationMetadata
from app.services.station_overview import (
    build_status_overview_row,
    clear_display_status_override,
)


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


def test_overview_includes_last_offload_by_glider_and_skip_note():
    session = _session()
    station = StationMetadata(
        station_id="HFX01",
        last_offload_by_glider="m210",
        display_status_override="SKIPPED",
        display_status_override_note="Ice too thick",
        deployment_latitude=44.5,
        deployment_longitude=-63.5,
    )
    session.add(station)
    session.commit()
    session.refresh(station)

    row = build_status_overview_row(station, [])
    assert row["last_offload_by_glider"] == "m210"
    assert row["display_status_override_note"] == "Ice too thick"
    assert row["status_text"] == "Skipped"
    assert row["deployment_latitude"] == 44.5
    assert row["is_retired"] is False


def test_clear_display_status_override_clears_note():
    station = StationMetadata(
        station_id="FUN_09",
        display_status_override="SKIPPED",
        display_status_override_note="Weather",
        display_status_override_set_at_utc=datetime.now(timezone.utc),
    )
    clear_display_status_override(station)
    assert station.display_status_override is None
    assert station.display_status_override_set_at_utc is None
    assert station.display_status_override_note is None


def test_new_offload_clears_skip_override_and_note():
    session = _session()
    station = StationMetadata(
        station_id="CBS02",
        display_status_override="SKIPPED",
        display_status_override_note="No contact",
        display_status_override_set_at_utc=datetime.now(timezone.utc),
    )
    session.add(station)
    session.commit()

    log = OffloadLog(
        station_id="CBS02",
        logged_by_username="pilot",
        was_offloaded=True,
        offload_end_time_utc=datetime.now(timezone.utc),
        created_by_source="user",
        updated_by_source="user",
    )
    session.add(log)
    clear_display_status_override(station)
    session.add(station)
    session.commit()
    session.refresh(station)

    assert station.display_status_override is None
    assert station.display_status_override_note is None


def test_client_submission_id_idempotent_lookup():
    """Router create path looks up by (username, client_submission_id) before insert."""
    session = _session()
    session.add(StationMetadata(station_id="NCAT01"))
    session.flush()
    cid = "same-key-abc"
    first = OffloadLog(
        station_id="NCAT01",
        logged_by_username="pilot",
        was_offloaded=True,
        client_submission_id=cid,
        created_by_source="user",
        updated_by_source="user",
    )
    session.add(first)
    session.commit()
    session.refresh(first)

    existing = session.exec(
        select(OffloadLog).where(
            OffloadLog.logged_by_username == "pilot",
            OffloadLog.client_submission_id == cid,
        )
    ).first()
    assert existing is not None
    assert existing.id == first.id
    assert existing.was_offloaded is True


def test_archive_fields_on_station():
    session = _session()
    now = datetime.now(timezone.utc)
    station = StationMetadata(
        station_id="GULMPA02",
        is_retired=True,
        retired_at_utc=now,
        retired_reason="Recovered; VR4 redeployed on HFX",
    )
    session.add(station)
    session.commit()
    session.refresh(station)

    row = build_status_overview_row(station, [])
    assert row["is_retired"] is True
    assert row["retired_reason"] == "Recovered; VR4 redeployed on HFX"
    assert row["retired_at_utc"] is not None
