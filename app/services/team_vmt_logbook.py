"""Team VMT (Vemco Mobile Transceiver) log book service.

Local SQLite is the source of truth for inventory, battery checks, and service
history. Sensor Tracker is read-only for linkage, attachment, and service-time
accounting (same helpers as the Team Sensor Tracker browser).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx
from sqlmodel import Session as SQLModelSession, select

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
    SensorTrackerAnalyticsResponse,
    SensorTrackerDetailResponse,
    VmtBatteryCheckCreate,
    VmtBatteryCheckRead,
    VmtServiceEventCreate,
    VmtServiceEventRead,
    VmtStAccountingResponse,
    VmtStAttachmentRow,
    VmtSyncPreviewItem,
    VmtSyncResult,
    VmtUnitAuditLogRead,
    VmtUnitCreate,
    VmtUnitDetail,
    VmtUnitListItem,
    VmtUnitListResponse,
    VmtUnitUpdate,
)
from app.services.sensor_tracker_analytics import is_current_at
from app.services.sensor_tracker_query import (
    RELATIONSHIP_FETCH_CAP,
    SensorTrackerQueryError,
    _instrument_attachment_rows,
    _platform_ref_from_relationship,
    _record_id,
    _serial_of,
    _walk_tracker_pages,
    get_entity_analytics,
    get_entity_detail,
    get_entity_record,
    get_spec,
    relationship_window,
    resolve_entity_path,
)

logger = logging.getLogger(__name__)

VMT_ST_IDENTIFIER = "vmt"
DEFAULT_CODE_MAP = "A69-9001"
LOW_BATTERY_PERCENT = 20
LOW_BATTERY_DAYS = 45
ST_OVERLAY_CONCURRENCY = 6

_AUDIT_FIELDS = (
    "tag_id",
    "code_map",
    "always_tx",
    "comments",
    "custody_status",
    "custody_status_other",
    "sensor_tracker_instrument_id",
    "is_active",
)

_CUSTODY_VALUES = {s.value for s in VmtCustodyStatus}
_SERVICE_EVENT_VALUES = {s.value for s in VmtServiceEventType}


class VmtLogbookError(Exception):
    """Domain error for VMT log book operations."""

    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_serial(value: str) -> str:
    return (value or "").strip()


def _validate_custody(status: Optional[str], other: Optional[str]) -> None:
    if status is None or status == "":
        return
    if status not in _CUSTODY_VALUES:
        raise VmtLogbookError(
            f"Invalid custody_status; expected one of {sorted(_CUSTODY_VALUES)}"
        )
    if status == VmtCustodyStatus.OTHER.value and not (other or "").strip():
        raise VmtLogbookError("custody_status_other is required when status is other")


def _validate_service_event_type(event_type: str) -> str:
    value = (event_type or "").strip()
    if value not in _SERVICE_EVENT_VALUES:
        raise VmtLogbookError(
            f"Invalid event_type; expected one of {sorted(_SERVICE_EVENT_VALUES)}"
        )
    return value


def _latest_battery(session: SQLModelSession, unit_id: int) -> Optional[VmtBatteryCheck]:
    return session.exec(
        select(VmtBatteryCheck)
        .where(VmtBatteryCheck.vmt_unit_id == unit_id)
        .order_by(
            VmtBatteryCheck.checked_at.desc(),
            VmtBatteryCheck.recorded_at_utc.desc(),
            VmtBatteryCheck.id.desc(),
        )
    ).first()


def _is_low_battery(
    days_remaining: Optional[int],
    percent_remaining: Optional[int],
) -> bool:
    if percent_remaining is not None and percent_remaining < LOW_BATTERY_PERCENT:
        return True
    if days_remaining is not None and days_remaining < LOW_BATTERY_DAYS:
        return True
    return False


def _st_browser_url(instrument_id: Optional[int]) -> Optional[str]:
    if instrument_id is None:
        return None
    return f"/team/sensor-tracker?type=instrument&id={instrument_id}"


def _unit_snapshot(unit: VmtUnit) -> Dict[str, Any]:
    return {field: getattr(unit, field) for field in _AUDIT_FIELDS}


def _write_audit(
    session: SQLModelSession,
    *,
    unit: VmtUnit,
    before: Dict[str, Any],
    after: Dict[str, Any],
    username: Optional[str],
) -> None:
    changes: Dict[str, Any] = {}
    for key in _AUDIT_FIELDS:
        old = before.get(key)
        new = after.get(key)
        if old != new:
            changes[key] = {"before": old, "after": new}
    if not changes:
        return
    session.add(
        VmtUnitAuditLog(
            vmt_unit_id=unit.id,
            changed_by_username=username,
            changed_at_utc=_utcnow(),
            changes_json=changes,
        )
    )


def get_unit_or_404(session: SQLModelSession, unit_id: int) -> VmtUnit:
    unit = session.get(VmtUnit, unit_id)
    if unit is None:
        raise VmtLogbookError(f"VMT unit {unit_id} not found", status_code=404)
    return unit


def create_unit(
    session: SQLModelSession,
    body: VmtUnitCreate,
    *,
    username: str,
    created_via: str = VmtCreatedVia.MANUAL.value,
) -> VmtUnit:
    serial = _normalize_serial(body.serial_number)
    if not serial:
        raise VmtLogbookError("serial_number is required")
    existing = session.exec(
        select(VmtUnit).where(VmtUnit.serial_number == serial)
    ).first()
    if existing is not None:
        raise VmtLogbookError(
            f"VMT with serial {serial} already exists (id={existing.id})",
            status_code=409,
        )
    _validate_custody(body.custody_status, body.custody_status_other)
    now = _utcnow()
    link_status = VmtSensorTrackerLinkStatus.NEVER_LINKED.value
    if body.sensor_tracker_instrument_id is not None:
        link_status = VmtSensorTrackerLinkStatus.LINKED.value
    unit = VmtUnit(
        serial_number=serial,
        tag_id=(body.tag_id or "").strip() or None,
        code_map=(body.code_map or DEFAULT_CODE_MAP).strip() or DEFAULT_CODE_MAP,
        always_tx=bool(body.always_tx),
        comments=body.comments,
        custody_status=body.custody_status or None,
        custody_status_other=body.custody_status_other,
        sensor_tracker_instrument_id=body.sensor_tracker_instrument_id,
        sensor_tracker_identifier=(
            VMT_ST_IDENTIFIER if body.sensor_tracker_instrument_id is not None else None
        ),
        sensor_tracker_link_status=link_status,
        created_via=created_via,
        is_active=bool(body.is_active),
        created_at_utc=now,
        updated_at_utc=now,
        updated_by_username=username,
    )
    session.add(unit)
    session.commit()
    session.refresh(unit)
    return unit


def update_unit(
    session: SQLModelSession,
    unit_id: int,
    body: VmtUnitUpdate,
    *,
    username: str,
) -> VmtUnit:
    unit = get_unit_or_404(session, unit_id)
    before = _unit_snapshot(unit)
    data = body.model_dump(exclude_unset=True)
    if "custody_status" in data or "custody_status_other" in data:
        status = data.get("custody_status", unit.custody_status)
        other = data.get("custody_status_other", unit.custody_status_other)
        _validate_custody(status, other)
    for key, value in data.items():
        if key == "code_map" and value is not None:
            value = (value or "").strip() or DEFAULT_CODE_MAP
        if key == "tag_id" and value is not None:
            value = (value or "").strip() or None
        setattr(unit, key, value)
    if "sensor_tracker_instrument_id" in data:
        st_id = data["sensor_tracker_instrument_id"]
        if st_id is None:
            if unit.sensor_tracker_link_status == VmtSensorTrackerLinkStatus.LINKED.value:
                unit.sensor_tracker_link_status = (
                    VmtSensorTrackerLinkStatus.NEVER_LINKED.value
                )
        else:
            unit.sensor_tracker_link_status = VmtSensorTrackerLinkStatus.LINKED.value
            if not unit.sensor_tracker_identifier:
                unit.sensor_tracker_identifier = VMT_ST_IDENTIFIER
    unit.updated_at_utc = _utcnow()
    unit.updated_by_username = username
    after = _unit_snapshot(unit)
    _write_audit(session, unit=unit, before=before, after=after, username=username)
    session.add(unit)
    session.commit()
    session.refresh(unit)
    return unit


def append_battery_check(
    session: SQLModelSession,
    unit_id: int,
    body: VmtBatteryCheckCreate,
    *,
    username: str,
) -> VmtBatteryCheck:
    unit = get_unit_or_404(session, unit_id)
    row = VmtBatteryCheck(
        vmt_unit_id=unit.id,
        checked_at=body.checked_at,
        days_remaining=body.days_remaining,
        percent_remaining=body.percent_remaining,
        notes=body.notes,
        recorded_by_username=username,
        recorded_at_utc=_utcnow(),
    )
    session.add(row)
    unit.updated_at_utc = _utcnow()
    unit.updated_by_username = username
    session.add(unit)
    session.commit()
    session.refresh(row)
    return row


def append_service_event(
    session: SQLModelSession,
    unit_id: int,
    body: VmtServiceEventCreate,
    *,
    username: str,
) -> VmtServiceEvent:
    unit = get_unit_or_404(session, unit_id)
    event_type = _validate_service_event_type(body.event_type)
    row = VmtServiceEvent(
        vmt_unit_id=unit.id,
        event_date=body.event_date,
        event_type=event_type,
        description=body.description,
        recorded_by_username=username,
        recorded_at_utc=_utcnow(),
    )
    session.add(row)
    unit.updated_at_utc = _utcnow()
    unit.updated_by_username = username
    session.add(unit)
    session.commit()
    session.refresh(row)
    return row


def list_units_local(
    session: SQLModelSession,
    *,
    include_inactive: bool = False,
) -> List[VmtUnit]:
    stmt = select(VmtUnit).order_by(VmtUnit.serial_number)
    if not include_inactive:
        stmt = stmt.where(VmtUnit.is_active.is_(True))
    return list(session.exec(stmt).all())


def _list_item_from_unit(
    session: SQLModelSession,
    unit: VmtUnit,
    *,
    is_attached: bool = False,
    attached_platform_name: Optional[str] = None,
) -> VmtUnitListItem:
    latest = _latest_battery(session, unit.id) if unit.id is not None else None
    days = latest.days_remaining if latest else None
    percent = latest.percent_remaining if latest else None
    return VmtUnitListItem(
        id=unit.id,
        serial_number=unit.serial_number,
        tag_id=unit.tag_id,
        code_map=unit.code_map,
        always_tx=unit.always_tx,
        comments=unit.comments,
        custody_status=None if is_attached else unit.custody_status,
        custody_status_other=None if is_attached else unit.custody_status_other,
        sensor_tracker_instrument_id=unit.sensor_tracker_instrument_id,
        sensor_tracker_identifier=unit.sensor_tracker_identifier,
        sensor_tracker_link_status=unit.sensor_tracker_link_status,
        created_via=unit.created_via,
        is_active=unit.is_active,
        updated_at_utc=unit.updated_at_utc,
        updated_by_username=unit.updated_by_username,
        latest_battery_checked_at=latest.checked_at if latest else None,
        latest_days_remaining=days,
        latest_percent_remaining=percent,
        is_attached=is_attached,
        attached_platform_name=attached_platform_name,
        st_browser_url=_st_browser_url(unit.sensor_tracker_instrument_id),
        low_battery=_is_low_battery(days, percent),
    )


def unit_detail_local(session: SQLModelSession, unit_id: int) -> VmtUnitDetail:
    unit = get_unit_or_404(session, unit_id)
    base = _list_item_from_unit(session, unit)
    batteries = session.exec(
        select(VmtBatteryCheck)
        .where(VmtBatteryCheck.vmt_unit_id == unit_id)
        .order_by(
            VmtBatteryCheck.checked_at.desc(),
            VmtBatteryCheck.recorded_at_utc.desc(),
        )
    ).all()
    services = session.exec(
        select(VmtServiceEvent)
        .where(VmtServiceEvent.vmt_unit_id == unit_id)
        .order_by(
            VmtServiceEvent.event_date.desc(),
            VmtServiceEvent.recorded_at_utc.desc(),
        )
    ).all()
    audits = session.exec(
        select(VmtUnitAuditLog)
        .where(VmtUnitAuditLog.vmt_unit_id == unit_id)
        .order_by(VmtUnitAuditLog.changed_at_utc.desc())
    ).all()
    return VmtUnitDetail(
        **base.model_dump(),
        sensor_tracker_last_seen_at_utc=unit.sensor_tracker_last_seen_at_utc,
        sensor_tracker_last_sync_at_utc=unit.sensor_tracker_last_sync_at_utc,
        sensor_tracker_sync_error=unit.sensor_tracker_sync_error,
        created_at_utc=unit.created_at_utc,
        battery_checks=[VmtBatteryCheckRead.model_validate(r) for r in batteries],
        service_events=[VmtServiceEventRead.model_validate(r) for r in services],
        audit_logs=[VmtUnitAuditLogRead.model_validate(r) for r in audits],
    )


# ---------------------------------------------------------------------------
# Sensor Tracker live helpers
# ---------------------------------------------------------------------------


async def resolve_instrument_by_serial(
    serial: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[Dict[str, Any]]:
    """Return the first ST instrument whose serial matches exactly."""
    serial = _normalize_serial(serial)
    if not serial:
        return None
    path = await resolve_entity_path(get_spec("instrument"), client=client)
    rows, _count, _more = await _walk_tracker_pages(
        path,
        {"serial": serial},
        min_rows=RELATIONSHIP_FETCH_CAP,
        max_rows=RELATIONSHIP_FETCH_CAP,
        client=client,
    )
    exact = [
        row
        for row in rows
        if isinstance(row, dict) and (_serial_of(row) or "").strip() == serial
    ]
    if exact:
        return exact[0]
    # Fallback: identifier=vmt scan filtered by serial (if serial filter ignored)
    rows, _count, _more = await _walk_tracker_pages(
        path,
        {"identifier": VMT_ST_IDENTIFIER},
        min_rows=RELATIONSHIP_FETCH_CAP,
        max_rows=RELATIONSHIP_FETCH_CAP,
        client=client,
    )
    for row in rows:
        if isinstance(row, dict) and (_serial_of(row) or "").strip() == serial:
            return row
    return None


async def discover_vmt_instruments(
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> List[Dict[str, Any]]:
    """All Sensor Tracker instruments with identifier == vmt."""
    path = await resolve_entity_path(get_spec("instrument"), client=client)
    rows, _count, _more = await _walk_tracker_pages(
        path,
        {"identifier": VMT_ST_IDENTIFIER},
        min_rows=RELATIONSHIP_FETCH_CAP,
        max_rows=RELATIONSHIP_FETCH_CAP,
        client=client,
    )
    out: List[Dict[str, Any]] = []
    seen_ids: set = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        ident = str(row.get("identifier") or "").strip().lower()
        if ident != VMT_ST_IDENTIFIER:
            continue
        rec_id = _record_id(row)
        serial = (_serial_of(row) or "").strip()
        if not serial:
            continue
        if rec_id is not None and rec_id in seen_ids:
            continue
        if rec_id is not None:
            seen_ids.add(rec_id)
        out.append(row)
    return out


async def resolve_current_attachment(
    instrument_id: int,
    *,
    client: Optional[httpx.AsyncClient] = None,
    as_of: Optional[datetime] = None,
) -> Tuple[bool, Optional[str], List[Dict[str, Any]]]:
    """Return (is_attached, platform_name, attachment_rows) for an ST instrument."""
    as_of = as_of or _utcnow()
    record = await get_entity_record("instrument", instrument_id, client=client)
    rec_id = _record_id(record) or instrument_id
    rows, _more, _notes = await _instrument_attachment_rows(
        record, rec_id, client=client
    )
    open_rows = [
        row
        for row in rows
        if is_current_at([relationship_window(row)], as_of)
    ]
    if not open_rows:
        return False, None, rows
    platform_name: Optional[str] = None
    for row in open_rows:
        via = "instrument_on_platform" if "platform" in row else "instrument_on_data_logger"
        plat_id, plat_name, _plat_serial = await _platform_ref_from_relationship(
            row, client=client
        )
        if plat_name:
            platform_name = plat_name
            break
        if plat_id is not None:
            platform_name = f"platform #{plat_id}"
            break
        # Logger-mounted: still try platform via logger path above
        _ = via
    return True, platform_name, rows


async def _overlay_for_unit(
    unit: VmtUnit,
    *,
    client: Optional[httpx.AsyncClient] = None,
    persist_link: bool = False,
    session: Optional[SQLModelSession] = None,
) -> Tuple[bool, Optional[str], Optional[str]]:
    """Live attachment overlay; optionally persist link_status updates.

    Returns (is_attached, platform_name, error_message).
    """
    instrument_id = unit.sensor_tracker_instrument_id
    try:
        if instrument_id is None:
            found = await resolve_instrument_by_serial(
                unit.serial_number, client=client
            )
            if found is None:
                return False, None, None
            instrument_id = _record_id(found)
            if persist_link and session is not None and instrument_id is not None:
                unit.sensor_tracker_instrument_id = instrument_id
                unit.sensor_tracker_identifier = (
                    str(found.get("identifier") or VMT_ST_IDENTIFIER).strip()
                    or VMT_ST_IDENTIFIER
                )
                unit.sensor_tracker_link_status = (
                    VmtSensorTrackerLinkStatus.LINKED.value
                )
                unit.sensor_tracker_last_seen_at_utc = _utcnow()
                unit.sensor_tracker_sync_error = None
                session.add(unit)
        assert instrument_id is not None
        is_attached, platform_name, _rows = await resolve_current_attachment(
            instrument_id, client=client
        )
        if persist_link and session is not None:
            unit.sensor_tracker_link_status = VmtSensorTrackerLinkStatus.LINKED.value
            unit.sensor_tracker_last_seen_at_utc = _utcnow()
            unit.sensor_tracker_sync_error = None
            session.add(unit)
        return is_attached, platform_name, None
    except SensorTrackerQueryError as exc:
        if exc.status_code == 404 and unit.sensor_tracker_instrument_id is not None:
            if persist_link and session is not None:
                unit.sensor_tracker_link_status = (
                    VmtSensorTrackerLinkStatus.NOT_FOUND.value
                )
                unit.sensor_tracker_sync_error = str(exc)
                unit.sensor_tracker_last_sync_at_utc = _utcnow()
                session.add(unit)
            return False, None, "not_found"
        return False, None, str(exc)
    except Exception as exc:  # noqa: BLE001 — overlay must not fail the list
        logger.warning("VMT ST overlay failed for %s: %s", unit.serial_number, exc)
        return False, None, str(exc)


async def list_units_with_overlay(
    session: SQLModelSession,
    *,
    include_inactive: bool = False,
    client: Optional[httpx.AsyncClient] = None,
) -> VmtUnitListResponse:
    units = list_units_local(session, include_inactive=include_inactive)
    sem = asyncio.Semaphore(ST_OVERLAY_CONCURRENCY)
    overlays: Dict[int, Tuple[bool, Optional[str], Optional[str]]] = {}

    async def _one(unit: VmtUnit) -> None:
        async with sem:
            overlays[unit.id] = await _overlay_for_unit(unit, client=client)

    await asyncio.gather(*[_one(u) for u in units if u.id is not None])
    items: List[VmtUnitListItem] = []
    for unit in units:
        is_attached, platform_name, err = overlays.get(unit.id, (False, None, None))
        if err == "not_found":
            unit.sensor_tracker_link_status = (
                VmtSensorTrackerLinkStatus.NOT_FOUND.value
            )
        item = _list_item_from_unit(
            session,
            unit,
            is_attached=is_attached,
            attached_platform_name=platform_name,
        )
        items.append(item)
    return VmtUnitListResponse(count=len(items), units=items)


async def get_unit_detail_with_overlay(
    session: SQLModelSession,
    unit_id: int,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> VmtUnitDetail:
    detail = unit_detail_local(session, unit_id)
    unit = get_unit_or_404(session, unit_id)
    is_attached, platform_name, err = await _overlay_for_unit(unit, client=client)
    if err == "not_found":
        detail.sensor_tracker_link_status = VmtSensorTrackerLinkStatus.NOT_FOUND.value
    detail.is_attached = is_attached
    detail.attached_platform_name = platform_name
    if is_attached:
        detail.custody_status = None
        detail.custody_status_other = None
    return detail


def _format_window_value(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return str(value)


async def build_attachment_history_rows(
    rows: Sequence[Dict[str, Any]],
    *,
    client: Optional[httpx.AsyncClient] = None,
    as_of: Optional[datetime] = None,
) -> List[VmtStAttachmentRow]:
    as_of = as_of or _utcnow()
    out: List[VmtStAttachmentRow] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        start, end = relationship_window(row)
        plat_id, plat_name, plat_serial = await _platform_ref_from_relationship(
            row, client=client
        )
        via = "data_logger" if row.get("data_logger") or row.get("logger") else "platform"
        out.append(
            VmtStAttachmentRow(
                start_time=_format_window_value(start),
                end_time=_format_window_value(end),
                platform_name=plat_name,
                platform_serial=plat_serial,
                platform_id=plat_id,
                via=via,
                currently_open=is_current_at([(start, end)], as_of),
            )
        )
    out.sort(key=lambda r: r.start_time or "", reverse=True)
    return out


async def get_st_accounting(
    session: SQLModelSession,
    unit_id: int,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> VmtStAccountingResponse:
    unit = get_unit_or_404(session, unit_id)
    instrument_id = unit.sensor_tracker_instrument_id
    if instrument_id is None:
        found = await resolve_instrument_by_serial(unit.serial_number, client=client)
        if found is not None:
            instrument_id = _record_id(found)
            if instrument_id is not None:
                unit.sensor_tracker_instrument_id = instrument_id
                unit.sensor_tracker_identifier = (
                    str(found.get("identifier") or VMT_ST_IDENTIFIER).strip()
                    or VMT_ST_IDENTIFIER
                )
                unit.sensor_tracker_link_status = (
                    VmtSensorTrackerLinkStatus.LINKED.value
                )
                unit.sensor_tracker_last_seen_at_utc = _utcnow()
                unit.sensor_tracker_sync_error = None
                session.add(unit)
                session.commit()
                session.refresh(unit)

    if instrument_id is None:
        return VmtStAccountingResponse(
            vmt_unit_id=unit_id,
            link_status=unit.sensor_tracker_link_status,
            message="No Sensor Tracker instrument linked for this serial.",
            st_browser_url=None,
        )

    try:
        analytics_raw = await get_entity_analytics(
            "instrument", instrument_id, client=client
        )
        detail_raw = await get_entity_detail(
            "instrument", instrument_id, client=client
        )
        record = detail_raw.get("raw") or await get_entity_record(
            "instrument", instrument_id, client=client
        )
        rows, _more, _notes = await _instrument_attachment_rows(
            record, instrument_id, client=client
        )
        history = await build_attachment_history_rows(rows, client=client)
        if unit.sensor_tracker_link_status != VmtSensorTrackerLinkStatus.LINKED.value:
            unit.sensor_tracker_link_status = VmtSensorTrackerLinkStatus.LINKED.value
            unit.sensor_tracker_last_seen_at_utc = _utcnow()
            unit.sensor_tracker_sync_error = None
            session.add(unit)
            session.commit()
        return VmtStAccountingResponse(
            vmt_unit_id=unit_id,
            link_status=VmtSensorTrackerLinkStatus.LINKED.value,
            analytics=SensorTrackerAnalyticsResponse.model_validate(analytics_raw),
            attachment_history=history,
            st_detail=SensorTrackerDetailResponse.model_validate(
                {
                    **detail_raw,
                    "buddy": None,
                }
            ),
            st_browser_url=_st_browser_url(instrument_id),
        )
    except SensorTrackerQueryError as exc:
        if exc.status_code == 404:
            unit.sensor_tracker_link_status = (
                VmtSensorTrackerLinkStatus.NOT_FOUND.value
            )
            unit.sensor_tracker_sync_error = str(exc)
            unit.sensor_tracker_last_sync_at_utc = _utcnow()
            session.add(unit)
            session.commit()
            last = unit.sensor_tracker_instrument_id
            return VmtStAccountingResponse(
                vmt_unit_id=unit_id,
                link_status=VmtSensorTrackerLinkStatus.NOT_FOUND.value,
                message=(
                    f"Showing local log book only; last known ST instrument "
                    f"#{last} was not found in Sensor Tracker."
                ),
                st_browser_url=_st_browser_url(last),
            )
        raise


async def sync_vmt_units_from_sensor_tracker(
    session: SQLModelSession,
    *,
    username: str,
    dry_run: bool = True,
    client: Optional[httpx.AsyncClient] = None,
) -> VmtSyncResult:
    """Discover identifier=vmt instruments; create/refresh local units; never delete."""
    items: List[VmtSyncPreviewItem] = []
    created = updated = link_lost = unchanged = errors = 0
    now = _utcnow()

    try:
        discovered = await discover_vmt_instruments(client=client)
    except SensorTrackerQueryError as exc:
        return VmtSyncResult(
            dry_run=dry_run,
            errors=1,
            items=[
                VmtSyncPreviewItem(
                    action="error",
                    detail=f"Sensor Tracker discovery failed: {exc}",
                )
            ],
            summary=f"Sync failed: {exc}",
        )

    local_units = list(session.exec(select(VmtUnit)).all())
    by_serial = {u.serial_number: u for u in local_units}
    seen_serials: set = set()

    for row in discovered:
        serial = (_serial_of(row) or "").strip()
        st_id = _record_id(row)
        if not serial:
            errors += 1
            items.append(
                VmtSyncPreviewItem(
                    action="error",
                    sensor_tracker_instrument_id=st_id,
                    detail="Instrument missing serial",
                )
            )
            continue
        seen_serials.add(serial)
        existing = by_serial.get(serial)
        if existing is None:
            created += 1
            items.append(
                VmtSyncPreviewItem(
                    action="create",
                    serial_number=serial,
                    sensor_tracker_instrument_id=st_id,
                    detail="Would create from Sensor Tracker"
                    if dry_run
                    else "Created from Sensor Tracker",
                )
            )
            if not dry_run:
                unit = VmtUnit(
                    serial_number=serial,
                    code_map=DEFAULT_CODE_MAP,
                    always_tx=False,
                    sensor_tracker_instrument_id=st_id,
                    sensor_tracker_identifier=VMT_ST_IDENTIFIER,
                    sensor_tracker_link_status=VmtSensorTrackerLinkStatus.LINKED.value,
                    sensor_tracker_last_seen_at_utc=now,
                    sensor_tracker_last_sync_at_utc=now,
                    sensor_tracker_sync_error=None,
                    created_via=VmtCreatedVia.ST_SYNC.value,
                    is_active=True,
                    created_at_utc=now,
                    updated_at_utc=now,
                    updated_by_username=username,
                )
                session.add(unit)
            continue

        changed = (
            existing.sensor_tracker_instrument_id != st_id
            or existing.sensor_tracker_link_status
            != VmtSensorTrackerLinkStatus.LINKED.value
            or existing.sensor_tracker_identifier != VMT_ST_IDENTIFIER
        )
        if changed:
            updated += 1
            items.append(
                VmtSyncPreviewItem(
                    action="update",
                    serial_number=serial,
                    sensor_tracker_instrument_id=st_id,
                    vmt_unit_id=existing.id,
                    detail="Would refresh ST linkage"
                    if dry_run
                    else "Refreshed ST linkage",
                )
            )
            if not dry_run:
                existing.sensor_tracker_instrument_id = st_id
                existing.sensor_tracker_identifier = VMT_ST_IDENTIFIER
                existing.sensor_tracker_link_status = (
                    VmtSensorTrackerLinkStatus.LINKED.value
                )
                existing.sensor_tracker_last_seen_at_utc = now
                existing.sensor_tracker_last_sync_at_utc = now
                existing.sensor_tracker_sync_error = None
                existing.updated_at_utc = now
                existing.updated_by_username = username
                session.add(existing)
        else:
            unchanged += 1
            items.append(
                VmtSyncPreviewItem(
                    action="unchanged",
                    serial_number=serial,
                    sensor_tracker_instrument_id=st_id,
                    vmt_unit_id=existing.id,
                )
            )
            if not dry_run:
                existing.sensor_tracker_last_seen_at_utc = now
                existing.sensor_tracker_last_sync_at_utc = now
                session.add(existing)

    for unit in local_units:
        if unit.serial_number in seen_serials:
            continue
        if unit.sensor_tracker_instrument_id is None and (
            unit.sensor_tracker_link_status
            in (
                VmtSensorTrackerLinkStatus.NEVER_LINKED.value,
                VmtSensorTrackerLinkStatus.NOT_FOUND.value,
            )
        ):
            continue
        if (
            unit.sensor_tracker_link_status
            == VmtSensorTrackerLinkStatus.NOT_FOUND.value
        ):
            unchanged += 1
            items.append(
                VmtSyncPreviewItem(
                    action="unchanged",
                    serial_number=unit.serial_number,
                    sensor_tracker_instrument_id=unit.sensor_tracker_instrument_id,
                    vmt_unit_id=unit.id,
                    detail="Already marked not_found",
                )
            )
            continue
        link_lost += 1
        items.append(
            VmtSyncPreviewItem(
                action="link_lost",
                serial_number=unit.serial_number,
                sensor_tracker_instrument_id=unit.sensor_tracker_instrument_id,
                vmt_unit_id=unit.id,
                detail=(
                    "Would mark ST link not_found (local history retained)"
                    if dry_run
                    else "Marked ST link not_found (local history retained)"
                ),
            )
        )
        if not dry_run:
            unit.sensor_tracker_link_status = (
                VmtSensorTrackerLinkStatus.NOT_FOUND.value
            )
            unit.sensor_tracker_last_sync_at_utc = now
            unit.sensor_tracker_sync_error = (
                "Instrument with identifier=vmt and this serial not returned by sync"
            )
            unit.updated_at_utc = now
            unit.updated_by_username = username
            session.add(unit)

    if not dry_run:
        session.commit()

    summary = (
        f"{'Dry-run' if dry_run else 'Sync'}: created={created}, updated={updated}, "
        f"link_lost={link_lost}, unchanged={unchanged}, errors={errors}"
    )
    return VmtSyncResult(
        dry_run=dry_run,
        created=created,
        updated=updated,
        link_lost=link_lost,
        unchanged=unchanged,
        errors=errors,
        items=items,
        summary=summary,
    )
