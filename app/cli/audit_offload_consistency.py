"""
Unified dry-run for offload log / VRL / mission consistency.

Runs the existing VRL and mission audits (no third matcher, no --apply).
Apply stays on the dedicated CLIs after you review the CSVs.

Examples:

  conda activate WorkPython
  python -m app.cli.audit_offload_consistency --mission m227-SV3-1071 --mission m219-SV3-1121
  python -m app.cli.audit_offload_consistency --all-local-vm4 --csv-dir data_store/tmp_offload_consistency
  python -m app.cli.audit_offload_consistency --mission m227-SV3-1071 --station HFX231
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from sqlmodel import select

from app.core import models
from app.core.infra.db import SQLModelSession, sqlite_engine
from app.services.offload_consistency_audit import build_consistency_summary
from app.services.offload_mission_audit import (
    audit_missions,
    list_local_vm4_mission_ids,
)
from app.services.offload_vrl_audit import audit_offload_logs_for_vrl_issues

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("offload_consistency_audit")

MISSION_CSV_FIELDS = [
    "expected_mission_id",
    "reason",
    "station_id",
    "log_id",
    "actual_mission_id",
    "vrl_file_name",
    "was_offloaded",
    "session_ref_utc",
    "log_ref_utc",
    "serial_number",
    "can_apply",
    "parser_session_ref",
    "created_by_source",
]


def _load_vrl_logs(
    session: SQLModelSession,
    *,
    station_id: Optional[str],
) -> list[models.OffloadLog]:
    stmt = select(models.OffloadLog).where(models.OffloadLog.vrl_file_name.is_not(None))
    if station_id:
        stmt = stmt.where(models.OffloadLog.station_id == station_id)
    return list(session.exec(stmt).all())


def _write_csv(
    path: Path,
    fieldnames: list[str],
    rows: Iterable[dict[str, Any]],
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        return path
    except PermissionError:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        alt = path.with_name(f"{path.stem}_{stamp}{path.suffix}")
        with alt.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        logger.warning(
            "Could not overwrite %s (file locked?). Wrote %s instead.",
            path,
            alt,
        )
        return alt


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run unified offload consistency audit (VRL + mission). "
            "Does not apply fixes — use audit_offload_vrl_attach / "
            "audit_offload_mission_id with --apply after review."
        )
    )
    parser.add_argument(
        "--mission",
        action="append",
        default=[],
        help="Mission folder id for mission audit (repeatable).",
    )
    parser.add_argument(
        "--all-local-vm4",
        action="store_true",
        help="Scan every local mission dir that has Vemco VM4 Information.csv.",
    )
    parser.add_argument("--station", help="Limit both audits to one station_id.")
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=30,
        help="Mission enrichment match window in minutes (default 30).",
    )
    parser.add_argument(
        "--max-delta-hours",
        type=float,
        default=48.0,
        help="VRL stamp vs log time threshold in hours (default 48).",
    )
    parser.add_argument(
        "--csv-dir",
        type=Path,
        help=(
            "Directory for linked CSVs: offload_vrl_findings.csv and "
            "offload_mission_findings.csv"
        ),
    )
    args = parser.parse_args()

    mission_ids = list(args.mission or [])
    if args.all_local_vm4:
        discovered = list_local_vm4_mission_ids()
        logger.info("Discovered %s local mission(s) with VM4 info CSV", len(discovered))
        for mid in discovered:
            if mid not in mission_ids:
                mission_ids.append(mid)

    if not mission_ids:
        logger.error("Provide --mission and/or --all-local-vm4 for the mission half")
        return 2

    with SQLModelSession(sqlite_engine) as session:
        vrl_logs = _load_vrl_logs(session, station_id=args.station)
        vrl_findings = audit_offload_logs_for_vrl_issues(
            vrl_logs, max_delta_hours=args.max_delta_hours
        )
        mission_findings = audit_missions(
            session,
            mission_ids,
            station_id=args.station,
            time_window_minutes=args.window_minutes,
        )

        summary = build_consistency_summary(
            vrl_findings=vrl_findings,
            mission_findings=mission_findings,
            scanned_with_vrl=len(vrl_logs),
            missions_scanned=mission_ids,
            dry_run=True,
        )

        logger.info(
            "VRL: scanned %s with names → %s suspect row(s); "
            "mission: %s finding row(s) across %s mission(s)%s",
            summary["vrl"]["scanned_with_vrl"],
            summary["vrl"]["suspect_rows"],
            summary["mission"]["finding_rows"],
            len(mission_ids),
            f" station={args.station}" if args.station else "",
        )
        logger.info(
            "Highlights: stamp_mismatch=%s mission_missing=%s mission_mismatch=%s "
            "failed_with_vrl=%s no_matching_log=%s no_station=%s applyable=%s",
            summary["highlights"]["vrl_stamp_mismatch"],
            summary["highlights"]["mission_missing"],
            summary["highlights"]["mission_mismatch"],
            summary["highlights"]["failed_with_vrl"],
            summary["highlights"]["no_matching_log"],
            summary["highlights"]["no_station"],
            summary["highlights"]["mission_applyable"],
        )

        written: dict[str, str] = {}
        if args.csv_dir:
            vrl_fields = (
                list(vrl_findings[0].as_dict().keys())
                if vrl_findings
                else [
                    "log_id",
                    "station_id",
                    "vrl_file_name",
                    "vrl_stamp_utc",
                    "log_ref_utc",
                    "delta_hours",
                    "was_offloaded",
                    "created_by_source",
                    "reason",
                ]
            )
            vrl_path = _write_csv(
                args.csv_dir / "offload_vrl_findings.csv",
                vrl_fields,
                (row.as_dict() for row in vrl_findings),
            )
            mission_path = _write_csv(
                args.csv_dir / "offload_mission_findings.csv",
                MISSION_CSV_FIELDS,
                (row.as_dict() for row in mission_findings),
            )
            written = {
                "vrl_csv": str(vrl_path),
                "mission_csv": str(mission_path),
            }
            logger.info("Wrote %s and %s", vrl_path, mission_path)

        out = {**summary, "csv": written}
        print(json.dumps(out, indent=2))
        logger.info(
            "Dry-run only. Apply with: "
            "python -m app.cli.audit_offload_vrl_attach --apply "
            "--reasons vrl_stamp_far_from_log_time ; "
            "python -m app.cli.audit_offload_mission_id --apply "
            "--reasons mission_mismatch,mission_missing "
            "(plus the same --mission / --station filters)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
