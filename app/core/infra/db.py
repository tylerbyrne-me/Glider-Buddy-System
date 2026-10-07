import logging

from sqlalchemy import event
from sqlmodel import Session as SQLModelSession  # type: ignore
from sqlmodel import create_engine

from app.config import settings  # Assuming settings are in app.config

logger = logging.getLogger(__name__)

# --- Database Setup (SQLite with SQLModel) ---
# Use echo=False for production, True can be noisy but useful for debugging SQL
sqlite_engine = create_engine(
    settings.sqlite_database_url,
    echo=settings.sqlite_echo_log,
    connect_args={
        "check_same_thread": False,
        "timeout": 15,
    },  # busy timeout in seconds (sqlite3)
)


@event.listens_for(sqlite_engine, "connect")
def _configure_sqlite_connection(dbapi_connection, connection_record) -> None:
    """Enable WAL + explicit busy_timeout on every new SQLite connection."""
    # Only apply SQLite pragmas (unit tests may use other dialects later).
    if sqlite_engine.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def get_db_session():
    # The session is managed by FastAPI's dependency injection system.
    # It will be automatically closed after the request.
    with SQLModelSession(sqlite_engine) as session:
        yield session
