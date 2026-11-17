"""add navwarn request drafts

Revision ID: 20261116_navwarn_requests
Revises: 20261110_user_team_access
Create Date: 2026-11-16

Team Canadian Coast Guard NAVWARN request drafts, separate from submitted_forms.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20261116_navwarn_requests"
down_revision: Union[str, Sequence[str], None] = "20261110_user_team_access"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "navwarn_requests" not in tables:
        op.create_table(
            "navwarn_requests",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(), nullable=True),
            sa.Column("catalog_mission_id", sa.String(), nullable=True),
            sa.Column("hull_name", sa.String(), nullable=True),
            sa.Column("desk", sa.String(), nullable=False, server_default="sydney"),
            sa.Column("requester_name", sa.String(), nullable=False, server_default=""),
            sa.Column("telephone", sa.String(), nullable=True),
            sa.Column("email", sa.String(), nullable=True),
            sa.Column("publish_contact", sa.String(), nullable=True),
            sa.Column("publish_contact_custom", sa.Text(), nullable=True),
            sa.Column("is_update_or_cancel", sa.String(), nullable=True),
            sa.Column("previous_navwarn_number", sa.String(), nullable=True),
            sa.Column("start_datetime", sa.String(), nullable=True),
            sa.Column("timezone", sa.String(), nullable=True),
            sa.Column("days_of_operation", sa.String(), nullable=True),
            sa.Column("days_other", sa.String(), nullable=True),
            sa.Column("hours_of_operation", sa.String(), nullable=True),
            sa.Column("hours_other", sa.String(), nullable=True),
            sa.Column("completion_datetime", sa.String(), nullable=True),
            sa.Column("completion_firmness", sa.String(), nullable=True),
            sa.Column("position_format", sa.String(), nullable=False, server_default="dmm"),
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column("place_name", sa.String(), nullable=True),
            sa.Column("extra_positions", sa.Text(), nullable=True),
            sa.Column("nature_category", sa.String(), nullable=True),
            sa.Column("nature_topic", sa.String(), nullable=True),
            sa.Column("nature_other", sa.Text(), nullable=True),
            sa.Column("vessels_on_scene", sa.Text(), nullable=True),
            sa.Column("markers_description", sa.Text(), nullable=True),
            sa.Column("wash_berth", sa.String(), nullable=True),
            sa.Column("other_details", sa.Text(), nullable=True),
            sa.Column("created_at_utc", sa.DateTime(), nullable=False),
            sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
            sa.Column("updated_by_username", sa.String(), nullable=True),
            sa.ForeignKeyConstraint(["catalog_mission_id"], ["catalog_missions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_navwarn_requests_title", "navwarn_requests", ["title"])
        op.create_index(
            "ix_navwarn_requests_catalog_mission_id",
            "navwarn_requests",
            ["catalog_mission_id"],
        )
        op.create_index(
            "ix_navwarn_requests_hull_name", "navwarn_requests", ["hull_name"]
        )
        op.create_index("ix_navwarn_requests_desk", "navwarn_requests", ["desk"])
        op.create_index(
            "ix_navwarn_requests_updated_by_username",
            "navwarn_requests",
            ["updated_by_username"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    if "navwarn_requests" in tables:
        op.drop_index(
            "ix_navwarn_requests_updated_by_username", table_name="navwarn_requests"
        )
        op.drop_index("ix_navwarn_requests_desk", table_name="navwarn_requests")
        op.drop_index("ix_navwarn_requests_hull_name", table_name="navwarn_requests")
        op.drop_index(
            "ix_navwarn_requests_catalog_mission_id", table_name="navwarn_requests"
        )
        op.drop_index("ix_navwarn_requests_title", table_name="navwarn_requests")
        op.drop_table("navwarn_requests")
