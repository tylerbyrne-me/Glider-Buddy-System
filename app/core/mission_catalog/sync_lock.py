"""Cross-process lock for catalog apply / provision / final-sync writes."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from app.core.utils import cross_process_file_lock

CATALOG_WRITE_LOCK_PATH = Path("data_store/mission_catalog_write.lock")
CATALOG_WRITE_STATE_PATH = Path("data_store/mission_catalog_write_state.json")
CATALOG_PARTIAL_MARKER = Path("data_store/mission_catalog_last_partial.txt")
DEFAULT_LOCK_TIMEOUT_SECONDS = 180.0
TEAM_LOCK_TIMEOUT_SECONDS = 5.0


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_lock_state(*, in_progress: bool, actor: str = "", detail: str = "") -> None:
    CATALOG_WRITE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "in_progress": bool(in_progress),
        "actor": actor or "",
        "detail": detail or "",
        "updated_at_utc": _utcnow_iso(),
    }
    CATALOG_WRITE_STATE_PATH.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def read_lock_state() -> dict:
    if not CATALOG_WRITE_STATE_PATH.is_file():
        return {
            "in_progress": False,
            "actor": "",
            "detail": "",
            "updated_at_utc": None,
        }
    try:
        data = json.loads(CATALOG_WRITE_STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not a dict")
        return {
            "in_progress": bool(data.get("in_progress")),
            "actor": str(data.get("actor") or ""),
            "detail": str(data.get("detail") or ""),
            "updated_at_utc": data.get("updated_at_utc"),
        }
    except Exception:
        return {
            "in_progress": False,
            "actor": "",
            "detail": "",
            "updated_at_utc": None,
        }


def mark_partial_run(summary: str = "") -> None:
    CATALOG_PARTIAL_MARKER.parent.mkdir(parents=True, exist_ok=True)
    line = f"{_utcnow_iso()}\t{summary or 'partial'}\n"
    with CATALOG_PARTIAL_MARKER.open("a", encoding="utf-8") as fh:
        fh.write(line)


def last_partial_at() -> Optional[datetime]:
    if not CATALOG_PARTIAL_MARKER.is_file():
        return None
    try:
        lines = [
            ln.strip()
            for ln in CATALOG_PARTIAL_MARKER.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        if not lines:
            return None
        stamp = lines[-1].split("\t", 1)[0]
        return datetime.fromisoformat(stamp)
    except Exception:
        return None


@contextmanager
def catalog_write_lock(
    *,
    timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
    actor: str = "scheduler",
    detail: str = "apply",
) -> Iterator[None]:
    """Exclusive lock shared by CLI apply, scheduler, and Team provision retries."""
    with cross_process_file_lock(
        CATALOG_WRITE_LOCK_PATH,
        timeout_seconds=timeout_seconds,
    ):
        write_lock_state(in_progress=True, actor=actor, detail=detail)
        try:
            yield
        finally:
            write_lock_state(in_progress=False, actor=actor, detail="")
