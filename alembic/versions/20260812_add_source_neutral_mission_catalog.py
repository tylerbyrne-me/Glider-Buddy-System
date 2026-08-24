"""add_source_neutral_mission_catalog

Revision ID: 20260812_mission_catalog
Revises: 20260809_slocum_eom_url
Create Date: 2026-08-12

Source-neutral mission catalog tables plus nullable catalog_mission_id FKs
on MissionOverview, SensorTrackerDeployment, and SlocumDeployment.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "20260812_mission_catalog"
down_revision: Union[str, Sequence[str], None] = "20260809_slocum_eom_url"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    if not inspector.has_table("catalog_platforms"):
        op.create_table(
            "catalog_platforms",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("canonical_name", sa.String(), nullable=False),
            sa.Column("platform_family", sa.String(), nullable=True),
            sa.Column("owner_organization", sa.String(), nullable=True),
            sa.Column("data_prefix", sa.String(), nullable=True),
            sa.Column("aliases_json", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at_utc", sa.DateTime(), nullable=False),
            sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_catalog_platforms_canonical_name", "catalog_platforms", ["canonical_name"])
        op.create_index("ix_catalog_platforms_platform_family", "catalog_platforms", ["platform_family"])
        op.create_index("ix_catalog_platforms_owner_organization", "catalog_platforms", ["owner_organization"])
        op.create_index("ix_catalog_platforms_data_prefix", "catalog_platforms", ["data_prefix"])
        op.create_index("ix_catalog_platforms_is_active", "catalog_platforms", ["is_active"])

    if not inspector.has_table("catalog_missions"):
        op.create_table(
            "catalog_missions",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("platform_id", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(), nullable=True),
            sa.Column("deployment_number", sa.Integer(), nullable=True),
            sa.Column("start_time", sa.DateTime(), nullable=True),
            sa.Column("end_time", sa.DateTime(), nullable=True),
            sa.Column("operational_state", sa.String(), nullable=False, server_default="active"),
            sa.Column("sync_policy", sa.String(), nullable=False, server_default="catalog_only"),
            sa.Column("visibility", sa.String(), nullable=False, server_default="internal"),
            sa.Column("has_manual_overrides", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("provenance", sa.String(), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at_utc", sa.DateTime(), nullable=False),
            sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["platform_id"], ["catalog_platforms.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_catalog_missions_platform_id", "catalog_missions", ["platform_id"])
        op.create_index("ix_catalog_missions_title", "catalog_missions", ["title"])
        op.create_index("ix_catalog_missions_deployment_number", "catalog_missions", ["deployment_number"])
        op.create_index("ix_catalog_missions_start_time", "catalog_missions", ["start_time"])
        op.create_index("ix_catalog_missions_end_time", "catalog_missions", ["end_time"])
        op.create_index("ix_catalog_missions_operational_state", "catalog_missions", ["operational_state"])
        op.create_index("ix_catalog_missions_sync_policy", "catalog_missions", ["sync_policy"])
        op.create_index("ix_catalog_missions_visibility", "catalog_missions", ["visibility"])
        op.create_index("ix_catalog_missions_provenance", "catalog_missions", ["provenance"])
        op.create_index("ix_catalog_missions_last_seen_at", "catalog_missions", ["last_seen_at"])

    if not inspector.has_table("catalog_external_identities"):
        op.create_table(
            "catalog_external_identities",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("mission_id", sa.String(length=36), nullable=False),
            sa.Column("provider_key", sa.String(), nullable=False),
            sa.Column("identity_kind", sa.String(), nullable=False),
            sa.Column("external_id", sa.String(), nullable=False),
            sa.Column("is_canonical", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at_utc", sa.DateTime(), nullable=False),
            sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["mission_id"], ["catalog_missions.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider_key",
                "identity_kind",
                "external_id",
                name="uq_catalog_external_identity",
            ),
        )
        op.create_index("ix_catalog_external_identities_mission_id", "catalog_external_identities", ["mission_id"])
        op.create_index("ix_catalog_external_identities_provider_key", "catalog_external_identities", ["provider_key"])
        op.create_index("ix_catalog_external_identities_identity_kind", "catalog_external_identities", ["identity_kind"])
        op.create_index("ix_catalog_external_identities_external_id", "catalog_external_identities", ["external_id"])

    if not inspector.has_table("catalog_mission_sources"):
        op.create_table(
            "catalog_mission_sources",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("mission_id", sa.String(length=36), nullable=True),
            sa.Column("provider_key", sa.String(), nullable=False),
            sa.Column("source_kind", sa.String(), nullable=False),
            sa.Column("collection", sa.String(), nullable=False, server_default=""),
            sa.Column("external_ref", sa.String(), nullable=False),
            sa.Column("source_variant", sa.String(), nullable=False, server_default="unknown"),
            sa.Column("capabilities_json", sa.Text(), nullable=True),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
            sa.Column("match_status", sa.String(), nullable=False, server_default="unmatched"),
            sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
            sa.Column("verification_error", sa.Text(), nullable=True),
            sa.Column("consecutive_misses", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("first_seen_at", sa.DateTime(), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at_utc", sa.DateTime(), nullable=False),
            sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["mission_id"], ["catalog_missions.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "provider_key",
                "collection",
                "external_ref",
                name="uq_catalog_mission_source",
            ),
        )
        op.create_index("ix_catalog_mission_sources_mission_id", "catalog_mission_sources", ["mission_id"])
        op.create_index("ix_catalog_mission_sources_provider_key", "catalog_mission_sources", ["provider_key"])
        op.create_index("ix_catalog_mission_sources_source_kind", "catalog_mission_sources", ["source_kind"])
        op.create_index("ix_catalog_mission_sources_collection", "catalog_mission_sources", ["collection"])
        op.create_index("ix_catalog_mission_sources_external_ref", "catalog_mission_sources", ["external_ref"])
        op.create_index("ix_catalog_mission_sources_source_variant", "catalog_mission_sources", ["source_variant"])
        op.create_index("ix_catalog_mission_sources_enabled", "catalog_mission_sources", ["enabled"])
        op.create_index("ix_catalog_mission_sources_match_status", "catalog_mission_sources", ["match_status"])
        op.create_index("ix_catalog_mission_sources_is_verified", "catalog_mission_sources", ["is_verified"])
        op.create_index("ix_catalog_mission_sources_last_seen_at", "catalog_mission_sources", ["last_seen_at"])

    def _add_catalog_fk(table_name: str) -> None:
        if not inspector.has_table(table_name):
            return
        columns = {col["name"] for col in inspector.get_columns(table_name)}
        if "catalog_mission_id" in columns:
            return
        op.add_column(
            table_name,
            sa.Column("catalog_mission_id", sa.String(length=36), nullable=True),
        )
        op.create_index(
            f"ix_{table_name}_catalog_mission_id",
            table_name,
            ["catalog_mission_id"],
        )

    _add_catalog_fk("mission_overview")
    _add_catalog_fk("sensor_tracker_deployments")
    _add_catalog_fk("slocum_deployments")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)

    def _drop_catalog_fk(table_name: str) -> None:
        if not inspector.has_table(table_name):
            return
        columns = {col["name"] for col in inspector.get_columns(table_name)}
        if "catalog_mission_id" not in columns:
            return
        op.drop_index(f"ix_{table_name}_catalog_mission_id", table_name=table_name)
        op.drop_column(table_name, "catalog_mission_id")

    _drop_catalog_fk("slocum_deployments")
    _drop_catalog_fk("sensor_tracker_deployments")
    _drop_catalog_fk("mission_overview")

    if inspector.has_table("catalog_mission_sources"):
        op.drop_table("catalog_mission_sources")
    if inspector.has_table("catalog_external_identities"):
        op.drop_table("catalog_external_identities")
    if inspector.has_table("catalog_missions"):
        op.drop_table("catalog_missions")
    if inspector.has_table("catalog_platforms"):
        op.drop_table("catalog_platforms")
