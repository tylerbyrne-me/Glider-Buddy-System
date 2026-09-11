"""Tests for catalog workspace dual-key helpers and enrollment overrides."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine

from app.core.mission_catalog.workspace import (
    build_mission_list_item,
    build_workspace_payload,
    link_form_to_catalog,
    resolve_form_mission_keys,
    set_enrollment_override,
)
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
from app.core.models.enums import CatalogEnrollmentOverride, CatalogOperationalState


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        engine,
        tables=[
            CatalogPlatform.__table__,
            CatalogMission.__table__,
            CatalogMissionSource.__table__,
            CatalogExternalIdentity.__table__,
            SensorTrackerDeployment.__table__,
            MissionOverview.__table__,
            MissionInstrument.__table__,
            SlocumDeployment.__table__,
            SubmittedForm.__table__,
        ],
    )
    return Session(engine)


def test_resolve_form_keys_from_catalog_and_legacy() -> None:
    session = _session()
    mission = CatalogMission(
        id="cat-ws-1",
        deployment_number=250,
        operational_state="planned",
        sync_policy="catalog_only",
    )
    session.add(mission)
    session.add(
        SensorTrackerDeployment(
            mission_id="m250",
            sensor_tracker_deployment_id=9001,
            catalog_mission_id="cat-ws-1",
        )
    )
    session.commit()

    from_catalog = resolve_form_mission_keys(
        session, catalog_mission_id="cat-ws-1"
    )
    assert from_catalog["mission_id"] == "m250"
    assert from_catalog["catalog_mission_id"] == "cat-ws-1"

    from_legacy = resolve_form_mission_keys(session, mission_id="m250")
    assert from_legacy["catalog_mission_id"] == "cat-ws-1"


def test_link_form_preserves_legacy_mission_id() -> None:
    session = _session()
    session.add(
        CatalogMission(
            id="cat-ws-2",
            deployment_number=251,
            operational_state="planned",
            sync_policy="catalog_only",
        )
    )
    session.commit()
    form = SubmittedForm(
        mission_id=None,
        form_type="pre_deployment_checklist",
        form_title="Pre-Deployment Checklist",
        submitted_by_username="tester",
        submission_timestamp=datetime.now(timezone.utc),
        sections_data={},
    )
    session.add(form)
    session.commit()
    session.refresh(form)

    linked = link_form_to_catalog(
        session, form, "cat-ws-2", legacy_mission_id="m251"
    )
    assert linked.catalog_mission_id == "cat-ws-2"
    assert linked.mission_id == "m251"


def test_forced_off_roundtrip_restores_continuous() -> None:
    session = _session()
    mission = CatalogMission(
        id="cat-ws-override",
        deployment_number=230,
        operational_state=CatalogOperationalState.ACTIVE.value,
        sync_policy="continuous",
        enrollment_override=CatalogEnrollmentOverride.AUTOMATIC.value,
        start_time=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    session.add(mission)
    session.commit()

    off = set_enrollment_override(session, mission, "forced_off")
    assert off.enrollment_override == "forced_off"
    assert off.sync_policy == "catalog_only"

    on = set_enrollment_override(session, mission, "automatic")
    assert on.enrollment_override == "automatic"
    assert on.sync_policy == "continuous"


def test_mission_list_item_includes_readiness() -> None:
    session = _session()
    platform = CatalogPlatform(
        canonical_name="SV3-1070",
        platform_family="wave_glider",
        data_prefix="SV3-1070",
    )
    session.add(platform)
    session.commit()
    session.refresh(platform)
    mission = CatalogMission(
        id="cat-ws-ready-list",
        title="m230",
        deployment_number=230,
        operational_state=CatalogOperationalState.ACTIVE.value,
        sync_policy="continuous",
        platform_id=platform.id,
        start_time=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    session.add(mission)
    session.commit()
    item = build_mission_list_item(session, mission)
    assert item["id"] == mission.id
    assert item["readiness"] in (
        "waiting_for_source",
        "waiting_for_live_row",
        "ready",
        "waiting_for_deployment_number",
    )
    assert "readiness_reasons" in item
    payload = build_workspace_payload(session, mission)
    assert payload["readiness"] == item["readiness"]
    assert "links" in payload
