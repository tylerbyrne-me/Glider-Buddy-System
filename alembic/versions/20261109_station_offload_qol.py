"""station_offload_qol

Revision ID: 20261109_station_offload_qol
Revises: 20261020_slocum_mission_metrics
Create Date: 2026-11-09

Station Offload QOL: skip reason, retire audit fields, offload log
client_submission_id for idempotent creates.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20261109_station_offload_qol"
down_revision: Union[str, Sequence[str], None] = "20261020_slocum_mission_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STATION_COLUMNS = (
    ("display_status_override_note", sa.Text(), True),
    ("retired_at_utc", sa.DateTime(timezone=True), True),
    ("retired_reason", sa.Text(), True),
)
OFFLOAD_CLIENT_SUBMISSION_ID = "client_submission_id"
OFFLOAD_CLIENT_SUBMISSION_INDEX = "uq_offload_logs_user_client_submission_id"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("station_metadata"):
        existing = {
            col["name"] for col in inspector.get_columns("station_metadata")
        }
        for name, col_type, nullable in STATION_COLUMNS:
            if name not in existing:
                op.add_column(
                    "station_metadata",
                    sa.Column(name, col_type, nullable=nullable),
                )

    if inspector.has_table("offload_logs"):
        existing = {col["name"] for col in inspector.get_columns("offload_logs")}
        if OFFLOAD_CLIENT_SUBMISSION_ID not in existing:
            op.add_column(
                "offload_logs",
                sa.Column(
                    OFFLOAD_CLIENT_SUBMISSION_ID,
                    sa.String(length=64),
                    nullable=True,
                ),
            )
        indexes = {idx["name"] for idx in inspector.get_indexes("offload_logs")}
        if OFFLOAD_CLIENT_SUBMISSION_INDEX not in indexes:
            # Partial uniqueness: multiple NULL client_submission_id rows remain
            # allowed on SQLite (NULL != NULL in unique indexes).
            op.create_index(
                OFFLOAD_CLIENT_SUBMISSION_INDEX,
                "offload_logs",
                ["logged_by_username", OFFLOAD_CLIENT_SUBMISSION_ID],
                unique=True,
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("offload_logs"):
        indexes = {idx["name"] for idx in inspector.get_indexes("offload_logs")}
        if OFFLOAD_CLIENT_SUBMISSION_INDEX in indexes:
            op.drop_index(
                OFFLOAD_CLIENT_SUBMISSION_INDEX, table_name="offload_logs"
            )
        columns = {col["name"] for col in inspector.get_columns("offload_logs")}
        if OFFLOAD_CLIENT_SUBMISSION_ID in columns:
            op.drop_column("offload_logs", OFFLOAD_CLIENT_SUBMISSION_ID)

    if inspector.has_table("station_metadata"):
        columns = {
            col["name"] for col in inspector.get_columns("station_metadata")
        }
        for name, _col_type, _nullable in reversed(STATION_COLUMNS):
            if name in columns:
                op.drop_column("station_metadata", name)
