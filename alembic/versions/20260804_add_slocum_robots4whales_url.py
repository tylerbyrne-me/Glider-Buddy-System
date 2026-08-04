"""add_slocum_robots4whales_url

Revision ID: 20260804_slocum_r4w_url
Revises: 20260722_reactivate_hist
Create Date: 2026-08-04

Robots4Whales deployment page URL on slocum_deployments for DMON review cache.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260804_slocum_r4w_url"
down_revision: Union[str, Sequence[str], None] = "20260722_reactivate_hist"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("slocum_deployments"):
        return
    columns = {col["name"] for col in inspector.get_columns("slocum_deployments")}
    if "robots4whales_url" not in columns:
        op.add_column(
            "slocum_deployments",
            sa.Column("robots4whales_url", sa.String(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("slocum_deployments"):
        return
    columns = {col["name"] for col in inspector.get_columns("slocum_deployments")}
    if "robots4whales_url" in columns:
        op.drop_column("slocum_deployments", "robots4whales_url")
