"""Catalog enablement: env override, then ACTIVE∧CONTINUOUS enrollment when env is empty."""

from __future__ import annotations

import logging
from typing import List, Optional, Set

from sqlmodel import Session, select

from app.config import settings
from app.core.mission_aliases import (
    configured_slocum_dataset_keys,
    resolve_slocum_dataset_id,
    reverse_slocum_alias,
)
from app.core.models.database import (
    CatalogExternalIdentity,
    CatalogMission,
    CatalogMissionSource,
    MissionOverview,
    SlocumDeployment,
)
from app.core.models.enums import (
    CatalogIdentityKind,
    CatalogOperationalState,
    CatalogSyncPolicy,
)
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


def _log_env_catalog_parity(family: str, env_keys: List[str], session: Session) -> None:
    """Parity rail: keep env strings; log gaps vs catalog identities."""
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
        return

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


def _enrolled_active_missions(session: Session) -> List[CatalogMission]:
    """Catalog missions that are ACTIVE and enrolled (CONTINUOUS)."""
    return list(
        session.exec(
            select(CatalogMission).where(
                CatalogMission.operational_state
                == CatalogOperationalState.ACTIVE.value,
                CatalogMission.sync_policy == CatalogSyncPolicy.CONTINUOUS.value,
            )
        ).all()
    )


def _has_realtime_wgms_source(session: Session, mission_id: str) -> bool:
    sources = session.exec(
        select(CatalogMissionSource).where(
            CatalogMissionSource.mission_id == mission_id,
            CatalogMissionSource.source_kind == "wgms_remote",
            CatalogMissionSource.enabled == True,  # noqa: E712
        )
    ).all()
    for source in sources:
        collection = (source.collection or "").strip().lower()
        variant = (source.source_variant or "").strip().lower()
        if "realtime" in collection or variant == "realtime":
            return True
    return False


def _live_wave_glider_keys(session: Session) -> List[str]:
    """Enrolled ACTIVE WG keys with a realtime WGMS source + linked overview.

    Membership = catalog ACTIVE ∧ CONTINUOUS. Prefer folder-style overview PK
    (m###-SV3-####). Unenrolled in-water missions (e.g. m230) stay out.
    """
    from app.core.mission_catalog.live_link import prefer_wave_glider_overview

    enrolled = {
        mission.id: mission
        for mission in _enrolled_active_missions(session)
        if mission.id and _has_realtime_wgms_source(session, mission.id)
    }
    if not enrolled:
        return []

    by_catalog: dict[str, list[MissionOverview]] = {}
    for overview in session.exec(select(MissionOverview)).all():
        catalog_id = getattr(overview, "catalog_mission_id", None)
        if not catalog_id or catalog_id not in enrolled:
            continue
        by_catalog.setdefault(catalog_id, []).append(overview)

    keys: List[str] = []
    for catalog_id, siblings in by_catalog.items():
        preferred = prefer_wave_glider_overview(siblings)
        if preferred is None:
            logger.warning(
                "Catalog enablement: skipping ambiguous WG overviews for "
                "catalog_mission_id=%s: %s",
                catalog_id,
                [o.mission_id for o in siblings],
            )
            continue
        if preferred.mission_id:
            keys.append(str(preferred.mission_id).strip())
    keys = [k for k in keys if k]
    keys.sort()
    return keys


def _slocum_live_key(deployment: SlocumDeployment) -> Optional[str]:
    dataset = (deployment.erddap_dataset_id or "").strip()
    if dataset:
        alias = reverse_slocum_alias(dataset)
        return (alias or dataset).strip() or None
    mission_key = (deployment.mission_key or "").strip()
    return mission_key or None


def _live_slocum_keys(session: Session, *, is_active: bool) -> List[str]:
    """Slocum keys from live deployment rows.

    Active: require ``is_active`` and ``catalog_mission_id`` ∈ enrolled
    (ACTIVE ∧ CONTINUOUS). Historical: inactive deployments (enrollment not
    required for historical warm lists).
    """
    if not is_active:
        deployments = session.exec(
            select(SlocumDeployment).where(
                SlocumDeployment.is_active == False  # noqa: E712
            )
        ).all()
        keys: List[str] = []
        seen: Set[str] = set()
        for deployment in deployments:
            key = _slocum_live_key(deployment)
            if not key or key in seen:
                continue
            seen.add(key)
            keys.append(key)
        keys.sort()
        return keys

    enrolled_ids = {m.id for m in _enrolled_active_missions(session) if m.id}
    if not enrolled_ids:
        return []

    deployments = session.exec(
        select(SlocumDeployment).where(
            SlocumDeployment.is_active == True  # noqa: E712
        )
    ).all()
    keys: List[str] = []
    seen: Set[str] = set()
    for deployment in deployments:
        catalog_id = getattr(deployment, "catalog_mission_id", None)
        if not catalog_id or catalog_id not in enrolled_ids:
            continue
        key = _slocum_live_key(deployment)
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    keys.sort()
    return keys


def list_catalog_sync_targets(
    platform_family: str,
    session: Optional[Session] = None,
    *,
    operational_state: str = "active",
) -> List[str]:
    """Return sync targets for a platform family.

    Membership rules:
    - Non-empty ``ACTIVE_*`` / historical env lists win (override / fail-safe).
    - When the matching env list is **empty** and catalog is enabled, derive keys
      from enrolled catalog missions (ACTIVE ∧ CONTINUOUS) with live rows.
      Unenrolled ST-open missions (e.g. m230) never appear.
    - Catalog disabled / empty / no session → env list (possibly empty).
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

    if env_keys:
        _log_env_catalog_parity(family, env_keys, session)
        return list(env_keys)

    # Empty env → enrolled ACTIVE∧CONTINUOUS authority.
    if family in ("wave_glider", "wg", "wave"):
        live_keys = _live_wave_glider_keys(session)
        logger.info(
            "Catalog enablement: empty ACTIVE_REALTIME_MISSIONS; "
            "enrolled WG keys=%s",
            live_keys,
        )
        return live_keys

    want_active = operational_state != "completed"
    live_keys = _live_slocum_keys(session, is_active=want_active)
    logger.info(
        "Catalog enablement: empty Slocum env list (active=%s); enrolled keys=%s",
        want_active,
        live_keys,
    )
    return live_keys


def log_enablement_parity(session: Optional[Session] = None) -> None:
    """Log env vs catalog / enrolled counts for soak monitoring (read-only)."""
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
    enrolled = len(_enrolled_active_missions(session))
    live_wg = _live_wave_glider_keys(session) if not wg else []
    live_sl = _live_slocum_keys(session, is_active=True) if not sl else []
    logger.info(
        "Catalog enablement parity: env_wg=%d catalog_codes=%d env_slocum=%d "
        "catalog_slocum_keys=%d enrolled_active=%d live_wg=%d live_slocum=%d",
        len(wg),
        len(codes),
        len(sl),
        len(slocum_keys),
        enrolled,
        len(live_wg) if not wg else -1,
        len(live_sl) if not sl else -1,
    )


def resolve_active_wave_glider_keys(session: Optional[Session] = None) -> List[str]:
    """Resolve WG active keys via catalog enablement; env fallback on error."""
    try:
        if session is not None:
            return list(list_catalog_sync_targets("wave_glider", session))
        from app.core.infra.db import SQLModelSession, sqlite_engine

        with SQLModelSession(sqlite_engine) as sess:
            return list(list_catalog_sync_targets("wave_glider", sess))
    except Exception as exc:
        logger.warning(
            "Catalog enablement failed (%s); falling back to ACTIVE_REALTIME_MISSIONS",
            exc,
        )
        return env_wave_glider_active_keys()


def resolve_active_slocum_keys(session: Optional[Session] = None) -> List[str]:
    """Resolve Slocum active keys via catalog enablement; env fallback on error."""
    try:
        if session is not None:
            return list(list_catalog_sync_targets("slocum", session))
        from app.core.infra.db import SQLModelSession, sqlite_engine

        with SQLModelSession(sqlite_engine) as sess:
            return list(list_catalog_sync_targets("slocum", sess))
    except Exception as exc:
        logger.warning(
            "Catalog enablement failed (%s); falling back to ACTIVE_SLOCUM_DATASETS",
            exc,
        )
        return env_slocum_active_keys()
