"""Team-hub Wave Glider Operational Risk Assessment drafts.

Drafts are contractor requests, not mission checklists, so they stay out of
``submitted_forms``. A per-hull profile remembers vehicle config Tracker does
not store.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from app.core.models.database import (
    CatalogMission,
    CatalogPlatform,
    MissionOverview,
    OraHullProfile,
    OraRequest,
    SlocumDeployment,
)
from app.core.models.schemas import (
    OraContextTrack,
    OraDeviceRow,
    OraDraftRead,
    OraDraftSummary,
    OraDraftWrite,
    OraHullProfileRead,
    OraLoadoutResponse,
    OraMissionOption,
)
from app.platforms.wave_glider.ora_devices import (
    default_device_rows,
    infer_vehicle_model,
    instrument_label,
    merge_tracker_instruments,
)
from app.platforms.wave_glider.ora_pdf import (
    OraCoordinate,
    OraDeviceLine,
    OraDocumentFields,
    pdf_filename,
    render_ora_pdf,
)

logger = logging.getLogger(__name__)

PURPOSES = {"mission", "demo", "training", "regional_analysis"}
COORDINATE_MODES = {"hold_station", "box", "course"}
VEHICLE_MODELS = {"sv2", "sv3"}
UMBILICALS = {"4", "8", "20"}
YES_NO = {"yes", "no"}
CONTEXT_TRACK_LIMIT = 24


class OraError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def format_operation_dates(
    start: Optional[datetime], end: Optional[datetime]
) -> str:
    def _fmt(value: datetime) -> str:
        return f"{value.day} {value.strftime('%b')} {value.year}"

    if start and end:
        return f"{_fmt(start)} – {_fmt(end)}"
    if start:
        return _fmt(start)
    if end:
        return _fmt(end)
    return ""


def _clean_choice(value: Optional[str], allowed: set[str]) -> Optional[str]:
    text = (value or "").strip().lower()
    if not text:
        return None
    if text not in allowed:
        raise OraError(f"Unexpected value {value!r}.")
    return text


def _clean_purposes(values: list[str]) -> list[str]:
    cleaned = []
    for value in values:
        choice = _clean_choice(value, PURPOSES)
        if choice and choice not in cleaned:
            cleaned.append(choice)
    return cleaned


def _validate_coordinates(rows: list[Any]) -> list[dict[str, Any]]:
    cleaned = []
    for row in rows:
        lat = row.lat
        lon = row.lon
        if lat is not None and not -90 <= lat <= 90:
            raise OraError("Latitude must be between -90 and 90.")
        if lon is not None and not -180 <= lon <= 180:
            raise OraError("Longitude must be between -180 and 180.")
        label = (row.label or "").strip()
        comment = (row.comment or "").strip()
        if lat is None and lon is None and not label and not comment:
            continue
        cleaned.append(
            {"label": label, "lat": lat, "lon": lon, "comment": comment}
        )
    if len(cleaned) > 40:
        raise OraError("Use 40 coordinates or fewer.")
    return cleaned


def _validate_devices(rows: list[OraDeviceRow]) -> list[dict[str, Any]]:
    cleaned = []
    for row in rows:
        name = (row.name or "").strip()
        if not name:
            continue
        cleaned.append(
            {
                "name": name[:200],
                "power_draw": (row.power_draw or "").strip()[:80],
                "duty_cycle": (row.duty_cycle or "").strip()[:80],
                "source": (row.source or "manual").strip()[:40] or "manual",
                "included": bool(row.included),
            }
        )
    if len(cleaned) > 60:
        raise OraError("Use 60 devices or fewer.")
    return cleaned


def _apply_write(row: OraRequest, body: OraDraftWrite, username: str) -> None:
    mode = _clean_choice(body.coordinate_mode, COORDINATE_MODES) or "course"
    notes = (body.notes or "").strip()
    if len(notes) > 8000:
        raise OraError("Notes are limited to 8000 characters.")
    row.title = (body.title or "").strip() or None
    row.catalog_mission_id = (body.catalog_mission_id or "").strip() or None
    row.hull_name = (body.hull_name or "").strip() or None
    row.requester = (body.requester or "").strip()
    row.project_code = (body.project_code or "").strip() or None
    row.project_code_other = (body.project_code_other or "").strip() or None
    row.client = (body.client or "").strip() or None
    row.dates_of_operation = (body.dates_of_operation or "").strip() or None
    row.purposes_json = _clean_purposes(body.purposes)
    row.priority = body.priority
    row.coordinate_mode = mode
    row.coordinates_json = _validate_coordinates(body.coordinates)
    row.vehicle_model = _clean_choice(body.vehicle_model, VEHICLE_MODELS)
    row.umbilical_m = _clean_choice(body.umbilical_m, UMBILICALS)
    row.towing = _clean_choice(body.towing, YES_NO)
    row.towed_device = (body.towed_device or "").strip() or None
    row.ecos_up_to_date = _clean_choice(body.ecos_up_to_date, YES_NO)
    row.sv3_software_version = (body.sv3_software_version or "").strip() or None
    row.apu_count = (body.apu_count or "").strip() or None
    row.smc_version = (body.smc_version or "").strip() or None
    row.devices_json = _validate_devices(body.devices)
    row.notes = notes or None
    row.updated_at_utc = _utcnow()
    row.updated_by_username = username


def _hull_profile_read(row: Optional[OraHullProfile]) -> Optional[OraHullProfileRead]:
    if row is None:
        return None
    return OraHullProfileRead.model_validate(row)


def remember_hull_profile(
    session: Session, body: OraDraftWrite, username: str
) -> Optional[OraHullProfile]:
    hull = (body.hull_name or "").strip()
    if not hull:
        return None
    row = session.exec(
        select(OraHullProfile).where(OraHullProfile.hull_name == hull)
    ).first()
    if row is None:
        row = OraHullProfile(hull_name=hull, updated_at_utc=_utcnow())
        session.add(row)
    # Keep the last non-empty value so a partial draft does not wipe the hull.
    updates = {
        "vehicle_model": _clean_choice(body.vehicle_model, VEHICLE_MODELS),
        "umbilical_m": _clean_choice(body.umbilical_m, UMBILICALS),
        "towing": _clean_choice(body.towing, YES_NO),
        "towed_device": (body.towed_device or "").strip() or None,
        "ecos_up_to_date": _clean_choice(body.ecos_up_to_date, YES_NO),
        "sv3_software_version": (body.sv3_software_version or "").strip() or None,
        "apu_count": (body.apu_count or "").strip() or None,
        "smc_version": (body.smc_version or "").strip() or None,
    }
    for attr, value in updates.items():
        if value:
            setattr(row, attr, value)
    row.updated_at_utc = _utcnow()
    row.updated_by_username = username
    return row


def draft_to_read(row: OraRequest) -> OraDraftRead:
    return OraDraftRead(
        id=row.id or 0,
        title=row.title,
        catalog_mission_id=row.catalog_mission_id,
        hull_name=row.hull_name,
        requester=row.requester or "",
        project_code=row.project_code,
        project_code_other=row.project_code_other,
        client=row.client,
        dates_of_operation=row.dates_of_operation,
        purposes=list(row.purposes_json or []),
        priority=row.priority,
        coordinate_mode=row.coordinate_mode or "course",
        coordinates=list(row.coordinates_json or []),
        vehicle_model=row.vehicle_model,
        umbilical_m=row.umbilical_m,
        towing=row.towing,
        towed_device=row.towed_device,
        ecos_up_to_date=row.ecos_up_to_date,
        sv3_software_version=row.sv3_software_version,
        apu_count=row.apu_count,
        smc_version=row.smc_version,
        devices=list(row.devices_json or []),
        notes=row.notes,
        created_at_utc=row.created_at_utc,
        updated_at_utc=row.updated_at_utc,
        updated_by_username=row.updated_by_username,
    )


def list_drafts(session: Session) -> list[OraDraftSummary]:
    rows = session.exec(
        select(OraRequest).order_by(OraRequest.updated_at_utc.desc())
    ).all()
    return [
        OraDraftSummary(
            id=row.id or 0,
            title=row.title,
            hull_name=row.hull_name,
            requester=row.requester or "",
            dates_of_operation=row.dates_of_operation,
            updated_at_utc=row.updated_at_utc,
        )
        for row in rows
    ]


def get_draft(session: Session, draft_id: int) -> OraRequest:
    row = session.get(OraRequest, draft_id)
    if row is None:
        raise OraError("ORA draft not found.", status_code=404)
    return row


def _require_wave_glider_mission(session: Session, catalog_mission_id: Optional[str]) -> None:
    if not catalog_mission_id:
        return
    mission = session.get(CatalogMission, catalog_mission_id)
    if mission is None:
        raise OraError("Catalog mission not found.", status_code=404)
    if mission.platform_id is None:
        return
    platform = session.get(CatalogPlatform, mission.platform_id)
    family = (platform.platform_family if platform else None) or ""
    if family and family != "wave_glider":
        raise OraError("Link a Wave Glider catalog mission.")


def create_draft(session: Session, body: OraDraftWrite, username: str) -> OraRequest:
    _require_wave_glider_mission(session, (body.catalog_mission_id or "").strip() or None)
    row = OraRequest(requester=(body.requester or "").strip(), created_at_utc=_utcnow())
    _apply_write(row, body, username)
    if not row.devices_json:
        row.devices_json = default_device_rows()
    session.add(row)
    remember_hull_profile(session, body, username)
    session.commit()
    session.refresh(row)
    return row


def update_draft(
    session: Session, draft_id: int, body: OraDraftWrite, username: str
) -> OraRequest:
    _require_wave_glider_mission(session, (body.catalog_mission_id or "").strip() or None)
    row = get_draft(session, draft_id)
    _apply_write(row, body, username)
    session.add(row)
    remember_hull_profile(session, body, username)
    session.commit()
    session.refresh(row)
    return row


def delete_draft(session: Session, draft_id: int) -> None:
    row = get_draft(session, draft_id)
    session.delete(row)
    session.commit()


def _mission_label(mission: CatalogMission, platform: Optional[CatalogPlatform]) -> str:
    parts: list[str] = []
    if mission.deployment_number:
        parts.append(f"m{int(mission.deployment_number)}")
    if platform and platform.canonical_name:
        parts.append(platform.canonical_name)
    elif mission.title:
        parts.append(mission.title)
    return "-".join(parts) or mission.id[:8]


def list_wave_glider_missions(session: Session) -> list[OraMissionOption]:
    rows = session.exec(
        select(CatalogMission, CatalogPlatform)
        .join(CatalogPlatform, CatalogMission.platform_id == CatalogPlatform.id)
        .where(CatalogPlatform.platform_family == "wave_glider")
        .where(CatalogMission.operational_state.in_(("planned", "active")))
        .order_by(CatalogMission.start_time.desc())
    ).all()
    profiles = {
        profile.hull_name: profile
        for profile in session.exec(select(OraHullProfile)).all()
    }
    options = []
    for mission, platform in rows:
        hull = platform.canonical_name if platform else None
        options.append(
            OraMissionOption(
                id=mission.id,
                label=_mission_label(mission, platform),
                platform_name=hull,
                operational_state=mission.operational_state,
                start_time=mission.start_time.isoformat() if mission.start_time else None,
                end_time=mission.end_time.isoformat() if mission.end_time else None,
                dates_of_operation=format_operation_dates(
                    mission.start_time, mission.end_time
                ),
                vehicle_model=infer_vehicle_model(hull),
                hull_profile=_hull_profile_read(profiles.get(hull or "")),
            )
        )
    return options


def _track_target(
    session: Session, mission: CatalogMission
) -> tuple[Optional[str], Optional[str]]:
    overview = session.exec(
        select(MissionOverview).where(MissionOverview.catalog_mission_id == mission.id)
    ).first()
    if overview and (overview.mission_id or "").strip():
        return "wave_glider", overview.mission_id.strip()
    deployment = session.exec(
        select(SlocumDeployment).where(
            SlocumDeployment.catalog_mission_id == mission.id
        )
    ).first()
    if deployment is None:
        return None, None
    key = (deployment.erddap_dataset_id or deployment.mission_key or "").strip()
    if not key:
        return None, None
    return "slocum", key


def list_context_tracks(session: Session) -> list[OraContextTrack]:
    missions = session.exec(
        select(CatalogMission)
        .where(CatalogMission.operational_state.in_(("planned", "active")))
        .order_by(CatalogMission.updated_at_utc.desc())
        .limit(CONTEXT_TRACK_LIMIT)
    ).all()
    platforms = {
        platform.id: platform
        for platform in session.exec(select(CatalogPlatform)).all()
        if platform.id is not None
    }
    tracks = []
    for mission in missions:
        platform = platforms.get(mission.platform_id)
        kind, track_id = _track_target(session, mission)
        tracks.append(
            OraContextTrack(
                catalog_mission_id=mission.id,
                label=_mission_label(mission, platform),
                platform_family=platform.platform_family if platform else None,
                platform_name=platform.canonical_name if platform else None,
                track_kind=kind,
                track_id=track_id,
            )
        )
    return tracks


def fields_from_write(body: OraDraftWrite) -> OraDocumentFields:
    """Validate and map a draft payload onto the PDF."""
    probe = OraRequest(requester="", created_at_utc=_utcnow(), updated_at_utc=_utcnow())
    _apply_write(probe, body, username="")
    return OraDocumentFields(
        requester=probe.requester or "",
        project_code=probe.project_code or "",
        project_code_other=probe.project_code_other or "",
        client=probe.client or "",
        dates_of_operation=probe.dates_of_operation or "",
        purposes=list(probe.purposes_json or []),
        priority=probe.priority,
        coordinates=[
            OraCoordinate(
                label=point.get("label") or "",
                lat=point.get("lat"),
                lon=point.get("lon"),
                comment=point.get("comment") or "",
            )
            for point in (probe.coordinates_json or [])
        ],
        vehicle_model=probe.vehicle_model,
        umbilical_m=probe.umbilical_m,
        towing=probe.towing,
        towed_device=probe.towed_device or "",
        ecos_up_to_date=probe.ecos_up_to_date,
        sv3_software_version=probe.sv3_software_version or "",
        apu_count=probe.apu_count or "",
        smc_version=probe.smc_version or "",
        devices=[
            OraDeviceLine(
                name=device.get("name") or "",
                power_draw=device.get("power_draw") or "",
                duty_cycle=device.get("duty_cycle") or "",
                included=bool(device.get("included", True)),
            )
            for device in (probe.devices_json or [])
        ],
        notes=probe.notes or "",
        title=probe.title or "",
        hull_name=probe.hull_name or "",
    )


def render_draft_pdf(body: OraDraftWrite) -> tuple[bytes, str]:
    fields = fields_from_write(body)
    return render_ora_pdf(fields), pdf_filename(body.title, body.hull_name)


def _logger_identifier(row: dict[str, Any]) -> Optional[str]:
    logger_row = row.get("data_logger") if isinstance(row.get("data_logger"), dict) else row
    if not isinstance(logger_row, dict):
        return None
    for key in ("identifier", "name", "data_logger_identifier"):
        value = logger_row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


async def load_tracker_devices(platform_name: str, devices: list[OraDeviceRow]) -> OraLoadoutResponse:
    """Pull instrument names for a hull and merge them into the device table."""
    name = (platform_name or "").strip()
    if not name:
        raise OraError("Enter a hull or Sensor Tracker platform name first.")
    from app.services.sensor_tracker_service import SensorTrackerService

    try:
        service = SensorTrackerService(skip_auth=True)
    except Exception as exc:
        logger.warning("ORA Tracker client unavailable: %s", exc)
        raise OraError(
            "Sensor Tracker is not available from this server.",
            status_code=502,
        ) from exc
    warning = None
    labels: list[str] = []
    try:
        direct = await service.fetch_instruments_on_platform(name)
    except Exception as exc:
        logger.warning("ORA Tracker platform instruments failed for %s: %s", name, exc)
        raise OraError(
            f"Sensor Tracker did not return instruments for {name}.",
            status_code=502,
        ) from exc
    for row in direct or []:
        label = instrument_label(row)
        if label:
            labels.append(label)
    try:
        loggers = await service.fetch_data_loggers_on_platform(name)
    except Exception as exc:
        logger.warning("ORA Tracker loggers failed for %s: %s", name, exc)
        loggers = []
        warning = "Platform instruments loaded. Data-logger instruments could not be listed."
    for logger_row in loggers or []:
        if not isinstance(logger_row, dict):
            continue
        identifier = _logger_identifier(logger_row)
        if not identifier:
            continue
        try:
            mounted = await service.fetch_instruments_on_data_logger(identifier)
        except Exception as exc:
            logger.warning("ORA Tracker logger %s failed: %s", identifier, exc)
            warning = warning or "Some data-logger instruments could not be loaded."
            continue
        for row in mounted or []:
            label = instrument_label(row)
            if label:
                labels.append(label)
    unique: list[str] = []
    seen: set[str] = set()
    for label in labels:
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(label)
    current = [row.model_dump() for row in devices]
    merged = merge_tracker_instruments(current, unique)
    return OraLoadoutResponse(
        platform_name=name,
        instrument_names=unique,
        devices=[OraDeviceRow.model_validate(row) for row in merged],
        warning=warning,
    )
