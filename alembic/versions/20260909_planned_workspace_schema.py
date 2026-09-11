"""planned_workspace_schema

Revision ID: 20260909_planned_ws
Revises: 20260909_enroll_ovr
Create Date: 2026-09-09

Allow catalog-anchored planned deployments: nullable mission_id / deployment_number
on sensor_tracker_deployments; catalog_mission_id on instruments, sensors, forms.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision: str = "20260909_planned_ws"
down_revision: Union[str, Sequence[str], None] = "20260909_enroll_ovr"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(table):
        return
    existing = {col["name"] for col in inspector.get_columns(table)}
    if column.name not in existing:
        op.add_column(table, column)


def _create_index_if_missing(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table(table):
        return
    existing = {idx["name"] for idx in inspector.get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("sensor_tracker_deployments"):
        # SQLite: recreate uniqueness via unique index on ST deployment id.
        _create_index_if_missing(
            "ix_sensor_tracker_deployments_st_id_unique",
            "sensor_tracker_deployments",
            ["sensor_tracker_deployment_id"],
            unique=True,
        )

    _add_column_if_missing(
        "mission_instruments",
        sa.Column("catalog_mission_id", sa.String(), nullable=True),
    )
    _create_index_if_missing(
        "ix_mission_instruments_catalog_mission_id",
        "mission_instruments",
        ["catalog_mission_id"],
    )

    _add_column_if_missing(
        "mission_sensors",
        sa.Column("catalog_mission_id", sa.String(), nullable=True),
    )
    _create_index_if_missing(
        "ix_mission_sensors_catalog_mission_id",
        "mission_sensors",
        ["catalog_mission_id"],
    )

    _add_column_if_missing(
        "submitted_forms",
        sa.Column("catalog_mission_id", sa.String(), nullable=True),
    )
    _create_index_if_missing(
        "ix_submitted_forms_catalog_mission_id",
        "submitted_forms",
        ["catalog_mission_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    def _drop_index(name: str, table: str) -> None:
        if not inspector.has_table(table):
            return
        existing = {idx["name"] for idx in inspector.get_indexes(table)}
        if name in existing:
            op.drop_index(name, table_name=table)

    def _drop_column(table: str, column: str) -> None:
        if not inspector.has_table(table):
            return
        cols = {c["name"] for c in inspector.get_columns(table)}
        if column in cols:
            op.drop_column(table, column)

    _drop_index("ix_submitted_forms_catalog_mission_id", "submitted_forms")
    _drop_column("submitted_forms", "catalog_mission_id")
    _drop_index("ix_mission_sensors_catalog_mission_id", "mission_sensors")
    _drop_column("mission_sensors", "catalog_mission_id")
    _drop_index("ix_mission_instruments_catalog_mission_id", "mission_instruments")
    _drop_column("mission_instruments", "catalog_mission_id")
    _drop_index(
        "ix_sensor_tracker_deployments_st_id_unique",
        "sensor_tracker_deployments",
    )
