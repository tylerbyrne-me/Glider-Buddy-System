"""slocum mission_key uniqueness

Revision ID: 20260915_slocum_mk
Revises: 20260911_catalog_ops
Create Date: 2026-09-15

Enforce one non-null SlocumDeployment.mission_key row in total (active or
completed). Realtime/delayed variation belongs on CatalogMissionSource /
erddap_dataset_id, not sibling metadata rows. Nullable legacy/test rows remain.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text


revision: str = "20260915_slocum_mk"
down_revision: Union[str, Sequence[str], None] = "20260911_catalog_ops"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "uq_slocum_deployments_mission_key_nonnull"


def _has_table(table: str) -> bool:
    return table in inspect(op.get_bind()).get_table_names()


def _has_index(table: str, name: str) -> bool:
    if not _has_table(table):
        return False
    return any(idx["name"] == name for idx in inspect(op.get_bind()).get_indexes(table))


def _report_duplicate_mission_keys(bind) -> None:
    dups = bind.execute(
        text(
            """
            SELECT mission_key, COUNT(*) AS n
            FROM slocum_deployments
            WHERE mission_key IS NOT NULL
              AND TRIM(mission_key) != ''
            GROUP BY mission_key
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()
    if not dups:
        return
    lines = [
        "Duplicate SlocumDeployment.mission_key values block uniqueness migration:"
    ]
    for row in dups:
        detail = bind.execute(
            text(
                """
                SELECT id, is_active, catalog_mission_id, erddap_dataset_id, status
                FROM slocum_deployments
                WHERE mission_key = :mk
                ORDER BY id
                """
            ),
            {"mk": row[0]},
        ).fetchall()
        lines.append(f"  mission_key={row[0]} count={row[1]} rows={detail}")
    lines.append(
        "Repair with: python -m app.cli.mission_catalog_repair_duplicates "
        "(safe empty orphans) or resolve ambiguous groups manually, then re-run "
        "alembic upgrade."
    )
    raise RuntimeError("\n".join(lines))


def upgrade() -> None:
    bind = op.get_bind()
    if not _has_table("slocum_deployments"):
        return
    _report_duplicate_mission_keys(bind)
    if _has_index("slocum_deployments", INDEX_NAME):
        return
    # SQLite / Postgres partial unique: one row per non-null mission_key.
    dialect = bind.dialect.name
    if dialect == "sqlite":
        op.execute(
            sa.text(
                f"""
                CREATE UNIQUE INDEX {INDEX_NAME}
                ON slocum_deployments (mission_key)
                WHERE mission_key IS NOT NULL AND TRIM(mission_key) != ''
                """
            )
        )
    else:
        op.create_index(
            INDEX_NAME,
            "slocum_deployments",
            ["mission_key"],
            unique=True,
            postgresql_where=sa.text(
                "mission_key IS NOT NULL AND btrim(mission_key) <> ''"
            ),
        )


def downgrade() -> None:
    if not _has_table("slocum_deployments"):
        return
    if _has_index("slocum_deployments", INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name="slocum_deployments")
