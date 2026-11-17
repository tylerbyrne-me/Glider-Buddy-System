"""Team NAVWARN draft storage and duplicate-as-update."""

from __future__ import annotations

from sqlmodel import Session, SQLModel, create_engine, select

from app.core.models.database import (
    CatalogMission,
    CatalogPlatform,
    NavwarnRequest,
)
from app.core.models.schemas import NavwarnDraftWrite
from app.services import team_navwarn


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        engine,
        tables=[
            CatalogPlatform.__table__,
            CatalogMission.__table__,
            NavwarnRequest.__table__,
        ],
    )
    return Session(engine)


def _body(**overrides) -> NavwarnDraftWrite:
    data = dict(
        title="Spring Bloom",
        hull_name="C34166NS",
        desk="sydney",
        requester_name="Tyler Byrne, Dalhousie University, C34166NS",
        telephone="902-719-7078",
        email="tylerbyrne@dal.ca",
        publish_contact="no",
        is_update_or_cancel="no",
        start_datetime="15:00 UTC 2026-04-21",
        timezone="utc",
        days_of_operation="daily",
        hours_of_operation="24h",
        completion_datetime="15:00 UTC 2026-04-23",
        completion_firmness="estimated",
        position_format="dmm",
        latitude=44.512,
        longitude=-63.409,
        place_name="Halifax Approaches",
        nature_category="obstruction",
        nature_topic="other",
        nature_other="Acoustic/Oceanographic Survey",
        vessels_on_scene="Wave Glider C34166NS",
        wash_berth="none",
    )
    data.update(overrides)
    return NavwarnDraftWrite.model_validate(data)


def test_create_and_list_draft() -> None:
    session = _session()
    created = team_navwarn.create_draft(session, _body(), username="tyler")
    assert created.id is not None
    summaries = team_navwarn.list_drafts(session)
    assert len(summaries) == 1
    assert summaries[0].hull_name == "C34166NS"
    assert summaries[0].desk == "sydney"


def test_invalid_latitude_rejected() -> None:
    session = _session()
    try:
        team_navwarn.create_draft(session, _body(latitude=120), username="tyler")
    except team_navwarn.NavwarnError as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("expected NavwarnError")


def test_area_round_trip_and_duplicate() -> None:
    session = _session()
    area = {
        "mode": "polygon",
        "points": [
            {"lat": 44.5, "lon": -63.5},
            {"lat": 44.6, "lon": -63.4},
            {"lat": 44.4, "lon": -63.3},
        ],
        "radius_km": None,
    }
    created = team_navwarn.create_draft(session, _body(area=area), username="tyler")
    read = team_navwarn.draft_to_read(created)
    assert read.area is not None
    assert read.area.mode == "polygon"
    assert len(read.area.points) == 3

    copy = team_navwarn.duplicate_as_update(session, created.id, username="tyler")
    assert team_navwarn.draft_to_read(copy).area.points[1].lat == 44.6

    empty = team_navwarn.create_draft(
        session, _body(area={"mode": "course", "points": []}), username="tyler"
    )
    assert empty.area_json is None


def test_area_validation() -> None:
    session = _session()
    bad_areas = [
        {"mode": "zigzag", "points": [{"lat": 44.5, "lon": -63.5}]},
        {"mode": "hold", "points": [{"lat": 44.5, "lon": -63.5}, {"lat": 44.6, "lon": -63.4}]},
        {"mode": "course", "points": [{"lat": 95, "lon": -63.5}]},
        {"mode": "hold", "points": [{"lat": 44.5, "lon": -63.5}], "radius_km": -1},
    ]
    for area in bad_areas:
        try:
            team_navwarn.create_draft(session, _body(area=area), username="tyler")
        except team_navwarn.NavwarnError as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError(f"expected NavwarnError for {area}")


def test_duplicate_as_update() -> None:
    session = _session()
    created = team_navwarn.create_draft(session, _body(), username="tyler")
    copy = team_navwarn.duplicate_as_update(
        session,
        created.id,
        username="tyler",
        previous_navwarn_number="NW-N-0623-26",
    )
    assert copy.id != created.id
    assert copy.is_update_or_cancel == "yes"
    assert copy.previous_navwarn_number == "NW-N-0623-26"
    assert copy.hull_name == "C34166NS"
    assert "(update)" in (copy.title or "")
    rows = session.exec(select(NavwarnRequest)).all()
    assert len(rows) == 2


def test_wave_glider_mission_guard() -> None:
    session = _session()
    platform = CatalogPlatform(canonical_name="peggy", platform_family="slocum")
    session.add(platform)
    session.commit()
    session.refresh(platform)
    mission = CatalogMission(
        id="m-slocum",
        platform_id=platform.id,
        operational_state="active",
        title="Peggy",
    )
    session.add(mission)
    session.commit()
    try:
        team_navwarn.create_draft(
            session,
            _body(catalog_mission_id="m-slocum"),
            username="tyler",
        )
    except team_navwarn.NavwarnError as exc:
        assert "Wave Glider" in exc.message
    else:
        raise AssertionError("expected NavwarnError")


def test_render_docx_and_pdf() -> None:
    content, name = team_navwarn.render_draft_docx(_body(desk="port_aux_basques"))
    assert name.endswith(".docx")
    assert content[:2] == b"PK"
    pdf, pdf_name = team_navwarn.render_draft_pdf(_body())
    assert pdf_name.endswith(".pdf")
    assert pdf.startswith(b"%PDF")


def test_default_text_for_hull() -> None:
    text = team_navwarn.default_text_for_hull("C34167NS")
    assert "C34167NS" in text["vessels_on_scene"]
    assert "C34167NS" in text["markers_description"]
    assert "Acoustic/Oceanographic Survey" in text["nature_other"]


def test_float_hull_from_component_rows() -> None:
    from app.platforms.wave_glider.navwarn_form import parse_float_sv3_hull_id

    assert parse_float_sv3_hull_id("Float SV3 - C34167NS") == "C34167NS"
    assert parse_float_sv3_hull_id("float sv3 – C34164NS") == "C34164NS"
    assert parse_float_sv3_hull_id("SV3-1070") is None

    hull_id, component_name = team_navwarn.float_hull_from_component_rows(
        [
            {
                "component": {"name": "Float SV3 - C34167NS"},
                "start_time": "2026-01-01 00:00:00",
                "end_time": None,
            },
            {
                "component": {"name": "Some other part"},
                "start_time": "2026-01-01 00:00:00",
                "end_time": None,
            },
        ]
    )
    assert hull_id == "C34167NS"
    assert component_name == "Float SV3 - C34167NS"

    ended_only = team_navwarn.float_hull_from_component_rows(
        [
            {
                "component": {"name": "Float SV3 - C34167NS"},
                "start_time": "2025-01-01 00:00:00",
                "end_time": "2025-06-01 00:00:00",
            }
        ]
    )
    assert ended_only == (None, None)
