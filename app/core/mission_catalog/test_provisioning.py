"""Tests for platform provisioning handlers."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine, select

from app.core.mission_catalog.handlers import SlocumHandler, WaveGliderHandler
from app.core.mission_catalog.provisioning import provision_mission
from app.core.models.database import (
    CatalogExternalIdentity,
    CatalogMission,
    CatalogMissionSource,
    CatalogPlatform,
    MissionOverview,
    SlocumDeployment,
)
from app.core.models.enums import (
    CatalogIdentityKind,
    CatalogOperationalState,
    CatalogSyncPolicy,
)


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        engine,
        tables=[
            CatalogPlatform.__table__,
            CatalogMission.__table__,
            CatalogMissionSource.__table__,
            CatalogExternalIdentity.__table__,
            MissionOverview.__table__,
            SlocumDeployment.__table__,
        ],
    )
    return Session(engine)


def test_wg_planned_waits_for_start() -> None:
    session = _session()
    platform = CatalogPlatform(
        canonical_name="SV3-1071",
        platform_family="wave_glider",
        data_prefix="SV3-1071",
    )
    session.add(platform)
    session.commit()
    session.refresh(platform)
    mission = CatalogMission(
        id="cat-wg-planned",
        title="m231",
        deployment_number=231,
        start_time=None,
        operational_state=CatalogOperationalState.PLANNED.value,
        sync_policy=CatalogSyncPolicy.CATALOG_ONLY.value,
        platform_id=platform.id,
    )
    session.add(mission)
    session.commit()
    result = provision_mission(session, mission, dry_run=True)
    assert result.readiness == "waiting_for_start"
    assert "waiting_for_start" in result.reasons


def test_wg_creates_overview_when_ready() -> None:
    session = _session()
    platform = CatalogPlatform(
        canonical_name="SV3-1071",
        platform_family="wave_glider",
        data_prefix="SV3-1071",
    )
    session.add(platform)
    session.commit()
    session.refresh(platform)
    mission = CatalogMission(
        id="cat-wg-active",
        title="m231",
        deployment_number=231,
        start_time=datetime(2026, 9, 1, tzinfo=timezone.utc),
        operational_state=CatalogOperationalState.ACTIVE.value,
        sync_policy=CatalogSyncPolicy.CONTINUOUS.value,
        platform_id=platform.id,
    )
    session.add(mission)
    session.add(
        CatalogMissionSource(
            mission_id=mission.id,
            provider_key="ceotr_wgms_remote",
            source_kind="wgms_remote",
            collection="output_realtime_missions",
            external_ref="m231-SV3-1071",
            source_variant="realtime",
            enabled=True,
            match_status="linked",
        )
    )
    session.commit()
    result = WaveGliderHandler().provision(session, mission, dry_run=False)
    assert result.readiness == "ready"
    assert any(a.startswith("created_overview:") for a in result.actions)
    overview = session.get(MissionOverview, "m231-SV3-1071")
    assert overview is not None
    assert overview.catalog_mission_id == mission.id


def test_slocum_completion_archives_deployment() -> None:
    session = _session()
    platform = CatalogPlatform(
        canonical_name="fundy",
        platform_family="slocum",
    )
    session.add(platform)
    session.commit()
    session.refresh(platform)
    mission = CatalogMission(
        id="cat-sl-done",
        title="m229",
        deployment_number=229,
        start_time=datetime(2026, 7, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 9, 1, tzinfo=timezone.utc),
        operational_state=CatalogOperationalState.COMPLETED.value,
        sync_policy=CatalogSyncPolicy.ON_DEMAND.value,
        platform_id=platform.id,
    )
    session.add(mission)
    session.commit()
    dep = SlocumDeployment(
        name="Fundy",
        glider_name="fundy",
        mission_key="fundy_20260724_229",
        erddap_dataset_id="fundy_20260724_229_realtime",
        is_active=True,
        status="active",
        created_by_username="test",
        catalog_mission_id=mission.id,
    )
    session.add(dep)
    session.commit()
    result = SlocumHandler().on_completed(session, mission, dry_run=False)
    session.refresh(dep)
    assert dep.is_active is False
    assert dep.status == "completed"
    assert any(a.startswith("archived_slocum:") for a in result.actions)


def test_slocum_waiting_for_source_without_erddap() -> None:
    session = _session()
    platform = CatalogPlatform(canonical_name="peggy", platform_family="slocum")
    session.add(platform)
    session.commit()
    session.refresh(platform)
    mission = CatalogMission(
        id="cat-sl-m231",
        title="m231",
        deployment_number=231,
        start_time=datetime(2026, 9, 1, tzinfo=timezone.utc),
        operational_state=CatalogOperationalState.ACTIVE.value,
        sync_policy=CatalogSyncPolicy.CONTINUOUS.value,
        platform_id=platform.id,
    )
    session.add(mission)
    session.commit()
    result = provision_mission(session, mission, dry_run=True)
    assert result.readiness == "waiting_for_source"
    assert "waiting_for_source" in result.reasons
    assert session.exec(select(SlocumDeployment)).first() is None


def test_slocum_provision_links_when_erddap_arrives() -> None:
    session = _session()
    platform = CatalogPlatform(canonical_name="peggy", platform_family="slocum")
    session.add(platform)
    session.commit()
    session.refresh(platform)
    mission = CatalogMission(
        id="cat-sl-erddap",
        title="m226",
        deployment_number=226,
        start_time=datetime(2026, 6, 21, tzinfo=timezone.utc),
        operational_state=CatalogOperationalState.ACTIVE.value,
        sync_policy=CatalogSyncPolicy.CONTINUOUS.value,
        platform_id=platform.id,
    )
    session.add(mission)
    session.add(
        CatalogMissionSource(
            mission_id=mission.id,
            provider_key="ceotr_erddap",
            source_kind="erddap",
            collection="tabledap",
            external_ref="peggy_20260621_226_realtime",
            source_variant="realtime",
            enabled=True,
            match_status="linked",
        )
    )
    session.add(
        CatalogExternalIdentity(
            mission_id=mission.id,
            provider_key="ceotr_erddap",
            identity_kind=CatalogIdentityKind.ERDDAP_DATASET_ID.value,
            external_id="peggy_20260621_226_realtime",
        )
    )
    session.commit()
    first = SlocumHandler().provision(session, mission, dry_run=False)
    assert first.readiness == "ready"
    deps = list(session.exec(select(SlocumDeployment)).all())
    assert len(deps) == 1
    assert deps[0].catalog_mission_id == mission.id
    assert deps[0].is_active is True

    second = SlocumHandler().provision(session, mission, dry_run=False)
    assert second.readiness == "ready"
    assert "deployment_already_linked" in second.actions
    assert len(list(session.exec(select(SlocumDeployment)).all())) == 1


def test_slocum_reopen_reactivates_same_deployment() -> None:
    session = _session()
    platform = CatalogPlatform(canonical_name="fundy", platform_family="slocum")
    session.add(platform)
    session.commit()
    session.refresh(platform)
    mission = CatalogMission(
        id="cat-sl-reopen",
        title="m229",
        deployment_number=229,
        start_time=datetime(2026, 7, 1, tzinfo=timezone.utc),
        end_time=None,
        operational_state=CatalogOperationalState.ACTIVE.value,
        sync_policy=CatalogSyncPolicy.CONTINUOUS.value,
        platform_id=platform.id,
    )
    session.add(mission)
    session.add(
        CatalogMissionSource(
            mission_id=mission.id,
            provider_key="ceotr_erddap",
            source_kind="erddap",
            collection="tabledap",
            external_ref="fundy_20260724_229_realtime",
            source_variant="realtime",
            enabled=True,
            match_status="linked",
        )
    )
    session.commit()
    dep = SlocumDeployment(
        name="Fundy",
        glider_name="fundy",
        mission_key="fundy_20260724_229",
        erddap_dataset_id="fundy_20260724_229_realtime",
        is_active=False,
        status="completed",
        created_by_username="test",
        catalog_mission_id=mission.id,
    )
    session.add(dep)
    session.commit()
    dep_id = dep.id

    result = SlocumHandler().provision(session, mission, dry_run=False)
    session.refresh(dep)
    assert result.readiness == "ready"
    assert any(a.startswith("reactivated_slocum:") for a in result.actions)
    assert dep.is_active is True
    assert dep.status == "active"
    assert len(list(session.exec(select(SlocumDeployment)).all())) == 1
    assert session.get(SlocumDeployment, dep_id) is not None
