"""Tests for catalog health and status reports."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine

from app.core.mission_catalog.health import build_catalog_health_report
from app.core.mission_catalog.status import build_catalog_status_report
from app.core.models.database import (
    CatalogExternalIdentity,
    CatalogMission,
    CatalogMissionSource,
    CatalogPlatform,
    MissionOverview,
    SlocumDeployment,
)
from app.core.models.enums import (
    CatalogEnrollmentOverride,
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


def test_status_report_has_safe_flags(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.mission_catalog.status.catalog_auto_apply_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.core.mission_catalog.status.catalog_is_stale",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.core.mission_catalog.status.last_success_at",
        lambda: datetime(2026, 9, 10, tzinfo=timezone.utc),
    )
    report = build_catalog_status_report()
    assert report["auto_apply"] is True
    assert "sync_interval_minutes" in report
    assert report["last_success_at"] is not None
    assert "is_startup_leader" in report


def test_health_reports_enrolled_but_not_ready() -> None:
    session = _session()
    platform = CatalogPlatform(canonical_name="peggy", platform_family="slocum")
    session.add(platform)
    session.commit()
    session.refresh(platform)
    mission = CatalogMission(
        id="cat-health-m231",
        title="m231",
        deployment_number=231,
        start_time=datetime(2026, 9, 1, tzinfo=timezone.utc),
        operational_state=CatalogOperationalState.ACTIVE.value,
        sync_policy=CatalogSyncPolicy.CONTINUOUS.value,
        platform_id=platform.id,
    )
    session.add(mission)
    session.commit()
    report = build_catalog_health_report(session)
    assert report["enrolled_active_count"] == 1
    codes = {i["issue"] for i in report["issues"]}
    assert "enrolled_but_not_ready" in codes
    assert "missing_source_links" in codes
    assert "status" in report


def test_health_forced_off_but_continuous() -> None:
    session = _session()
    mission = CatalogMission(
        id="cat-health-forced",
        title="m230",
        deployment_number=230,
        start_time=datetime(2026, 8, 1, tzinfo=timezone.utc),
        operational_state=CatalogOperationalState.ACTIVE.value,
        sync_policy=CatalogSyncPolicy.CONTINUOUS.value,
        enrollment_override=CatalogEnrollmentOverride.FORCED_OFF.value,
    )
    session.add(mission)
    session.commit()
    report = build_catalog_health_report(session)
    assert any(i["issue"] == "forced_off_but_continuous" for i in report["issues"])


def test_health_completed_without_archived_live_row() -> None:
    session = _session()
    platform = CatalogPlatform(canonical_name="fundy", platform_family="slocum")
    session.add(platform)
    session.commit()
    session.refresh(platform)
    mission = CatalogMission(
        id="cat-health-done",
        title="m229",
        deployment_number=229,
        start_time=datetime(2026, 7, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 9, 1, tzinfo=timezone.utc),
        operational_state=CatalogOperationalState.COMPLETED.value,
        sync_policy=CatalogSyncPolicy.ON_DEMAND.value,
        platform_id=platform.id,
    )
    session.add(mission)
    session.add(
        SlocumDeployment(
            name="Fundy",
            glider_name="fundy",
            mission_key="fundy_20260724_229",
            erddap_dataset_id="fundy_20260724_229_realtime",
            is_active=True,
            status="active",
            created_by_username="test",
            catalog_mission_id=mission.id,
        )
    )
    session.commit()
    report = build_catalog_health_report(session)
    assert any(
        i["issue"] == "completed_without_archived_live_row" for i in report["issues"]
    )
