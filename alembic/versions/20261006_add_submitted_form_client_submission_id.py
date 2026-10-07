"""add_submitted_form_client_submission_id

Revision ID: 20261006_form_client_sub_id
Revises: 20260928_ora_requests
Create Date: 2026-10-06

Nullable client_submission_id for idempotent PIC/form creates, with a
unique index scoped by submitter username.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20261006_form_client_sub_id"
down_revision: Union[str, Sequence[str], None] = "20260928_ora_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMN = "client_submission_id"
INDEX = "uq_submitted_forms_user_client_submission_id"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("submitted_forms"):
        return
    columns = {col["name"] for col in inspector.get_columns("submitted_forms")}
    if COLUMN not in columns:
        op.add_column(
            "submitted_forms",
            sa.Column(COLUMN, sa.String(length=64), nullable=True),
        )
    existing = {idx["name"] for idx in inspector.get_indexes("submitted_forms")}
    if INDEX not in existing:
        # Partial uniqueness: multiple NULL client_submission_id rows remain allowed
        # on SQLite (NULL != NULL in unique indexes).
        op.create_index(
            INDEX,
            "submitted_forms",
            ["submitted_by_username", COLUMN],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("submitted_forms"):
        return
    existing = {idx["name"] for idx in inspector.get_indexes("submitted_forms")}
    if INDEX in existing:
        op.drop_index(INDEX, table_name="submitted_forms")
    columns = {col["name"] for col in inspector.get_columns("submitted_forms")}
    if COLUMN in columns:
        op.drop_column("submitted_forms", COLUMN)
