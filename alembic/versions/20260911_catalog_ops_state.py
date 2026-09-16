"""catalog_ops_state

Revision ID: 20260911_catalog_ops
Revises: 20260909_planned_ws
Create Date: 2026-09-11

Add catalog mission events, reconcile runs, work items, and live-row unique indexes.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text


revision: str = "20260911_catalog_ops"
down_revision: Union[str, Sequence[str], None] = "20260909_planned_ws"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(table: str) -> bool:
    return table in inspect(op.get_bind()).get_table_names()


def _has_index(table: str, name: str) -> bool:
    if not _has_table(table):
        return False
    return any(idx["name"] == name for idx in inspect(op.get_bind()).get_indexes(table))


def _report_duplicate_live_links(bind) -> None:
    """Fail migration with a clear report if unique indexes would collide."""
    overview_dups = bind.execute(
        text(
            """
            SELECT catalog_mission_id, COUNT(*) AS n
            FROM mission_overview
            WHERE catalog_mission_id IS NOT NULL
            GROUP BY catalog_mission_id
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    slocum_dups = bind.execute(
        text(
            """
            SELECT catalog_mission_id, COUNT(*) AS n
            FROM slocum_deployments
            WHERE catalog_mission_id IS NOT NULL
              AND COALESCE(is_active, 1) = 1
            GROUP BY catalog_mission_id
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    if not overview_dups and not slocum_dups:
        return
    lines = ["Catalog live-row duplicates block unique-index migration:"]
    for row in overview_dups:
        lines.append(f"  mission_overview catalog_mission_id={row[0]} count={row[1]}")
    for row in slocum_dups:
        lines.append(
            f"  slocum_deployments (active) catalog_mission_id={row[0]} count={row[1]}"
        )
    lines.append(
        "Repair with: python -m app.cli.mission_catalog_repair_duplicates "
        "(or resolve manually), then re-run alembic upgrade."
    )
    raise RuntimeError("\n".join(lines))


def upgrade() -> None:
    bind = op.get_bind()

    if not _has_table("catalog_mission_events"):
        op.create_table(
            "catalog_mission_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("catalog_mission_id", sa.String(length=36), nullable=False),
            sa.Column("event_type", sa.String(), nullable=False),
            sa.Column("actor", sa.String(), nullable=False, server_default="system"),
            sa.Column("source", sa.String(), nullable=False, server_default="reconcile"),
            sa.Column("before_json", sa.JSON(), nullable=True),
            sa.Column("after_json", sa.JSON(), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("created_at_utc", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["catalog_mission_id"],
                ["catalog_missions.id"],
            ),
        )
        op.create_index(
            "ix_catalog_mission_events_catalog_mission_id",
            "catalog_mission_events",
            ["catalog_mission_id"],
        )
        op.create_index(
            "ix_catalog_mission_events_event_type",
            "catalog_mission_events",
            ["event_type"],
        )
        op.create_index(
            "ix_catalog_mission_events_created_at_utc",
            "catalog_mission_events",
            ["created_at_utc"],
        )

    if not _has_table("catalog_reconcile_runs"):
        op.create_table(
            "catalog_reconcile_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("started_at_utc", sa.DateTime(), nullable=False),
            sa.Column("finished_at_utc", sa.DateTime(), nullable=True),
            sa.Column("trigger", sa.String(), nullable=False, server_default="scheduler"),
            sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("status", sa.String(), nullable=False, server_default="dry_run"),
            sa.Column("gate_clean", sa.Boolean(), nullable=True),
            sa.Column("counts_json", sa.JSON(), nullable=True),
            sa.Column("provision_acted", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("provision_errors", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("final_sync_acted", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("final_sync_errors", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("actor", sa.String(), nullable=False, server_default="scheduler"),
        )
        op.create_index(
            "ix_catalog_reconcile_runs_started_at_utc",
            "catalog_reconcile_runs",
            ["started_at_utc"],
        )
        op.create_index(
            "ix_catalog_reconcile_runs_status",
            "catalog_reconcile_runs",
            ["status"],
        )

    if not _has_table("catalog_mission_work_items"):
        op.create_table(
            "catalog_mission_work_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("catalog_mission_id", sa.String(length=36), nullable=False),
            sa.Column("work_type", sa.String(), nullable=False, server_default="final_sync"),
            sa.Column("status", sa.String(), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("next_retry_at_utc", sa.DateTime(), nullable=True),
            sa.Column("last_attempt_at_utc", sa.DateTime(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("result_json", sa.JSON(), nullable=True),
            sa.Column("created_at_utc", sa.DateTime(), nullable=False),
            sa.Column("updated_at_utc", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(
                ["catalog_mission_id"],
                ["catalog_missions.id"],
            ),
            sa.UniqueConstraint(
                "catalog_mission_id",
                "work_type",
                name="uq_catalog_mission_work_item",
            ),
        )
        op.create_index(
            "ix_catalog_mission_work_items_catalog_mission_id",
            "catalog_mission_work_items",
            ["catalog_mission_id"],
        )
        op.create_index(
            "ix_catalog_mission_work_items_status",
            "catalog_mission_work_items",
            ["status"],
        )
        op.create_index(
            "ix_catalog_mission_work_items_next_retry_at_utc",
            "catalog_mission_work_items",
            ["next_retry_at_utc"],
        )

    _report_duplicate_live_links(bind)

    # SQLite partial unique indexes (one live overview / one active Slocum per catalog mission).
    if _has_table("mission_overview") and not _has_index(
        "mission_overview", "uq_mission_overview_catalog_mission_id"
    ):
        op.execute(
            """
            CREATE UNIQUE INDEX uq_mission_overview_catalog_mission_id
            ON mission_overview (catalog_mission_id)
            WHERE catalog_mission_id IS NOT NULL
            """
        )

    if _has_table("slocum_deployments") and not _has_index(
        "slocum_deployments", "uq_slocum_deployments_active_catalog_mission_id"
    ):
        op.execute(
            """
            CREATE UNIQUE INDEX uq_slocum_deployments_active_catalog_mission_id
            ON slocum_deployments (catalog_mission_id)
            WHERE catalog_mission_id IS NOT NULL AND COALESCE(is_active, 1) = 1
            """
        )


def downgrade() -> None:
    if _has_index("slocum_deployments", "uq_slocum_deployments_active_catalog_mission_id"):
        op.execute("DROP INDEX IF EXISTS uq_slocum_deployments_active_catalog_mission_id")
    if _has_index("mission_overview", "uq_mission_overview_catalog_mission_id"):
        op.execute("DROP INDEX IF EXISTS uq_mission_overview_catalog_mission_id")
    if _has_table("catalog_mission_work_items"):
        op.drop_table("catalog_mission_work_items")
    if _has_table("catalog_reconcile_runs"):
        op.drop_table("catalog_reconcile_runs")
    if _has_table("catalog_mission_events"):
        op.drop_table("catalog_mission_events")
