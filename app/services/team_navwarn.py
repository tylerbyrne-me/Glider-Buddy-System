"""Team-hub Canadian Coast Guard NAVWARN request drafts.

Drafts are Coast Guard forms, not mission checklists, so they stay out of
``submitted_forms``. Download fills the official .docx template and a ReportLab
PDF copy; the app does not send mail.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from app.core.models.database import CatalogMission, CatalogPlatform, NavwarnRequest
from app.core.models.schemas import (
    NavwarnArea,
    NavwarnDraftRead,
    NavwarnDraftSummary,
    NavwarnDraftWrite,
    NavwarnFloatHullResponse,
)
from app.platforms.wave_glider.navwarn_docx import (
    NavwarnDocxError,
    docx_filename,
    render_navwarn_docx,
)
from app.platforms.wave_glider.navwarn_form import (
    DAYS_OPTIONS,
    FIRM_ESTIMATED_OPTIONS,
    HOURS_OPTIONS,
    NAVWARN_DESKS,
    POSITION_FORMATS,
    PUBLISH_CONTACT_OPTIONS,
    TIMEZONE_OPTIONS,
    UPDATE_OR_CANCEL_OPTIONS,
    WASH_BERTH_OPTIONS,
    NavwarnDocumentFields,
    default_markers_text,
    default_other_details_text,
    default_vessels_text,
    nature_options_for,
    parse_float_sv3_hull_id,
)
from app.platforms.wave_glider.navwarn_pdf import pdf_filename, render_navwarn_pdf
from app.services import team_ora
from app.services.sensor_tracker_query import is_currently_attached

logger = logging.getLogger(__name__)

DESKS = set(NAVWARN_DESKS)
PUBLISH = {key for key, _ in PUBLISH_CONTACT_OPTIONS}
UPDATE = {key for key, _ in UPDATE_OR_CANCEL_OPTIONS}
TIMEZONES = {key for key, _ in TIMEZONE_OPTIONS}
DAYS = {key for key, _ in DAYS_OPTIONS}
HOURS = {key for key, _ in HOURS_OPTIONS}
FIRMNESS = {key for key, _ in FIRM_ESTIMATED_OPTIONS}
POSITIONS = {key for key, _ in POSITION_FORMATS}
WASH = {key for key, _ in WASH_BERTH_OPTIONS}
NATURE_CATEGORIES = {"marine_works", "obstruction", "offshore", "recreational"}
AREA_MODES = {"hold", "course", "polygon"}
AREA_POINT_LIMIT = 100


class NavwarnError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _clean_choice(value: Optional[str], allowed: set[str]) -> Optional[str]:
    text = (value or "").strip().lower()
    if not text:
        return None
    if text not in allowed:
        raise NavwarnError(f"Unexpected value {value!r}.")
    return text


def _clip(text: Optional[str], limit: int) -> Optional[str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return None
    if len(cleaned) > limit:
        raise NavwarnError(f"Text is limited to {limit} characters.")
    return cleaned


def _clean_area(area: Optional[NavwarnArea]) -> Optional[dict[str, Any]]:
    if area is None:
        return None
    mode = _clean_choice(area.mode, AREA_MODES) or "hold"
    if len(area.points) > AREA_POINT_LIMIT:
        raise NavwarnError(f"Map area is limited to {AREA_POINT_LIMIT} points.")
    points = []
    for point in area.points:
        if not -90 <= point.lat <= 90 or not -180 <= point.lon <= 180:
            raise NavwarnError("Map area points must be valid latitude/longitude.")
        points.append({"lat": round(point.lat, 6), "lon": round(point.lon, 6)})
    if mode == "hold" and len(points) > 1:
        raise NavwarnError("Hold station uses a single map point.")
    radius_km = area.radius_km
    if radius_km is not None and not 0 < radius_km <= 500:
        raise NavwarnError("Hold radius must be between 0 and 500 km.")
    if not points:
        return None
    return {"mode": mode, "points": points, "radius_km": radius_km}


def _area_read(raw: Any) -> Optional[NavwarnArea]:
    if not isinstance(raw, dict):
        return None
    try:
        return NavwarnArea.model_validate(raw)
    except ValueError:
        logger.warning("Ignoring malformed NAVWARN area_json: %r", raw)
        return None


def _apply_write(row: NavwarnRequest, body: NavwarnDraftWrite, username: str) -> None:
    desk = _clean_choice(body.desk, DESKS) or "sydney"
    latitude = body.latitude
    longitude = body.longitude
    if latitude is not None and not -90 <= latitude <= 90:
        raise NavwarnError("Latitude must be between -90 and 90.")
    if longitude is not None and not -180 <= longitude <= 180:
        raise NavwarnError("Longitude must be between -180 and 180.")

    nature_category = _clean_choice(body.nature_category, NATURE_CATEGORIES)
    nature_topic = None
    if nature_category:
        allowed_topics = {key for key, _ in nature_options_for(nature_category)}
        nature_topic = _clean_choice(body.nature_topic, allowed_topics)

    row.title = _clip(body.title, 200)
    row.catalog_mission_id = (body.catalog_mission_id or "").strip() or None
    row.hull_name = _clip(body.hull_name, 80)
    row.desk = desk
    row.requester_name = (body.requester_name or "").strip()
    row.telephone = _clip(body.telephone, 80)
    row.email = _clip(body.email, 200)
    row.publish_contact = _clean_choice(body.publish_contact, PUBLISH) or "no"
    row.publish_contact_custom = _clip(body.publish_contact_custom, 2000)
    row.is_update_or_cancel = (
        _clean_choice(body.is_update_or_cancel, UPDATE) or "no"
    )
    row.previous_navwarn_number = _clip(body.previous_navwarn_number, 80)
    row.start_datetime = _clip(body.start_datetime, 120)
    row.timezone = _clean_choice(body.timezone, TIMEZONES) or "utc"
    row.days_of_operation = _clean_choice(body.days_of_operation, DAYS) or "daily"
    row.days_other = _clip(body.days_other, 400)
    row.hours_of_operation = _clean_choice(body.hours_of_operation, HOURS) or "24h"
    row.hours_other = _clip(body.hours_other, 400)
    row.completion_datetime = _clip(body.completion_datetime, 120)
    row.completion_firmness = (
        _clean_choice(body.completion_firmness, FIRMNESS) or "estimated"
    )
    row.position_format = _clean_choice(body.position_format, POSITIONS) or "dmm"
    row.latitude = latitude
    row.longitude = longitude
    row.place_name = _clip(body.place_name, 200)
    row.extra_positions = _clip(body.extra_positions, 4000)
    row.area_json = _clean_area(body.area)
    row.nature_category = nature_category or "obstruction"
    row.nature_topic = nature_topic or "other"
    row.nature_other = _clip(body.nature_other, 2000)
    row.vessels_on_scene = _clip(body.vessels_on_scene, 4000)
    row.markers_description = _clip(body.markers_description, 4000)
    row.wash_berth = _clean_choice(body.wash_berth, WASH) or "none"
    row.other_details = _clip(body.other_details, 8000)
    row.updated_at_utc = _utcnow()
    row.updated_by_username = username


def draft_to_read(row: NavwarnRequest) -> NavwarnDraftRead:
    return NavwarnDraftRead(
        id=row.id or 0,
        title=row.title,
        catalog_mission_id=row.catalog_mission_id,
        hull_name=row.hull_name,
        desk=row.desk or "sydney",
        requester_name=row.requester_name or "",
        telephone=row.telephone,
        email=row.email,
        publish_contact=row.publish_contact,
        publish_contact_custom=row.publish_contact_custom,
        is_update_or_cancel=row.is_update_or_cancel,
        previous_navwarn_number=row.previous_navwarn_number,
        start_datetime=row.start_datetime,
        timezone=row.timezone,
        days_of_operation=row.days_of_operation,
        days_other=row.days_other,
        hours_of_operation=row.hours_of_operation,
        hours_other=row.hours_other,
        completion_datetime=row.completion_datetime,
        completion_firmness=row.completion_firmness,
        position_format=row.position_format or "dmm",
        latitude=row.latitude,
        longitude=row.longitude,
        place_name=row.place_name,
        extra_positions=row.extra_positions,
        area=_area_read(row.area_json),
        nature_category=row.nature_category,
        nature_topic=row.nature_topic,
        nature_other=row.nature_other,
        vessels_on_scene=row.vessels_on_scene,
        markers_description=row.markers_description,
        wash_berth=row.wash_berth,
        other_details=row.other_details,
        created_at_utc=row.created_at_utc,
        updated_at_utc=row.updated_at_utc,
        updated_by_username=row.updated_by_username,
    )


def list_drafts(session: Session) -> list[NavwarnDraftSummary]:
    rows = session.exec(
        select(NavwarnRequest).order_by(NavwarnRequest.updated_at_utc.desc())
    ).all()
    return [
        NavwarnDraftSummary(
            id=row.id or 0,
            title=row.title,
            hull_name=row.hull_name,
            desk=row.desk or "sydney",
            requester_name=row.requester_name or "",
            start_datetime=row.start_datetime,
            previous_navwarn_number=row.previous_navwarn_number,
            updated_at_utc=row.updated_at_utc,
        )
        for row in rows
    ]


def get_draft(session: Session, draft_id: int) -> NavwarnRequest:
    row = session.get(NavwarnRequest, draft_id)
    if row is None:
        raise NavwarnError("NAVWARN draft not found.", status_code=404)
    return row


def _require_wave_glider_mission(
    session: Session, catalog_mission_id: Optional[str]
) -> None:
    if not catalog_mission_id:
        return
    mission = session.get(CatalogMission, catalog_mission_id)
    if mission is None:
        raise NavwarnError("Catalog mission not found.", status_code=404)
    if mission.platform_id is None:
        return
    platform = session.get(CatalogPlatform, mission.platform_id)
    family = (platform.platform_family if platform else None) or ""
    if family and family != "wave_glider":
        raise NavwarnError("Link a Wave Glider catalog mission.")


def create_draft(
    session: Session, body: NavwarnDraftWrite, username: str
) -> NavwarnRequest:
    _require_wave_glider_mission(
        session, (body.catalog_mission_id or "").strip() or None
    )
    row = NavwarnRequest(
        requester_name=(body.requester_name or "").strip(),
        created_at_utc=_utcnow(),
    )
    _apply_write(row, body, username)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def update_draft(
    session: Session, draft_id: int, body: NavwarnDraftWrite, username: str
) -> NavwarnRequest:
    _require_wave_glider_mission(
        session, (body.catalog_mission_id or "").strip() or None
    )
    row = get_draft(session, draft_id)
    _apply_write(row, body, username)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def delete_draft(session: Session, draft_id: int) -> None:
    row = get_draft(session, draft_id)
    session.delete(row)
    session.commit()


def duplicate_as_update(
    session: Session,
    draft_id: int,
    username: str,
    previous_navwarn_number: Optional[str] = None,
) -> NavwarnRequest:
    """Copy a draft and mark it as an update to a previously published NAVWARN."""
    source = get_draft(session, draft_id)
    read = draft_to_read(source)
    payload = NavwarnDraftWrite.model_validate(
        {
            **read.model_dump(exclude={"id", "created_at_utc", "updated_at_utc", "updated_by_username"}),
            "is_update_or_cancel": "yes",
            "previous_navwarn_number": (
                (previous_navwarn_number or "").strip()
                or (source.previous_navwarn_number or "")
            )
            or None,
            "title": (
                f"{(source.title or 'NAVWARN').strip()} (update)"
                if source.title
                else "NAVWARN update"
            ),
        }
    )
    return create_draft(session, payload, username)


def default_text_for_hull(hull_name: str) -> dict[str, str]:
    return {
        "vessels_on_scene": default_vessels_text(hull_name),
        "markers_description": default_markers_text(hull_name),
        "other_details": default_other_details_text(),
        "nature_other": "Acoustic/Oceanographic Survey",
    }


def _component_display_name(row: dict[str, Any]) -> str:
    nested = row.get("component") if isinstance(row.get("component"), dict) else None
    for source in (nested, row):
        if not isinstance(source, dict):
            continue
        for key in ("name", "title", "identifier"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def float_hull_from_component_rows(
    rows: list[dict[str, Any]],
) -> tuple[Optional[str], Optional[str]]:
    """Return ``(hull_id, component_name)`` from currently attached Float SV3 rows."""
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not is_currently_attached(row):
            continue
        component_name = _component_display_name(row)
        hull_id = parse_float_sv3_hull_id(component_name)
        if hull_id:
            return hull_id, component_name
    return None, None


async def resolve_float_hull_from_tracker(
    platform_name: str,
) -> NavwarnFloatHullResponse:
    """Look up the Coast Guard hull ID from the platform's Float SV3 component.

    Sensor Tracker platforms are named like ``SV3-1070``. The NAVWARN hull ID is
    the suffix of the attached component ``Float SV3 - C34167NS``.
    """
    name = (platform_name or "").strip()
    if not name:
        raise NavwarnError("Enter a Sensor Tracker platform name first.")
    from app.services.sensor_tracker_service import SensorTrackerService

    try:
        service = SensorTrackerService(skip_auth=True)
    except Exception as exc:
        logger.warning("NAVWARN Tracker client unavailable: %s", exc)
        raise NavwarnError(
            "Sensor Tracker is not available from this server.",
            status_code=502,
        ) from exc

    try:
        rows = await service.fetch_components_on_platform(name)
    except Exception as exc:
        logger.warning("NAVWARN Tracker components failed for %s: %s", name, exc)
        raise NavwarnError(
            f"Sensor Tracker did not return components for {name}.",
            status_code=502,
        ) from exc

    hull_id, component_name = float_hull_from_component_rows(
        [row for row in (rows or []) if isinstance(row, dict)]
    )
    warning = None
    if not hull_id:
        warning = (
            f"No currently attached 'Float SV3 - …' component found on {name}."
        )
    return NavwarnFloatHullResponse(
        platform_name=name,
        hull_id=hull_id,
        component_name=component_name,
        warning=warning,
    )


def fields_from_write(body: NavwarnDraftWrite) -> NavwarnDocumentFields:
    probe = NavwarnRequest(
        requester_name="",
        created_at_utc=_utcnow(),
        updated_at_utc=_utcnow(),
    )
    _apply_write(probe, body, username="")
    return NavwarnDocumentFields(
        desk=probe.desk or "sydney",
        title=probe.title or "",
        catalog_mission_id=probe.catalog_mission_id,
        hull_name=probe.hull_name or "",
        requester_name=probe.requester_name or "",
        telephone=probe.telephone or "",
        email=probe.email or "",
        publish_contact=probe.publish_contact,
        publish_contact_custom=probe.publish_contact_custom or "",
        is_update_or_cancel=probe.is_update_or_cancel,
        previous_navwarn_number=probe.previous_navwarn_number or "",
        start_datetime=probe.start_datetime or "",
        timezone=probe.timezone,
        days_of_operation=probe.days_of_operation,
        days_other=probe.days_other or "",
        hours_of_operation=probe.hours_of_operation,
        hours_other=probe.hours_other or "",
        completion_datetime=probe.completion_datetime or "",
        completion_firmness=probe.completion_firmness,
        position_format=probe.position_format or "dmm",
        latitude=probe.latitude,
        longitude=probe.longitude,
        place_name=probe.place_name or "",
        extra_positions=probe.extra_positions or "",
        nature_category=probe.nature_category,
        nature_topic=probe.nature_topic,
        nature_other=probe.nature_other or "",
        vessels_on_scene=probe.vessels_on_scene or "",
        markers_description=probe.markers_description or "",
        wash_berth=probe.wash_berth,
        other_details=probe.other_details or "",
    )


def render_draft_docx(body: NavwarnDraftWrite) -> tuple[bytes, str]:
    fields = fields_from_write(body)
    try:
        content = render_navwarn_docx(fields)
    except NavwarnDocxError as exc:
        raise NavwarnError(str(exc), status_code=500) from exc
    return content, docx_filename(fields)


def render_draft_pdf(body: NavwarnDraftWrite) -> tuple[bytes, str]:
    fields = fields_from_write(body)
    content = render_navwarn_pdf(fields)
    return content, pdf_filename(fields)


def list_wave_glider_missions(session: Session):
    """Reuse the ORA mission picker (Wave Glider planned/active only)."""
    return team_ora.list_wave_glider_missions(session)
