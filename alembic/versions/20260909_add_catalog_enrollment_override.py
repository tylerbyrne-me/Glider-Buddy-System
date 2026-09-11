"""add_catalog_enrollment_override

Revision ID: 20260909_enroll_ovr
Revises: 20260831_form_list_idx
Create Date: 2026-09-09

Tri-state enrollment override on catalog_missions: automatic | forced_on | forced_off.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "20260909_enroll_ovr"
down_revision: Union[str, Sequence[str], None] = "20260831_form_list_idx"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("catalog_missions"):
        return
    columns = {col["name"] for col in inspector.get_columns("catalog_missions")}
    if "enrollment_override" not in columns:
        op.add_column(
            "catalog_missions",
            sa.Column(
                "enrollment_override",
                sa.String(),
                nullable=False,
                server_default="automatic",
            ),
        )
        op.create_index(
            "ix_catalog_missions_enrollment_override",
            "catalog_missions",
            ["enrollment_override"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("catalog_missions"):
        return
    existing = {idx["name"] for idx in inspector.get_indexes("catalog_missions")}
    if "ix_catalog_missions_enrollment_override" in existing:
        op.drop_index(
            "ix_catalog_missions_enrollment_override",
            table_name="catalog_missions",
        )
    columns = {col["name"] for col in inspector.get_columns("catalog_missions")}
    if "enrollment_override" in columns:
        op.drop_column("catalog_missions", "enrollment_override")
