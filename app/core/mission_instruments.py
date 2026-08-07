"""Load mission instruments with nested Sensor Tracker sensors for UI / APIs."""

from __future__ import annotations

from typing import List, Sequence, Union

from sqlalchemy.orm import selectinload
from sqlmodel import Session as SQLModelSession
from sqlmodel import col, select

from app.core.models import database as models
from app.core.models.schemas import MissionInstrumentRead


def load_mission_instruments_with_sensors(
    session: SQLModelSession,
    mission_ids: Union[str, Sequence[str]],
) -> List[MissionInstrumentRead]:
    """
    Return instruments for one or more mission id variants (full id and/or
    deployment code like ``m229``), each with nested ``sensors`` populated.
    """
    ids: List[str]
    if isinstance(mission_ids, str):
        ids = [mission_ids]
    else:
        ids = [mid for mid in mission_ids if mid]
    if not ids:
        return []

    instruments = session.exec(
        select(models.MissionInstrument)
        .where(col(models.MissionInstrument.mission_id).in_(ids))
        .options(selectinload(models.MissionInstrument.sensors))
        .order_by(models.MissionInstrument.id)
    ).all()

    return [MissionInstrumentRead.model_validate(inst) for inst in instruments]


def mission_id_variants(mission_id: str, mission_base: str | None = None) -> List[str]:
    """Unique list of mission_id strings to match instruments against."""
    variants: List[str] = []
    for value in (mission_id, mission_base):
        if value and value not in variants:
            variants.append(value)
    return variants
