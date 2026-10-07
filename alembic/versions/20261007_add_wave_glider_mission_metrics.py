"""add_wave_glider_mission_metrics

Revision ID: 20261007_wg_mission_metrics
Revises: 20261006_form_client_sub_id
Create Date: 2026-10-07

Persisted lifetime distance / observed max battery Wh for Wave Glider dashboards.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20261007_wg_mission_metrics"
down_revision: Union[str, Sequence[str], None] = "20261006_form_client_sub_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "wave_glider_mission_metrics"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table(TABLE):
        return
    op.create_table(
        TABLE,
        sa.Column("mission_id", sa.String(), primary_key=True, nullable=False),
        sa.Column("total_distance_nm", sa.Float(), nullable=True),
        sa.Column("distance_method", sa.String(), nullable=True),
        sa.Column("telemetry_data_through_ts", sa.DateTime(), nullable=True),
        sa.Column("telemetry_source_mtime", sa.DateTime(), nullable=True),
        sa.Column("observed_max_battery_wh", sa.Float(), nullable=True),
        sa.Column("power_data_through_ts", sa.DateTime(), nullable=True),
        sa.Column("power_source_mtime", sa.DateTime(), nullable=True),
        sa.Column("calculation_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("computed_at_utc", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table(TABLE):
        op.drop_table(TABLE)
