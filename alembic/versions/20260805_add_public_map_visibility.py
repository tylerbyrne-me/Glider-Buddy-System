"""add_public_map_visibility_flags

Revision ID: 20260805_public_map
Revises: 20260804_slocum_r4w_url
Create Date: 2026-08-05

Public login-map visibility flags on mission_overview and slocum_deployments,
plus SlocumDeployment.weekly_report_url for gated public report links.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260805_public_map"
down_revision: Union[str, Sequence[str], None] = "20260804_slocum_r4w_url"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_bool_column(table: str, name: str) -> None:
    columns = {col["name"] for col in inspect(op.get_bind()).get_columns(table)}
    if name not in columns:
        op.add_column(
            table,
            sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def _add_string_column(table: str, name: str) -> None:
    columns = {col["name"] for col in inspect(op.get_bind()).get_columns(table)}
    if name not in columns:
        op.add_column(table, sa.Column(name, sa.String(), nullable=True))


def _drop_column_if_exists(table: str, name: str) -> None:
    columns = {col["name"] for col in inspect(op.get_bind()).get_columns(table)}
    if name in columns:
        op.drop_column(table, name)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("mission_overview"):
        _add_bool_column("mission_overview", "public_map_enabled")
        _add_bool_column("mission_overview", "public_weekly_report_enabled")

    if inspector.has_table("slocum_deployments"):
        _add_bool_column("slocum_deployments", "public_map_enabled")
        _add_bool_column("slocum_deployments", "public_weekly_report_enabled")
        _add_string_column("slocum_deployments", "weekly_report_url")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if inspector.has_table("mission_overview"):
        _drop_column_if_exists("mission_overview", "public_weekly_report_enabled")
        _drop_column_if_exists("mission_overview", "public_map_enabled")

    if inspector.has_table("slocum_deployments"):
        _drop_column_if_exists("slocum_deployments", "weekly_report_url")
        _drop_column_if_exists("slocum_deployments", "public_weekly_report_enabled")
        _drop_column_if_exists("slocum_deployments", "public_map_enabled")
