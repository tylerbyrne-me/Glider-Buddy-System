"""add_slocum_mission_metrics

Revision ID: 20261020_slocum_mission_metrics
Revises: 20261007_wg_mission_metrics
Create Date: 2026-10-20

Persisted lifetime mission track distance for Slocum dashboards / reports.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20261020_slocum_mission_metrics"
down_revision: Union[str, Sequence[str], None] = "20261007_wg_mission_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "slocum_mission_metrics"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table(TABLE):
        return
    op.create_table(
        TABLE,
        sa.Column("mission_key", sa.String(), primary_key=True, nullable=False),
        sa.Column("total_distance_km", sa.Float(), nullable=True),
        sa.Column("distance_method", sa.String(), nullable=True),
        sa.Column("track_data_through_ts", sa.DateTime(), nullable=True),
        sa.Column("source_erddap_dataset_id", sa.String(), nullable=True),
        sa.Column("dashboard_last_data_timestamp", sa.DateTime(), nullable=True),
        sa.Column("calculation_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("computed_at_utc", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if inspector.has_table(TABLE):
        op.drop_table(TABLE)
