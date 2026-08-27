"""Unit tests for ST lifecycle authority and CONTINUOUS enrollment persistence."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine

from app.core.mission_catalog.providers_config import ProviderSpec, ProvidersManifest
from app.core.mission_catalog.reconcile import (
    _apply_lifecycle_fields,
    _resolve_sync_policy,
    _update_mission_from_discovery,
)
from app.core.mission_catalog.schemas import DiscoveredMission
from app.core.models.database import CatalogMission
from app.core.models.enums import (
    CatalogOperationalState,
    CatalogSyncPolicy,
)


def _manifest() -> ProvidersManifest:
    return ProvidersManifest(
        providers=[
            ProviderSpec(
                key="ceotr_sensor_tracker",
                connector="sensor_tracker",
                organization="ceotr",
                lifecycle_authority=True,
            ),
            ProviderSpec(
                key="ceotr_wgms_remote",
                connector="wgms_remote",
                organization="ceotr",
            ),
            ProviderSpec(
                key="legacy_env",
                connector="legacy_env",
                organization="ceotr",
            ),
        ],
        wave_glider_prefixes=["SV3"],
        slocum_known_names=[],
    )


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine, tables=[CatalogMission.__table__])
    return Session(engine)


def test_wgms_observation_does_not_wipe_st_end_date() -> None:
    session = _session()
    end = datetime(2024, 1, 15, tzinfo=timezone.utc)
    mission = CatalogMission(
        id="cat-1",
        title="m176",
        deployment_number=176,
        start_time=datetime(2023, 8, 2, tzinfo=timezone.utc),
        end_time=end,
        operational_state=CatalogOperationalState.COMPLETED.value,
        sync_policy=CatalogSyncPolicy.ON_DEMAND.value,
    )
    session.add(mission)
    session.commit()

    discovered = DiscoveredMission(
        provider_key="ceotr_wgms_remote",
        title="m176-SV3-1070",
        deployment_number=176,
        start_time=None,
        end_time=None,
        operational_state=CatalogOperationalState.COMPLETED,
        sync_policy=CatalogSyncPolicy.CATALOG_ONLY,
    )
    _update_mission_from_discovery(
        session,
        mission,
        discovered,
        platform=None,
        dry_run=False,
        manifest=_manifest(),
    )
    session.commit()
    session.refresh(mission)
    assert mission.end_time is not None
    assert mission.end_time.replace(tzinfo=timezone.utc) == end
    assert mission.operational_state == CatalogOperationalState.COMPLETED.value


def test_st_observation_can_clear_end_date_when_reopened() -> None:
    session = _session()
    mission = CatalogMission(
        id="cat-2",
        title="m227",
        deployment_number=227,
        start_time=datetime(2026, 7, 8, tzinfo=timezone.utc),
        end_time=datetime(2026, 8, 1, tzinfo=timezone.utc),
        operational_state=CatalogOperationalState.COMPLETED.value,
        sync_policy=CatalogSyncPolicy.ON_DEMAND.value,
    )
    session.add(mission)
    session.commit()

    discovered = DiscoveredMission(
        provider_key="ceotr_sensor_tracker",
        title="m227-SV3-1071",
        deployment_number=227,
        start_time=datetime(2026, 7, 8, tzinfo=timezone.utc),
        end_time=None,
        operational_state=CatalogOperationalState.ACTIVE,
    )
    _update_mission_from_discovery(
        session,
        mission,
        discovered,
        platform=None,
        dry_run=False,
        manifest=_manifest(),
    )
    session.commit()
    session.refresh(mission)
    assert mission.end_time is None
    assert mission.operational_state == CatalogOperationalState.ACTIVE.value


def test_legacy_env_seeds_continuous_without_touching_dates() -> None:
    session = _session()
    end = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mission = CatalogMission(
        id="cat-3",
        title="m227",
        deployment_number=227,
        start_time=datetime(2026, 7, 8, tzinfo=timezone.utc),
        end_time=None,
        operational_state=CatalogOperationalState.ACTIVE.value,
        sync_policy=CatalogSyncPolicy.CATALOG_ONLY.value,
    )
    session.add(mission)
    session.commit()

    discovered = DiscoveredMission(
        provider_key="legacy_env",
        title="m227-SV3-1071",
        deployment_number=227,
        start_time=None,
        end_time=end,  # would be dangerous if applied
        operational_state=CatalogOperationalState.ACTIVE,
        sync_policy=CatalogSyncPolicy.CONTINUOUS,
    )
    _update_mission_from_discovery(
        session,
        mission,
        discovered,
        platform=None,
        dry_run=False,
        manifest=_manifest(),
    )
    session.commit()
    session.refresh(mission)
    assert mission.end_time is None
    assert mission.sync_policy == CatalogSyncPolicy.CONTINUOUS.value
    assert mission.operational_state == CatalogOperationalState.ACTIVE.value


def test_continuous_preserved_on_st_refresh_while_active() -> None:
    session = _session()
    mission = CatalogMission(
        id="cat-4",
        title="m227",
        deployment_number=227,
        start_time=datetime(2026, 7, 8, tzinfo=timezone.utc),
        end_time=None,
        operational_state=CatalogOperationalState.ACTIVE.value,
        sync_policy=CatalogSyncPolicy.CONTINUOUS.value,
    )
    session.add(mission)
    session.commit()

    discovered = DiscoveredMission(
        provider_key="ceotr_sensor_tracker",
        title="m227-SV3-1071",
        deployment_number=227,
        start_time=datetime(2026, 7, 8, tzinfo=timezone.utc),
        end_time=None,
    )
    _update_mission_from_discovery(
        session,
        mission,
        discovered,
        platform=None,
        dry_run=False,
        manifest=_manifest(),
    )
    session.commit()
    session.refresh(mission)
    assert mission.sync_policy == CatalogSyncPolicy.CONTINUOUS.value


def test_continuous_drops_to_on_demand_when_completed() -> None:
    assert (
        _resolve_sync_policy(
            operational_state=CatalogOperationalState.COMPLETED.value,
            derived_policy=CatalogSyncPolicy.CATALOG_ONLY.value,
            existing_policy=CatalogSyncPolicy.CONTINUOUS.value,
        )
        == CatalogSyncPolicy.ON_DEMAND.value
    )


def test_wgms_realtime_continuous_does_not_enroll() -> None:
    """WGMS emits CONTINUOUS for realtime folders, but only legacy_env may enroll.

    m230-style: in the water (ACTIVE) with a WGMS realtime folder, deliberately
    not in the env lists — must stay unenrolled (catalog_only).
    """
    session = _session()
    mission = CatalogMission(
        id="cat-m230",
        title="m230-SV3-1070",
        deployment_number=230,
        start_time=datetime(2026, 8, 21, tzinfo=timezone.utc),
        end_time=None,
        operational_state=CatalogOperationalState.ACTIVE.value,
        sync_policy=CatalogSyncPolicy.CATALOG_ONLY.value,
    )
    session.add(mission)
    session.commit()

    discovered = DiscoveredMission(
        provider_key="ceotr_wgms_remote",
        title="m230-SV3-1070",
        deployment_number=230,
        operational_state=CatalogOperationalState.ACTIVE,
        sync_policy=CatalogSyncPolicy.CONTINUOUS,
    )
    _update_mission_from_discovery(
        session,
        mission,
        discovered,
        platform=None,
        dry_run=False,
        manifest=_manifest(),
    )
    session.commit()
    session.refresh(mission)
    assert mission.sync_policy == CatalogSyncPolicy.CATALOG_ONLY.value


def test_apply_lifecycle_honors_adapter_completed_without_dates() -> None:
    discovered = DiscoveredMission(
        provider_key="ceotr_wgms_remote",
        title="m176-SV3-1070",
        deployment_number=176,
        operational_state=CatalogOperationalState.COMPLETED,
        sync_policy=CatalogSyncPolicy.CATALOG_ONLY,
    )
    state, policy = _apply_lifecycle_fields(discovered)
    assert state == CatalogOperationalState.COMPLETED.value
    assert policy == CatalogSyncPolicy.CATALOG_ONLY.value
