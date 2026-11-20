"""Shared ERDDAP source preference helpers for completed Slocum cutover."""

from __future__ import annotations

from typing import List, Optional

from sqlmodel import Session, select

from app.core.models.database import CatalogMission, CatalogMissionSource
from app.core.models.enums import CatalogMatchStatus, CatalogSourceVariant

_BAD_MATCH = {
    CatalogMatchStatus.STALE.value,
    CatalogMatchStatus.CONFLICT.value,
}

WAITING_FOR_DELAYED_SOURCE = "waiting_for_delayed_source"
WAITING_FOR_PAST_SOURCE = "waiting_for_past_source"
WAIT_SOURCE_ERRORS = frozenset(
    {WAITING_FOR_DELAYED_SOURCE, WAITING_FOR_PAST_SOURCE}
)


def _is_fresh_source(source: CatalogMissionSource) -> bool:
    if not bool(source.enabled):
        return False
    return (source.match_status or "").lower() not in _BAD_MATCH


def _is_delayed_erddap_source(source: CatalogMissionSource) -> bool:
    variant = (source.source_variant or "").strip().lower()
    ref = (source.external_ref or "").strip().lower()
    return variant == CatalogSourceVariant.DELAYED.value or "delayed" in ref


def fresh_erddap_sources(
    session: Session, mission_id: str
) -> List[CatalogMissionSource]:
    rows = list(
        session.exec(
            select(CatalogMissionSource).where(
                CatalogMissionSource.mission_id == mission_id,
                CatalogMissionSource.source_kind == "erddap",
                CatalogMissionSource.enabled == True,  # noqa: E712
            )
        ).all()
    )
    return [s for s in rows if _is_fresh_source(s)]


def preferred_slocum_delayed_ref(
    session: Session,
    mission: CatalogMission | str,
) -> Optional[str]:
    """Return linked delayed ERDDAP external_ref for a mission, if any.

    Matches ``source_variant == delayed`` or ``delayed`` in ``external_ref``.
    Excludes STALE/CONFLICT and disabled sources.
    """
    mission_id = mission if isinstance(mission, str) else mission.id
    if not mission_id:
        return None
    delayed = [
        s
        for s in fresh_erddap_sources(session, mission_id)
        if _is_delayed_erddap_source(s)
    ]
    if not delayed:
        return None
    ref = (delayed[0].external_ref or "").strip()
    return ref or None


def erddap_dataset_looks_realtime(dataset_id: Optional[str]) -> bool:
    text = (dataset_id or "").strip().lower()
    if not text:
        return True
    if text.endswith("_delayed") or "delayed" in text:
        return False
    return text.endswith("_realtime") or "realtime" in text


def deployment_needs_delayed_cutover(
    session: Session,
    mission: CatalogMission,
    *,
    erddap_dataset_id: Optional[str],
) -> bool:
    """True when delayed is linked but the live pointer is still realtime/empty."""
    delayed_ref = preferred_slocum_delayed_ref(session, mission)
    if not delayed_ref:
        return False
    current = (erddap_dataset_id or "").strip()
    if current == delayed_ref:
        return False
    return erddap_dataset_looks_realtime(current) or not current
