"""
Wave Glider form submission persistence (PIC handoff and related WG forms).

Validates payload, resolves catalog keys, persists mission-overview side effects,
and maps SQLite lock exhaustion to a stable 503.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import Session, select

from app.core import models, utils
from app.core.forms.pic_handoff_autofill import (
    SENSOR_SAMPLING_CONFIG,
    SENSOR_SAMPLING_ITEM_ID_TO_KEY,
)
from app.core.infra.logging_config import get_request_id
from app.core.mission_catalog.workspace import resolve_form_mission_keys

logger = logging.getLogger(__name__)

ALLOWED_WG_FORM_TYPES = frozenset({"pic_handoff_checklist", "pre_deployment_checklist"})
SQLITE_LOCK_MARKERS = ("database is locked", "database is busy")


class FormSubmitValidationError(ValueError):
    """Raised for client-correctable submit payload problems."""


def _is_sqlite_lock_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in SQLITE_LOCK_MARKERS)


def parse_vessel_standoff_from_sections(sections_data: Optional[List[dict]]) -> Optional[int]:
    if not sections_data:
        return None
    for section in sections_data:
        for item in section.get("items") or []:
            if item.get("id") == "vessel_standoff_m_val" and item.get("value") not in (None, ""):
                try:
                    return int(str(item["value"]).strip())
                except (ValueError, TypeError):
                    pass
    return None


def parse_sensor_sampling_value(sensor_key: str, value: str) -> Optional[dict]:
    value = (value or "").strip()
    if not value:
        return None
    parts = [p.strip() for p in value.split(",")]
    try:
        if sensor_key == "ctd":
            if len(parts) < 4:
                return None
            return {
                "period_sec": int(parts[0]),
                "samples_per_block": int(parts[1]),
                "flush_time_sec": int(parts[2]),
                "off_time_sec": int(parts[3]),
            }
        if sensor_key == "c3":
            if len(parts) < 4:
                return None
            use_pump = str(parts[0]).lower() in ("true", "1", "yes")
            return {
                "use_pump": use_pump,
                "flush_sec": int(parts[1]),
                "avg_period_block_sec": int(parts[2]),
                "off_time_sec": int(parts[3]),
            }
        if sensor_key in ("waves", "weather", "vr2c"):
            if not parts:
                return None
            return {"interval_min": int(parts[0])}
    except (ValueError, TypeError):
        return None
    return None


def parse_sensor_sampling_from_sections(sections_data: Optional[List[dict]]) -> Optional[dict]:
    if not sections_data:
        return None
    collected = {}
    for section in sections_data:
        for item in section.get("items") or []:
            iid = item.get("id")
            key = SENSOR_SAMPLING_ITEM_ID_TO_KEY.get(iid)
            if not key:
                continue
            val = item.get("value")
            parsed = parse_sensor_sampling_value(key, str(val) if val is not None else "")
            if parsed is not None:
                collected[key] = parsed
    return collected if collected else None


def persist_mission_overview_side_effects(
    session: Session,
    mission_id: str,
    sections_data: Optional[List[dict]],
) -> None:
    """Persist vessel standoff and sensor sampling rates from form sections."""
    mission_overview = session.get(models.MissionOverview, mission_id)
    if mission_overview is None and "-" in mission_id:
        mission_overview = session.get(
            models.MissionOverview, utils.deployment_mission_code_from_mission_id(mission_id)
        )
    if mission_overview is None:
        return

    updated = False
    standoff_m = parse_vessel_standoff_from_sections(sections_data)
    if standoff_m is not None and standoff_m >= 0:
        mission_overview.vessel_standoff_m = standoff_m
        updated = True
    sampling_rates = parse_sensor_sampling_from_sections(sections_data)
    if sampling_rates is not None:
        mission_overview.sensor_sampling_rates = json.dumps(sampling_rates)
        updated = True
    if updated:
        mission_overview.updated_at_utc = datetime.now(timezone.utc)
        session.add(mission_overview)


def validate_form_submit_payload(
    *,
    form_type: Optional[str],
    form_title: Optional[str],
    sections_data: Any,
    client_submission_id: Optional[str] = None,
) -> None:
    if not form_type or not str(form_type).strip():
        raise FormSubmitValidationError("form_type is required")
    if str(form_type).strip() not in ALLOWED_WG_FORM_TYPES:
        raise FormSubmitValidationError(f"Unsupported form_type: {form_type}")
    if not form_title or not str(form_title).strip():
        raise FormSubmitValidationError("form_title is required")
    if not isinstance(sections_data, list) or len(sections_data) == 0:
        raise FormSubmitValidationError("sections_data must be a non-empty list")
    if client_submission_id is not None:
        cid = str(client_submission_id).strip()
        if not cid:
            raise FormSubmitValidationError("client_submission_id must be non-empty when provided")
        if len(cid) > 64:
            raise FormSubmitValidationError("client_submission_id must be at most 64 characters")


def _find_by_client_submission_id(
    session: Session,
    *,
    username: str,
    client_submission_id: str,
) -> Optional[models.SubmittedForm]:
    return session.exec(
        select(models.SubmittedForm).where(
            models.SubmittedForm.submitted_by_username == username,
            models.SubmittedForm.client_submission_id == client_submission_id,
        )
    ).first()


def _commit_or_raise_lock(session: Session) -> None:
    try:
        session.commit()
    except OperationalError as exc:
        session.rollback()
        if _is_sqlite_lock_error(exc):
            logger.warning(
                "FORM_SUBMIT_SQLITE_LOCK pid=%s request_id=%s err=%s",
                os.getpid(),
                get_request_id(),
                exc,
            )
            raise HTTPException(
                status_code=503,
                detail="Database temporarily busy; please retry.",
                headers={"Retry-After": "2"},
            ) from exc
        raise


def persist_form_submission(
    session: Session,
    *,
    mission_id: str,
    form_type: str,
    form_title: str,
    sections_data: List[dict],
    current_user: models.User,
    catalog_mission_id: Optional[str] = None,
    client_submission_id: Optional[str] = None,
) -> models.SubmittedForm:
    """
    Insert a submitted form (idempotent when ``client_submission_id`` is set).
    """
    started = time.monotonic()
    validate_form_submit_payload(
        form_type=form_type,
        form_title=form_title,
        sections_data=sections_data,
        client_submission_id=client_submission_id,
    )

    cid = (client_submission_id or "").strip() or None
    if cid:
        existing = _find_by_client_submission_id(
            session, username=current_user.username, client_submission_id=cid
        )
        if existing is not None:
            logger.info(
                "FORM_SUBMIT_IDEMPOTENT id=%s client_submission_id=%s user=%s duration=%.3fs pid=%s request_id=%s",
                existing.id,
                cid,
                current_user.username,
                time.monotonic() - started,
                os.getpid(),
                get_request_id(),
            )
            return existing

    legacy_mission_id = mission_id
    if len(mission_id) >= 32 and "-" in mission_id and not catalog_mission_id:
        if session.get(models.CatalogMission, mission_id) is not None:
            catalog_mission_id = mission_id
            legacy_mission_id = None

    keys = resolve_form_mission_keys(
        session,
        mission_id=legacy_mission_id,
        catalog_mission_id=catalog_mission_id,
    )
    legacy_mission_id = keys.get("mission_id") or legacy_mission_id
    catalog_mission_id = keys.get("catalog_mission_id") or catalog_mission_id

    submitted_form = models.SubmittedForm(
        mission_id=legacy_mission_id,
        catalog_mission_id=catalog_mission_id,
        form_type=form_type,
        form_title=form_title,
        submitted_by_username=current_user.username,
        submission_timestamp=datetime.now(timezone.utc),
        sections_data=sections_data,
        client_submission_id=cid,
    )
    session.add(submitted_form)

    if legacy_mission_id:
        persist_mission_overview_side_effects(session, legacy_mission_id, sections_data)

    try:
        _commit_or_raise_lock(session)
    except IntegrityError as exc:
        session.rollback()
        if cid:
            existing = _find_by_client_submission_id(
                session, username=current_user.username, client_submission_id=cid
            )
            if existing is not None:
                logger.info(
                    "FORM_SUBMIT_IDEMPOTENT_RACE id=%s client_submission_id=%s user=%s pid=%s request_id=%s",
                    existing.id,
                    cid,
                    current_user.username,
                    os.getpid(),
                    get_request_id(),
                )
                return existing
        raise HTTPException(status_code=409, detail="Form submission conflict") from exc

    session.refresh(submitted_form)
    logger.info(
        "FORM_SUBMIT_OK id=%s mission=%s form_type=%s user=%s duration=%.3fs pid=%s request_id=%s",
        submitted_form.id,
        legacy_mission_id,
        form_type,
        current_user.username,
        time.monotonic() - started,
        os.getpid(),
        get_request_id(),
    )
    return submitted_form


def update_form_submission(
    session: Session,
    db_form: models.SubmittedForm,
    *,
    sections_data: List[dict],
    form_title: Optional[str],
    current_user: models.User,
) -> models.SubmittedForm:
    if not isinstance(sections_data, list) or len(sections_data) == 0:
        raise FormSubmitValidationError("sections_data must be a non-empty list")

    if form_title:
        db_form.form_title = form_title
    db_form.sections_data = sections_data
    db_form.edited_by_username = current_user.username
    db_form.last_edited_timestamp = datetime.now(timezone.utc)
    session.add(db_form)

    if db_form.mission_id:
        persist_mission_overview_side_effects(session, db_form.mission_id, sections_data)

    _commit_or_raise_lock(session)
    session.refresh(db_form)
    return db_form


# Keep sampling config import used by older forms helpers if needed.
__all__ = [
    "ALLOWED_WG_FORM_TYPES",
    "FormSubmitValidationError",
    "SENSOR_SAMPLING_CONFIG",
    "parse_vessel_standoff_from_sections",
    "parse_sensor_sampling_from_sections",
    "persist_mission_overview_side_effects",
    "persist_form_submission",
    "update_form_submission",
    "validate_form_submit_payload",
]
