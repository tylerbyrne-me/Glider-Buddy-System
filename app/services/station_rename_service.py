"""
Re-key station_metadata.station_id and dependent rows in one transaction.

SQLite FKs have no ON UPDATE CASCADE, so rename is insert-new → UPDATE children
→ delete-old (not an in-place PK UPDATE).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import delete, update
from sqlmodel import select

from app.core import models
from app.core.infra.db import SQLModelSession

logger = logging.getLogger(__name__)

_SHEET_REF_MARKER = ":station_offload_sheet:"


class StationRenameError(Exception):
    """Base rename failure with a stable machine code for the router."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class StationRenameResult:
    station: models.StationMetadata
    old_station_id: str
    new_station_id: str
    offload_logs_moved: int
    flag_events_moved: int
    hardware_history_moved: int
    season_snapshots_moved: int
    parser_session_refs_rewritten: int


def _normalize_station_id(value: Optional[str]) -> str:
    return (value or "").strip()


def rename_station_id(
    session: SQLModelSession,
    *,
    old_station_id: str,
    new_station_id: str,
    commit: bool = True,
) -> StationRenameResult:
    """
    Re-key a station and move offload logs, flags, hardware history, and
    season snapshots. Rewrites sheet-style parser_session_ref suffixes.
    """
    old_id = _normalize_station_id(old_station_id)
    new_id = _normalize_station_id(new_station_id)

    if not old_id:
        raise StationRenameError("invalid_old_id", "Current station_id is required")
    if not new_id:
        raise StationRenameError("invalid_new_id", "new_station_id is required")
    if new_id == old_id:
        raise StationRenameError(
            "unchanged",
            "new_station_id must differ from the current station_id",
        )

    source = session.get(models.StationMetadata, old_id)
    if not source:
        raise StationRenameError("not_found", f"Station '{old_id}' not found")

    if session.get(models.StationMetadata, new_id):
        raise StationRenameError(
            "conflict",
            f"Station '{new_id}' already exists; rename refuses to merge",
        )

    row_data = source.model_dump()
    row_data["station_id"] = new_id
    new_station = models.StationMetadata.model_validate(row_data)
    session.add(new_station)
    session.flush()

    logs_result = session.execute(
        update(models.OffloadLog)
        .where(models.OffloadLog.station_id == old_id)
        .values(station_id=new_id)
    )
    offload_logs_moved = int(logs_result.rowcount or 0)

    flags_result = session.execute(
        update(models.StationFlagEvent)
        .where(models.StationFlagEvent.station_id == old_id)
        .values(station_id=new_id)
    )
    flag_events_moved = int(flags_result.rowcount or 0)

    hw_result = session.execute(
        update(models.StationHardwareHistory)
        .where(models.StationHardwareHistory.station_id == old_id)
        .values(station_id=new_id)
    )
    hardware_history_moved = int(hw_result.rowcount or 0)

    snaps_result = session.execute(
        update(models.StationMetadataSeasonSnapshot)
        .where(models.StationMetadataSeasonSnapshot.station_id == old_id)
        .values(station_id=new_id)
    )
    season_snapshots_moved = int(snaps_result.rowcount or 0)

    old_sheet_suffix = f"{_SHEET_REF_MARKER}{old_id}"
    new_sheet_suffix = f"{_SHEET_REF_MARKER}{new_id}"
    sheet_logs = session.exec(
        select(models.OffloadLog).where(
            models.OffloadLog.station_id == new_id,
            models.OffloadLog.parser_session_ref.isnot(None),
        )
    ).all()
    parser_session_refs_rewritten = 0
    for log in sheet_logs:
        ref = (log.parser_session_ref or "").strip()
        if not ref.endswith(old_sheet_suffix):
            continue
        log.parser_session_ref = ref[: -len(old_sheet_suffix)] + new_sheet_suffix
        session.add(log)
        parser_session_refs_rewritten += 1

    # Avoid ORM relationship cascade wiping reassigned logs: delete by PK only.
    session.expire(source)
    session.execute(
        delete(models.StationMetadata).where(models.StationMetadata.station_id == old_id)
    )

    if commit:
        session.commit()
        session.refresh(new_station)
    else:
        session.flush()

    result = StationRenameResult(
        station=new_station,
        old_station_id=old_id,
        new_station_id=new_id,
        offload_logs_moved=offload_logs_moved,
        flag_events_moved=flag_events_moved,
        hardware_history_moved=hardware_history_moved,
        season_snapshots_moved=season_snapshots_moved,
        parser_session_refs_rewritten=parser_session_refs_rewritten,
    )
    logger.info(
        "Renamed station_id %s -> %s (logs=%s flags=%s hardware=%s snapshots=%s refs=%s)",
        old_id,
        new_id,
        offload_logs_moved,
        flag_events_moved,
        hardware_history_moved,
        season_snapshots_moved,
        parser_session_refs_rewritten,
    )
    return result
