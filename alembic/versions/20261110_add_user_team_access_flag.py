"""add_user_team_access_flag

Revision ID: 20261110_user_team_access
Revises: 20261109_station_offload_qol
Create Date: 2026-11-10

Per-user Team hub access flag on users table (default off; admins always allowed in app).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20261110_user_team_access"
down_revision: Union[str, Sequence[str], None] = "20261109_station_offload_qol"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("users")}

    if "can_access_team" not in columns:
        op.add_column(
            "users",
            sa.Column("can_access_team", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )
        op.create_index("ix_users_can_access_team", "users", ["can_access_team"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("users")}
    indexes = {ix["name"] for ix in inspector.get_indexes("users")}

    if "ix_users_can_access_team" in indexes:
        op.drop_index("ix_users_can_access_team", table_name="users")
    if "can_access_team" in columns:
        op.drop_column("users", "can_access_team")
