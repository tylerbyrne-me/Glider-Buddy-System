"""Catalog enablement: env keys as the live sync gate during cutover."""

from __future__ import annotations

import logging
from typing import List, Optional, Set

from sqlmodel import Session, select

from app.config import settings
from app.core.mission_aliases import (
    configured_slocum_dataset_keys,
    resolve_slocum_dataset_id,
)
from app.core.models.database import CatalogExternalIdentity, CatalogMission
from app.core.models.enums import CatalogIdentityKind
from app.core.utils import deployment_mission_code_from_mission_id, slocum_mission_key
from app.feature_toggle_config import DEFAULT_FEATURE_TOGGLES

logger = logging.getLogger(__name__)


def _mission_catalog_enabled() -> bool:
    try:
        from app.core.infra import feature_toggles

        return bool(feature_toggles.is_feature_enabled("mission_catalog"))
    except Exception:
        return bool(DEFAULT_FEATURE_TOGGLES.get("mission_catalog", True))


def _catalog_deployment_codes(session: Session) -> Set[str]:
    codes: Set[str] = set()
    for mission in session.exec(select(CatalogMission)).all():
        if mission.deployment_number is not None:
            codes.add(f"m{int(mission.deployment_number)}")
    for identity in session.exec(
        select(CatalogExternalIdentity).where(
            CatalogExternalIdentity.identity_kind
            == CatalogIdentityKind.DEPLOYMENT_CODE.value
        )
    ).all():
        if identity.external_id:
            codes.add(identity.external_id.strip().lower())
    return codes


def _catalog_slocum_mission_keys(session: Session) -> Set[str]:
    keys: Set[str] = set()
    for identity in session.exec(
        select(CatalogExternalIdentity).where(
            CatalogExternalIdentity.identity_kind
            == CatalogIdentityKind.ERDDAP_MISSION_KEY.value
        )
    ).all():
        if identity.external_id:
            keys.add(identity.external_id.strip())
    for identity in session.exec(
        select(CatalogExternalIdentity).where(
            CatalogExternalIdentity.identity_kind
            == CatalogIdentityKind.ERDDAP_DATASET_ID.value
        )
    ).all():
        if identity.external_id:
            keys.add(slocum_mission_key(identity.external_id))
    return {k for k in keys if k}


def env_wave_glider_active_keys() -> List[str]:
    return [m.strip() for m in (settings.active_realtime_missions or []) if m and str(m).strip()]


def env_slocum_active_keys() -> List[str]:
    return configured_slocum_dataset_keys(settings.active_slocum_datasets)


def env_slocum_historical_keys() -> List[str]:
    return configured_slocum_dataset_keys(settings.historical_slocum_datasets)


def list_catalog_sync_targets(
    platform_family: str,
    session: Optional[Session] = None,
    *,
    operational_state: str = "active",
) -> List[str]:
    """Return sync targets for a platform family.

    During cutover this is always the **exact env key strings** for the live
    subset. Catalog-only extras (ST-open not in env, preemptive no-mission-id)
    are never added. If catalog is empty/disabled, env lists are returned
    unchanged (fail-safe).
    """
    family = (platform_family or "").strip().lower()
    if family in ("wave_glider", "wg", "wave"):
        env_keys = env_wave_glider_active_keys()
    elif family in ("slocum",):
        if operational_state == "completed":
            env_keys = env_slocum_historical_keys()
        else:
            env_keys = env_slocum_active_keys()
    else:
        logger.warning("Unknown platform_family for enablement: %s", platform_family)
        return []

    if not _mission_catalog_enabled() or session is None:
        return list(env_keys)

    mission_count = len(list(session.exec(select(CatalogMission)).all()))
    if mission_count == 0:
        return list(env_keys)

    # Parity rail: keep env strings; log gaps vs catalog identities.
    if family in ("wave_glider", "wg", "wave"):
        codes = _catalog_deployment_codes(session)
        missing = []
        for key in env_keys:
            code = deployment_mission_code_from_mission_id(key)
            if code and code.lower() not in {c.lower() for c in codes}:
                missing.append(key)
        if missing:
            logger.warning(
                "Catalog enablement: env WG keys missing from catalog identities: %s",
                missing,
            )
    else:
        catalog_keys = _catalog_slocum_mission_keys(session)
        missing = []
        for key in env_keys:
            canonical = resolve_slocum_dataset_id(key)
            mkey = slocum_mission_key(canonical) or canonical
            if mkey not in catalog_keys and canonical not in catalog_keys:
                missing.append(key)
        if missing:
            logger.warning(
                "Catalog enablement: env Slocum keys missing from catalog identities: %s",
                missing,
            )

    return list(env_keys)


def log_enablement_parity(session: Optional[Session] = None) -> None:
    """Log env vs catalog counts for soak monitoring (read-only)."""
    wg = env_wave_glider_active_keys()
    sl = env_slocum_active_keys()
    if session is None:
        logger.info(
            "Catalog enablement parity: env_wg=%d env_slocum=%d (no session)",
            len(wg),
            len(sl),
        )
        return
    codes = _catalog_deployment_codes(session)
    slocum_keys = _catalog_slocum_mission_keys(session)
    logger.info(
        "Catalog enablement parity: env_wg=%d catalog_codes=%d env_slocum=%d catalog_slocum_keys=%d",
        len(wg),
        len(codes),
        len(sl),
        len(slocum_keys),
    )
