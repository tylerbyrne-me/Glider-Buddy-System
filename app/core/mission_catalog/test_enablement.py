"""Unit tests for catalog enablement membership (env override + enrollment)."""

from __future__ import annotations

from sqlmodel import Session, SQLModel, create_engine

from app.core.mission_catalog import enablement as enablement_mod
from app.core.mission_catalog.enablement import list_catalog_sync_targets
from app.core.models.database import (
    CatalogExternalIdentity,
    CatalogMission,
    CatalogMissionSource,
    MissionOverview,
    SlocumDeployment,
)
from app.core.models.enums import (
    CatalogOperationalState,
    CatalogSourceKind,
    CatalogSourceVariant,
    CatalogSyncPolicy,
)


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        engine,
        tables=[
            CatalogMission.__table__,
            CatalogExternalIdentity.__table__,
            CatalogMissionSource.__table__,
            MissionOverview.__table__,
            SlocumDeployment.__table__,
        ],
    )
    return Session(engine)


def _add_catalog_mission(
    session: Session,
    *,
    mission_id: str,
    operational_state: str = CatalogOperationalState.ACTIVE.value,
    sync_policy: str = CatalogSyncPolicy.CONTINUOUS.value,
    deployment_number: int | None = 229,
) -> CatalogMission:
    row = CatalogMission(
        id=mission_id,
        title="Test",
        deployment_number=deployment_number,
        operational_state=operational_state,
        sync_policy=sync_policy,
    )
    session.add(row)
    session.commit()
    return row


def _add_realtime_wgms_source(session: Session, mission_id: str) -> None:
    session.add(
        CatalogMissionSource(
            mission_id=mission_id,
            provider_key="ceotr_wgms_remote",
            source_kind=CatalogSourceKind.WGMS_REMOTE.value,
            collection="output_realtime_missions",
            external_ref=f"folder-{mission_id}",
            source_variant=CatalogSourceVariant.REALTIME.value,
            enabled=True,
        )
    )
    session.commit()


def test_env_nonempty_overrides_live_rows(monkeypatch) -> None:
    session = _session()
    catalog = _add_catalog_mission(session, mission_id="cat-live")
    _add_realtime_wgms_source(session, catalog.id)
    session.add(
        MissionOverview(
            mission_id="m229-SV3-1071",
            catalog_mission_id=catalog.id,
        )
    )
    session.commit()
    monkeypatch.setattr(
        enablement_mod.settings,
        "active_realtime_missions",
        ["m229-SV3-1071", "env-only-key"],
    )
    monkeypatch.setattr(enablement_mod, "_mission_catalog_enabled", lambda: True)

    keys = list_catalog_sync_targets("wave_glider", session)
    assert keys == ["m229-SV3-1071", "env-only-key"]


def test_empty_env_wg_uses_enrolled_active_with_realtime_source(monkeypatch) -> None:
    session = _session()
    active = _add_catalog_mission(session, mission_id="cat-active", deployment_number=229)
    completed = _add_catalog_mission(
        session,
        mission_id="cat-done",
        operational_state=CatalogOperationalState.COMPLETED.value,
        sync_policy=CatalogSyncPolicy.ON_DEMAND.value,
        deployment_number=211,
    )
    # ACTIVE but not enrolled (m230-style) — must stay out.
    unenrolled = _add_catalog_mission(
        session,
        mission_id="cat-unenrolled",
        sync_policy=CatalogSyncPolicy.CATALOG_ONLY.value,
        deployment_number=230,
    )
    # ST-only catalog mission with no overview must not appear.
    _add_catalog_mission(session, mission_id="cat-st-only", deployment_number=100)

    _add_realtime_wgms_source(session, active.id)
    _add_realtime_wgms_source(session, unenrolled.id)
    session.add(
        MissionOverview(mission_id="m229-SV3-1071", catalog_mission_id=active.id)
    )
    session.add(MissionOverview(mission_id="m229", catalog_mission_id=active.id))
    session.add(
        MissionOverview(mission_id="m211-SV3-1070", catalog_mission_id=completed.id)
    )
    session.add(
        MissionOverview(mission_id="m230-SV3-1070", catalog_mission_id=unenrolled.id)
    )
    session.commit()

    monkeypatch.setattr(enablement_mod.settings, "active_realtime_missions", [])
    monkeypatch.setattr(enablement_mod, "_mission_catalog_enabled", lambda: True)

    keys = list_catalog_sync_targets("wave_glider", session)
    assert keys == ["m229-SV3-1071"]


def test_empty_env_wg_requires_realtime_wgms_source(monkeypatch) -> None:
    session = _session()
    active = _add_catalog_mission(session, mission_id="cat-no-src", deployment_number=229)
    session.add(
        MissionOverview(mission_id="m229-SV3-1071", catalog_mission_id=active.id)
    )
    session.commit()
    monkeypatch.setattr(enablement_mod.settings, "active_realtime_missions", [])
    monkeypatch.setattr(enablement_mod, "_mission_catalog_enabled", lambda: True)
    assert list_catalog_sync_targets("wave_glider", session) == []


def test_empty_env_slocum_uses_enrolled_active_deployments(monkeypatch) -> None:
    session = _session()
    enrolled = _add_catalog_mission(session, mission_id="cat-slocum", deployment_number=229)
    unenrolled = _add_catalog_mission(
        session,
        mission_id="cat-slocum-open",
        sync_policy=CatalogSyncPolicy.CATALOG_ONLY.value,
        deployment_number=225,
    )
    session.add(
        SlocumDeployment(
            name="Fundy",
            glider_name="fundy",
            created_by_username="test",
            is_active=True,
            mission_key="fundy_20260724_229",
            erddap_dataset_id="fundy_20260724_229_realtime",
            catalog_mission_id=enrolled.id,
        )
    )
    session.add(
        SlocumDeployment(
            name="Stale Fundy",
            glider_name="fundy",
            created_by_username="test",
            is_active=True,
            mission_key="fundy_20260621_225",
            erddap_dataset_id="fundy_20260621_225_realtime",
            catalog_mission_id=unenrolled.id,
        )
    )
    session.add(
        SlocumDeployment(
            name="Old",
            glider_name="peggy",
            created_by_username="test",
            is_active=False,
            mission_key="peggy_20250522_206",
            erddap_dataset_id="peggy_20250522_206_delayed",
        )
    )
    session.commit()

    monkeypatch.setattr(enablement_mod.settings, "active_slocum_datasets", [])
    monkeypatch.setattr(enablement_mod.settings, "historical_slocum_datasets", [])
    monkeypatch.setattr(enablement_mod, "_mission_catalog_enabled", lambda: True)
    monkeypatch.setattr(
        enablement_mod,
        "reverse_slocum_alias",
        lambda dataset: "fundy" if "fundy_20260724" in dataset else None,
    )

    active = list_catalog_sync_targets("slocum", session)
    assert active == ["fundy"]

    historical = list_catalog_sync_targets(
        "slocum", session, operational_state="completed"
    )
    assert historical == ["peggy_20250522_206_delayed"]


def test_catalog_disabled_returns_env(monkeypatch) -> None:
    session = _session()
    monkeypatch.setattr(enablement_mod, "_mission_catalog_enabled", lambda: False)
    monkeypatch.setattr(
        enablement_mod.settings, "active_realtime_missions", ["m229-SV3-1071"]
    )
    assert list_catalog_sync_targets("wave_glider", session) == ["m229-SV3-1071"]
    assert list_catalog_sync_targets("wave_glider", None) == ["m229-SV3-1071"]
