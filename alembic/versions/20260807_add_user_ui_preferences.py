"""add_user_ui_preferences

Revision ID: 20260807_user_ui_prefs
Revises: 20260805_public_map
Create Date: 2026-08-07

Per-user appearance preferences JSON on users table (theme_mode, accent, density, map_style).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260807_user_ui_prefs"
down_revision: Union[str, Sequence[str], None] = "20260805_public_map"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {col["name"] for col in inspect(op.get_bind()).get_columns("users")}
    if "ui_preferences" not in columns:
        op.add_column("users", sa.Column("ui_preferences", sa.JSON(), nullable=True))


def downgrade() -> None:
    columns = {col["name"] for col in inspect(op.get_bind()).get_columns("users")}
    if "ui_preferences" in columns:
        op.drop_column("users", "ui_preferences")
