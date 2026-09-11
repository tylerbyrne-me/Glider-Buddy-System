"""Catalog mission workspace helpers (planned + active staging views)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.core.models.database import (
    CatalogExternalIdentity,
    CatalogMission,
    CatalogMissionSource,
    CatalogPlatform,
    MissionInstrument,
    MissionOverview,
    SensorTrackerDeployment,
    SlocumDeployment,
    SubmittedForm,
)
from app.core.models.enums import CatalogEnrollmentOverride


def get_catalog_mission(session: Session, catalog_mission_id: str) -> Optional[CatalogMission]:
    return session.get(CatalogMission, catalog_mission_id)


def list_workspace_missions(
    session: Session,
    *,
    operational_state: Optional[str] = None,
    limit: int = 100,
) -> List[CatalogMission]:
    stmt = select(CatalogMission).order_by(CatalogMission.updated_at_utc.desc())
    if operational_state:
        stmt = stmt.where(CatalogMission.operational_state == operational_state)
    if limit:
        stmt = stmt.limit(limit)
    return list(session.exec(stmt).all())


def _platform_for(session: Session, mission: CatalogMission) -> Optional[CatalogPlatform]:
    if not mission.platform_id:
        return None
    return session.get(CatalogPlatform, mission.platform_id)


def mission_readiness(
    session: Session, mission: CatalogMission
) -> tuple[str, List[str], Optional[str]]:
    """Return (readiness, reasons, platform_family) via provisioning handlers (read-only)."""
    from app.core.mission_catalog.provisioning import get_handler, provision_mission

    # Ensure handlers registered.
    from app.core.mission_catalog import handlers as _handlers  # noqa: F401

    platform = _platform_for(session, mission)
    family = getattr(platform, "platform_family", None) if platform else None
    handler = get_handler(family)
    if handler is None:
        return "unsupported_family", [f"no_handler:{family or 'unknown'}"], family

    # Use dry-run provision path for consistent enrollment/planned/completed gates
    # without mutating rows.
    result = provision_mission(session, mission, dry_run=True)
    return result.readiness, list(result.reasons), family


def build_mission_list_item(
    session: Session, mission: CatalogMission
) -> Dict[str, Any]:
    """Compact list DTO including readiness for Team catalog tables."""
    platform = _platform_for(session, mission)
    readiness, reasons, family = mission_readiness(session, mission)
    overviews = list(
        session.exec(
            select(MissionOverview).where(
                MissionOverview.catalog_mission_id == mission.id
            )
        ).all()
    )
    slocum = list(
        session.exec(
            select(SlocumDeployment).where(
                SlocumDeployment.catalog_mission_id == mission.id
            )
        ).all()
    )
    source_count = len(
        list(
            session.exec(
                select(CatalogMissionSource).where(
                    CatalogMissionSource.mission_id == mission.id
                )
            ).all()
        )
    )
    return {
        "id": mission.id,
        "title": mission.title,
        "deployment_number": mission.deployment_number,
        "operational_state": mission.operational_state,
        "sync_policy": mission.sync_policy,
        "enrollment_override": mission.enrollment_override or "automatic",
        "start_time": mission.start_time.isoformat() if mission.start_time else None,
        "end_time": mission.end_time.isoformat() if mission.end_time else None,
        "platform_family": family or (
            getattr(platform, "platform_family", None) if platform else None
        ),
        "platform_name": getattr(platform, "canonical_name", None) if platform else None,
        "readiness": readiness,
        "readiness_reasons": reasons,
        "source_count": source_count,
        "overview_count": len(overviews),
        "slocum_deployment_count": len(slocum),
        "has_live_row": bool(overviews or slocum),
        "updated_at_utc": mission.updated_at_utc.isoformat()
        if mission.updated_at_utc
        else None,
    }


def build_workspace_payload(
    session: Session,
    mission: CatalogMission,
) -> Dict[str, Any]:
    """Read-only workspace DTO for Team catalog mission detail."""
    platform = _platform_for(session, mission)

    identities = list(
        session.exec(
            select(CatalogExternalIdentity).where(
                CatalogExternalIdentity.mission_id == mission.id
            )
        ).all()
    )
    sources = list(
        session.exec(
            select(CatalogMissionSource).where(
                CatalogMissionSource.mission_id == mission.id
            )
        ).all()
    )
    st_row = session.exec(
        select(SensorTrackerDeployment).where(
            SensorTrackerDeployment.catalog_mission_id == mission.id
        )
    ).first()
    if st_row is None and mission.deployment_number is not None:
        st_row = session.exec(
            select(SensorTrackerDeployment).where(
                SensorTrackerDeployment.mission_id == f"m{int(mission.deployment_number)}"
            )
        ).first()

    overviews = list(
        session.exec(
            select(MissionOverview).where(
                MissionOverview.catalog_mission_id == mission.id
            )
        ).all()
    )
    slocum = list(
        session.exec(
            select(SlocumDeployment).where(
                SlocumDeployment.catalog_mission_id == mission.id
            )
        ).all()
    )
    instruments = list(
        session.exec(
            select(MissionInstrument).where(
                MissionInstrument.catalog_mission_id == mission.id
            )
        ).all()
    )
    if not instruments and st_row and st_row.mission_id:
        instruments = list(
            session.exec(
                select(MissionInstrument).where(
                    MissionInstrument.mission_id == st_row.mission_id
                )
            ).all()
        )
    forms = list(
        session.exec(
            select(SubmittedForm).where(
                SubmittedForm.catalog_mission_id == mission.id
            )
        ).all()
    )

    readiness, readiness_reasons, family = mission_readiness(session, mission)

    # Dashboard / admin deep-links when live keys exist.
    links: Dict[str, Optional[str]] = {
        "wave_glider_dashboard": None,
        "slocum_dashboard": None,
        "slocum_admin_overviews": "/admin/slocum/mission-overviews"
        if family == "slocum" or slocum
        else None,
    }
    if overviews:
        mid = overviews[0].mission_id
        if mid:
            links["wave_glider_dashboard"] = f"/wave-glider/dashboard.html?mission={mid}"
    if slocum:
        dep = slocum[0]
        key = (dep.erddap_dataset_id or dep.mission_key or "").strip()
        if key:
            links["slocum_dashboard"] = f"/slocum/dashboard.html?dataset={key}"

    return {
        "id": mission.id,
        "title": mission.title,
        "deployment_number": mission.deployment_number,
        "start_time": mission.start_time.isoformat() if mission.start_time else None,
        "end_time": mission.end_time.isoformat() if mission.end_time else None,
        "operational_state": mission.operational_state,
        "sync_policy": mission.sync_policy,
        "enrollment_override": mission.enrollment_override or "automatic",
        "platform_family": family
        or (getattr(platform, "platform_family", None) if platform else None),
        "platform_name": getattr(platform, "canonical_name", None) if platform else None,
        "readiness": readiness,
        "identities": [
            {
                "kind": i.identity_kind,
                "external_id": i.external_id,
                "provider_key": i.provider_key,
            }
            for i in identities
        ],
        "sources": [
            {
                "id": s.id,
                "kind": s.source_kind,
                "collection": s.collection,
                "external_ref": s.external_ref,
                "variant": s.source_variant,
                "enabled": s.enabled,
                "match_status": s.match_status,
            }
            for s in sources
        ],
        "sensor_tracker_deployment": (
            {
                "id": st_row.id,
                "mission_id": st_row.mission_id,
                "sensor_tracker_deployment_id": st_row.sensor_tracker_deployment_id,
                "deployment_number": st_row.deployment_number,
                "sync_status": st_row.sync_status,
                "last_synced_at": (
                    st_row.last_synced_at.isoformat() if st_row.last_synced_at else None
                ),
            }
            if st_row
            else None
        ),
        "overviews": [{"mission_id": o.mission_id} for o in overviews],
        "slocum_deployments": [
            {
                "id": d.id,
                "mission_key": d.mission_key,
                "erddap_dataset_id": d.erddap_dataset_id,
                "is_active": d.is_active,
                "status": d.status,
            }
            for d in slocum
        ],
        "instruments": [
            {
                "id": i.id,
                "mission_id": i.mission_id,
                "identifier": i.instrument_identifier,
                "name": i.instrument_name or i.instrument_short_name,
            }
            for i in instruments
        ],
        "forms": [
            {
                "id": f.id,
                "form_type": f.form_type,
                "form_title": f.form_title,
                "mission_id": f.mission_id,
                "submission_timestamp": f.submission_timestamp.isoformat()
                if f.submission_timestamp
                else None,
            }
            for f in forms
        ],
        "readiness_reasons": readiness_reasons,
        "links": links,
        "updated_at_utc": mission.updated_at_utc.isoformat()
        if mission.updated_at_utc
        else None,
    }


def set_enrollment_override(
    session: Session,
    mission: CatalogMission,
    override: str,
) -> CatalogMission:
    allowed = {e.value for e in CatalogEnrollmentOverride}
    value = (override or "").strip().lower()
    if value not in allowed:
        raise ValueError(f"Invalid enrollment_override: {override!r}")
    mission.enrollment_override = value
    mission.has_manual_overrides = value != CatalogEnrollmentOverride.AUTOMATIC.value
    mission.updated_at_utc = datetime.now(timezone.utc)
    # Apply immediately for forced_on / forced_off while ACTIVE.
    if mission.operational_state == "completed":
        mission.sync_policy = "on_demand"
    elif value == CatalogEnrollmentOverride.FORCED_OFF.value:
        if mission.operational_state == "active":
            mission.sync_policy = "catalog_only"
    elif value == CatalogEnrollmentOverride.FORCED_ON.value:
        if mission.operational_state in ("active", "planned"):
            mission.sync_policy = "continuous"
    elif value == CatalogEnrollmentOverride.AUTOMATIC.value:
        if (
            mission.operational_state == "active"
            and mission.sync_policy == "catalog_only"
        ):
            # Restore enrollable policy; next reconcile may also seed CONTINUOUS.
            mission.sync_policy = "continuous"
    session.add(mission)
    session.commit()
    session.refresh(mission)
    return mission


def link_form_to_catalog(
    session: Session,
    form: SubmittedForm,
    catalog_mission_id: str,
    *,
    legacy_mission_id: Optional[str] = None,
) -> SubmittedForm:
    form.catalog_mission_id = catalog_mission_id
    if legacy_mission_id and not form.mission_id:
        form.mission_id = legacy_mission_id
    session.add(form)
    session.commit()
    session.refresh(form)
    return form


def resolve_form_mission_keys(
    session: Session,
    *,
    mission_id: Optional[str] = None,
    catalog_mission_id: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """Return both keys for form queries (legacy + catalog)."""
    out = {"mission_id": mission_id, "catalog_mission_id": catalog_mission_id}
    if catalog_mission_id and not mission_id:
        mission = session.get(CatalogMission, catalog_mission_id)
        if mission and mission.deployment_number is not None:
            out["mission_id"] = f"m{int(mission.deployment_number)}"
        st = session.exec(
            select(SensorTrackerDeployment).where(
                SensorTrackerDeployment.catalog_mission_id == catalog_mission_id
            )
        ).first()
        if st and st.mission_id:
            out["mission_id"] = st.mission_id
    if mission_id and not catalog_mission_id:
        st = session.exec(
            select(SensorTrackerDeployment).where(
                SensorTrackerDeployment.mission_id == mission_id
            )
        ).first()
        if st and st.catalog_mission_id:
            out["catalog_mission_id"] = st.catalog_mission_id
        overview = session.get(MissionOverview, mission_id)
        if overview and overview.catalog_mission_id:
            out["catalog_mission_id"] = overview.catalog_mission_id
    return out
