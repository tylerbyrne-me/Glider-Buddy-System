"""
Slocum deployment identity helpers.

SlocumDeployment is the briefing/metadata owner for an ERDDAP mission (shared by
realtime and delayed datasets via ``mission_key``), analogous to Wave Glider
MissionOverview for a mission folder id. Rows are get-or-created from the
dataset id — no separate manual "link" step.

Identity model:
- One metadata-owning ``SlocumDeployment`` per suffix-neutral ``mission_key``.
- ``_realtime`` and ``_delayed`` are source variants on the same deployment,
  not sibling briefing rows.
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
    *,
    include_inactive: bool,
) -> Optional[models.SlocumDeployment]:
    """
    Match legacy rows that stored only the env alias as mission_key / erddap_dataset_id.

    Used when an alias key is renamed or removed from SLOCUM_DATASET_ALIAS_MAP_JSON.
    """
    glider_name = parsed["glider_name"]
    start_date = parsed["start_date"]
    dep_number = str(parsed["deployment_number"])
    stmt = select(models.SlocumDeployment).where(
        models.SlocumDeployment.glider_name == glider_name,
    )
    if not include_inactive:
        stmt = stmt.where(models.SlocumDeployment.is_active == True)  # noqa: E712
    candidates = session.exec(stmt).all()
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
        # Prefer active when both exist (live ops), then catalog-linked, then
        # rows that already own briefing artifacts, then oldest.
        is_active = 0 if dep.is_active else 1
        has_catalog = 0 if getattr(dep, "catalog_mission_id", None) else 1
        has_doc = 0 if dep.document_url else 1
        has_reports = 0 if (dep.weekly_report_url or dep.end_of_mission_report_url) else 1
        created = dep.created_at_utc or datetime.min.replace(tzinfo=timezone.utc)
        return (is_active, has_catalog, has_doc, has_reports, created, dep.id or 0)

    return sorted(unique.values(), key=sort_key)[0]


def resolve_deployment_for_dataset(
    session: SQLModelSession,
    dataset_id: str,
    *,
    include_inactive: bool = False,
) -> Optional[models.SlocumDeployment]:
    """
    Resolve the metadata-owning deployment for a dataset id.

    By default only active rows are considered (live SFMC / public-map / warm).
    Pass ``include_inactive=True`` for historical reads and identity existence
    checks so completed briefing rows remain visible without creating orphans.
    """
    dataset_id = resolve_slocum_dataset_id(dataset_id)
    mission_key = utils.slocum_mission_key(dataset_id)
    if not mission_key:
        return None

    candidates: list[models.SlocumDeployment] = []

    by_key_stmt = select(models.SlocumDeployment).where(
        models.SlocumDeployment.mission_key == mission_key,
    )
    if not include_inactive:
        by_key_stmt = by_key_stmt.where(
            models.SlocumDeployment.is_active == True  # noqa: E712
        )
    candidates.extend(session.exec(by_key_stmt).all())

    equivalent_keys = equivalent_slocum_dataset_keys(dataset_id)
    by_equivalent_stmt = select(models.SlocumDeployment).where(
        or_(
            models.SlocumDeployment.mission_key.in_(equivalent_keys),
            models.SlocumDeployment.erddap_dataset_id.in_(equivalent_keys),
        ),
    )
    if not include_inactive:
        by_equivalent_stmt = by_equivalent_stmt.where(
            models.SlocumDeployment.is_active == True  # noqa: E712
        )
    candidates.extend(session.exec(by_equivalent_stmt).all())

    parsed = utils.parse_slocum_dataset_id(dataset_id)
    if parsed:
        by_alias_only = _find_alias_only_deployment(
            session, parsed, include_inactive=include_inactive
        )
        if by_alias_only:
            candidates.append(by_alias_only)

    return _prefer_deployment(candidates)


def get_or_create_deployment_for_dataset(
    session: SQLModelSession,
    dataset_id: str,
    *,
    created_by_username: str,
    allow_create: bool = True,
    update_erddap_dataset_id: bool = True,
) -> Optional[models.SlocumDeployment]:
    """
    Return the SlocumDeployment for ``dataset_id``, creating one if needed.

    Resolution always considers inactive completed rows first so historical
    GETs and delayed handoffs cannot spawn empty duplicates. Creation is
    skipped when ``allow_create=False`` (historical / read-only paths).

    When an existing deployment is resolved from a different dataset id
    (e.g. delayed after realtime), ``erddap_dataset_id`` may be updated to the
    preferred source. That never creates a second mission row.

    Returns None when the dataset id cannot be parsed (same gate as Sensor Tracker
    mission-code derivation).
    """
    dataset_id = resolve_slocum_dataset_id(dataset_id)
    # Always include inactive for identity existence — completed briefing owner
    # must win over create.
    existing = resolve_deployment_for_dataset(
        session, dataset_id, include_inactive=True
    )
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
        # Do not reactivate completed rows on ordinary resolve/create.
        if (
            update_erddap_dataset_id
            and dataset_id
            and existing.erddap_dataset_id != dataset_id
        ):
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

    if not allow_create:
        return None

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
