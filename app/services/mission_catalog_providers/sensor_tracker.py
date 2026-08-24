"""Sensor Tracker lightweight discovery adapter (no instrument enrichment)."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from app.core.mission_catalog.lifecycle import derive_operational_state_and_policy
from app.core.mission_catalog.naming import (
    classify_platform_family,
    normalize_platform_prefix,
)
from app.core.mission_catalog.providers_config import ProviderSpec, ProvidersManifest
from app.core.mission_catalog.schemas import (
    DiscoveredIdentity,
    DiscoveredMission,
    DiscoveredPlatform,
    DiscoveryBatch,
)
from app.core.models.enums import CatalogIdentityKind

logger = logging.getLogger(__name__)


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return pd.to_datetime(value, utc=True).to_pydatetime()
    except Exception:
        return None


def _as_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_platform_lookups(
    platforms: List[Dict[str, Any]],
    platform_types: List[Dict[str, Any]],
) -> Tuple[Dict[int, Dict[str, Any]], Dict[int, str]]:
    """Return (platform_id -> platform dict, type_id -> model name)."""
    type_by_id: Dict[int, str] = {}
    for row in platform_types:
        type_id = _as_int(row.get("id") or row.get("pk"))
        model_name = row.get("model") or row.get("name") or row.get("platform_type")
        if type_id is not None and model_name:
            type_by_id[type_id] = str(model_name).strip()

    platform_by_id: Dict[int, Dict[str, Any]] = {}
    for row in platforms:
        pid = _as_int(row.get("id") or row.get("pk"))
        if pid is not None:
            platform_by_id[pid] = row
    return platform_by_id, type_by_id


def _resolve_platform_model(
    deployment: Dict[str, Any],
    platform_by_id: Dict[int, Dict[str, Any]],
    type_by_id: Dict[int, str],
) -> Tuple[Optional[str], Optional[str], Optional[int], Optional[int], Optional[str]]:
    """Return (platform_name, model_name, st_platform_id, st_type_id, raw_note)."""
    platform_raw = deployment.get("platform")
    platform_id = None
    platform_name = deployment.get("platform_name")
    type_id = _as_int(deployment.get("platform_type"))
    nested: Optional[Dict[str, Any]] = None

    if isinstance(platform_raw, dict):
        nested = platform_raw
        platform_id = _as_int(platform_raw.get("id") or platform_raw.get("pk"))
        platform_name = (
            platform_raw.get("name")
            or platform_raw.get("platform_name")
            or platform_name
        )
        type_id = _as_int(platform_raw.get("platform_type") or type_id)
    else:
        platform_id = _as_int(platform_raw)

    if platform_id is not None and platform_id in platform_by_id:
        nested = platform_by_id[platform_id]
        platform_name = nested.get("name") or nested.get("platform_name") or platform_name
        type_id = _as_int(nested.get("platform_type") or type_id)

    model_name = None
    if type_id is not None:
        model_name = type_by_id.get(type_id)
    if not model_name and isinstance(nested, dict):
        maybe = nested.get("model") or nested.get("platform_type_name")
        if maybe and not isinstance(maybe, (int, float)):
            model_name = str(maybe).strip()

    return (
        str(platform_name).strip() if platform_name else None,
        model_name,
        platform_id,
        type_id,
        None,
    )


def _platform_from_deployment(
    *,
    platform_name: Optional[str],
    model_name: Optional[str],
    st_platform_id: Optional[int],
    st_type_id: Optional[int],
    organization: str,
    manifest: ProvidersManifest,
    family: Optional[str],
) -> Optional[DiscoveredPlatform]:
    if not platform_name:
        return None
    return DiscoveredPlatform(
        canonical_name=platform_name,
        platform_family=family,
        owner_organization=organization,
        data_prefix=normalize_platform_prefix(platform_name),
        metadata={
            "st_platform_id": st_platform_id,
            "st_platform_type_id": st_type_id,
            "st_model": model_name,
        },
    )


async def discover_sensor_tracker(
    provider: ProviderSpec,
    manifest: ProvidersManifest,
) -> DiscoveryBatch:
    """List deployments from Sensor Tracker without deep instrument fetches."""
    from app.services.sensor_tracker_service import (
        SENSOR_TRACKER_AVAILABLE,
        SensorTrackerService,
    )

    batch = DiscoveryBatch(
        provider_key=provider.key,
        connector=provider.connector,
    )
    if not SENSOR_TRACKER_AVAILABLE:
        batch.errors.append("sensor_tracker_client not available")
        return batch

    try:
        service = SensorTrackerService(skip_auth=True)
        deployments = await service.list_all_deployments()
        platforms = await service.list_platforms()
        platform_types = await service.list_platform_types()
    except Exception as exc:
        logger.exception("Sensor Tracker list_all_deployments failed")
        batch.errors.append(str(exc))
        return batch

    if not isinstance(deployments, list):
        batch.errors.append("Unexpected Sensor Tracker deployments payload")
        return batch

    platform_by_id, type_by_id = _build_platform_lookups(platforms, platform_types)
    skipped_non_glider = 0
    model_missing_fallback = 0
    preemptive = 0

    for deployment in deployments:
        if not isinstance(deployment, dict):
            continue
        deployment_number_int = _as_int(deployment.get("deployment_number"))
        st_id = (
            deployment.get("id")
            or deployment.get("pk")
            or deployment.get("deployment_id")
        )
        start_time = _parse_dt(deployment.get("start_time"))
        end_time = _parse_dt(deployment.get("end_time"))

        (
            platform_name,
            model_name,
            st_platform_id,
            st_type_id,
            _,
        ) = _resolve_platform_model(deployment, platform_by_id, type_by_id)

        family = manifest.family_for_model(model_name)
        if family is None and model_name:
            # Model present but not allowlisted → drop
            skipped_non_glider += 1
            continue
        if family is None:
            # Model missing: name heuristic fallback for glider families only
            family = classify_platform_family(
                platform_name,
                wave_glider_prefixes=manifest.wave_glider_prefixes,
                slocum_known_names=manifest.slocum_known_names,
            )
            if family in ("wave_glider", "slocum"):
                model_missing_fallback += 1
            else:
                skipped_non_glider += 1
                continue

        operational_state, sync_policy = derive_operational_state_and_policy(
            start_time=start_time,
            end_time=end_time,
            deployment_number=deployment_number_int,
        )
        if deployment_number_int is None:
            preemptive += 1

        platform = _platform_from_deployment(
            platform_name=platform_name,
            model_name=model_name,
            st_platform_id=st_platform_id,
            st_type_id=st_type_id,
            organization=provider.organization,
            manifest=manifest,
            family=family,
        )

        identities: List[DiscoveredIdentity] = []
        if st_id is not None:
            identities.append(
                DiscoveredIdentity(
                    provider_key=provider.key,
                    identity_kind=CatalogIdentityKind.SENSOR_TRACKER_DEPLOYMENT_ID,
                    external_id=str(st_id),
                    is_canonical=True,
                )
            )
        # Never invent m{n} without a deployment_number (preemptive staging rows).
        if deployment_number_int is not None:
            identities.append(
                DiscoveredIdentity(
                    provider_key=provider.key,
                    identity_kind=CatalogIdentityKind.SENSOR_TRACKER_DEPLOYMENT_NUMBER,
                    external_id=str(deployment_number_int),
                )
            )
            identities.append(
                DiscoveredIdentity(
                    provider_key=provider.key,
                    identity_kind=CatalogIdentityKind.DEPLOYMENT_CODE,
                    external_id=f"m{deployment_number_int}",
                )
            )

        title = deployment.get("title")
        if not title and deployment_number_int is not None:
            title = f"m{deployment_number_int}"
        elif not title and st_id is not None:
            title = f"st-deployment-{st_id}"

        batch.missions.append(
            DiscoveredMission(
                provider_key=provider.key,
                title=str(title) if title else None,
                deployment_number=deployment_number_int,
                start_time=start_time,
                end_time=end_time,
                operational_state=operational_state,
                sync_policy=sync_policy,
                platform=platform,
                identities=identities,
                sources=[],
                metadata={
                    "raw_keys": sorted(str(k) for k in deployment.keys()),
                    "st_preemptive": deployment_number_int is None,
                    "st_model": model_name,
                    "st_platform_id": st_platform_id,
                },
            )
        )

    logger.info(
        "Sensor Tracker discovery %s: missions=%d skipped_non_glider=%d "
        "model_missing_fallback=%d preemptive_no_mid=%d",
        provider.key,
        len(batch.missions),
        skipped_non_glider,
        model_missing_fallback,
        preemptive,
    )
    return batch
