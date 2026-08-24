"""Catalog query and capability-aware source resolution."""

from __future__ import annotations

import json
import logging
from typing import List, Optional

from sqlmodel import Session, select

from app.core.mission_catalog.schemas import (
    CatalogMissionRead,
    CatalogSourceRead,
    MissionCatalogQuery,
    MissionSourceRequest,
    MissionSourceResolution,
)
from app.core.models.database import (
    CatalogExternalIdentity,
    CatalogMission,
    CatalogMissionSource,
    CatalogPlatform,
)
from app.core.models.enums import CatalogMatchStatus

logger = logging.getLogger(__name__)


def _parse_capabilities(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if item]


def source_to_read(source: CatalogMissionSource) -> CatalogSourceRead:
    return CatalogSourceRead(
        id=source.id,
        mission_id=source.mission_id,
        provider_key=source.provider_key,
        source_kind=source.source_kind,
        collection=source.collection or "",
        external_ref=source.external_ref,
        source_variant=source.source_variant,
        capabilities=_parse_capabilities(source.capabilities_json),
        priority=int(source.priority or 100),
        enabled=bool(source.enabled),
        match_status=source.match_status,
        is_verified=bool(source.is_verified),
    )


def mission_to_read(
    session: Session,
    mission: CatalogMission,
    *,
    sources: Optional[List[CatalogMissionSource]] = None,
) -> CatalogMissionRead:
    platform = None
    if mission.platform_id:
        platform = session.get(CatalogPlatform, mission.platform_id)
    if sources is None:
        sources = session.exec(
            select(CatalogMissionSource).where(
                CatalogMissionSource.mission_id == mission.id
            )
        ).all()
    return CatalogMissionRead(
        id=mission.id,
        title=mission.title,
        deployment_number=mission.deployment_number,
        start_time=mission.start_time,
        end_time=mission.end_time,
        operational_state=mission.operational_state,
        sync_policy=mission.sync_policy,
        platform_family=platform.platform_family if platform else None,
        platform_name=platform.canonical_name if platform else None,
        owner_organization=platform.owner_organization if platform else None,
        sources=[source_to_read(s) for s in sources],
    )


def list_catalog_missions(
    query: MissionCatalogQuery,
    session: Session,
) -> List[CatalogMissionRead]:
    """List catalog missions with optional filters."""
    statement = select(CatalogMission)
    if query.operational_state:
        statement = statement.where(
            CatalogMission.operational_state == query.operational_state
        )
    if query.sync_policy:
        statement = statement.where(CatalogMission.sync_policy == query.sync_policy)

    missions = list(session.exec(statement).all())
    results: List[CatalogMissionRead] = []

    for mission in missions:
        platform = (
            session.get(CatalogPlatform, mission.platform_id)
            if mission.platform_id
            else None
        )
        if query.platform_family:
            family = platform.platform_family if platform else None
            if family != query.platform_family:
                continue

        sources = list(
            session.exec(
                select(CatalogMissionSource).where(
                    CatalogMissionSource.mission_id == mission.id
                )
            ).all()
        )
        if query.source_kind:
            sources = [s for s in sources if s.source_kind == query.source_kind]
            if not sources:
                continue
        if query.provider_key:
            sources = [s for s in sources if s.provider_key == query.provider_key]
            if not sources:
                continue
        if query.match_status:
            sources = [s for s in sources if s.match_status == query.match_status]
            if not sources:
                continue
        if query.capability:
            filtered = []
            for source in sources:
                caps = _parse_capabilities(source.capabilities_json)
                if query.capability in caps:
                    filtered.append(source)
            sources = filtered
            if not sources:
                continue

        results.append(mission_to_read(session, mission, sources=sources))
        if query.limit is not None and len(results) >= query.limit:
            break

    if query.include_unmatched_sources:
        unmatched_stmt = select(CatalogMissionSource).where(
            CatalogMissionSource.mission_id.is_(None)  # type: ignore[arg-type]
        )
        if query.source_kind:
            unmatched_stmt = unmatched_stmt.where(
                CatalogMissionSource.source_kind == query.source_kind
            )
        if query.provider_key:
            unmatched_stmt = unmatched_stmt.where(
                CatalogMissionSource.provider_key == query.provider_key
            )
        unmatched = session.exec(unmatched_stmt).all()
        for source in unmatched:
            # Represent unmatched sources as synthetic reads under a placeholder mission.
            results.append(
                CatalogMissionRead(
                    id=f"unmatched:{source.id}",
                    title=f"Unmatched {source.external_ref}",
                    deployment_number=None,
                    start_time=None,
                    end_time=None,
                    operational_state="unknown",
                    sync_policy="catalog_only",
                    platform_family=None,
                    platform_name=None,
                    owner_organization=None,
                    sources=[source_to_read(source)],
                )
            )
            if query.limit is not None and len(results) >= query.limit:
                break

    return results


def _find_mission(
    session: Session,
    request: MissionSourceRequest,
) -> Optional[CatalogMission]:
    if request.mission_id:
        mission = session.get(CatalogMission, request.mission_id)
        if mission:
            return mission
    if request.identity_kind and request.identity_value:
        identity = session.exec(
            select(CatalogExternalIdentity).where(
                CatalogExternalIdentity.identity_kind == request.identity_kind,
                CatalogExternalIdentity.external_id == request.identity_value,
            )
        ).first()
        if identity:
            return session.get(CatalogMission, identity.mission_id)
    return None


def resolve_mission_sources(
    request: MissionSourceRequest,
    session: Session,
) -> MissionSourceResolution:
    """Select the best enabled source for a capability, returning alternates."""
    mission = _find_mission(session, request)
    if mission is None:
        return MissionSourceResolution(
            mission_id=request.mission_id,
            explanation="Mission not found in catalog",
        )

    sources = list(
        session.exec(
            select(CatalogMissionSource).where(
                CatalogMissionSource.mission_id == mission.id,
                CatalogMissionSource.enabled == True,  # noqa: E712
            )
        ).all()
    )
    if request.provider_key:
        sources = [s for s in sources if s.provider_key == request.provider_key]
    if request.preferred_source_kind:
        preferred = [s for s in sources if s.source_kind == request.preferred_source_kind]
        if preferred:
            sources = preferred + [s for s in sources if s not in preferred]

    candidates: List[CatalogMissionSource] = []
    for source in sources:
        if source.match_status == CatalogMatchStatus.STALE.value:
            continue
        if source.match_status == CatalogMatchStatus.CONFLICT.value:
            continue
        caps = _parse_capabilities(source.capabilities_json)
        if request.required_capability and request.required_capability not in caps:
            # Allow empty capabilities for track-capable ERDDAP/WGMS defaults
            if caps:
                continue
            if request.required_capability != "track":
                continue
        if not request.allow_unverified and source.source_kind == "erddap" and not source.is_verified:
            continue
        candidates.append(source)

    if request.preferred_variant:
        variant_hits = [
            s for s in candidates if s.source_variant == request.preferred_variant
        ]
        if variant_hits:
            rest = [s for s in candidates if s not in variant_hits]
            candidates = variant_hits + rest

    candidates.sort(key=lambda s: (int(s.priority or 100), s.external_ref))
    if not candidates:
        return MissionSourceResolution(
            mission_id=mission.id,
            explanation=(
                f"No enabled source with capability={request.required_capability!r} "
                f"(allow_unverified={request.allow_unverified})"
            ),
        )

    selected = candidates[0]
    alternates = candidates[1:]
    explanation = (
        f"Selected {selected.source_kind}:{selected.external_ref} "
        f"(priority={selected.priority}, variant={selected.source_variant})"
    )
    return MissionSourceResolution(
        mission_id=mission.id,
        selected=source_to_read(selected),
        alternates=[source_to_read(s) for s in alternates],
        explanation=explanation,
    )
