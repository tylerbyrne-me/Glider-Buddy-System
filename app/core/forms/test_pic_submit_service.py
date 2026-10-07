"""Tests for WG form submission persistence / idempotency."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.forms.pic_submit_service import (
    FormSubmitValidationError,
    persist_form_submission,
    update_form_submission,
    validate_form_submit_payload,
)
from app.core.models.database import MissionOverview, SubmittedForm
from app.core.models.enums import UserRoleEnum
from unittest.mock import MagicMock, patch


def _engine_session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(
        engine, tables=[SubmittedForm.__table__, MissionOverview.__table__]
    )
    return engine, Session(engine)


def _user(username: str = "pilot1"):
    user = MagicMock()
    user.username = username
    user.role = UserRoleEnum.pilot
    return user


def _sections():
    return [
        {
            "id": "general_status",
            "title": "General",
            "items": [
                {"id": "vessel_standoff_m_val", "value": "1200", "item_type": "text_input"},
                {
                    "id": "sensor_ctd_sampling_val",
                    "value": "10, 10, 100, 400",
                    "item_type": "text_input",
                },
            ],
        }
    ]


def test_validate_rejects_empty_sections():
    with pytest.raises(FormSubmitValidationError):
        validate_form_submit_payload(
            form_type="pic_handoff_checklist",
            form_title="PIC",
            sections_data=[],
        )


def test_persist_form_submission_happy_path_side_effects():
    _engine, session = _engine_session()
    session.add(MissionOverview(mission_id="m227"))
    session.commit()

    with patch(
        "app.core.forms.pic_submit_service.resolve_form_mission_keys",
        return_value={"mission_id": "m227", "catalog_mission_id": None},
    ):
        row = persist_form_submission(
            session,
            mission_id="m227",
            form_type="pic_handoff_checklist",
            form_title="PIC Handoff Checklist",
            sections_data=_sections(),
            current_user=_user(),
            client_submission_id="abc-123",
        )

    assert row.id is not None
    assert row.client_submission_id == "abc-123"
    overview = session.get(MissionOverview, "m227")
    assert overview.vessel_standoff_m == 1200
    assert overview.sensor_sampling_rates is not None
    assert "ctd" in overview.sensor_sampling_rates


def test_persist_form_submission_idempotent_by_client_id():
    _engine, session = _engine_session()
    with patch(
        "app.core.forms.pic_submit_service.resolve_form_mission_keys",
        return_value={"mission_id": "m227", "catalog_mission_id": None},
    ):
        first = persist_form_submission(
            session,
            mission_id="m227",
            form_type="pic_handoff_checklist",
            form_title="PIC Handoff Checklist",
            sections_data=_sections(),
            current_user=_user(),
            client_submission_id="same-key",
        )
        second = persist_form_submission(
            session,
            mission_id="m227",
            form_type="pic_handoff_checklist",
            form_title="PIC Handoff Checklist",
            sections_data=_sections(),
            current_user=_user(),
            client_submission_id="same-key",
        )

    assert first.id == second.id
    rows = session.exec(select(SubmittedForm)).all()
    assert len(rows) == 1


def test_persist_maps_sqlite_lock_to_503():
    _engine, session = _engine_session()

    def boom():
        raise OperationalError("stmt", {}, Exception("database is locked"))

    with patch(
        "app.core.forms.pic_submit_service.resolve_form_mission_keys",
        return_value={"mission_id": "m227", "catalog_mission_id": None},
    ), patch.object(session, "commit", side_effect=boom):
        with pytest.raises(HTTPException) as exc_info:
            persist_form_submission(
                session,
                mission_id="m227",
                form_type="pic_handoff_checklist",
                form_title="PIC Handoff Checklist",
                sections_data=_sections(),
                current_user=_user(),
            )
    assert exc_info.value.status_code == 503
    assert "Retry-After" in (exc_info.value.headers or {})


def test_update_form_submission():
    _engine, session = _engine_session()
    session.add(MissionOverview(mission_id="m227"))
    form = SubmittedForm(
        mission_id="m227",
        form_type="pic_handoff_checklist",
        form_title="PIC",
        sections_data=_sections(),
        submitted_by_username="pilot1",
        submission_timestamp=datetime.now(timezone.utc),
    )
    session.add(form)
    session.commit()
    session.refresh(form)

    updated = update_form_submission(
        session,
        form,
        sections_data=[
            {
                "id": "general_status",
                "title": "General",
                "items": [{"id": "vessel_standoff_m_val", "value": "900"}],
            }
        ],
        form_title="PIC edited",
        current_user=_user(),
    )
    assert updated.form_title == "PIC edited"
    assert updated.edited_by_username == "pilot1"
    assert session.get(MissionOverview, "m227").vessel_standoff_m == 900
