"""add ora request drafts and hull profiles

Revision ID: 20260928_ora_requests
Revises: 20260915_slocum_mk
Create Date: 2026-09-28

Team Wave Glider Operational Risk Assessment drafts, separate from submitted_forms.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260928_ora_requests"
down_revision: Union[str, Sequence[str], None] = "20260915_slocum_mk"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "ora_requests" not in tables:
        op.create_table(
            "ora_requests",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(), nullable=True),
            sa.Column("catalog_mission_id", sa.String(), nullable=True),
            sa.Column("hull_name", sa.String(), nullable=True),
            sa.Column("requester", sa.String(), nullable=False, server_default=""),
            sa.Column("project_code", sa.String(), nullable=True),
            sa.Column("project_code_other", sa.String(), nullable=True),
            sa.Column("client", sa.String(), nullable=True),
            sa.Column("dates_of_operation", sa.String(), nullable=True),
            sa.Column("purposes_json", sa.JSON(), nullable=True),
            sa.Column("priority", sa.Integer(), nullable=True),
            sa.Column("coordinate_mode", sa.String(), nullable=False, server_default="course"),
            sa.Column("coordinates_json", sa.JSON(), nullable=True),
            sa.Column("vehicle_model", sa.String(), nullable=True),
            sa.Column("umbilical_m", sa.String(), nullable=True),
            sa.Column("towing", sa.String(), nullable=True),
            sa.Column("towed_device", sa.String(), nullable=True),
            sa.Column("ecos_up_to_date", sa.String(), nullable=True),
            sa.Column("sv3_software_version", sa.String(), nullable=True),
            sa.Column("apu_count", sa.String(), nullable=True),
            sa.Column("smc_version", sa.String(), nullable=True),
            sa.Column("devices_json", sa.JSON(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_at_utc", sa.DateTime(), nullable=False),
            sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
            sa.Column("updated_by_username", sa.String(), nullable=True),
            sa.ForeignKeyConstraint(["catalog_mission_id"], ["catalog_missions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_ora_requests_title", "ora_requests", ["title"])
        op.create_index(
            "ix_ora_requests_catalog_mission_id", "ora_requests", ["catalog_mission_id"]
        )
        op.create_index("ix_ora_requests_hull_name", "ora_requests", ["hull_name"])
        op.create_index(
            "ix_ora_requests_coordinate_mode", "ora_requests", ["coordinate_mode"]
        )
        op.create_index(
            "ix_ora_requests_updated_by_username",
            "ora_requests",
            ["updated_by_username"],
        )

    if "ora_hull_profiles" not in tables:
        op.create_table(
            "ora_hull_profiles",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("hull_name", sa.String(), nullable=False),
            sa.Column("vehicle_model", sa.String(), nullable=True),
            sa.Column("umbilical_m", sa.String(), nullable=True),
            sa.Column("towing", sa.String(), nullable=True),
            sa.Column("towed_device", sa.String(), nullable=True),
            sa.Column("ecos_up_to_date", sa.String(), nullable=True),
            sa.Column("sv3_software_version", sa.String(), nullable=True),
            sa.Column("apu_count", sa.String(), nullable=True),
            sa.Column("smc_version", sa.String(), nullable=True),
            sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
            sa.Column("updated_by_username", sa.String(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("hull_name"),
        )
        op.create_index(
            "ix_ora_hull_profiles_hull_name", "ora_hull_profiles", ["hull_name"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "ora_hull_profiles" in tables:
        op.drop_index("ix_ora_hull_profiles_hull_name", table_name="ora_hull_profiles")
        op.drop_table("ora_hull_profiles")
    if "ora_requests" in tables:
        op.drop_index("ix_ora_requests_updated_by_username", table_name="ora_requests")
        op.drop_index("ix_ora_requests_coordinate_mode", table_name="ora_requests")
        op.drop_index("ix_ora_requests_hull_name", table_name="ora_requests")
        op.drop_index("ix_ora_requests_catalog_mission_id", table_name="ora_requests")
        op.drop_index("ix_ora_requests_title", table_name="ora_requests")
        op.drop_table("ora_requests")
