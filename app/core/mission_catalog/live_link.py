"""Link catalog missions onto existing live rows without creating or remapping PKs."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Set

from sqlmodel import Session, select

from app.core.models.database import (
    CatalogExternalIdentity,
    CatalogMission,
    MissionOverview,
    SensorTrackerDeployment,
    SlocumDeployment,
)
from app.core.models.enums import CatalogIdentityKind
from app.core.utils import deployment_mission_code_from_mission_id

logger = logging.getLogger(__name__)

# Canonical WG app keys: m227-SV3-1071. Legacy: m227 or 1071-m169.
_WG_FOLDER_STYLE = re.compile(r"^m\d+-SV\d+", re.IGNORECASE)
_WG_BARE_CODE = re.compile(r"^m\d+$", re.IGNORECASE)
_WG_LEGACY_SERIAL = re.compile(r"^\d+-m\d+$", re.IGNORECASE)


@dataclass
class LiveLinkReport:
    linked_overviews: int = 0
    linked_st_deployments: int = 0
    linked_slocum: int = 0
    skipped_ambiguous: List[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return (
            f"live_link: overviews={self.linked_overviews} "
            f"st={self.linked_st_deployments} slocum={self.linked_slocum} "
            f"ambiguous={len(self.skipped_ambiguous)}"
        )


def _deployment_code_for_mission(mission: CatalogMission, session: Session) -> Optional[str]:
    if mission.deployment_number is not None:
        return f"m{int(mission.deployment_number)}"
    identities = session.exec(
        select(CatalogExternalIdentity).where(
            CatalogExternalIdentity.mission_id == mission.id,
            CatalogExternalIdentity.identity_kind
            == CatalogIdentityKind.DEPLOYMENT_CODE.value,
        )
    ).all()
    if len(identities) == 1:
        return identities[0].external_id.strip().lower()
    return None


def _mission_keys_for_mission(mission: CatalogMission, session: Session) -> Set[str]:
    keys: Set[str] = set()
    for identity in session.exec(
        select(CatalogExternalIdentity).where(
            CatalogExternalIdentity.mission_id == mission.id,
            CatalogExternalIdentity.identity_kind
            == CatalogIdentityKind.ERDDAP_MISSION_KEY.value,
        )
    ).all():
        if identity.external_id:
            keys.add(identity.external_id.strip())
    return keys


def _is_wg_overview_identity(mission_id: str) -> bool:
    mid = (mission_id or "").strip()
    return bool(
        _WG_FOLDER_STYLE.match(mid)
        or _WG_BARE_CODE.match(mid)
        or _WG_LEGACY_SERIAL.match(mid)
    )


def prefer_wave_glider_overview(
    candidates: Sequence[MissionOverview],
) -> Optional[MissionOverview]:
    """Pick the live overview PK for catalog linking.

    Preference: ``m###-SV3-####`` > bare ``m###`` > never ``####-m###`` when a
    better form exists. Offload/test suffixes (``m209_test``) are ignored.
    Ambiguous same-class duplicates return None.
    """
    usable = [o for o in candidates if _is_wg_overview_identity(o.mission_id)]
    if not usable:
        return None
    folder = [o for o in usable if _WG_FOLDER_STYLE.match(o.mission_id.strip())]
    if len(folder) == 1:
        return folder[0]
    if len(folder) > 1:
        return None
    bare = [o for o in usable if _WG_BARE_CODE.match(o.mission_id.strip())]
    if len(bare) == 1:
        return bare[0]
    if len(bare) > 1:
        return None
    legacy = [o for o in usable if _WG_LEGACY_SERIAL.match(o.mission_id.strip())]
    if len(legacy) == 1:
        return legacy[0]
    return None


def prefer_slocum_deployment(
    candidates: Sequence[SlocumDeployment],
) -> Optional[SlocumDeployment]:
    """Prefer the active briefing row; ignore archived/inactive duplicates."""
    active = [
        row
        for row in candidates
        if row.is_active and (row.status or "").strip().lower() != "archived"
    ]
    if len(active) == 1:
        return active[0]
    if len(active) > 1:
        return None
    return None


def _link_if_unbound(
    row,
    mission_id: str,
    *,
    dry_run: bool,
    label: str,
    report: LiveLinkReport,
) -> bool:
    existing = getattr(row, "catalog_mission_id", None)
    if existing and existing != mission_id:
        report.skipped_ambiguous.append(f"{label} already linked to {existing}")
        return False
    if not dry_run:
        row.catalog_mission_id = mission_id
        return True
    return True


def link_catalog_to_live_rows(
    session: Session,
    *,
    dry_run: bool = False,
) -> LiveLinkReport:
    """Set catalog_mission_id on existing live rows when the join is unique.

    Never creates MissionOverview / SensorTrackerDeployment / SlocumDeployment.
    Ambiguous matches are skipped and recorded.
    """
    report = LiveLinkReport()
    missions = list(session.exec(select(CatalogMission)).all())
    all_overviews = list(session.exec(select(MissionOverview)).all())

    for mission in missions:
        code = _deployment_code_for_mission(mission, session)
        if code:
            st_rows = list(
                session.exec(
                    select(SensorTrackerDeployment).where(
                        SensorTrackerDeployment.mission_id == code
                    )
                ).all()
            )
            if len(st_rows) > 1:
                report.skipped_ambiguous.append(f"st:{code}")
            elif len(st_rows) == 1:
                row = st_rows[0]
                if _link_if_unbound(
                    row, mission.id, dry_run=dry_run, label=f"st:{code}", report=report
                ):
                    if not dry_run:
                        session.add(row)
                    report.linked_st_deployments += 1

            siblings = [
                o
                for o in all_overviews
                if deployment_mission_code_from_mission_id(o.mission_id) == code
                and _is_wg_overview_identity(o.mission_id)
            ]
            overview = prefer_wave_glider_overview(siblings)
            if siblings and overview is None:
                report.skipped_ambiguous.append(
                    f"overview:{code}:multiple:{[o.mission_id for o in siblings]}"
                )
            elif overview is not None:
                if _link_if_unbound(
                    overview,
                    mission.id,
                    dry_run=dry_run,
                    label=f"overview:{overview.mission_id}",
                    report=report,
                ):
                    if not dry_run:
                        session.add(overview)
                    report.linked_overviews += 1

        for mission_key in _mission_keys_for_mission(mission, session):
            slocum_rows = list(
                session.exec(
                    select(SlocumDeployment).where(
                        SlocumDeployment.mission_key == mission_key
                    )
                ).all()
            )
            chosen = prefer_slocum_deployment(slocum_rows)
            if slocum_rows and chosen is None:
                report.skipped_ambiguous.append(
                    f"slocum:{mission_key}:ids={[r.id for r in slocum_rows]}"
                )
                continue
            if chosen is None:
                continue
            if _link_if_unbound(
                chosen,
                mission.id,
                dry_run=dry_run,
                label=f"slocum:{mission_key}",
                report=report,
            ):
                if not dry_run:
                    session.add(chosen)
                report.linked_slocum += 1

    if not dry_run:
        session.commit()
    logger.info("%s", report.summary)
    if report.skipped_ambiguous:
        logger.warning("live_link ambiguous: %s", report.skipped_ambiguous)
    return report
