"""add_submitted_forms_list_indexes

Revision ID: 20260831_form_list_idx
Revises: 20260827_vmt_logbook
Create Date: 2026-08-31

Composite indexes for mission-scoped and fleet form list queries
(summary lists with time windows — ADR 0006).
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


revision: str = "20260831_form_list_idx"
down_revision: Union[str, Sequence[str], None] = "20260827_vmt_logbook"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MISSION_FORM_TS_INDEX = "ix_submitted_forms_mission_type_ts"
FORM_TYPE_TS_INDEX = "ix_submitted_forms_form_type_ts"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("submitted_forms"):
        return
    existing = {idx["name"] for idx in inspector.get_indexes("submitted_forms")}
    if MISSION_FORM_TS_INDEX not in existing:
        op.create_index(
            MISSION_FORM_TS_INDEX,
            "submitted_forms",
            ["mission_id", "form_type", "submission_timestamp"],
            unique=False,
        )
    if FORM_TYPE_TS_INDEX not in existing:
        op.create_index(
            FORM_TYPE_TS_INDEX,
            "submitted_forms",
            ["form_type", "submission_timestamp"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("submitted_forms"):
        return
    existing = {idx["name"] for idx in inspector.get_indexes("submitted_forms")}
    if FORM_TYPE_TS_INDEX in existing:
        op.drop_index(FORM_TYPE_TS_INDEX, table_name="submitted_forms")
    if MISSION_FORM_TS_INDEX in existing:
        op.drop_index(MISSION_FORM_TS_INDEX, table_name="submitted_forms")
