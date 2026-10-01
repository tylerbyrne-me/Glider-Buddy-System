"""Historical identity: resolver, labels, and safe mission_key repair."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine, select

from app.cli import mission_catalog_repair_duplicates as repair_cli
from app.core.mission_catalog.display_labels import (
    build_navigation_entries,
    slocum_nav_display_label,
    wave_glider_display_label,
)
from app.core.models.database import (
    CatalogMission,
    CatalogMissionSource,
    CatalogPlatform,
    MissionOverview,
    SlocumDeployment,
    SlocumDeploymentGoal,
    SlocumDeploymentMedia,
    SlocumDeploymentNote,
    SlocumSfmcSnapshot,
)
from app.core.models.enums import CatalogOperationalState, CatalogSyncPolicy
from app.platforms.slocum.deployment_service import (
    get_or_create_deployment_for_dataset,
    resolve_deployment_for_dataset,
)


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        engine,
        tables=[
            CatalogPlatform.__table__,
            CatalogMission.__table__,
            CatalogMissionSource.__table__,
            MissionOverview.__table__,
            SlocumDeployment.__table__,
            SlocumDeploymentGoal.__table__,
            SlocumDeploymentNote.__table__,
            SlocumDeploymentMedia.__table__,
            SlocumSfmcSnapshot.__table__,
        ],
    )
    return Session(engine)


def test_resolve_nav_display_label_m226_peggy() -> None:
    """Catalog cutover labels (ADR 0009) must resolve to the briefing owner."""
    session = _session()
    owner = SlocumDeployment(
        name="Peggy m226",
        glider_name="peggy",
        mission_key="peggy_20260621_226",
        erddap_dataset_id="peggy_20260621_226_realtime",
        status="active",
        is_active=True,
        created_by_username="pilot",
    )
    session.add(owner)
    session.commit()
    session.refresh(owner)

    for label in ("m226-Peggy", "m226-peggy", "M226-PEGGY"):
        resolved = resolve_deployment_for_dataset(session, label)
        assert resolved is not None, label
        assert resolved.id == owner.id

    created = get_or_create_deployment_for_dataset(
        session,
        "m226-Peggy",
        created_by_username="importer",
    )
    assert created is not None
    assert created.id == owner.id
    assert created.erddap_dataset_id == "peggy_20260621_226_realtime"
    assert created.mission_key == "peggy_20260621_226"
    assert len(session.exec(select(SlocumDeployment)).all()) == 1


def test_display_label_does_not_create_orphan() -> None:
    session = _session()
    missing = get_or_create_deployment_for_dataset(
        session,
        "m999-Nobody",
        created_by_username="importer",
    )
    assert missing is None
    assert session.exec(select(SlocumDeployment)).all() == []


def test_wave_glider_legacy_and_catalog_labels() -> None:
    assert wave_glider_display_label("1070-m170") == "m170-SV3-1070"
    assert (
        wave_glider_display_label(
            "m170",
            deployment_number=170,
            platform_canonical_name="SV3-1070",
        )
        == "m170-SV3-1070"
    )
    assert wave_glider_display_label("m170") == "m170"
    # Missing platform: keep folder-style key
    assert wave_glider_display_label("m209-C34167NS") == "m209-C34167NS"


def test_slocum_nav_labels_and_same_deployment_number_scopes() -> None:
    assert (
        slocum_nav_display_label("fundy_20260724_229_realtime") == "m229-Fundy"
    )
    assert (
        slocum_nav_display_label(
            "other_key",
            deployment_number=229,
            glider_name="peggy",
        )
        == "m229-Peggy"
    )
    # Same deployment number, different glider names stay distinct labels
    assert slocum_nav_display_label(
        "a", deployment_number=100, glider_name="fundy"
    ) != slocum_nav_display_label("b", deployment_number=100, glider_name="peggy")
    from app.core.mission_catalog.display_labels import parse_slocum_nav_display_label

    assert parse_slocum_nav_display_label("m226-Peggy") == {
        "deployment_number": 226,
        "glider_name": "Peggy",
    }
    assert parse_slocum_nav_display_label("peggy_20260621_226_realtime") is None


def test_resolve_includes_inactive_completed_owner() -> None:
    session = _session()
    owner = SlocumDeployment(
        name="Fundy hist",
        glider_name="fundy",
        mission_key="fundy_20260724_229",
        erddap_dataset_id="fundy_20260724_229_delayed",
        document_url="https://example.com/plan.pdf",
        status="completed",
        is_active=False,
        created_by_username="pilot",
        catalog_mission_id="cat-1",
    )
    session.add(owner)
    session.commit()
    session.refresh(owner)

    active_only = resolve_deployment_for_dataset(
        session, "fundy_20260724_229_delayed", include_inactive=False
    )
    assert active_only is None

    hist = resolve_deployment_for_dataset(
        session, "fundy_20260724_229_delayed", include_inactive=True
    )
    assert hist is not None
    assert hist.id == owner.id
    assert hist.document_url == "https://example.com/plan.pdf"


def test_historical_get_does_not_create_and_preserves_row_count() -> None:
    session = _session()
    owner = SlocumDeployment(
        name="Fundy hist",
        glider_name="fundy",
        mission_key="fundy_20260724_229",
        erddap_dataset_id="fundy_20260724_229_realtime",
        document_url="https://example.com/plan.pdf",
        status="completed",
        is_active=False,
        created_by_username="pilot",
    )
    session.add(owner)
    session.commit()
    session.refresh(owner)
    before = len(session.exec(select(SlocumDeployment)).all())

    resolved = get_or_create_deployment_for_dataset(
        session,
        "fundy_20260724_229_delayed",
        created_by_username="reader",
        allow_create=False,
        update_erddap_dataset_id=False,
    )
    assert resolved is not None
    assert resolved.id == owner.id
    after = len(session.exec(select(SlocumDeployment)).all())
    assert after == before

    missing = get_or_create_deployment_for_dataset(
        session,
        "unknown_20200101_1_realtime",
        created_by_username="reader",
        allow_create=False,
    )
    assert missing is None
    assert len(session.exec(select(SlocumDeployment)).all()) == before


def test_realtime_and_delayed_share_same_deployment_row() -> None:
    session = _session()
    dep = get_or_create_deployment_for_dataset(
        session,
        "fundy_20260724_229_realtime",
        created_by_username="pilot",
    )
    assert dep is not None
    owner_id = dep.id
    note = SlocumDeploymentNote(
        deployment_id=owner_id,
        content="briefing note",
        created_by_username="pilot",
    )
    session.add(note)
    session.commit()

    delayed = get_or_create_deployment_for_dataset(
        session,
        "fundy_20260724_229_delayed",
        created_by_username="system",
        update_erddap_dataset_id=True,
    )
    assert delayed is not None
    assert delayed.id == owner_id
    assert delayed.erddap_dataset_id == "fundy_20260724_229_delayed"
    assert delayed.mission_key == "fundy_20260724_229"
    notes = session.exec(
        select(SlocumDeploymentNote).where(
            SlocumDeploymentNote.deployment_id == owner_id
        )
    ).all()
    assert len(notes) == 1
    assert len(session.exec(select(SlocumDeployment)).all()) == 1


def test_resolve_does_not_reactivate_completed_row() -> None:
    session = _session()
    owner = SlocumDeployment(
        name="Fundy hist",
        glider_name="fundy",
        mission_key="fundy_20260724_229",
        erddap_dataset_id="fundy_20260724_229_delayed",
        status="completed",
        is_active=False,
        created_by_username="pilot",
    )
    session.add(owner)
    session.commit()

    again = get_or_create_deployment_for_dataset(
        session,
        "fundy_20260724_229_realtime",
        created_by_username="reader",
        allow_create=False,
        update_erddap_dataset_id=False,
    )
    assert again is not None
    assert again.is_active is False
    assert again.status == "completed"


def test_reopen_path_reactivates_same_row_via_explicit_update() -> None:
    """Ordinary reads must not reopen; explicit reactivation keeps the same id."""
    session = _session()
    owner = SlocumDeployment(
        name="Fundy hist",
        glider_name="fundy",
        mission_key="fundy_20260724_229",
        erddap_dataset_id="fundy_20260724_229_delayed",
        status="completed",
        is_active=False,
        created_by_username="pilot",
        catalog_mission_id="cat-reopen",
    )
    session.add(owner)
    session.commit()
    session.refresh(owner)

    # Simulate catalog reopen/provision: explicit reactivation + prefer realtime.
    owner.is_active = True
    owner.status = "active"
    owner.erddap_dataset_id = "fundy_20260724_229_realtime"
    owner.updated_at_utc = datetime.now(timezone.utc)
    session.add(owner)
    session.commit()
    session.refresh(owner)

    live = resolve_deployment_for_dataset(
        session, "fundy_20260724_229_realtime", include_inactive=False
    )
    assert live is not None
    assert live.id == owner.id
    assert live.is_active is True
    assert live.erddap_dataset_id.endswith("_realtime")


def test_navigation_entries_preserve_keys() -> None:
    session = _session()
    platform = CatalogPlatform(
        canonical_name="SV3-1070",
        platform_family="wave_glider",
    )
    session.add(platform)
    session.commit()
    session.refresh(platform)
    mission = CatalogMission(
        id="cat-wg-1",
        platform_id=platform.id,
        deployment_number=170,
        operational_state=CatalogOperationalState.COMPLETED.value,
        sync_policy=CatalogSyncPolicy.ON_DEMAND.value,
    )
    session.add(mission)
    overview = MissionOverview(
        mission_id="1070-m170",
        catalog_mission_id="cat-wg-1",
    )
    session.add(overview)
    session.commit()

    entries = build_navigation_entries(
        session, ["1070-m170"], platform_family="wave_glider"
    )
    assert entries == [
        {
            "key": "1070-m170",
            "label": "m170-SV3-1070",
            "catalog_mission_id": "cat-wg-1",
        }
    ]


def test_repair_safe_empty_orphan_and_ambiguous_refusal() -> None:
    session = _session()
    owner = SlocumDeployment(
        name="Owner",
        glider_name="fundy",
        mission_key="fundy_20260724_229",
        erddap_dataset_id="fundy_20260724_229_delayed",
        document_url="https://example.com/plan.pdf",
        status="completed",
        is_active=False,
        created_by_username="pilot",
        catalog_mission_id="cat-owner",
    )
    orphan = SlocumDeployment(
        name="Orphan",
        glider_name="fundy",
        mission_key="fundy_20260724_229",
        erddap_dataset_id="fundy_20260724_229_realtime",
        status="active",
        is_active=True,
        created_by_username="system",
    )
    session.add(owner)
    session.add(orphan)
    session.commit()

    groups = repair_cli.find_mission_key_groups(session)
    assert "fundy_20260724_229" in groups
    status, keep, remove = repair_cli.classify_mission_key_group(
        groups["fundy_20260724_229"]
    )
    assert status == "safe_auto"
    assert keep is not None and keep.id == owner.id
    assert [o.id for o in remove] == [orphan.id]

    fixed = repair_cli.repair_mission_key_orphans(session, apply=True)
    session.commit()
    assert fixed == 1
    remaining = session.exec(select(SlocumDeployment)).all()
    assert len(remaining) == 1
    assert remaining[0].id == owner.id

    # Idempotent
    assert repair_cli.repair_mission_key_orphans(session, apply=True) == 0

    # Ambiguous: two metadata-bearing rows
    session2 = _session()
    a = SlocumDeployment(
        name="A",
        glider_name="peggy",
        mission_key="peggy_20260621_226",
        erddap_dataset_id="peggy_20260621_226_realtime",
        document_url="https://a.example/plan.pdf",
        status="completed",
        is_active=False,
        created_by_username="pilot",
        catalog_mission_id="cat-a",
    )
    b = SlocumDeployment(
        name="B",
        glider_name="peggy",
        mission_key="peggy_20260621_226",
        erddap_dataset_id="peggy_20260621_226_delayed",
        weekly_report_url="https://b.example/report.pdf",
        status="active",
        is_active=True,
        created_by_username="pilot",
        catalog_mission_id="cat-b",
    )
    session2.add(a)
    session2.add(b)
    session2.commit()
    groups2 = repair_cli.find_mission_key_groups(session2)
    status2, keep2, remove2 = repair_cli.classify_mission_key_group(
        groups2["peggy_20260621_226"]
    )
    assert status2 == "ambiguous_metadata"
    assert keep2 is None
    assert remove2 == []
    assert repair_cli.repair_mission_key_orphans(session2, apply=True) == 0
    assert len(session2.exec(select(SlocumDeployment)).all()) == 2


def test_migration_preflight_detects_duplicate_mission_keys() -> None:
    """Exercise the same duplicate query shape used by alembic preflight."""
    session = _session()
    session.add(
        SlocumDeployment(
            name="A",
            glider_name="fundy",
            mission_key="fundy_20260724_229",
            erddap_dataset_id="fundy_20260724_229_realtime",
            created_by_username="a",
            is_active=False,
        )
    )
    session.add(
        SlocumDeployment(
            name="B",
            glider_name="fundy",
            mission_key="fundy_20260724_229",
            erddap_dataset_id="fundy_20260724_229_delayed",
            created_by_username="b",
            is_active=True,
        )
    )
    session.commit()
    groups = repair_cli.find_mission_key_groups(session)
    assert len(groups["fundy_20260724_229"]) == 2
