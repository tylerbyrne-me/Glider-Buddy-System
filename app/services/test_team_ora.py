"""Team ORA draft storage, hull memory, and catalog links."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine, select

from app.core.models.database import (
    CatalogMission,
    CatalogPlatform,
    MissionOverview,
    OraHullProfile,
    OraRequest,
    SlocumDeployment,
)
from app.core.models.schemas import OraDeviceRow, OraDraftWrite
from app.services import team_ora


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        engine,
        tables=[
            CatalogPlatform.__table__,
            CatalogMission.__table__,
            OraRequest.__table__,
            OraHullProfile.__table__,
            MissionOverview.__table__,
            SlocumDeployment.__table__,
        ],
    )
    return Session(engine)


def _body(**overrides) -> OraDraftWrite:
    data = dict(
        title="Spring Bloom",
        hull_name="SV3-1071",
        requester="ada",
        client="Dalhousie",
        purposes=["mission"],
        priority=3,
        coordinate_mode="course",
        coordinates=[{"label": "Coordinate 1", "lat": 44.5, "lon": -63.4, "comment": "Deploy"}],
        vehicle_model="sv3",
        umbilical_m="8",
        sv3_software_version="3.2.2",
        devices=[{"name": "SMC", "power_draw": "0.9w", "duty_cycle": "100%", "included": True}],
    )
    data.update(overrides)
    return OraDraftWrite.model_validate(data)


def test_draft_save_remembers_hull_and_keeps_last_software() -> None:
    session = _session()
    created = team_ora.create_draft(session, _body(), username="ada")
    assert created.id is not None
    profile = session.exec(
        select(OraHullProfile).where(OraHullProfile.hull_name == "SV3-1071")
    ).first()
    assert profile is not None
    assert profile.sv3_software_version == "3.2.2"
    assert profile.umbilical_m == "8"

    updated = team_ora.update_draft(
        session,
        created.id,
        _body(sv3_software_version=None, umbilical_m=None, notes="Night ops"),
        username="ada",
    )
    assert updated.notes == "Night ops"
    assert updated.sv3_software_version is None
    session.refresh(profile)
    assert profile.sv3_software_version == "3.2.2"
    assert profile.umbilical_m == "8"


def test_invalid_coordinate_is_rejected() -> None:
    session = _session()
    try:
        team_ora.create_draft(
            session, _body(coordinates=[{"lat": 120, "lon": 0}]), username="ada"
        )
    except team_ora.OraError as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("expected OraError")


def test_mission_options_and_context_tracks() -> None:
    session = _session()
    wg = CatalogPlatform(canonical_name="SV3-1071", platform_family="wave_glider")
    slocum = CatalogPlatform(canonical_name="peggy", platform_family="slocum")
    session.add(wg)
    session.add(slocum)
    session.commit()
    session.refresh(wg)
    session.refresh(slocum)
    active = CatalogMission(
        id="wg-active",
        platform_id=wg.id,
        deployment_number=240,
        operational_state="active",
        start_time=datetime(2026, 4, 7, tzinfo=timezone.utc),
        end_time=datetime(2026, 5, 6, tzinfo=timezone.utc),
    )
    done = CatalogMission(
        id="wg-done",
        platform_id=wg.id,
        deployment_number=200,
        operational_state="completed",
    )
    other = CatalogMission(
        id="sl-active",
        platform_id=slocum.id,
        deployment_number=224,
        operational_state="active",
    )
    session.add(active)
    session.add(done)
    session.add(other)
    session.add(MissionOverview(mission_id="m240", catalog_mission_id="wg-active"))
    session.add(
        SlocumDeployment(
            name="Peggy",
            glider_name="peggy",
            created_by_username="ada",
            mission_key="peggy_20260621_224",
            erddap_dataset_id="peggy_20260621_224_realtime",
            catalog_mission_id="sl-active",
        )
    )
    session.commit()

    options = team_ora.list_wave_glider_missions(session)
    assert [item.id for item in options] == ["wg-active"]
    assert options[0].label == "m240-SV3-1071"
    assert options[0].dates_of_operation == "7 Apr 2026 – 6 May 2026"
    assert options[0].vehicle_model == "sv3"

    try:
        team_ora.create_draft(
            session,
            _body(catalog_mission_id="sl-active"),
            username="ada",
        )
    except team_ora.OraError as exc:
        assert "Wave Glider" in exc.message
    else:
        raise AssertionError("expected OraError for a Slocum link")

    tracks = {track.catalog_mission_id: track for track in team_ora.list_context_tracks(session)}
    assert tracks["wg-active"].track_kind == "wave_glider"
    assert tracks["wg-active"].track_id == "m240"
    assert tracks["sl-active"].track_kind == "slocum"
    assert tracks["sl-active"].track_id == "peggy_20260621_224_realtime"
    assert "wg-done" not in tracks


def test_tracker_loadout_merges_platform_and_logger_instruments() -> None:
    class FakeService:
        def __init__(self, skip_auth: bool = True) -> None:
            self.skip_auth = skip_auth

        async def fetch_instruments_on_platform(self, platform_name: str):
            assert platform_name == "SV3-1071"
            return [{"instrument": {"name": "RDI 600 ADCP"}}]

        async def fetch_data_loggers_on_platform(self, platform_name: str):
            return [{"data_logger": {"identifier": "science-1"}}]

        async def fetch_instruments_on_data_logger(self, identifier: str):
            assert identifier == "science-1"
            return [{"instrument": {"identifier": "VM4-009"}}]

    import app.services.sensor_tracker_service as tracker_module

    original = tracker_module.SensorTrackerService
    tracker_module.SensorTrackerService = FakeService
    try:
        result = asyncio.run(
            team_ora.load_tracker_devices(
                "SV3-1071",
                [OraDeviceRow.model_validate(row) for row in []],
            )
        )
    finally:
        tracker_module.SensorTrackerService = original

    names = [row.name for row in result.devices]
    assert "RDI 600 ADCP" in names
    assert "Innovasea VM4" in names
    assert "VMC, Rudder, GPS" in names
