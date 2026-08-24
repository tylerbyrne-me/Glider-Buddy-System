"""WGMS remote folder discovery adapter."""

from __future__ import annotations

import logging
import re
from typing import List, Set

import httpx

from app.core.mission_catalog.naming import parse_wgms_folder_name
from app.core.mission_catalog.providers_config import (
    ProviderSpec,
    ProvidersManifest,
    resolve_provider_base_url,
)
from app.core.mission_catalog.schemas import (
    DiscoveredIdentity,
    DiscoveredMission,
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

logger = logging.getLogger(__name__)

_FOLDER_PATTERNS = [
    r"<([mM]\d+-[A-Z0-9]+)/?>",
    r"<([mM]\d+-[^>]+)/?>",
    r"<([mM]\d+[^>]*)/?>",
    r'href=["\']([mM]\d+[^"\']*)["\']',
]


def _discover_folders(listing_html: str) -> List[str]:
    excluded = {"parent", "directory", "index", "..", ".", "", "private"}
    folders: Set[str] = set()
    for pattern in _FOLDER_PATTERNS:
        for match in re.findall(pattern, listing_html, re.IGNORECASE):
            folder_name = match.strip().rstrip("/")
            if folder_name.lower() in excluded:
                continue
            if re.match(r"^m\d+", folder_name, re.IGNORECASE):
                folders.add(folder_name)

    def sort_key(name: str):
        m = re.match(r"^m(\d+)", name, re.IGNORECASE)
        return (int(m.group(1)) if m else 9999, name.lower())

    return sorted(folders, key=sort_key)


async def discover_wgms_remote(
    provider: ProviderSpec,
    manifest: ProvidersManifest,
) -> DiscoveryBatch:
    """Discover mission folders under configured WGMS collections."""
    batch = DiscoveryBatch(provider_key=provider.key, connector=provider.connector)
    base = resolve_provider_base_url(provider)
    if not base:
        batch.errors.append(f"No base URL for provider {provider.key}")
        return batch

    collections = provider.collections or [
        "output_realtime_missions",
        "output_past_missions",
    ]
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for collection in collections:
            url = f"{base.rstrip('/')}/{collection.strip('/')}/"
            try:
                response = await client.get(url)
                response.raise_for_status()
            except Exception as exc:
                logger.warning("WGMS listing failed for %s: %s", url, exc)
                batch.errors.append(f"{collection}: {exc}")
                continue

            folders = _discover_folders(response.text)
            is_realtime = "realtime" in collection.lower()
            for folder in folders:
                code, vehicle = parse_wgms_folder_name(folder)
                deployment_number = None
                if code and code.lower().startswith("m"):
                    try:
                        deployment_number = int(code[1:])
                    except ValueError:
                        deployment_number = None

                source = DiscoveredSource(
                    provider_key=provider.key,
                    source_kind=CatalogSourceKind.WGMS_REMOTE,
                    collection=collection.strip("/"),
                    external_ref=folder,
                    source_variant=(
                        CatalogSourceVariant.REALTIME
                        if is_realtime
                        else CatalogSourceVariant.UNKNOWN
                    ),
                    capabilities=["track", "telemetry"],
                    priority=20 if is_realtime else 40,
                    is_verified=True,
                    platform_hint=vehicle,
                    platform_family_hint="wave_glider",
                    deployment_number=deployment_number,
                    title=folder,
                    owner_organization=provider.organization,
                    metadata={"vehicle_hint": vehicle},
                )

                if deployment_number is None:
                    batch.orphan_sources.append(source)
                    continue

                identities = [
                    DiscoveredIdentity(
                        provider_key=provider.key,
                        identity_kind=CatalogIdentityKind.WGMS_FOLDER,
                        external_id=folder,
                    ),
                    DiscoveredIdentity(
                        provider_key=provider.key,
                        identity_kind=CatalogIdentityKind.DEPLOYMENT_CODE,
                        external_id=f"m{deployment_number}",
                    ),
                ]
                batch.missions.append(
                    DiscoveredMission(
                        provider_key=provider.key,
                        title=folder,
                        deployment_number=deployment_number,
                        operational_state=(
                            CatalogOperationalState.ACTIVE
                            if is_realtime
                            else CatalogOperationalState.COMPLETED
                        ),
                        sync_policy=(
                            CatalogSyncPolicy.CONTINUOUS
                            if is_realtime
                            else CatalogSyncPolicy.CATALOG_ONLY
                        ),
                        identities=identities,
                        sources=[source],
                        metadata={"vehicle_hint": vehicle},
                    )
                )

    logger.info(
        "WGMS discovery %s: missions=%d orphans=%d",
        provider.key,
        len(batch.missions),
        len(batch.orphan_sources),
    )
    return batch
