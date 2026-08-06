"""
Slocum deployment identity helpers.

SlocumDeployment is the briefing/metadata owner for an ERDDAP mission (shared by
realtime and delayed datasets via ``mission_key``), analogous to Wave Glider
MissionOverview for a mission folder id. Rows are get-or-created from the
dataset id — no separate manual "link" step.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import or_
from sqlmodel import select

from app.core import models, utils
from app.core.infra.db import SQLModelSession
from app.core.mission_aliases import equivalent_slocum_dataset_keys, resolve_slocum_dataset_id

logger = logging.getLogger(__name__)


def _is_alias_only_identity(deployment: models.SlocumDeployment) -> bool:
    """True when mission identity is an env alias string, not a parseable ERDDAP id."""
    key = (deployment.mission_key or deployment.erddap_dataset_id or "").strip()
    if not key:
        return False
    return utils.parse_slocum_dataset_id(key) is None


def _find_alias_only_deployment(
    session: SQLModelSession,
    parsed: dict[str, Any],
) -> Optional[models.SlocumDeployment]:
    """
    Match legacy rows that stored only the env alias as mission_key / erddap_dataset_id.

    Used when an alias key is renamed or removed from SLOCUM_DATASET_ALIAS_MAP_JSON.
    """
    glider_name = parsed["glider_name"]
    start_date = parsed["start_date"]
    dep_number = str(parsed["deployment_number"])
    candidates = session.exec(
        select(models.SlocumDeployment).where(
            models.SlocumDeployment.is_active == True,  # noqa: E712
            models.SlocumDeployment.glider_name == glider_name,
        )
    ).all()
    matches: list[models.SlocumDeployment] = []
    for dep in candidates:
        if not _is_alias_only_identity(dep):
            continue
        dep_date = dep.deployment_date.date() if dep.deployment_date else None
        if dep_date == start_date:
            matches.append(dep)
            continue
        hay = f"{dep.name}|{dep.erddap_dataset_id}|{dep.mission_key}|{dep.glider_name}"
        if dep_number in hay:
            matches.append(dep)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        logger.warning(
            "Multiple alias-only Slocum deployments match glider=%s start=%s; skipping auto-link",
            glider_name,
            start_date,
        )
    return None


def _prefer_deployment(
    candidates: list[models.SlocumDeployment],
) -> Optional[models.SlocumDeployment]:
    """Prefer the briefing row that already owns metadata when duplicates exist."""
    if not candidates:
        return None
    unique: dict[int, models.SlocumDeployment] = {}
    for dep in candidates:
        if dep.id is not None:
            unique[dep.id] = dep
    if not unique:
        return None
    if len(unique) == 1:
        return next(iter(unique.values()))

    def sort_key(dep: models.SlocumDeployment) -> tuple:
        has_doc = 0 if dep.document_url else 1
        created = dep.created_at_utc or datetime.min.replace(tzinfo=timezone.utc)
        return (has_doc, created, dep.id or 0)

    return sorted(unique.values(), key=sort_key)[0]


def resolve_deployment_for_dataset(
    session: SQLModelSession,
    dataset_id: str,
) -> Optional[models.SlocumDeployment]:
    dataset_id = resolve_slocum_dataset_id(dataset_id)
    mission_key = utils.slocum_mission_key(dataset_id)
    if not mission_key:
        return None

    candidates: list[models.SlocumDeployment] = []

    by_key = session.exec(
        select(models.SlocumDeployment).where(
            models.SlocumDeployment.mission_key == mission_key,
            models.SlocumDeployment.is_active == True,  # noqa: E712
        )
    ).all()
    candidates.extend(by_key)

    equivalent_keys = equivalent_slocum_dataset_keys(dataset_id)
    by_equivalent = session.exec(
        select(models.SlocumDeployment).where(
            models.SlocumDeployment.is_active == True,  # noqa: E712
            or_(
                models.SlocumDeployment.mission_key.in_(equivalent_keys),
                models.SlocumDeployment.erddap_dataset_id.in_(equivalent_keys),
            ),
        )
    ).all()
    candidates.extend(by_equivalent)

    parsed = utils.parse_slocum_dataset_id(dataset_id)
    if parsed:
        by_alias_only = _find_alias_only_deployment(session, parsed)
        if by_alias_only:
            candidates.append(by_alias_only)

    return _prefer_deployment(candidates)


def get_or_create_deployment_for_dataset(
    session: SQLModelSession,
    dataset_id: str,
    *,
    created_by_username: str,
) -> Optional[models.SlocumDeployment]:
    """
    Return the active SlocumDeployment for ``dataset_id``, creating one if needed.

    Resolution is by suffix-agnostic ``mission_key`` so realtime and delayed
    datasets share the same briefing metadata. When an existing deployment is
    resolved from a different dataset id (e.g. delayed after realtime),
    ``erddap_dataset_id`` is updated to the most recently seen id.

    Returns None when the dataset id cannot be parsed (same gate as Sensor Tracker
    mission-code derivation).
    """
    dataset_id = resolve_slocum_dataset_id(dataset_id)
    existing = resolve_deployment_for_dataset(session, dataset_id)
    if existing:
        changed = False
        mission_key = utils.slocum_mission_key(dataset_id)
        if mission_key and (
            not existing.mission_key
            or (
                existing.mission_key != mission_key
                and utils.parse_slocum_dataset_id(existing.mission_key or "") is None
            )
        ):
            existing.mission_key = mission_key
            changed = True
        if dataset_id and existing.erddap_dataset_id != dataset_id:
            existing.erddap_dataset_id = dataset_id
            changed = True
        if changed:
            existing.updated_at_utc = datetime.now(timezone.utc)
            session.add(existing)
            session.commit()
            session.refresh(existing)
            logger.info(
                "Updated SlocumDeployment id=%s mission_key=%s erddap_dataset_id=%s",
                existing.id,
                existing.mission_key,
                existing.erddap_dataset_id,
            )
        return existing

    parsed = utils.parse_slocum_dataset_id(dataset_id)
    if not parsed:
        logger.warning("Cannot create SlocumDeployment for unparseable dataset id: %s", dataset_id)
        return None

    start_date = parsed.get("start_date")
    deployment_date = None
    if start_date is not None:
        deployment_date = datetime.combine(start_date, datetime.min.time()).replace(tzinfo=timezone.utc)

    glider_name = parsed["glider_name"]
    mission_key = utils.slocum_mission_key(dataset_id)
    name = f"{glider_name} {start_date}" if start_date is not None else f"{glider_name} {dataset_id}"
    deployment = models.SlocumDeployment(
        name=name,
        glider_name=glider_name,
        deployment_date=deployment_date,
        mission_key=mission_key,
        erddap_dataset_id=dataset_id,
        status="active",
        created_by_username=created_by_username or "system",
    )
    session.add(deployment)
    session.commit()
    session.refresh(deployment)
    logger.info(
        "Auto-created SlocumDeployment id=%s for dataset_id=%s mission_key=%s (by %s)",
        deployment.id,
        dataset_id,
        mission_key,
        created_by_username,
    )
    return deployment
