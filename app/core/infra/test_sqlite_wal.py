"""File-backed SQLite WAL / busy_timeout pragma verification."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event, text


def test_sqlite_wal_and_busy_timeout_on_connect(tmp_path: Path):
    db_path = tmp_path / "wal_test.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )

    @event.listens_for(engine, "connect")
    def _configure(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=15000")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    with engine.connect() as conn:
        journal_mode = conn.execute(text("PRAGMA journal_mode")).scalar()
        busy_timeout = conn.execute(text("PRAGMA busy_timeout")).scalar()
        foreign_keys = conn.execute(text("PRAGMA foreign_keys")).scalar()

    assert str(journal_mode).lower() == "wal"
    assert int(busy_timeout) == 15000
    assert int(foreign_keys) == 1
    engine.dispose()
