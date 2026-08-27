"""Unit tests for unmatched ERDDAP catalog source listing."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine

from app.core.mission_catalog.service import (
    _safe_provider_url,
    list_unmatched_sources,
    unmatched_source_to_read,
)
from app.core.models.database import CatalogMissionSource
from app.core.models.enums import CatalogMatchStatus, CatalogSourceKind, CatalogSourceVariant
from app.services.team_ops_catalog import get_ops_script, list_ops_scripts


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        engine,
        tables=[CatalogMissionSource.__table__],
    )
    return Session(engine)


def _add_source(
    session: Session,
    *,
    external_ref: str,
    source_kind: str = CatalogSourceKind.ERDDAP.value,
    match_status: str = CatalogMatchStatus.UNMATCHED.value,
    mission_id: str | None = None,
    last_seen_at: datetime | None = None,
    metadata_json: dict | None = None,
) -> CatalogMissionSource:
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    source = CatalogMissionSource(
        mission_id=mission_id,
        provider_key="oceantrack_erddap",
        source_kind=source_kind,
        collection="tabledap",
        external_ref=external_ref,
        source_variant=CatalogSourceVariant.REALTIME.value,
        enabled=True,
        match_status=match_status,
        first_seen_at=now,
        last_seen_at=last_seen_at or now,
        metadata_json=metadata_json,
    )
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


def test_list_unmatched_sources_filters_and_orders() -> None:
    session = _session()
    older = datetime(2026, 8, 20, tzinfo=timezone.utc)
    newer = datetime(2026, 8, 25, tzinfo=timezone.utc)
    _add_source(
        session,
        external_ref="bond_test_for_sci_water_depth_realtime",
        last_seen_at=newer,
        metadata_json={"server": "https://erddap.oceantrack.org/erddap"},
    )
    _add_source(
        session,
        external_ref="unit_1190_20250515_214_delayed",
        last_seen_at=older,
    )
    _add_source(
        session,
        external_ref="linked_dataset_realtime",
        mission_id="some-mission",
        match_status=CatalogMatchStatus.LINKED.value,
    )
    _add_source(
        session,
        external_ref="wgms_only_folder",
        source_kind="wgms_remote",
    )

    rows = list_unmatched_sources(session, source_kind="erddap")
    assert [r.external_ref for r in rows] == [
        "bond_test_for_sci_water_depth_realtime",
        "unit_1190_20250515_214_delayed",
    ]
    assert rows[0].provider_url == (
        "https://erddap.oceantrack.org/erddap/tabledap/"
        "bond_test_for_sci_water_depth_realtime.html"
    )
    assert rows[1].provider_url is None


def test_safe_provider_url_rejects_non_http() -> None:
    assert _safe_provider_url({"server": "ftp://evil"}, collection="tabledap", external_ref="x") is None
    assert _safe_provider_url({"server": "not-a-url"}, collection="tabledap", external_ref="x") is None
    assert (
        _safe_provider_url(
            {"server": "https://erddap.example/erddap"},
            collection="tabledap",
            external_ref="abc_realtime",
        )
        == "https://erddap.example/erddap/tabledap/abc_realtime.html"
    )


def test_unmatched_source_to_read_maps_fields() -> None:
    session = _session()
    source = _add_source(session, external_ref="unit_1190_20250515_214_delayed")
    read = unmatched_source_to_read(source)
    assert read.external_ref == "unit_1190_20250515_214_delayed"
    assert read.match_status == CatalogMatchStatus.UNMATCHED.value
    assert read.provider_key == "oceantrack_erddap"


def test_mission_catalog_page_registered_in_ops_catalog() -> None:
    spec = get_ops_script("mission_catalog")
    assert spec.kind == "page"
    assert spec.href == "/team/mission-catalog"
    assert any(s.id == "mission_catalog" for s in list_ops_scripts())
