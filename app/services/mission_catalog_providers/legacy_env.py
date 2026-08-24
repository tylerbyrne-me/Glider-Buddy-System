"""Legacy .env mission inventory backfill adapter."""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from app.config import settings
from app.core.mission_aliases import resolve_slocum_dataset_id
from app.core.mission_catalog.naming import parse_erddap_dataset_id, parse_wgms_folder_name
from app.core.mission_catalog.providers_config import ProviderSpec, ProvidersManifest
from app.core.mission_catalog.schemas import (
    DiscoveredIdentity,
    DiscoveredMission,
    DiscoveredPlatform,
    DiscoveredSource,
    DiscoveryBatch,
)
from app.core.models.enums import (
    CatalogIdentityKind,
    CatalogOperationalState,
    CatalogSourceKind,
    CatalogSourceVariant,
    CatalogSyncPolicy,
)
from app.core.utils import slocum_mission_key

logger = logging.getLogger(__name__)


def _variant(mode: Optional[str]) -> CatalogSourceVariant:
    if mode == "realtime":
        return CatalogSourceVariant.REALTIME
    if mode == "delayed":
        return CatalogSourceVariant.DELAYED
    return CatalogSourceVariant.UNKNOWN


def discover_legacy_env(
    provider: ProviderSpec,
    manifest: ProvidersManifest,
) -> DiscoveryBatch:
    """Import ACTIVE_*/HISTORICAL_*/alias maps into discovery records."""
    batch = DiscoveryBatch(provider_key=provider.key, connector=provider.connector)

    # Wave Glider active missions
    for mission_id in settings.active_realtime_missions or []:
        key = str(mission_id).strip()
        if not key:
            continue
        folder = settings.remote_mission_folder_map.get(key)
        if folder is None:
            # Try "1071 m169" style keys already in map by fuzzy match later
            for map_key, map_value in (settings.remote_mission_folder_map or {}).items():
                if key in map_key or map_key.endswith(key):
                    folder = map_value
                    break
        code_match = re.search(r"m(\d+)", key, re.IGNORECASE)
        deployment_number = int(code_match.group(1)) if code_match else None
        identities = [
            DiscoveredIdentity(
                provider_key=provider.key,
                identity_kind=CatalogIdentityKind.LEGACY_ENV_KEY,
                external_id=key,
                is_canonical=True,
            )
        ]
        if deployment_number is not None:
            identities.append(
                DiscoveredIdentity(
                    provider_key=provider.key,
                    identity_kind=CatalogIdentityKind.DEPLOYMENT_CODE,
                    external_id=f"m{deployment_number}",
                )
            )
        sources: List[DiscoveredSource] = []
        if folder:
            identities.append(
                DiscoveredIdentity(
                    provider_key=provider.key,
                    identity_kind=CatalogIdentityKind.WGMS_FOLDER,
                    external_id=folder,
                )
            )
            sources.append(
                DiscoveredSource(
                    provider_key="ceotr_wgms_remote",
                    source_kind=CatalogSourceKind.WGMS_REMOTE,
                    collection="output_realtime_missions",
                    external_ref=folder,
                    source_variant=CatalogSourceVariant.REALTIME,
                    capabilities=["track", "telemetry"],
                    priority=10,
                    is_verified=True,
                    platform_family_hint="wave_glider",
                    deployment_number=deployment_number,
                    owner_organization=provider.organization,
                    metadata={"provenance": "legacy_env"},
                )
            )
        batch.missions.append(
            DiscoveredMission(
                provider_key=provider.key,
                title=key,
                deployment_number=deployment_number,
                operational_state=CatalogOperationalState.ACTIVE,
                sync_policy=CatalogSyncPolicy.CONTINUOUS,
                platform=DiscoveredPlatform(
                    canonical_name=key,
                    platform_family="wave_glider",
                    owner_organization=provider.organization,
                ),
                identities=identities,
                sources=sources,
                metadata={"provenance": "legacy_env", "list": "ACTIVE_REALTIME_MISSIONS"},
            )
        )

    # Remaining folder map entries (historical / mapped)
    for map_key, folder in (settings.remote_mission_folder_map or {}).items():
        code, vehicle = parse_wgms_folder_name(str(folder))
        deployment_number = None
        if code and code.startswith("m"):
            try:
                deployment_number = int(code[1:])
            except ValueError:
                deployment_number = None
        # Skip if already covered by active list exact identity
        already = any(
            any(
                i.identity_kind == CatalogIdentityKind.LEGACY_ENV_KEY
                and i.external_id == str(map_key)
                for i in m.identities
            )
            for m in batch.missions
        )
        if already:
            continue
        batch.missions.append(
            DiscoveredMission(
                provider_key=provider.key,
                title=str(map_key),
                deployment_number=deployment_number,
                operational_state=CatalogOperationalState.COMPLETED,
                sync_policy=CatalogSyncPolicy.CATALOG_ONLY,
                platform=DiscoveredPlatform(
                    canonical_name=vehicle or str(map_key),
                    platform_family="wave_glider",
                    owner_organization=provider.organization,
                    data_prefix=None,
                ),
                identities=[
                    DiscoveredIdentity(
                        provider_key=provider.key,
                        identity_kind=CatalogIdentityKind.LEGACY_ENV_KEY,
                        external_id=str(map_key),
                    ),
                    DiscoveredIdentity(
                        provider_key=provider.key,
                        identity_kind=CatalogIdentityKind.WGMS_FOLDER,
                        external_id=str(folder),
                    ),
                ]
                + (
                    [
                        DiscoveredIdentity(
                            provider_key=provider.key,
                            identity_kind=CatalogIdentityKind.DEPLOYMENT_CODE,
                            external_id=f"m{deployment_number}",
                        )
                    ]
                    if deployment_number is not None
                    else []
                ),
                sources=[
                    DiscoveredSource(
                        provider_key="ceotr_wgms_remote",
                        source_kind=CatalogSourceKind.WGMS_REMOTE,
                        collection="output_past_missions",
                        external_ref=str(folder),
                        capabilities=["track", "telemetry"],
                        priority=40,
                        is_verified=True,
                        platform_family_hint="wave_glider",
                        deployment_number=deployment_number,
                        owner_organization=provider.organization,
                        metadata={"provenance": "legacy_env"},
                    )
                ],
                metadata={"provenance": "legacy_env", "list": "REMOTE_MISSION_FOLDER_MAP"},
            )
        )

    def _add_slocum(configured_key: str, *, active: bool) -> None:
        key = str(configured_key).strip()
        if not key:
            return
        canonical = resolve_slocum_dataset_id(key)
        parsed = parse_erddap_dataset_id(canonical)
        mission_key = slocum_mission_key(canonical) or canonical
        identities = [
            DiscoveredIdentity(
                provider_key=provider.key,
                identity_kind=CatalogIdentityKind.LEGACY_ENV_KEY,
                external_id=key,
            ),
            DiscoveredIdentity(
                provider_key=provider.key,
                identity_kind=CatalogIdentityKind.ERDDAP_DATASET_ID,
                external_id=canonical,
            ),
            DiscoveredIdentity(
                provider_key=provider.key,
                identity_kind=CatalogIdentityKind.ERDDAP_MISSION_KEY,
                external_id=mission_key,
            ),
        ]
        batch.missions.append(
            DiscoveredMission(
                provider_key=provider.key,
                title=key,
                deployment_number=parsed["deployment_number"] if parsed else None,
                operational_state=(
                    CatalogOperationalState.ACTIVE
                    if active
                    else CatalogOperationalState.COMPLETED
                ),
                sync_policy=(
                    CatalogSyncPolicy.CONTINUOUS
                    if active
                    else CatalogSyncPolicy.WARM
                ),
                platform=DiscoveredPlatform(
                    canonical_name=(parsed["prefix"] if parsed else key),
                    platform_family="slocum",
                    owner_organization=provider.organization,
                    data_prefix=(parsed["prefix"] if parsed else None),
                ),
                identities=identities,
                sources=[
                    DiscoveredSource(
                        provider_key="oceantrack_erddap",
                        source_kind=CatalogSourceKind.ERDDAP,
                        collection="tabledap",
                        external_ref=canonical,
                        source_variant=_variant(parsed.get("mode") if parsed else None),
                        capabilities=["track", "dashboard", "ctd"],
                        priority=10 if active else 50,
                        is_verified=False,
                        platform_hint=parsed["prefix"] if parsed else None,
                        platform_family_hint="slocum",
                        deployment_number=parsed["deployment_number"] if parsed else None,
                        owner_organization=provider.organization,
                        metadata={"provenance": "legacy_env", "configured_key": key},
                    )
                ],
                metadata={
                    "provenance": "legacy_env",
                    "list": "ACTIVE_SLOCUM_DATASETS" if active else "HISTORICAL_SLOCUM_DATASETS",
                },
            )
        )

    for key in settings.active_slocum_datasets or []:
        _add_slocum(key, active=True)
    for key in settings.historical_slocum_datasets or []:
        _add_slocum(key, active=False)

    logger.info("Legacy env discovery: %d missions", len(batch.missions))
    return batch
