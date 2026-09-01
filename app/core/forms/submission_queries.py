"""
Shared helpers for listing submitted forms without loading sections_data.

See docs/wiki/standards/FORM_SUBMISSION_POLICIES.md and ADR 0006.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.core import models
from app.core.models.schemas import SubmittedFormListResponse, SubmittedFormSummary

DEFAULT_MISSION_LIST_DAYS = 7
DEFAULT_MY_PIC_DAYS = 90
DEFAULT_LIST_LIMIT = 100
MAX_LIST_LIMIT = 500
PILOT_ALL_FORMS_HOURS = 72
RECENT_PIC_HOURS = 24

_SUMMARY_COLUMNS = (
    models.SubmittedForm.id,
    models.SubmittedForm.mission_id,
    models.SubmittedForm.form_type,
    models.SubmittedForm.form_title,
    models.SubmittedForm.submitted_by_username,
    models.SubmittedForm.submission_timestamp,
    models.SubmittedForm.edited_by_username,
    models.SubmittedForm.last_edited_timestamp,
)


def clamp_list_limit(limit: Optional[int], *, default: int = DEFAULT_LIST_LIMIT) -> int:
    value = default if limit is None else int(limit)
    if value < 1:
        return 1
    return min(value, MAX_LIST_LIMIT)


def clamp_list_offset(offset: Optional[int]) -> int:
    value = 0 if offset is None else int(offset)
    return max(0, value)


def effective_days_window(
    days: Optional[int],
    *,
    default_days: int = DEFAULT_MISSION_LIST_DAYS,
) -> int:
    """
    Resolve the day window to apply.

    ``None`` → surface default. ``0`` → no time filter (full history, still paginated).
    """
    if days is None:
        return default_days
    return max(0, int(days))


def submission_cutoff_for_days(days: int) -> Optional[datetime]:
    """UTC cutoff for a day window, or None when days == 0 (no filter)."""
    if days <= 0:
        return None
    return datetime.now(timezone.utc) - timedelta(days=days)


def submission_cutoff_for_hours(hours: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours)


def list_submitted_form_summaries(
    session: Session,
    *,
    form_type: Optional[str] = None,
    mission_id: Optional[str] = None,
    mission_ids: Optional[Sequence[str]] = None,
    submitted_by_username: Optional[str] = None,
    cutoff: Optional[datetime] = None,
    days: int = DEFAULT_MISSION_LIST_DAYS,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
) -> SubmittedFormListResponse:
    """
    Return paginated summary rows (no sections_data).

    ``days`` is echoed in the response for UI labels; pass the already-resolved
    window value (use ``effective_days_window``). When ``cutoff`` is set, filter
    ``submission_timestamp >= cutoff``; when ``cutoff`` is None, no time filter.
    """
    limit = clamp_list_limit(limit)
    offset = clamp_list_offset(offset)

    filters = []
    if form_type:
        filters.append(models.SubmittedForm.form_type == form_type)
    if mission_id:
        filters.append(models.SubmittedForm.mission_id == mission_id)
    if mission_ids is not None:
        keys = [k.strip() for k in mission_ids if k and str(k).strip()]
        if not keys:
            return SubmittedFormListResponse(
                items=[],
                total=0,
                days=days,
                limit=limit,
                offset=offset,
                has_more=False,
            )
        filters.append(col(models.SubmittedForm.mission_id).in_(keys))
    if submitted_by_username:
        filters.append(models.SubmittedForm.submitted_by_username == submitted_by_username)
    if cutoff is not None:
        filters.append(models.SubmittedForm.submission_timestamp >= cutoff)

    count_stmt = select(func.count()).select_from(models.SubmittedForm)
    if filters:
        count_stmt = count_stmt.where(*filters)
    total = int(session.exec(count_stmt).one() or 0)

    list_stmt = select(*_SUMMARY_COLUMNS)
    if filters:
        list_stmt = list_stmt.where(*filters)
    list_stmt = (
        list_stmt.order_by(models.SubmittedForm.submission_timestamp.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = session.exec(list_stmt).all()
    items = [
        SubmittedFormSummary(
            id=row[0],
            mission_id=row[1],
            form_type=row[2],
            form_title=row[3],
            submitted_by_username=row[4],
            submission_timestamp=row[5],
            edited_by_username=row[6],
            last_edited_timestamp=row[7],
        )
        for row in rows
    ]
    return SubmittedFormListResponse(
        items=items,
        total=total,
        days=days,
        limit=limit,
        offset=offset,
        has_more=(offset + len(items)) < total,
    )
