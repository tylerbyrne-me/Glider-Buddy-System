"""add navwarn map area

Revision ID: 20261116_navwarn_area
Revises: 20261116_user_telephone
Create Date: 2026-11-16

Map editor area (hold / course / polygon points) on NAVWARN request drafts.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20261116_navwarn_area"
down_revision: Union[str, Sequence[str], None] = "20261116_user_telephone"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "navwarn_requests" not in set(inspector.get_table_names()):
        return
    columns = {col["name"] for col in inspector.get_columns("navwarn_requests")}
    if "area_json" not in columns:
        op.add_column(
            "navwarn_requests",
            sa.Column("area_json", sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if "navwarn_requests" not in set(inspector.get_table_names()):
        return
    columns = {col["name"] for col in inspector.get_columns("navwarn_requests")}
    if "area_json" in columns:
        op.drop_column("navwarn_requests", "area_json")
