"""Platform provisioning handlers (Wave Glider + Slocum)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from sqlmodel import Session, select

from app.core.mission_catalog.live_link import (
    prefer_slocum_deployment,
    prefer_wave_glider_overview,
)
from app.core.mission_catalog.provisioning import (
    ProvisioningResult,
    register_handler,
)
from app.core.models.database import (
    CatalogExternalIdentity,
    CatalogMission,
    CatalogMissionSource,
    CatalogPlatform,
    MissionOverview,
    SlocumDeployment,
)
from app.core.models.enums import CatalogIdentityKind, CatalogSourceVariant
from app.core.utils import deployment_mission_code_from_mission_id, slocum_mission_key

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _deployment_code(mission: CatalogMission, session: Session) -> Optional[str]:
    if mission.deployment_number is not None:
        return f"m{int(mission.deployment_number)}"
    identities = session.exec(
        select(CatalogExternalIdentity).where(
            CatalogExternalIdentity.mission_id == mission.id,
            CatalogExternalIdentity.identity_kind
            == CatalogIdentityKind.DEPLOYMENT_CODE.value,
        )
    ).all()
    if len(identities) == 1 and identities[0].external_id:
        return identities[0].external_id.strip().lower()
    return None


def _platform_serial(session: Session, mission: CatalogMission) -> Optional[str]:
    if not mission.platform_id:
        return None
    platform = session.get(CatalogPlatform, mission.platform_id)
    if not platform:
        return None
    name = (platform.canonical_name or "").strip()
    if name.upper().startswith("SV3-") or name.upper().startswith("SV2-"):
        return name
    prefix = (platform.data_prefix or "").strip()
    if prefix:
        return prefix
    return name or None


class WaveGliderHandler:
    family = "wave_glider"

    def readiness(
        self, session: Session, mission: CatalogMission
    ) -> tuple[str, List[str]]:
        reasons: List[str] = []
        if mission.operational_state == "planned":
            reasons.append("waiting_for_start")
        code = _deployment_code(mission, session)
        if not code:
            reasons.append("waiting_for_deployment_number")
        sources = list(
            session.exec(
                select(CatalogMissionSource).where(
                    CatalogMissionSource.mission_id == mission.id,
                    CatalogMissionSource.source_kind == "wgms_remote",
                    CatalogMissionSource.enabled == True,  # noqa: E712
                )
            ).all()
        )
        realtime = [
            s
            for s in sources
            if "realtime" in (s.collection or "").lower()
            or (s.source_variant or "").lower() == CatalogSourceVariant.REALTIME.value
        ]
        if not realtime:
            reasons.append("waiting_for_source")
        overviews = list(
            session.exec(
                select(MissionOverview).where(
                    MissionOverview.catalog_mission_id == mission.id
                )
            ).all()
        )
        if not overviews and code:
            # Also check legacy code siblings not yet linked
            siblings = [
                o
                for o in session.exec(select(MissionOverview)).all()
                if deployment_mission_code_from_mission_id(o.mission_id) == code
            ]
            preferred = prefer_wave_glider_overview(siblings)
            if siblings and preferred is None:
                reasons.append("ambiguous_identity")
            elif not siblings:
                reasons.append("waiting_for_live_row")
        if reasons:
            return reasons[0], reasons
        return "ready", []

    def provision(
        self, session: Session, mission: CatalogMission, *, dry_run: bool = False
    ) -> ProvisioningResult:
        ready, reasons = self.readiness(session, mission)
        result = ProvisioningResult(
            mission_id=mission.id,
            platform_family=self.family,
            readiness=ready,
            reasons=reasons,
        )
        if ready != "ready" and "waiting_for_live_row" not in reasons:
            return result

        code = _deployment_code(mission, session)
        if not code:
            result.readiness = "waiting_for_deployment_number"
            result.reasons.append("waiting_for_deployment_number")
            return result

        serial = _platform_serial(session, mission)
        preferred_key = f"{code}-{serial}" if serial and not serial.lower().startswith("m") else code
        if serial and ("SV3" in serial.upper() or "SV2" in serial.upper() or "DL" in serial.upper()):
            preferred_key = f"{code}-{serial}"

        existing = list(
            session.exec(
                select(MissionOverview).where(
                    MissionOverview.catalog_mission_id == mission.id
                )
            ).all()
        )
        if not existing:
            siblings = [
                o
                for o in session.exec(select(MissionOverview)).all()
                if deployment_mission_code_from_mission_id(o.mission_id) == code
            ]
            preferred = prefer_wave_glider_overview(siblings)
            if siblings and preferred is None:
                result.readiness = "ambiguous_identity"
                result.reasons.append("ambiguous_identity")
                return result
            if preferred is not None:
                if not dry_run:
                    preferred.catalog_mission_id = mission.id
                    preferred.updated_at_utc = _utcnow()
                    session.add(preferred)
                    session.commit()
                result.actions.append(f"linked_overview:{preferred.mission_id}")
                result.readiness = "ready"
                result.reasons = []
                return result

            # Create canonical overview when none exists.
            if dry_run:
                result.actions.append(f"would_create_overview:{preferred_key}")
                result.readiness = "ready"
                return result
            overview = MissionOverview(mission_id=preferred_key, catalog_mission_id=mission.id)
            session.add(overview)
            session.commit()
            result.actions.append(f"created_overview:{preferred_key}")
            result.readiness = "ready"
            result.reasons = []
            return result

        result.readiness = "ready"
        result.reasons = []
        result.actions.append("overview_already_linked")
        return result

    def on_completed(
        self, session: Session, mission: CatalogMission, *, dry_run: bool = False
    ) -> ProvisioningResult:
        result = ProvisioningResult(
            mission_id=mission.id,
            platform_family=self.family,
            readiness="completed",
            actions=[],
        )
        # Prefer past WGMS source when present (priority bump).
        sources = list(
            session.exec(
                select(CatalogMissionSource).where(
                    CatalogMissionSource.mission_id == mission.id,
                    CatalogMissionSource.source_kind == "wgms_remote",
                )
            ).all()
        )
        past = [
            s
            for s in sources
            if "past" in (s.collection or "").lower()
            or (s.source_variant or "").lower() == "delayed"
        ]
        if past and not dry_run:
            for source in past:
                source.priority = min(int(source.priority or 100), 10)
                source.updated_at_utc = _utcnow()
                session.add(source)
            session.commit()
            result.actions.append("prefer_past_wgms_source")
        elif past:
            result.actions.append("would_prefer_past_wgms_source")
        result.actions.append("retained_overview")
        return result


class SlocumHandler:
    family = "slocum"

    def _erddap_keys(self, session: Session, mission: CatalogMission) -> List[str]:
        keys: List[str] = []
        for identity in session.exec(
            select(CatalogExternalIdentity).where(
                CatalogExternalIdentity.mission_id == mission.id,
                CatalogExternalIdentity.identity_kind.in_(
                    [
                        CatalogIdentityKind.ERDDAP_MISSION_KEY.value,
                        CatalogIdentityKind.ERDDAP_DATASET_ID.value,
                    ]
                ),
            )
        ).all():
            if identity.external_id:
                keys.append(identity.external_id.strip())
        for source in session.exec(
            select(CatalogMissionSource).where(
                CatalogMissionSource.mission_id == mission.id,
                CatalogMissionSource.source_kind == "erddap",
                CatalogMissionSource.enabled == True,  # noqa: E712
            )
        ).all():
            if source.external_ref:
                keys.append(source.external_ref.strip())
        # Deduplicate preserving order
        seen = set()
        out = []
        for key in keys:
            if key not in seen:
                seen.add(key)
                out.append(key)
        return out

    def readiness(
        self, session: Session, mission: CatalogMission
    ) -> tuple[str, List[str]]:
        reasons: List[str] = []
        if mission.operational_state == "planned":
            reasons.append("waiting_for_start")
        keys = self._erddap_keys(session, mission)
        if not keys:
            reasons.append("waiting_for_source")
        deployments = list(
            session.exec(
                select(SlocumDeployment).where(
                    SlocumDeployment.catalog_mission_id == mission.id
                )
            ).all()
        )
        if not deployments and keys:
            # Look for existing by mission_key
            for key in keys:
                mkey = slocum_mission_key(key) or key
                rows = list(
                    session.exec(
                        select(SlocumDeployment).where(
                            SlocumDeployment.mission_key == mkey
                        )
                    ).all()
                )
                chosen = prefer_slocum_deployment(rows)
                if rows and chosen is None:
                    reasons.append("ambiguous_identity")
                    break
            else:
                if not any(
                    session.exec(
                        select(SlocumDeployment).where(
                            SlocumDeployment.mission_key
                            == (slocum_mission_key(k) or k)
                        )
                    ).first()
                    for k in keys
                ):
                    reasons.append("waiting_for_live_row")
        if reasons:
            return reasons[0], reasons
        return "ready", []

    def provision(
        self, session: Session, mission: CatalogMission, *, dry_run: bool = False
    ) -> ProvisioningResult:
        ready, reasons = self.readiness(session, mission)
        result = ProvisioningResult(
            mission_id=mission.id,
            platform_family=self.family,
            readiness=ready,
            reasons=list(reasons),
        )
        keys = self._erddap_keys(session, mission)
        if not keys:
            result.readiness = "waiting_for_source"
            if "waiting_for_source" not in result.reasons:
                result.reasons.append("waiting_for_source")
            return result

        linked = list(
            session.exec(
                select(SlocumDeployment).where(
                    SlocumDeployment.catalog_mission_id == mission.id
                )
            ).all()
        )
        if linked:
            result.readiness = "ready"
            result.reasons = []
            reactivated = False
            for dep in linked:
                if dep.is_active and (dep.status or "").lower() == "active":
                    continue
                if dry_run:
                    result.actions.append(f"would_reactivate_slocum:{dep.id}")
                    reactivated = True
                    continue
                dep.is_active = True
                dep.status = "active"
                dep.updated_at_utc = _utcnow()
                session.add(dep)
                result.actions.append(f"reactivated_slocum:{dep.id}")
                reactivated = True
            if reactivated and not dry_run:
                session.commit()
            if not reactivated:
                result.actions.append("deployment_already_linked")
            return result

        from app.platforms.slocum.deployment_service import (
            get_or_create_deployment_for_dataset,
        )

        dataset_id = keys[0]
        if dry_run:
            result.actions.append(f"would_create_or_link_slocum:{dataset_id}")
            result.readiness = "ready"
            return result

        deployment = get_or_create_deployment_for_dataset(
            session, dataset_id, created_by_username="catalog_provisioning"
        )
        if deployment is None:
            result.readiness = "waiting_for_source"
            result.errors.append(f"unparseable_dataset:{dataset_id}")
            return result
        deployment.catalog_mission_id = mission.id
        if not deployment.is_active:
            deployment.is_active = True
            deployment.status = "active"
        deployment.updated_at_utc = _utcnow()
        session.add(deployment)
        session.commit()
        result.actions.append(
            f"linked_slocum:{deployment.mission_key or deployment.erddap_dataset_id}"
        )
        result.readiness = "ready"
        result.reasons = []
        return result

    def on_completed(
        self, session: Session, mission: CatalogMission, *, dry_run: bool = False
    ) -> ProvisioningResult:
        result = ProvisioningResult(
            mission_id=mission.id,
            platform_family=self.family,
            readiness="completed",
        )
        deployments = list(
            session.exec(
                select(SlocumDeployment).where(
                    SlocumDeployment.catalog_mission_id == mission.id
                )
            ).all()
        )
        if not deployments:
            result.actions.append("no_slocum_deployment")
            return result
        for dep in deployments:
            if dry_run:
                result.actions.append(f"would_archive_slocum:{dep.id}")
                continue
            dep.is_active = False
            dep.status = "completed"
            dep.updated_at_utc = _utcnow()
            session.add(dep)
            result.actions.append(f"archived_slocum:{dep.id}")
        # Prefer delayed ERDDAP source when present.
        delayed = list(
            session.exec(
                select(CatalogMissionSource).where(
                    CatalogMissionSource.mission_id == mission.id,
                    CatalogMissionSource.source_kind == "erddap",
                    CatalogMissionSource.source_variant
                    == CatalogSourceVariant.DELAYED.value,
                )
            ).all()
        )
        if delayed and not dry_run:
            for source in delayed:
                source.priority = min(int(source.priority or 100), 10)
                source.updated_at_utc = _utcnow()
                session.add(source)
            result.actions.append("prefer_delayed_erddap")
        if not dry_run:
            session.commit()
        return result


def ensure_handlers_registered() -> None:
    register_handler(WaveGliderHandler())
    register_handler(SlocumHandler())


ensure_handlers_registered()
