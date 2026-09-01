"""Tests for form submission summary lists and retention windows (ADR 0006)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session, SQLModel, create_engine

from app.core.forms.submission_queries import (
    DEFAULT_MISSION_LIST_DAYS,
    effective_days_window,
    list_submitted_form_summaries,
    submission_cutoff_for_days,
)
from app.core.models.database import SubmittedForm


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine, tables=[SubmittedForm.__table__])
    return Session(engine)


def _add_form(
    session: Session,
    *,
    mission_id: str,
    form_type: str,
    when: datetime,
    title: str = "Test Form",
    username: str = "pilot1",
    sections_data: list | None = None,
) -> SubmittedForm:
    row = SubmittedForm(
        mission_id=mission_id,
        form_type=form_type,
        form_title=title,
        sections_data=sections_data
        if sections_data is not None
        else [{"id": "s1", "title": "S", "items": [{"id": "a", "label": "A", "value": "x"}]}],
        submitted_by_username=username,
        submission_timestamp=when,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def test_effective_days_window_defaults_and_zero():
    assert effective_days_window(None) == DEFAULT_MISSION_LIST_DAYS
    assert effective_days_window(None, default_days=90) == 90
    assert effective_days_window(0) == 0
    assert effective_days_window(7) == 7


def test_mission_pic_list_returns_summaries_without_sections_data():
    session = _session()
    now = datetime.now(timezone.utc)
    recent = _add_form(
        session,
        mission_id="m227",
        form_type="pic_handoff_checklist",
        when=now - timedelta(days=1),
        sections_data=[
            {
                "id": "heavy",
                "title": "Heavy",
                "items": [{"id": "x", "label": "X", "value": "y" * 500}],
            }
        ],
    )
    old = _add_form(
        session,
        mission_id="m227",
        form_type="pic_handoff_checklist",
        when=now - timedelta(days=45),
    )

    resolved_days = effective_days_window(None, default_days=DEFAULT_MISSION_LIST_DAYS)
    cutoff = submission_cutoff_for_days(resolved_days)
    result = list_submitted_form_summaries(
        session,
        form_type="pic_handoff_checklist",
        mission_id="m227",
        cutoff=cutoff,
        days=resolved_days,
        limit=100,
        offset=0,
    )

    assert result.days == DEFAULT_MISSION_LIST_DAYS
    assert result.total == 1
    assert len(result.items) == 1
    assert result.items[0].id == recent.id
    assert result.items[0].mission_id == "m227"
    dumped = result.model_dump()
    assert "sections_data" not in dumped["items"][0]
    assert all(item.id != old.id for item in result.items)


def test_days_zero_returns_paginated_full_history_metadata():
    session = _session()
    now = datetime.now(timezone.utc)
    for i in range(5):
        _add_form(
            session,
            mission_id="m227",
            form_type="pic_handoff_checklist",
            when=now - timedelta(days=i * 10),
            title=f"Form {i}",
        )

    result = list_submitted_form_summaries(
        session,
        form_type="pic_handoff_checklist",
        mission_id="m227",
        cutoff=None,
        days=0,
        limit=2,
        offset=0,
    )
    assert result.days == 0
    assert result.total == 5
    assert len(result.items) == 2
    assert result.has_more is True

    page2 = list_submitted_form_summaries(
        session,
        form_type="pic_handoff_checklist",
        mission_id="m227",
        cutoff=None,
        days=0,
        limit=2,
        offset=2,
    )
    assert len(page2.items) == 2
    assert page2.has_more is True
    assert {i.id for i in result.items}.isdisjoint({i.id for i in page2.items})


def test_slocum_checklist_list_parity():
    session = _session()
    now = datetime.now(timezone.utc)
    recent = _add_form(
        session,
        mission_id="peggy_20250522_206",
        form_type="slocum_daily_checklist",
        when=now - timedelta(days=2),
    )
    _add_form(
        session,
        mission_id="peggy_20250522_206",
        form_type="slocum_daily_checklist",
        when=now - timedelta(days=60),
    )
    # Different mission should not appear
    _add_form(
        session,
        mission_id="other_mission",
        form_type="slocum_daily_checklist",
        when=now - timedelta(days=1),
    )

    result = list_submitted_form_summaries(
        session,
        form_type="slocum_daily_checklist",
        mission_ids=["peggy_20250522_206"],
        cutoff=submission_cutoff_for_days(DEFAULT_MISSION_LIST_DAYS),
        days=DEFAULT_MISSION_LIST_DAYS,
    )
    assert result.total == 1
    assert result.items[0].id == recent.id
    assert result.items[0].form_type == "slocum_daily_checklist"


def test_detail_row_still_has_sections_data():
    session = _session()
    now = datetime.now(timezone.utc)
    blob = [{"id": "s", "title": "Section", "items": [{"id": "i", "label": "L", "value": "v"}]}]
    row = _add_form(
        session,
        mission_id="m227",
        form_type="pic_handoff_checklist",
        when=now,
        sections_data=blob,
    )
    loaded = session.get(SubmittedForm, row.id)
    assert loaded is not None
    assert loaded.sections_data == blob
