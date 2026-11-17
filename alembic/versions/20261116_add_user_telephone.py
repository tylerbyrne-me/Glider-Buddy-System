"""add user telephone

Revision ID: 20261116_user_telephone
Revises: 20261116_navwarn_requests
Create Date: 2026-11-16

Optional contact telephone on users for team forms such as NAVWARN.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20261116_user_telephone"
down_revision: Union[str, Sequence[str], None] = "20261116_navwarn_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("users")}

    if "telephone" not in columns:
        op.add_column(
            "users",
            sa.Column("telephone", sa.String(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("users")}

    if "telephone" in columns:
        op.drop_column("users", "telephone")
