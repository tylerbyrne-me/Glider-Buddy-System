"""add_vmt_logbook_tables

Revision ID: 20260827_vmt_logbook
Revises: 20260812_mission_catalog
Create Date: 2026-08-27

VMT (Vemco Mobile Transceiver) Team log book: units, battery checks,
service events, and unit field audit log.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260827_vmt_logbook"
down_revision: Union[str, Sequence[str], None] = "20260812_mission_catalog"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "vmt_units" not in tables:
        op.create_table(
            "vmt_units",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("serial_number", sa.String(), nullable=False),
            sa.Column("tag_id", sa.String(), nullable=True),
            sa.Column("code_map", sa.String(), nullable=False, server_default="A69-9001"),
            sa.Column("always_tx", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("comments", sa.Text(), nullable=True),
            sa.Column("custody_status", sa.String(), nullable=True),
            sa.Column("custody_status_other", sa.String(), nullable=True),
            sa.Column("sensor_tracker_instrument_id", sa.Integer(), nullable=True),
            sa.Column("sensor_tracker_identifier", sa.String(), nullable=True),
            sa.Column(
                "sensor_tracker_link_status",
                sa.String(),
                nullable=False,
                server_default="never_linked",
            ),
            sa.Column("sensor_tracker_last_seen_at_utc", sa.DateTime(), nullable=True),
            sa.Column("sensor_tracker_last_sync_at_utc", sa.DateTime(), nullable=True),
            sa.Column("sensor_tracker_sync_error", sa.Text(), nullable=True),
            sa.Column("created_via", sa.String(), nullable=False, server_default="manual"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("created_at_utc", sa.DateTime(), nullable=False),
            sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
            sa.Column("updated_by_username", sa.String(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("serial_number"),
        )
        op.create_index("ix_vmt_units_serial_number", "vmt_units", ["serial_number"])
        op.create_index("ix_vmt_units_tag_id", "vmt_units", ["tag_id"])
        op.create_index("ix_vmt_units_code_map", "vmt_units", ["code_map"])
        op.create_index("ix_vmt_units_always_tx", "vmt_units", ["always_tx"])
        op.create_index("ix_vmt_units_custody_status", "vmt_units", ["custody_status"])
        op.create_index(
            "ix_vmt_units_sensor_tracker_instrument_id",
            "vmt_units",
            ["sensor_tracker_instrument_id"],
        )
        op.create_index(
            "ix_vmt_units_sensor_tracker_identifier",
            "vmt_units",
            ["sensor_tracker_identifier"],
        )
        op.create_index(
            "ix_vmt_units_sensor_tracker_link_status",
            "vmt_units",
            ["sensor_tracker_link_status"],
        )
        op.create_index("ix_vmt_units_created_via", "vmt_units", ["created_via"])
        op.create_index("ix_vmt_units_is_active", "vmt_units", ["is_active"])
        op.create_index(
            "ix_vmt_units_updated_by_username",
            "vmt_units",
            ["updated_by_username"],
        )

    if "vmt_battery_checks" not in tables:
        op.create_table(
            "vmt_battery_checks",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("vmt_unit_id", sa.Integer(), nullable=False),
            sa.Column("checked_at", sa.Date(), nullable=False),
            sa.Column("days_remaining", sa.Integer(), nullable=True),
            sa.Column("percent_remaining", sa.Integer(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("recorded_by_username", sa.String(), nullable=True),
            sa.Column("recorded_at_utc", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["vmt_unit_id"], ["vmt_units.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_vmt_battery_checks_vmt_unit_id",
            "vmt_battery_checks",
            ["vmt_unit_id"],
        )
        op.create_index(
            "ix_vmt_battery_checks_checked_at",
            "vmt_battery_checks",
            ["checked_at"],
        )
        op.create_index(
            "ix_vmt_battery_checks_recorded_by_username",
            "vmt_battery_checks",
            ["recorded_by_username"],
        )
        op.create_index(
            "ix_vmt_battery_checks_recorded_at_utc",
            "vmt_battery_checks",
            ["recorded_at_utc"],
        )

    if "vmt_service_events" not in tables:
        op.create_table(
            "vmt_service_events",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("vmt_unit_id", sa.Integer(), nullable=False),
            sa.Column("event_date", sa.Date(), nullable=True),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("recorded_by_username", sa.String(), nullable=True),
            sa.Column("recorded_at_utc", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["vmt_unit_id"], ["vmt_units.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_vmt_service_events_vmt_unit_id",
            "vmt_service_events",
            ["vmt_unit_id"],
        )
        op.create_index(
            "ix_vmt_service_events_event_date",
            "vmt_service_events",
            ["event_date"],
        )
        op.create_index(
            "ix_vmt_service_events_event_type",
            "vmt_service_events",
            ["event_type"],
        )
        op.create_index(
            "ix_vmt_service_events_recorded_by_username",
            "vmt_service_events",
            ["recorded_by_username"],
        )
        op.create_index(
            "ix_vmt_service_events_recorded_at_utc",
            "vmt_service_events",
            ["recorded_at_utc"],
        )

    if "vmt_unit_audit_log" not in tables:
        op.create_table(
            "vmt_unit_audit_log",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("vmt_unit_id", sa.Integer(), nullable=False),
            sa.Column("changed_by_username", sa.String(), nullable=True),
            sa.Column("changed_at_utc", sa.DateTime(), nullable=False),
            sa.Column("changes_json", sa.JSON(), nullable=True),
            sa.ForeignKeyConstraint(["vmt_unit_id"], ["vmt_units.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_vmt_unit_audit_log_vmt_unit_id",
            "vmt_unit_audit_log",
            ["vmt_unit_id"],
        )
        op.create_index(
            "ix_vmt_unit_audit_log_changed_by_username",
            "vmt_unit_audit_log",
            ["changed_by_username"],
        )
        op.create_index(
            "ix_vmt_unit_audit_log_changed_at_utc",
            "vmt_unit_audit_log",
            ["changed_at_utc"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "vmt_unit_audit_log" in tables:
        op.drop_index("ix_vmt_unit_audit_log_changed_at_utc", table_name="vmt_unit_audit_log")
        op.drop_index(
            "ix_vmt_unit_audit_log_changed_by_username",
            table_name="vmt_unit_audit_log",
        )
        op.drop_index("ix_vmt_unit_audit_log_vmt_unit_id", table_name="vmt_unit_audit_log")
        op.drop_table("vmt_unit_audit_log")

    if "vmt_service_events" in tables:
        op.drop_index("ix_vmt_service_events_recorded_at_utc", table_name="vmt_service_events")
        op.drop_index(
            "ix_vmt_service_events_recorded_by_username",
            table_name="vmt_service_events",
        )
        op.drop_index("ix_vmt_service_events_event_type", table_name="vmt_service_events")
        op.drop_index("ix_vmt_service_events_event_date", table_name="vmt_service_events")
        op.drop_index("ix_vmt_service_events_vmt_unit_id", table_name="vmt_service_events")
        op.drop_table("vmt_service_events")

    if "vmt_battery_checks" in tables:
        op.drop_index("ix_vmt_battery_checks_recorded_at_utc", table_name="vmt_battery_checks")
        op.drop_index(
            "ix_vmt_battery_checks_recorded_by_username",
            table_name="vmt_battery_checks",
        )
        op.drop_index("ix_vmt_battery_checks_checked_at", table_name="vmt_battery_checks")
        op.drop_index("ix_vmt_battery_checks_vmt_unit_id", table_name="vmt_battery_checks")
        op.drop_table("vmt_battery_checks")

    if "vmt_units" in tables:
        op.drop_index("ix_vmt_units_updated_by_username", table_name="vmt_units")
        op.drop_index("ix_vmt_units_is_active", table_name="vmt_units")
        op.drop_index("ix_vmt_units_created_via", table_name="vmt_units")
        op.drop_index("ix_vmt_units_sensor_tracker_link_status", table_name="vmt_units")
        op.drop_index("ix_vmt_units_sensor_tracker_identifier", table_name="vmt_units")
        op.drop_index("ix_vmt_units_sensor_tracker_instrument_id", table_name="vmt_units")
        op.drop_index("ix_vmt_units_custody_status", table_name="vmt_units")
        op.drop_index("ix_vmt_units_always_tx", table_name="vmt_units")
        op.drop_index("ix_vmt_units_code_map", table_name="vmt_units")
        op.drop_index("ix_vmt_units_tag_id", table_name="vmt_units")
        op.drop_index("ix_vmt_units_serial_number", table_name="vmt_units")
        op.drop_table("vmt_units")
