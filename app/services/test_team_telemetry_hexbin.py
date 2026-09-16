"""Unit tests for catalog-driven Team telemetry hexbin inventory."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine

from app.core.models.database import (
    CatalogMission,
    CatalogMissionSource,
    CatalogPlatform,
)
from app.core.models.enums import (
    CatalogMatchStatus,
    CatalogOperationalState,
    CatalogSourceKind,
    CatalogSourceVariant,
    CatalogSyncPolicy,
)
from app.services.team_telemetry_hexbin import (
    HexbinTrackSource,
    _cache_csv_path,
    _format_date_range,
    list_catalog_hexbin_sources,
    plot_hexbin,
)
import pandas as pd
from pathlib import Path
from unittest.mock import patch


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        engine,
        tables=[
            CatalogPlatform.__table__,
            CatalogMission.__table__,
            CatalogMissionSource.__table__,
        ],
    )
    return Session(engine)


def _add_platform(session: Session, *, name: str = "SV3-1070") -> CatalogPlatform:
    row = CatalogPlatform(
        canonical_name=name,
        platform_family="wave_glider",
        owner_organization="ceotr",
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _add_mission(
    session: Session,
    *,
    mission_id: str,
    platform_id: int,
    deployment_number: int | None,
    operational_state: str,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> CatalogMission:
    row = CatalogMission(
        id=mission_id,
        platform_id=platform_id,
        title=f"Mission {deployment_number}",
        deployment_number=deployment_number,
        start_time=start_time,
        end_time=end_time,
        operational_state=operational_state,
        sync_policy=(
            CatalogSyncPolicy.CONTINUOUS.value
            if operational_state == CatalogOperationalState.ACTIVE.value
            else CatalogSyncPolicy.ON_DEMAND.value
        ),
    )
    session.add(row)
    session.commit()
    return row


def _add_source(
    session: Session,
    *,
    mission_id: str,
    source_kind: str,
    collection: str,
    external_ref: str,
    source_variant: str = CatalogSourceVariant.UNKNOWN.value,
    enabled: bool = True,
    match_status: str = CatalogMatchStatus.LINKED.value,
    capabilities_json: str | None = '["track","telemetry"]',
) -> CatalogMissionSource:
    row = CatalogMissionSource(
        mission_id=mission_id,
        provider_key="test_provider",
        source_kind=source_kind,
        collection=collection,
        external_ref=external_ref,
        source_variant=source_variant,
        capabilities_json=capabilities_json,
        enabled=enabled,
        match_status=match_status,
        is_verified=True,
    )
    session.add(row)
    session.commit()
    return row


def test_inventory_includes_active_realtime_and_past_and_erddap() -> None:
    session = _session()
    platform = _add_platform(session)
    active = _add_mission(
        session,
        mission_id="cat-active-230",
        platform_id=platform.id,
        deployment_number=230,
        operational_state=CatalogOperationalState.ACTIVE.value,
        start_time=datetime(2026, 8, 21, tzinfo=timezone.utc),
    )
    completed = _add_mission(
        session,
        mission_id="cat-done-216",
        platform_id=platform.id,
        deployment_number=216,
        operational_state=CatalogOperationalState.COMPLETED.value,
        start_time=datetime(2025, 10, 10, tzinfo=timezone.utc),
        end_time=datetime(2025, 11, 7, tzinfo=timezone.utc),
    )
    _add_source(
        session,
        mission_id=active.id,
        source_kind=CatalogSourceKind.WGMS_REMOTE.value,
        collection="output_realtime_missions",
        external_ref="m230-SV3-1070",
        source_variant=CatalogSourceVariant.REALTIME.value,
    )
    _add_source(
        session,
        mission_id=completed.id,
        source_kind=CatalogSourceKind.WGMS_REMOTE.value,
        collection="output_past_missions",
        external_ref="m216-C34164NS",
    )
    _add_source(
        session,
        mission_id=completed.id,
        source_kind=CatalogSourceKind.ERDDAP.value,
        collection="tabledap",
        external_ref="DL_20150820_49_delayed",
        source_variant=CatalogSourceVariant.DELAYED.value,
    )

    sources = list_catalog_hexbin_sources(session, source_filter="all", max_missions=40)
    refs = [s.external_ref for s in sources]
    assert "m230-SV3-1070" in refs
    assert "m216-C34164NS" in refs
    assert "DL_20150820_49_delayed" in refs
    # Active mission comes first.
    assert sources[0].external_ref == "m230-SV3-1070"
    assert sources[0].collection == "output_realtime_missions"


def test_inventory_excludes_disabled_stale_conflict() -> None:
    session = _session()
    platform = _add_platform(session)
    mission = _add_mission(
        session,
        mission_id="cat-m1",
        platform_id=platform.id,
        deployment_number=200,
        operational_state=CatalogOperationalState.COMPLETED.value,
    )
    _add_source(
        session,
        mission_id=mission.id,
        source_kind=CatalogSourceKind.WGMS_REMOTE.value,
        collection="output_past_missions",
        external_ref="m200-good",
    )
    _add_source(
        session,
        mission_id=mission.id,
        source_kind=CatalogSourceKind.WGMS_REMOTE.value,
        collection="output_past_missions",
        external_ref="m200-disabled",
        enabled=False,
    )
    _add_source(
        session,
        mission_id=mission.id,
        source_kind=CatalogSourceKind.WGMS_REMOTE.value,
        collection="output_past_missions",
        external_ref="m200-stale",
        match_status=CatalogMatchStatus.STALE.value,
    )
    _add_source(
        session,
        mission_id=mission.id,
        source_kind=CatalogSourceKind.ERDDAP.value,
        collection="tabledap",
        external_ref="bad_conflict",
        match_status=CatalogMatchStatus.CONFLICT.value,
    )

    sources = list_catalog_hexbin_sources(session, source_filter="all")
    assert [s.external_ref for s in sources] == ["m200-good"]


def test_max_missions_keeps_all_sources_for_included_missions() -> None:
    session = _session()
    platform = _add_platform(session)
    active = _add_mission(
        session,
        mission_id="cat-a",
        platform_id=platform.id,
        deployment_number=230,
        operational_state=CatalogOperationalState.ACTIVE.value,
    )
    older = _add_mission(
        session,
        mission_id="cat-b",
        platform_id=platform.id,
        deployment_number=100,
        operational_state=CatalogOperationalState.COMPLETED.value,
    )
    newer_completed = _add_mission(
        session,
        mission_id="cat-c",
        platform_id=platform.id,
        deployment_number=220,
        operational_state=CatalogOperationalState.COMPLETED.value,
    )
    for collection, ref in (
        ("output_realtime_missions", "m230-rt"),
        ("output_past_missions", "m230-past"),
    ):
        _add_source(
            session,
            mission_id=active.id,
            source_kind=CatalogSourceKind.WGMS_REMOTE.value,
            collection=collection,
            external_ref=ref,
            source_variant=(
                CatalogSourceVariant.REALTIME.value
                if "realtime" in collection
                else CatalogSourceVariant.UNKNOWN.value
            ),
        )
    _add_source(
        session,
        mission_id=newer_completed.id,
        source_kind=CatalogSourceKind.WGMS_REMOTE.value,
        collection="output_past_missions",
        external_ref="m220-past",
    )
    _add_source(
        session,
        mission_id=older.id,
        source_kind=CatalogSourceKind.WGMS_REMOTE.value,
        collection="output_past_missions",
        external_ref="m100-past",
    )

    sources = list_catalog_hexbin_sources(session, source_filter="wgms", max_missions=2)
    refs = [s.external_ref for s in sources]
    assert refs == ["m230-rt", "m230-past", "m220-past"]
    assert "m100-past" not in refs
    # Cap applies to missions; both sources for the active mission are kept.
    assert sum(1 for s in sources if s.mission_id == active.id) == 2


def test_cache_path_namespaces_by_collection() -> None:
    realtime = HexbinTrackSource(
        mission_id="m1",
        deployment_number=230,
        operational_state="active",
        source_kind="wgms_remote",
        collection="output_realtime_missions",
        external_ref="m230-SV3-1070",
        source_variant="realtime",
    )
    past = HexbinTrackSource(
        mission_id="m1",
        deployment_number=230,
        operational_state="active",
        source_kind="wgms_remote",
        collection="output_past_missions",
        external_ref="m230-SV3-1070",
        source_variant="unknown",
    )
    assert _cache_csv_path(realtime) != _cache_csv_path(past)
    assert "output_realtime_missions" in str(_cache_csv_path(realtime))
    assert "output_past_missions" in str(_cache_csv_path(past))


def test_date_range_includes_2026_when_active_points_present() -> None:
    frame = pd.DataFrame(
        {
            "Timestamp": [
                "2025-06-01T00:00:00Z",
                "2026-09-01T12:00:00Z",
            ]
        }
    )
    assert _format_date_range(frame["Timestamp"]) == "2025-06-01 - 2026-09-01"


def test_plot_hexbin_adds_regional_inset(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "Longitude": [-60.4, -60.3, -60.2],
            "Latitude": [44.0, 44.05, 44.1],
            "Timestamp": [
                "2026-08-01T00:00:00Z",
                "2026-08-02T00:00:00Z",
                "2026-08-03T00:00:00Z",
            ],
        }
    )
    extent = (-60.5, -60.1, 43.9, 44.2)
    output = tmp_path / "hexbin_with_inset.png"

    with patch(
        "app.services.team_telemetry_hexbin._add_report_regional_inset"
    ) as add_inset, patch(
        "app.services.team_telemetry_hexbin._regional_inset_extent",
        return_value=[-62.0, -58.0, 42.0, 46.0],
    ) as regional_extent:
        plot_hexbin(
            frame,
            extent,
            gridsize=10,
            output_path=output,
            title="Test hexbin",
            include_bathymetry=False,
            include_regional_inset=True,
        )

    regional_extent.assert_called_once()
    add_inset.assert_called_once()
    assert add_inset.call_args.args[2] == list(extent)
    assert output.is_file()
    assert output.stat().st_size > 0


def test_plot_hexbin_can_skip_regional_inset(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "Longitude": [-60.4, -60.3],
            "Latitude": [44.0, 44.05],
            "Timestamp": ["2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"],
        }
    )
    output = tmp_path / "hexbin_no_inset.png"
    with patch(
        "app.services.team_telemetry_hexbin._add_report_regional_inset"
    ) as add_inset:
        plot_hexbin(
            frame,
            (-60.5, -60.1, 43.9, 44.2),
            gridsize=10,
            output_path=output,
            title="Test hexbin",
            include_bathymetry=False,
            include_regional_inset=False,
        )
    add_inset.assert_not_called()
    assert output.is_file()
