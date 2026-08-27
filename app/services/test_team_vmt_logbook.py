"""Unit tests for Team VMT log book service (local DB + mocked ST sync)."""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.models.database import (
    VmtBatteryCheck,
    VmtServiceEvent,
    VmtUnit,
    VmtUnitAuditLog,
)
from app.core.models.enums import (
    VmtCreatedVia,
    VmtCustodyStatus,
    VmtSensorTrackerLinkStatus,
    VmtServiceEventType,
)
from app.core.models.schemas import (
    VmtBatteryCheckCreate,
    VmtServiceEventCreate,
    VmtUnitCreate,
    VmtUnitUpdate,
)
from app.services import team_vmt_logbook as vmt
from app.services.sensor_tracker_query import SensorTrackerQueryError


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        engine,
        tables=[
            VmtUnit.__table__,
            VmtBatteryCheck.__table__,
            VmtServiceEvent.__table__,
            VmtUnitAuditLog.__table__,
        ],
    )
    return Session(engine)


def test_create_unit_and_reject_duplicate_serial():
    session = _session()
    unit = vmt.create_unit(
        session,
        VmtUnitCreate(
            serial_number="1540753",
            tag_id="54908",
            custody_status=VmtCustodyStatus.COVE.value,
        ),
        username="tester",
    )
    assert unit.id is not None
    assert unit.serial_number == "1540753"
    assert unit.created_via == VmtCreatedVia.MANUAL.value
    assert unit.sensor_tracker_link_status == VmtSensorTrackerLinkStatus.NEVER_LINKED.value

    with pytest.raises(vmt.VmtLogbookError) as exc:
        vmt.create_unit(
            session,
            VmtUnitCreate(serial_number="1540753"),
            username="tester",
        )
    assert exc.value.status_code == 409


def test_append_battery_and_service_are_append_only():
    session = _session()
    unit = vmt.create_unit(
        session,
        VmtUnitCreate(serial_number="1188712"),
        username="tester",
    )
    b1 = vmt.append_battery_check(
        session,
        unit.id,
        VmtBatteryCheckCreate(
            checked_at=date(2026, 1, 13),
            days_remaining=100,
            percent_remaining=50,
        ),
        username="tester",
    )
    b2 = vmt.append_battery_check(
        session,
        unit.id,
        VmtBatteryCheckCreate(
            checked_at=date(2026, 6, 19),
            days_remaining=80,
            percent_remaining=40,
        ),
        username="tester",
    )
    assert b1.id != b2.id
    rows = session.exec(select(VmtBatteryCheck)).all()
    assert len(rows) == 2

    s1 = vmt.append_service_event(
        session,
        unit.id,
        VmtServiceEventCreate(
            event_type=VmtServiceEventType.REBATTERY.value,
            description="Rebattery 2024",
            event_date=date(2024, 1, 1),
        ),
        username="tester",
    )
    assert s1.id is not None
    assert len(session.exec(select(VmtServiceEvent)).all()) == 1


def test_update_unit_writes_audit_log():
    session = _session()
    unit = vmt.create_unit(
        session,
        VmtUnitCreate(serial_number="1360669", always_tx=False),
        username="tester",
    )
    vmt.update_unit(
        session,
        unit.id,
        VmtUnitUpdate(always_tx=True, comments="New battery"),
        username="auditor",
    )
    audits = session.exec(select(VmtUnitAuditLog)).all()
    assert len(audits) == 1
    assert audits[0].changed_by_username == "auditor"
    assert "always_tx" in audits[0].changes_json
    assert audits[0].changes_json["always_tx"]["before"] is False
    assert audits[0].changes_json["always_tx"]["after"] is True


def test_sync_creates_and_is_idempotent():
    session = _session()

    discovered: List[Dict[str, Any]] = [
        {"id": 336, "identifier": "vmt", "serial": "1540753"},
        {"id": 337, "identifier": "vmt", "serial": "1282445"},
    ]

    async def _run() -> None:
        with patch.object(
            vmt, "discover_vmt_instruments", new=AsyncMock(return_value=discovered)
        ):
            first = await vmt.sync_vmt_units_from_sensor_tracker(
                session, username="syncer", dry_run=False
            )
            assert first.created == 2
            assert first.updated == 0
            units = session.exec(select(VmtUnit)).all()
            assert len(units) == 2
            by_serial = {u.serial_number: u for u in units}
            assert by_serial["1540753"].sensor_tracker_instrument_id == 336
            assert (
                by_serial["1540753"].sensor_tracker_link_status
                == VmtSensorTrackerLinkStatus.LINKED.value
            )
            assert by_serial["1540753"].created_via == VmtCreatedVia.ST_SYNC.value

            second = await vmt.sync_vmt_units_from_sensor_tracker(
                session, username="syncer", dry_run=False
            )
            assert second.created == 0
            assert second.unchanged == 2
            assert len(session.exec(select(VmtUnit)).all()) == 2

    asyncio.run(_run())


def test_sync_marks_link_lost_without_deleting_history():
    session = _session()
    unit = vmt.create_unit(
        session,
        VmtUnitCreate(
            serial_number="9999999",
            sensor_tracker_instrument_id=999,
        ),
        username="tester",
    )
    vmt.append_battery_check(
        session,
        unit.id,
        VmtBatteryCheckCreate(
            checked_at=date(2026, 1, 1),
            percent_remaining=10,
            days_remaining=5,
        ),
        username="tester",
    )
    vmt.append_service_event(
        session,
        unit.id,
        VmtServiceEventCreate(
            event_type=VmtServiceEventType.OTHER.value,
            description="Keep me",
        ),
        username="tester",
    )

    async def _run() -> None:
        with patch.object(
            vmt, "discover_vmt_instruments", new=AsyncMock(return_value=[])
        ):
            result = await vmt.sync_vmt_units_from_sensor_tracker(
                session, username="syncer", dry_run=False
            )
        assert result.link_lost == 1
        refreshed = session.get(VmtUnit, unit.id)
        assert refreshed is not None
        assert (
            refreshed.sensor_tracker_link_status
            == VmtSensorTrackerLinkStatus.NOT_FOUND.value
        )
        assert refreshed.sensor_tracker_instrument_id == 999
        assert len(session.exec(select(VmtBatteryCheck)).all()) == 1
        assert len(session.exec(select(VmtServiceEvent)).all()) == 1

    asyncio.run(_run())


def test_st_accounting_not_found_retains_local_message():
    session = _session()
    unit = vmt.create_unit(
        session,
        VmtUnitCreate(
            serial_number="1540747",
            sensor_tracker_instrument_id=42,
        ),
        username="tester",
    )

    async def _run() -> None:
        with patch(
            "app.services.team_vmt_logbook.resolve_instrument_by_serial",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.team_vmt_logbook.get_entity_analytics",
            new=AsyncMock(
                side_effect=SensorTrackerQueryError("gone", status_code=404)
            ),
        ), patch(
            "app.services.team_vmt_logbook.get_entity_detail",
            new=AsyncMock(
                side_effect=SensorTrackerQueryError("gone", status_code=404)
            ),
        ):
            payload = await vmt.get_st_accounting(session, unit.id)

        assert payload.link_status == VmtSensorTrackerLinkStatus.NOT_FOUND.value
        assert payload.message is not None
        assert "last known ST instrument #42" in payload.message
        assert session.get(VmtUnit, unit.id) is not None

    asyncio.run(_run())


def test_list_item_hides_custody_when_attached():
    session = _session()
    unit = vmt.create_unit(
        session,
        VmtUnitCreate(
            serial_number="1282445",
            custody_status=VmtCustodyStatus.COVE.value,
        ),
        username="tester",
    )
    item = vmt._list_item_from_unit(
        session,
        unit,
        is_attached=True,
        attached_platform_name="SV3-1071",
    )
    assert item.is_attached is True
    assert item.attached_platform_name == "SV3-1071"
    assert item.custody_status is None


def test_seed_idempotent():
    from app.cli.vmt_logbook_seed import seed_vmt_logbook

    session = _session()
    first = seed_vmt_logbook(session, dry_run=False, username="seed")
    assert first["created"] == 26
    assert first["batteries"] >= 1
    second = seed_vmt_logbook(session, dry_run=False, username="seed")
    assert second["created"] == 0
    assert second["updated"] == 26
    assert second["batteries"] == 0
    assert len(session.exec(select(VmtUnit)).all()) == 26
