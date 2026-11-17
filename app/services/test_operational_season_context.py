"""Operational season resolve: active open → else latest closed (winter gap)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from app.core.models.database import FieldSeason
from app.services.station_season_service import StationSeasonService


def _session() -> Session:
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _fk(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    SQLModel.metadata.create_all(engine, tables=[FieldSeason.__table__])
    return Session(engine)


def test_resolve_prefers_active_open_season():
    session = _session()
    session.add(
        FieldSeason(
            year=2026,
            is_active=True,
            created_at_utc=datetime(2026, 3, 1, tzinfo=timezone.utc),
        )
    )
    session.add(
        FieldSeason(
            year=2025,
            is_active=False,
            closed_at_utc=datetime(2025, 11, 1, tzinfo=timezone.utc),
            created_at_utc=datetime(2025, 3, 1, tzinfo=timezone.utc),
        )
    )
    session.commit()

    year, is_closed, source = StationSeasonService.resolve_operational_season_context(
        session
    )
    assert year == 2026
    assert is_closed is False
    assert source == "active_open"


def test_resolve_falls_back_to_latest_closed_when_no_active_open():
    """Close 2026 creates inactive 2027 shell; maps should keep showing 2026."""
    session = _session()
    session.add(
        FieldSeason(
            year=2027,
            is_active=False,
            created_at_utc=datetime(2026, 11, 15, tzinfo=timezone.utc),
        )
    )
    session.add(
        FieldSeason(
            year=2026,
            is_active=False,
            closed_at_utc=datetime(2026, 11, 15, tzinfo=timezone.utc),
            created_at_utc=datetime(2026, 3, 1, tzinfo=timezone.utc),
        )
    )
    session.commit()

    year, is_closed, source = StationSeasonService.resolve_operational_season_context(
        session
    )
    assert year == 2026
    assert is_closed is True
    assert source == "latest_closed"


def test_resolve_uses_new_active_season_once_opened():
    session = _session()
    session.add(
        FieldSeason(
            year=2027,
            is_active=True,
            created_at_utc=datetime(2027, 3, 1, tzinfo=timezone.utc),
        )
    )
    session.add(
        FieldSeason(
            year=2026,
            is_active=False,
            closed_at_utc=datetime(2026, 11, 15, tzinfo=timezone.utc),
            created_at_utc=datetime(2026, 3, 1, tzinfo=timezone.utc),
        )
    )
    session.commit()

    year, is_closed, source = StationSeasonService.resolve_operational_season_context(
        session
    )
    assert year == 2027
    assert is_closed is False
    assert source == "active_open"


def test_resolve_none_when_no_seasons():
    session = _session()
    year, is_closed, source = StationSeasonService.resolve_operational_season_context(
        session
    )
    assert year is None
    assert is_closed is False
    assert source == "none"
