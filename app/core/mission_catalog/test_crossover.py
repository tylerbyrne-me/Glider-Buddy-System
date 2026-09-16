"""Recovery / crossover tests: history, stale sources, final sync, lock, audit."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.mission_catalog import enablement as enablement_mod
from app.core.mission_catalog.audit import (
    EVENT_ENROLLMENT,
    list_mission_events,
)
from app.core.mission_catalog.enablement import list_catalog_sync_targets
from app.core.mission_catalog.final_sync import (
    ensure_final_sync_work_item,
    get_final_sync_work_item,
    process_final_sync_work_item,
    request_final_sync_retry,
)
from app.core.mission_catalog.handlers import SlocumHandler, WaveGliderHandler
from app.core.mission_catalog.health import build_catalog_health_report
from app.core.mission_catalog.provisioning import provision_mission
from app.core.mission_catalog.status import build_catalog_status_report
from app.core.mission_catalog.sync_lock import catalog_write_lock
from app.core.mission_catalog.workspace import set_enrollment_override
from app.core.models.database import (
    CatalogExternalIdentity,
    CatalogMission,
    CatalogMissionEvent,
    CatalogMissionSource,
    CatalogMissionWorkItem,
    CatalogPlatform,
    CatalogReconcileRun,
    MissionOverview,
    SlocumDeployment,
    SubmittedForm,
)
from app.core.models.enums import (
    CatalogIdentityKind,
    CatalogMatchStatus,
    CatalogOperationalState,
    CatalogSyncPolicy,
    CatalogWorkItemStatus,
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
            CatalogMissionEvent.__table__,
            CatalogReconcileRun.__table__,
            CatalogMissionWorkItem.__table__,
            MissionOverview.__table__,
            SlocumDeployment.__table__,
            SubmittedForm.__table__,
        ],
    )
    return Session(engine)


def test_historical_slocum_empty_env_is_completed_linked_inactive(
    monkeypatch,
) -> None:
    session = _session()
    monkeypatch.setattr(enablement_mod, "_mission_catalog_enabled", lambda: True)
    monkeypatch.setattr(enablement_mod, "env_slocum_historical_keys", lambda: [])
    monkeypatch.setattr(enablement_mod, "env_slocum_active_keys", lambda: [])

    completed = CatalogMission(
        id="cat-hist-ok",
        title="m200",
        deployment_number=200,
        operational_state=CatalogOperationalState.COMPLETED.value,
        sync_policy=CatalogSyncPolicy.ON_DEMAND.value,
    )
    orphan_completed = CatalogMission(
        id="cat-hist-orphan-mission",
        title="m201",
        deployment_number=201,
        operational_state=CatalogOperationalState.COMPLETED.value,
        sync_policy=CatalogSyncPolicy.ON_DEMAND.value,
    )
    session.add(completed)
    session.add(orphan_completed)
    session.add(
        SlocumDeployment(
            name="peggy hist",
            mission_key="peggy_20250101_200",
            erddap_dataset_id="peggy_20250101_200_delayed",
            glider_name="peggy",
            catalog_mission_id=completed.id,
            is_active=False,
            status="completed",
            created_by_username="test",
        )
    )
    # Unrelated archived row without catalog link — must be excluded.
    session.add(
        SlocumDeployment(
            name="orphan hist",
            mission_key="orphan_20240101_99",
            erddap_dataset_id="orphan_20240101_99_delayed",
            glider_name="orphan",
            catalog_mission_id=None,
            is_active=False,
            status="completed",
            created_by_username="test",
        )
    )
    session.commit()

    keys = list_catalog_sync_targets(
        "slocum", session, operational_state="completed"
    )
    assert keys == ["peggy_20250101_200_delayed"]


def test_historical_slocum_keys_skip_aliases(monkeypatch) -> None:
    session = _session()
    monkeypatch.setattr(enablement_mod, "_mission_catalog_enabled", lambda: True)
    monkeypatch.setattr(enablement_mod, "env_slocum_historical_keys", lambda: [])
    monkeypatch.setattr(
        enablement_mod,
        "reverse_slocum_alias",
        lambda dataset: "m229-Fundy" if "229" in dataset else None,
    )
    completed = CatalogMission(
        id="cat-hist-alias",
        title="m229",
        deployment_number=229,
        operational_state=CatalogOperationalState.COMPLETED.value,
        sync_policy=CatalogSyncPolicy.ON_DEMAND.value,
    )
    session.add(completed)
    session.add(
        SlocumDeployment(
            name="fundy",
            mission_key="fundy_20260724_229",
            erddap_dataset_id="fundy_20260724_229_realtime",
            glider_name="fundy",
            catalog_mission_id=completed.id,
            is_active=False,
            status="completed",
            created_by_username="test",
        )
    )
    session.commit()
    keys = list_catalog_sync_targets(
        "slocum", session, operational_state="completed"
    )
    assert keys == ["fundy_20260724_229_realtime"]


def test_stale_wgms_source_excluded_from_readiness() -> None:
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
        id="cat-stale-src",
        title="m240",
        deployment_number=240,
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
            external_ref="m240-SV3-1071",
            source_variant="realtime",
            enabled=True,
            match_status=CatalogMatchStatus.STALE.value,
        )
    )
    session.commit()
    ready, reasons = WaveGliderHandler().readiness(session, mission)
    assert ready == "waiting_for_source"
    assert "waiting_for_source" in reasons


def test_final_sync_enqueued_on_slocum_complete_and_survives_retry() -> None:
    session = _session()
    platform = CatalogPlatform(canonical_name="peggy", platform_family="slocum")
    session.add(platform)
    session.commit()
    session.refresh(platform)
    mission = CatalogMission(
        id="cat-final-sync",
        title="m210",
        deployment_number=210,
        start_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 2, 1, tzinfo=timezone.utc),
        operational_state=CatalogOperationalState.COMPLETED.value,
        sync_policy=CatalogSyncPolicy.ON_DEMAND.value,
        platform_id=platform.id,
    )
    session.add(mission)
    session.add(
        SlocumDeployment(
            name="peggy final",
            mission_key="peggy_20260101_210",
            erddap_dataset_id="peggy_20260101_210_realtime",
            glider_name="peggy",
            catalog_mission_id=mission.id,
            is_active=True,
            status="active",
            created_by_username="test",
        )
    )
    session.commit()

    result = SlocumHandler().on_completed(session, mission, dry_run=False)
    assert any(a.startswith("archived_slocum") for a in result.actions)
    item = get_final_sync_work_item(session, mission.id)
    assert item is not None
    assert item.status == CatalogWorkItemStatus.PENDING.value

    # Completion lifecycle stays completed even after failed final sync.
    async def _boom(*_a, **_k):
        raise RuntimeError("simulated outage")

    import app.core.mission_catalog.final_sync as fs_mod

    monkey_session = session

    async def run():
        # Patch inside process path via ensuring delayed path fails
        original = fs_mod._run_slocum_final_sync

        async def fail(session, mission):
            return {"ok": False, "error": "simulated outage", "retryable": True}

        fs_mod._run_slocum_final_sync = fail  # type: ignore
        try:
            outcome = await process_final_sync_work_item(
                monkey_session, item, actor="test"
            )
            assert outcome.get("ok") is False
        finally:
            fs_mod._run_slocum_final_sync = original  # type: ignore

    asyncio.run(run())
    session.refresh(mission)
    assert mission.operational_state == CatalogOperationalState.COMPLETED.value
    item2 = get_final_sync_work_item(session, mission.id)
    assert item2 is not None
    assert item2.status == CatalogWorkItemStatus.FAILED.value

    retried = request_final_sync_retry(session, mission.id, actor="admin")
    assert retried.status == CatalogWorkItemStatus.PENDING.value


def test_enrollment_override_records_audit_event(monkeypatch) -> None:
    session = _session()
    mission = CatalogMission(
        id="cat-audit",
        title="m220",
        deployment_number=220,
        operational_state=CatalogOperationalState.ACTIVE.value,
        sync_policy=CatalogSyncPolicy.CONTINUOUS.value,
        enrollment_override="automatic",
    )
    session.add(mission)
    session.commit()
    monkeypatch.setattr(
        "app.core.mission_catalog.workspace.invalidate_public_map_cache",
        lambda: True,
        raising=False,
    )
    # Direct patch path used by set_enrollment_override
    monkeypatch.setattr(
        "app.core.public_map_service.invalidate_public_map_cache",
        lambda: True,
    )
    updated = set_enrollment_override(
        session, mission, "forced_off", actor="alice"
    )
    assert updated.sync_policy == CatalogSyncPolicy.CATALOG_ONLY.value
    events = list_mission_events(session, mission.id)
    assert any(e.event_type == EVENT_ENROLLMENT and e.actor == "alice" for e in events)


def test_catalog_write_lock_times_out(tmp_path: Path, monkeypatch) -> None:
    lock_path = tmp_path / "mission_catalog_write.lock"
    state_path = tmp_path / "mission_catalog_write_state.json"
    monkeypatch.setattr(
        "app.core.mission_catalog.sync_lock.CATALOG_WRITE_LOCK_PATH", lock_path
    )
    monkeypatch.setattr(
        "app.core.mission_catalog.sync_lock.CATALOG_WRITE_STATE_PATH", state_path
    )
    with catalog_write_lock(timeout_seconds=2.0, actor="a", detail="hold"):
        with pytest.raises(TimeoutError):
            with catalog_write_lock(timeout_seconds=0.2, actor="b", detail="wait"):
                pass


def test_health_expected_vs_fault_severity() -> None:
    session = _session()
    platform = CatalogPlatform(canonical_name="cabot", platform_family="slocum")
    session.add(platform)
    session.commit()
    session.refresh(platform)
    mission = CatalogMission(
        id="cat-sev",
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
    enrolled = [
        i for i in report["issues"] if i["issue"] == "enrolled_but_not_ready"
    ]
    assert enrolled
    assert enrolled[0]["severity"] == "expected"
    assert "overall_severity" in report


def test_status_includes_lock_and_leader_labels(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.core.mission_catalog.status.catalog_auto_apply_enabled",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.core.mission_catalog.status.catalog_is_stale",
        lambda: False,
    )
    monkeypatch.setattr(
        "app.core.mission_catalog.status.last_success_at",
        lambda: datetime(2026, 9, 11, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        "app.core.mission_catalog.status.catalog_write_lock_status",
        lambda: {
            "in_progress": False,
            "actor": "",
            "detail": "",
            "updated_at_utc": None,
        },
    )
    monkeypatch.setattr(
        "app.core.mission_catalog.status.catalog_last_partial_at",
        lambda: None,
    )
    report = build_catalog_status_report()
    assert "this_worker_is_leader" in report
    assert "write_lock" in report
    assert report["scheduler_job_id"] == "system_mission_catalog_sync_job"


def test_planned_to_active_keeps_form_on_same_catalog_uuid() -> None:
    """Unnumbered planned workspace → numbered ACTIVE keeps form attachment."""
    session = _session()
    platform = CatalogPlatform(
        canonical_name="SV3-9999",
        platform_family="wave_glider",
        data_prefix="SV3-9999",
    )
    session.add(platform)
    session.commit()
    session.refresh(platform)

    catalog_id = "cat-planned-e2e"
    mission = CatalogMission(
        id=catalog_id,
        title="Unnumbered",
        deployment_number=None,
        start_time=None,
        operational_state=CatalogOperationalState.PLANNED.value,
        sync_policy=CatalogSyncPolicy.CATALOG_ONLY.value,
        platform_id=platform.id,
    )
    session.add(mission)
    session.add(
        CatalogExternalIdentity(
            mission_id=catalog_id,
            provider_key="sensor_tracker",
            identity_kind=CatalogIdentityKind.SENSOR_TRACKER_DEPLOYMENT_ID.value,
            external_id="999001",
        )
    )
    session.add(
        SubmittedForm(
            form_type="pre_deployment",
            form_title="Pre-deploy",
            catalog_mission_id=catalog_id,
            mission_id=None,
            sections_data=[],
            submitted_by_username="tester",
            submission_timestamp=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
    )
    session.commit()

    # Number assigned + start reached → ACTIVE continuous
    mission.deployment_number = 250
    mission.start_time = datetime(2026, 9, 1, tzinfo=timezone.utc)
    mission.operational_state = CatalogOperationalState.ACTIVE.value
    mission.sync_policy = CatalogSyncPolicy.CONTINUOUS.value
    session.add(mission)
    session.add(
        CatalogMissionSource(
            mission_id=catalog_id,
            provider_key="ceotr_wgms_remote",
            source_kind="wgms_remote",
            collection="output_realtime_missions",
            external_ref="m250-SV3-9999",
            source_variant="realtime",
            enabled=True,
            match_status="linked",
        )
    )
    session.commit()

    result = provision_mission(session, mission, dry_run=False)
    assert result.readiness == "ready"
    overviews = list(
        session.exec(
            select(MissionOverview).where(
                MissionOverview.catalog_mission_id == catalog_id
            )
        ).all()
    )
    assert len(overviews) == 1
    forms = list(
        session.exec(
            select(SubmittedForm).where(
                SubmittedForm.catalog_mission_id == catalog_id
            )
        ).all()
    )
    assert len(forms) == 1
    assert forms[0].catalog_mission_id == catalog_id


def test_completion_reopen_same_live_row() -> None:
    session = _session()
    platform = CatalogPlatform(canonical_name="fundy", platform_family="slocum")
    session.add(platform)
    session.commit()
    session.refresh(platform)
    mission = CatalogMission(
        id="cat-reopen",
        title="m226",
        deployment_number=226,
        start_time=datetime(2026, 6, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 7, 1, tzinfo=timezone.utc),
        operational_state=CatalogOperationalState.COMPLETED.value,
        sync_policy=CatalogSyncPolicy.ON_DEMAND.value,
        platform_id=platform.id,
    )
    session.add(mission)
    session.add(
        CatalogExternalIdentity(
            mission_id=mission.id,
            provider_key="erddap",
            identity_kind=CatalogIdentityKind.ERDDAP_DATASET_ID.value,
            external_id="fundy_20260621_226_realtime",
        )
    )
    session.add(
        SlocumDeployment(
            name="fundy reopen",
            mission_key="fundy_20260621_226",
            erddap_dataset_id="fundy_20260621_226_realtime",
            glider_name="fundy",
            catalog_mission_id=mission.id,
            is_active=False,
            status="completed",
            created_by_username="test",
        )
    )
    session.commit()
    ensure_final_sync_work_item(session, mission, actor="test")
    session.commit()

    # Reopen: clear end, ACTIVE, continuous
    mission.end_time = None
    mission.operational_state = CatalogOperationalState.ACTIVE.value
    mission.sync_policy = CatalogSyncPolicy.CONTINUOUS.value
    session.add(mission)
    session.commit()

    result = provision_mission(session, mission, dry_run=False)
    assert result.readiness == "ready"
    deps = list(
        session.exec(
            select(SlocumDeployment).where(
                SlocumDeployment.catalog_mission_id == mission.id
            )
        ).all()
    )
    assert len(deps) == 1
    assert deps[0].is_active is True
    assert any("reactivated_slocum" in a for a in result.actions)
