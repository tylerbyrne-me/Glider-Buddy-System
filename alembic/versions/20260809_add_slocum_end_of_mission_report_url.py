"""add_slocum_end_of_mission_report_url

Revision ID: 20260809_slocum_eom_url
Revises: 20260807_user_ui_prefs
Create Date: 2026-08-09

SlocumDeployment.end_of_mission_report_url for dashboard overview parity
with Wave Glider MissionOverview (latest report per type).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260809_slocum_eom_url"
down_revision: Union[str, Sequence[str], None] = "20260807_user_ui_prefs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("slocum_deployments"):
        return
    columns = {col["name"] for col in inspector.get_columns("slocum_deployments")}
    if "end_of_mission_report_url" not in columns:
        op.add_column(
            "slocum_deployments",
            sa.Column("end_of_mission_report_url", sa.String(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("slocum_deployments"):
        return
    columns = {col["name"] for col in inspector.get_columns("slocum_deployments")}
    if "end_of_mission_report_url" in columns:
        op.drop_column("slocum_deployments", "end_of_mission_report_url")
