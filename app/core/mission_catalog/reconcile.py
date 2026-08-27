"""Reconcile provider discovery batches into the source-neutral catalog."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Set, Tuple

from sqlmodel import Session, select

from app.core.mission_catalog.lifecycle import derive_operational_state_and_policy
from app.core.mission_catalog.naming import (
    classify_platform_family,
    mission_fingerprint,
    normalize_platform_prefix,
)
from app.core.mission_catalog.providers_config import ProvidersManifest
from app.core.mission_catalog.schemas import (
    DiscoveryBatch,
    DiscoveredMission,
    DiscoveredPlatform,
    DiscoveredSource,
    ReconcileCounts,
    ReconcileResult,
)
from app.core.models.database import (
    CatalogExternalIdentity,
    CatalogMission,
    CatalogMissionSource,
    CatalogPlatform,
)
from app.core.models.enums import (
    CatalogIdentityKind,
    CatalogMatchStatus,
    CatalogOperationalState,
    CatalogSyncPolicy,
)

logger = logging.getLogger(__name__)

# Cross-provider identity kinds: same org + external_id → one catalog mission.
_GLOBAL_IDENTITY_KINDS: Set[str] = {
    CatalogIdentityKind.DEPLOYMENT_CODE.value,
    CatalogIdentityKind.ERDDAP_MISSION_KEY.value,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _capabilities_json(capabilities: Iterable[str]) -> str:
    return json.dumps(sorted({str(c).strip() for c in capabilities if c}))


def _enum_value(value) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _owner_org_for_discovered(discovered: DiscoveredMission) -> Optional[str]:
    if discovered.platform and discovered.platform.owner_organization:
        return discovered.platform.owner_organization
    return (discovered.metadata or {}).get("owner_organization")


def _mission_owner_org(session: Session, mission: CatalogMission) -> Optional[str]:
    if mission.platform_id:
        platform = session.get(CatalogPlatform, mission.platform_id)
        if platform and platform.owner_organization:
            return platform.owner_organization
    meta = mission.metadata_json or {}
    return meta.get("owner_organization")


def _get_or_create_platform(
    session: Session,
    discovered: DiscoveredPlatform,
    *,
    dry_run: bool,
    counts: ReconcileCounts,
) -> Optional[CatalogPlatform]:
    """Match platforms by ST platform id or canonical name — never by data_prefix."""
    name = (discovered.canonical_name or "").strip()
    if not name:
        return None
    prefix = discovered.data_prefix or normalize_platform_prefix(name)
    st_platform_id = (discovered.metadata or {}).get("st_platform_id")

    existing: Optional[CatalogPlatform] = None
    if st_platform_id is not None:
        for platform in session.exec(select(CatalogPlatform)).all():
            meta = platform.metadata_json or {}
            if meta.get("st_platform_id") == st_platform_id:
                existing = platform
                break
    if existing is None:
        existing = session.exec(
            select(CatalogPlatform).where(CatalogPlatform.canonical_name == name)
        ).first()

    if existing:
        if not dry_run:
            if discovered.platform_family and not existing.platform_family:
                existing.platform_family = discovered.platform_family
            if discovered.owner_organization and not existing.owner_organization:
                existing.owner_organization = discovered.owner_organization
            if prefix and not existing.data_prefix:
                existing.data_prefix = prefix
            meta = dict(existing.metadata_json or {})
            for key in ("st_platform_id", "st_platform_type_id", "st_model"):
                if (discovered.metadata or {}).get(key) is not None:
                    meta[key] = discovered.metadata[key]
            existing.metadata_json = meta or None
            existing.updated_at_utc = _utcnow()
            session.add(existing)
        counts.platforms_upserted += 1
        return existing

    platform = CatalogPlatform(
        canonical_name=name,
        platform_family=discovered.platform_family,
        owner_organization=discovered.owner_organization,
        data_prefix=prefix,
        aliases_json=json.dumps(discovered.aliases) if discovered.aliases else None,
        metadata_json=discovered.metadata or None,
        created_at_utc=_utcnow(),
        updated_at_utc=_utcnow(),
    )
    counts.platforms_upserted += 1
    if dry_run:
        return platform
    session.add(platform)
    session.flush()
    return platform


def _identity_lookup(
    session: Session,
    provider_key: str,
    identity_kind: str,
    external_id: str,
) -> Optional[CatalogExternalIdentity]:
    return session.exec(
        select(CatalogExternalIdentity).where(
            CatalogExternalIdentity.provider_key == provider_key,
            CatalogExternalIdentity.identity_kind == identity_kind,
            CatalogExternalIdentity.external_id == external_id,
        )
    ).first()


def _global_identity_lookup(
    session: Session,
    identity_kind: str,
    external_id: str,
    *,
    owner_organization: Optional[str],
) -> Optional[CatalogExternalIdentity]:
    hits = session.exec(
        select(CatalogExternalIdentity).where(
            CatalogExternalIdentity.identity_kind == identity_kind,
            CatalogExternalIdentity.external_id == external_id,
        )
    ).all()
    for hit in hits:
        mission = session.get(CatalogMission, hit.mission_id)
        if not mission:
            continue
        if owner_organization:
            mission_org = _mission_owner_org(session, mission)
            if mission_org and mission_org != owner_organization:
                continue
        return hit
    return None


def _source_lookup(
    session: Session,
    provider_key: str,
    collection: str,
    external_ref: str,
) -> Optional[CatalogMissionSource]:
    return session.exec(
        select(CatalogMissionSource).where(
            CatalogMissionSource.provider_key == provider_key,
            CatalogMissionSource.collection == (collection or ""),
            CatalogMissionSource.external_ref == external_ref,
        )
    ).first()


def _fingerprint_lookup(
    session: Session,
    fingerprint: str,
) -> Optional[CatalogMission]:
    missions = session.exec(select(CatalogMission)).all()
    for mission in missions:
        meta = mission.metadata_json or {}
        if meta.get("fingerprint") == fingerprint:
            return mission
    return None


def _resolve_mission_for_discovery(
    session: Session,
    mission: DiscoveredMission,
    *,
    conflicts: List[str],
) -> Tuple[Optional[CatalogMission], str]:
    """Return (mission, match_method)."""
    owner = _owner_org_for_discovered(mission)

    for identity in mission.identities:
        kind = _enum_value(identity.identity_kind)
        if kind in _GLOBAL_IDENTITY_KINDS:
            hit = _global_identity_lookup(
                session,
                kind,
                identity.external_id,
                owner_organization=owner,
            )
        else:
            hit = _identity_lookup(
                session,
                identity.provider_key,
                kind,
                identity.external_id,
            )
        if hit:
            linked = session.get(CatalogMission, hit.mission_id)
            if linked:
                return linked, "external_identity"

    for source in mission.sources:
        hit = _source_lookup(
            session,
            source.provider_key,
            source.collection or "",
            source.external_ref,
        )
        if hit and hit.mission_id:
            linked = session.get(CatalogMission, hit.mission_id)
            if linked:
                return linked, "source_ref"

    # Fingerprint requires deployment_number; preemptive ST rows never match here.
    platform_prefix = None
    if mission.platform:
        platform_prefix = mission.platform.data_prefix or mission.platform.canonical_name
    fingerprint = mission_fingerprint(
        owner_organization=owner,
        platform_prefix=platform_prefix,
        start=mission.start_time,
        deployment_number=mission.deployment_number,
    )
    if fingerprint:
        linked = _fingerprint_lookup(session, fingerprint)
        if linked:
            return linked, "fingerprint"

    if mission.deployment_number is not None and platform_prefix:
        candidates = session.exec(
            select(CatalogMission).where(
                CatalogMission.deployment_number == mission.deployment_number
            )
        ).all()
        if len(candidates) > 1:
            conflicts.append(
                f"Ambiguous deployment_number={mission.deployment_number} "
                f"prefix={platform_prefix}; leaving for review"
            )
    return None, "none"


def _upsert_identities(
    session: Session,
    mission_id: str,
    discovered: DiscoveredMission,
    *,
    dry_run: bool,
    counts: ReconcileCounts,
) -> None:
    owner = _owner_org_for_discovered(discovered)
    for identity in discovered.identities:
        kind = _enum_value(identity.identity_kind)
        existing = _identity_lookup(
            session, identity.provider_key, kind, identity.external_id
        )
        if existing:
            if existing.mission_id != mission_id and not dry_run:
                counts.conflicts += 1
            continue
        if kind in _GLOBAL_IDENTITY_KINDS:
            global_hit = _global_identity_lookup(
                session,
                kind,
                identity.external_id,
                owner_organization=owner,
            )
            if global_hit and global_hit.mission_id != mission_id:
                counts.conflicts += 1
                continue
        counts.identities_upserted += 1
        if dry_run:
            continue
        session.add(
            CatalogExternalIdentity(
                mission_id=mission_id,
                provider_key=identity.provider_key,
                identity_kind=kind,
                external_id=identity.external_id,
                is_canonical=bool(identity.is_canonical),
                metadata_json=identity.metadata or None,
                created_at_utc=_utcnow(),
                updated_at_utc=_utcnow(),
            )
        )


def _upsert_source(
    session: Session,
    source: DiscoveredSource,
    *,
    mission_id: Optional[str],
    match_status: str,
    dry_run: bool,
    counts: ReconcileCounts,
    seen_source_keys: set[Tuple[str, str, str]],
) -> None:
    key = (source.provider_key, source.collection or "", source.external_ref)
    seen_source_keys.add(key)
    existing = _source_lookup(session, *key)
    kind = _enum_value(source.source_kind)
    variant = _enum_value(source.source_variant)
    now = _utcnow()
    if existing:
        if mission_id and existing.mission_id and existing.mission_id != mission_id:
            counts.conflicts += 1
            match_status = CatalogMatchStatus.CONFLICT.value
        if not dry_run:
            linked_mission = (
                session.get(CatalogMission, existing.mission_id)
                if existing.mission_id
                else None
            )
            preserve_manual = bool(
                linked_mission and linked_mission.has_manual_overrides
            )
            if mission_id and not existing.mission_id and not preserve_manual:
                existing.mission_id = mission_id
            if match_status == CatalogMatchStatus.LINKED.value and not preserve_manual:
                existing.match_status = CatalogMatchStatus.LINKED.value
            if not preserve_manual:
                existing.source_kind = kind
                existing.source_variant = variant
                existing.capabilities_json = _capabilities_json(source.capabilities)
                existing.priority = int(source.priority)
            existing.is_verified = bool(source.is_verified) or existing.is_verified
            if source.is_verified:
                existing.verified_at = now
            existing.consecutive_misses = 0
            existing.last_seen_at = now
            existing.updated_at_utc = now
            session.add(existing)
        if mission_id or existing.mission_id:
            counts.sources_linked += 1
        else:
            counts.sources_unmatched += 1
        return

    if mission_id:
        counts.sources_linked += 1
    else:
        counts.sources_unmatched += 1
    if dry_run:
        return
    session.add(
        CatalogMissionSource(
            mission_id=mission_id,
            provider_key=source.provider_key,
            source_kind=kind,
            collection=source.collection or "",
            external_ref=source.external_ref,
            source_variant=variant,
            capabilities_json=_capabilities_json(source.capabilities),
            priority=int(source.priority),
            enabled=True,
            match_status=match_status,
            is_verified=bool(source.is_verified),
            verified_at=now if source.is_verified else None,
            consecutive_misses=0,
            first_seen_at=now,
            last_seen_at=now,
            metadata_json=source.metadata or None,
            created_at_utc=now,
            updated_at_utc=now,
        )
    )


def _is_lifecycle_authority(
    discovered: DiscoveredMission,
    manifest: ProvidersManifest,
) -> bool:
    """True when this provider alone may set/clear dates and drive lifecycle."""
    provider = manifest.get(discovered.provider_key)
    if provider is None:
        return False
    if provider.lifecycle_authority:
        return True
    # Safe default: sensor_tracker connector is lifecycle authority.
    return provider.connector == "sensor_tracker"


def _may_seed_enrollment(
    discovered: DiscoveredMission,
    manifest: ProvidersManifest,
) -> bool:
    """Only the env lists (legacy_env) may seed CONTINUOUS enrollment.

    WGMS also emits CONTINUOUS for realtime folders, but a folder existing is
    data location — not GBS operating the mission (e.g. m230 stays unenrolled).
    """
    provider = manifest.get(discovered.provider_key)
    if provider is None:
        return False
    return provider.connector == "legacy_env"


def _apply_lifecycle_fields(
    discovered: DiscoveredMission,
    *,
    allow_continuous: bool = True,
) -> Tuple[str, str]:
    """Derive state/policy from dates; honor adapter state when no date evidence.

    ``allow_continuous=False`` masks an adapter-provided CONTINUOUS policy so
    non-enrollment providers (WGMS realtime folders) cannot enroll missions.
    """
    derived_state, derived_policy = derive_operational_state_and_policy(
        start_time=discovered.start_time,
        end_time=discovered.end_time,
        deployment_number=discovered.deployment_number,
    )
    has_date_evidence = (
        discovered.start_time is not None or discovered.end_time is not None
    )
    # Preemptive (no deployment_number) always uses derived PLANNED/CATALOG_ONLY.
    if discovered.deployment_number is None:
        return derived_state.value, derived_policy.value

    # WGMS/legacy past folders often set COMPLETED with no dates — honor that
    # when ST is not the observer (create path / non-authority adapters).
    if not has_date_evidence and discovered.operational_state is not None:
        state_value = _enum_value(discovered.operational_state)
        adapter_policy = (
            _enum_value(discovered.sync_policy) if discovered.sync_policy else None
        )
        if adapter_policy == CatalogSyncPolicy.CONTINUOUS.value and not allow_continuous:
            adapter_policy = None
        if adapter_policy is not None:
            return state_value, adapter_policy
        if state_value == CatalogOperationalState.COMPLETED.value:
            return state_value, CatalogSyncPolicy.ON_DEMAND.value
        return state_value, CatalogSyncPolicy.CATALOG_ONLY.value

    return derived_state.value, derived_policy.value


def _resolve_sync_policy(
    *,
    operational_state: str,
    derived_policy: str,
    existing_policy: Optional[str] = None,
    discovered_policy: Optional[str] = None,
) -> str:
    """Preserve CONTINUOUS enrollment while ACTIVE; drop to ON_DEMAND when done."""
    if operational_state == CatalogOperationalState.COMPLETED.value:
        return CatalogSyncPolicy.ON_DEMAND.value
    if operational_state == CatalogOperationalState.ARCHIVED.value:
        return CatalogSyncPolicy.CATALOG_ONLY.value
    # Seed or preserve enrollment for active (and planned) missions.
    if existing_policy == CatalogSyncPolicy.CONTINUOUS.value:
        return CatalogSyncPolicy.CONTINUOUS.value
    if discovered_policy == CatalogSyncPolicy.CONTINUOUS.value:
        return CatalogSyncPolicy.CONTINUOUS.value
    return derived_policy


def _create_mission(
    session: Session,
    discovered: DiscoveredMission,
    platform: Optional[CatalogPlatform],
    *,
    dry_run: bool,
    counts: ReconcileCounts,
    manifest: ProvidersManifest,
) -> CatalogMission:
    now = _utcnow()
    owner = None
    prefix = None
    if discovered.platform:
        owner = discovered.platform.owner_organization
        prefix = discovered.platform.data_prefix or discovered.platform.canonical_name
    fingerprint = mission_fingerprint(
        owner_organization=owner,
        platform_prefix=prefix,
        start=discovered.start_time,
        deployment_number=discovered.deployment_number,
    )
    may_seed = _may_seed_enrollment(discovered, manifest)
    discovered_policy = (
        _enum_value(discovered.sync_policy) if discovered.sync_policy else None
    )
    if discovered_policy == CatalogSyncPolicy.CONTINUOUS.value and not may_seed:
        discovered_policy = None
    state_value, derived_policy = _apply_lifecycle_fields(
        discovered, allow_continuous=may_seed
    )
    policy_value = _resolve_sync_policy(
        operational_state=state_value,
        derived_policy=derived_policy,
        discovered_policy=discovered_policy,
    )

    mission = CatalogMission(
        id=str(uuid.uuid4()),
        platform_id=platform.id if platform and getattr(platform, "id", None) else None,
        title=discovered.title,
        deployment_number=discovered.deployment_number,
        start_time=discovered.start_time,
        end_time=discovered.end_time,
        operational_state=state_value,
        sync_policy=policy_value,
        provenance=discovered.provider_key,
        first_seen_at=now,
        last_seen_at=now,
        metadata_json={
            **(discovered.metadata or {}),
            **({"fingerprint": fingerprint} if fingerprint else {}),
            **({"owner_organization": owner} if owner else {}),
        },
        created_at_utc=now,
        updated_at_utc=now,
    )
    counts.missions_created += 1
    if not dry_run:
        session.add(mission)
        session.flush()
    return mission


def _update_mission_from_discovery(
    session: Session,
    mission: CatalogMission,
    discovered: DiscoveredMission,
    platform: Optional[CatalogPlatform],
    *,
    dry_run: bool,
    manifest: ProvidersManifest,
) -> None:
    """Update mission fields.

    Only the lifecycle-authority provider (Sensor Tracker) may set/clear dates
    and drive operational_state. Other providers update sources/identities and
    may seed ``sync_policy=CONTINUOUS`` enrollment without touching dates.
    """
    if dry_run:
        return
    now = _utcnow()
    is_authority = _is_lifecycle_authority(discovered, manifest)
    may_seed = _may_seed_enrollment(discovered, manifest)
    discovered_policy = (
        _enum_value(discovered.sync_policy) if discovered.sync_policy else None
    )
    if discovered_policy == CatalogSyncPolicy.CONTINUOUS.value and not may_seed:
        # WGMS realtime folders emit CONTINUOUS but are data location only.
        discovered_policy = None

    if is_authority:
        # ST dates win, including None when ST reopens a deployment.
        if discovered.start_time is not None:
            mission.start_time = discovered.start_time
        mission.end_time = discovered.end_time
        state_value, derived_policy = _apply_lifecycle_fields(
            discovered, allow_continuous=may_seed
        )
        mission.operational_state = state_value
        mission.sync_policy = _resolve_sync_policy(
            operational_state=state_value,
            derived_policy=derived_policy,
            existing_policy=mission.sync_policy,
            discovered_policy=discovered_policy,
        )
        if discovered.deployment_number is not None:
            mission.deployment_number = discovered.deployment_number
    else:
        # Non-authority: never wipe dates or re-derive lifecycle.
        if discovered.deployment_number is not None and mission.deployment_number is None:
            mission.deployment_number = discovered.deployment_number
        # Enrollment seed: legacy_env CONTINUOUS only, while mission stays ACTIVE.
        if (
            discovered_policy == CatalogSyncPolicy.CONTINUOUS.value
            and mission.operational_state == CatalogOperationalState.ACTIVE.value
        ):
            mission.sync_policy = CatalogSyncPolicy.CONTINUOUS.value

    if not mission.has_manual_overrides:
        mission.title = discovered.title or mission.title
        if platform and getattr(platform, "id", None):
            mission.platform_id = platform.id

    meta = dict(mission.metadata_json or {})
    meta.update(discovered.metadata or {})
    owner = _owner_org_for_discovered(discovered)
    prefix = None
    if discovered.platform:
        prefix = discovered.platform.data_prefix or discovered.platform.canonical_name
    fingerprint = mission_fingerprint(
        owner_organization=owner,
        platform_prefix=prefix,
        start=discovered.start_time or mission.start_time,
        deployment_number=discovered.deployment_number
        if discovered.deployment_number is not None
        else mission.deployment_number,
    )
    if fingerprint:
        meta["fingerprint"] = fingerprint
    if owner:
        meta["owner_organization"] = owner
    mission.metadata_json = meta
    mission.last_seen_at = now
    mission.updated_at_utc = now
    session.add(mission)


def reconcile_batches(
    session: Session,
    batches: List[DiscoveryBatch],
    manifest: ProvidersManifest,
    *,
    dry_run: bool = False,
) -> ReconcileResult:
    """Apply discovery batches to the catalog.

    Never hard-deletes. Marks sources stale after consecutive misses.
    """
    counts = ReconcileCounts()
    conflicts: List[str] = []
    errors: List[str] = []
    seen_source_keys: set[Tuple[str, str, str]] = set()
    now = _utcnow()

    for batch in batches:
        errors.extend(batch.errors or [])
        for discovered in batch.missions:
            counts.discovered += 1
            try:
                platform = None
                if discovered.platform:
                    if not discovered.platform.platform_family:
                        if manifest.allowed_platform_models:
                            model = (discovered.platform.metadata or {}).get("st_model")
                            discovered.platform.platform_family = manifest.family_for_model(
                                model
                            )
                        if not discovered.platform.platform_family:
                            discovered.platform.platform_family = classify_platform_family(
                                discovered.platform.canonical_name,
                                wave_glider_prefixes=manifest.wave_glider_prefixes,
                                slocum_known_names=manifest.slocum_known_names,
                            )
                    platform = _get_or_create_platform(
                        session, discovered.platform, dry_run=dry_run, counts=counts
                    )

                mission, method = _resolve_mission_for_discovery(
                    session, discovered, conflicts=conflicts
                )
                if mission is None:
                    mission = _create_mission(
                        session,
                        discovered,
                        platform,
                        dry_run=dry_run,
                        counts=counts,
                        manifest=manifest,
                    )
                else:
                    counts.missions_updated += 1
                    _update_mission_from_discovery(
                        session,
                        mission,
                        discovered,
                        platform,
                        dry_run=dry_run,
                        manifest=manifest,
                    )

                mission_id = mission.id
                _upsert_identities(
                    session,
                    mission_id,
                    discovered,
                    dry_run=dry_run,
                    counts=counts,
                )
                for source in discovered.sources:
                    _upsert_source(
                        session,
                        source,
                        mission_id=mission_id,
                        match_status=CatalogMatchStatus.LINKED.value,
                        dry_run=dry_run,
                        counts=counts,
                        seen_source_keys=seen_source_keys,
                    )
            except Exception as exc:
                logger.exception("Reconcile mission failed: %s", exc)
                counts.failed += 1
                errors.append(str(exc))

        for orphan in batch.orphan_sources:
            counts.discovered += 1
            try:
                existing = _source_lookup(
                    session,
                    orphan.provider_key,
                    orphan.collection or "",
                    orphan.external_ref,
                )
                mission_id = existing.mission_id if existing else None
                status = (
                    CatalogMatchStatus.LINKED.value
                    if mission_id
                    else CatalogMatchStatus.UNMATCHED.value
                )
                # Fingerprint auto-link for unmatched inventory only (never invents missions).
                if mission_id is None and orphan.deployment_number and orphan.start_time:
                    fingerprint = mission_fingerprint(
                        owner_organization=orphan.owner_organization,
                        platform_prefix=orphan.platform_hint,
                        start=orphan.start_time,
                        deployment_number=orphan.deployment_number,
                    )
                    if fingerprint:
                        linked = _fingerprint_lookup(session, fingerprint)
                        if linked:
                            mission_id = linked.id
                            status = CatalogMatchStatus.LINKED.value
                # Also try global deployment_code when orphan has a number
                if mission_id is None and orphan.deployment_number is not None:
                    code_hit = _global_identity_lookup(
                        session,
                        CatalogIdentityKind.DEPLOYMENT_CODE.value,
                        f"m{int(orphan.deployment_number)}",
                        owner_organization=orphan.owner_organization,
                    )
                    if code_hit:
                        mission_id = code_hit.mission_id
                        status = CatalogMatchStatus.LINKED.value
                _upsert_source(
                    session,
                    orphan,
                    mission_id=mission_id,
                    match_status=status,
                    dry_run=dry_run,
                    counts=counts,
                    seen_source_keys=seen_source_keys,
                )
            except Exception as exc:
                logger.exception("Reconcile orphan source failed: %s", exc)
                counts.failed += 1
                errors.append(str(exc))

    enabled_provider_keys = {p.key for p in manifest.providers if p.enabled}
    existing_sources = session.exec(select(CatalogMissionSource)).all()
    for source in existing_sources:
        if source.provider_key not in enabled_provider_keys:
            continue
        key = (source.provider_key, source.collection or "", source.external_ref)
        if key in seen_source_keys:
            continue
        if dry_run and not seen_source_keys:
            continue
        if not dry_run:
            source.consecutive_misses = int(source.consecutive_misses or 0) + 1
            if source.consecutive_misses >= manifest.stale_miss_threshold:
                source.match_status = CatalogMatchStatus.STALE.value
                counts.stale += 1
            source.updated_at_utc = now
            session.add(source)

    counts.conflicts += len(conflicts)
    if not dry_run:
        session.commit()

    summary = (
        f"{'Dry-run' if dry_run else 'Applied'}: discovered={counts.discovered} "
        f"created={counts.missions_created} updated={counts.missions_updated} "
        f"linked={counts.sources_linked} unmatched={counts.sources_unmatched} "
        f"conflicts={counts.conflicts} stale={counts.stale} failed={counts.failed}"
    )
    return ReconcileResult(
        dry_run=dry_run,
        counts=counts,
        conflicts=conflicts,
        errors=errors,
        summary=summary,
    )
