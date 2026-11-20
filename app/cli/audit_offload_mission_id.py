"""
Audit offload_logs mission attribution against WG-VM4 sessions per mission folder.

Dry-run by default. Examples:

  conda activate WorkPython
  python -m app.cli.audit_offload_mission_id --mission m227-SV3-1071 --mission m219-SV3-1121
  python -m app.cli.audit_offload_mission_id --all-local-vm4 --csv data_store/tmp_mission_audit.csv
  python -m app.cli.audit_offload_mission_id --mission m227-SV3-1071 --station HFX231
  python -m app.cli.audit_offload_mission_id --mission m227-SV3-1071 --apply --reasons mission_mismatch,mission_missing
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.core.infra.db import SQLModelSession, sqlite_engine
from app.services.offload_mission_audit import (
    APPLYABLE_REASONS,
    apply_mission_audit_fixes,
    audit_missions,
    list_local_vm4_mission_ids,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("offload_mission_audit")

CSV_FIELDS = [
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Audit offload log mission IDs against VM4 completed sessions "
            "from mission folder CSVs."
        )
    )
    parser.add_argument(
        "--mission",
        action="append",
        default=[],
        help="Mission folder id to scan (repeatable).",
    )
    parser.add_argument(
        "--all-local-vm4",
        action="store_true",
        help="Scan every local mission dir that has Vemco VM4 Information.csv.",
    )
    parser.add_argument("--station", help="Limit matched stations to one station_id.")
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=30,
        help="Primary enrichment match window in minutes (default 30).",
    )
    parser.add_argument("--csv", type=Path, help="Write findings to CSV path.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Rewrite blank/sheet mission refs for applyable findings (default dry-run).",
    )
    parser.add_argument(
        "--reasons",
        default="mission_mismatch,mission_missing",
        help=(
            "Comma-separated reasons to apply "
            f"(default mission_mismatch,mission_missing; applyable={sorted(APPLYABLE_REASONS)})."
        ),
    )
    args = parser.parse_args()
    apply_reasons = {r.strip() for r in args.reasons.split(",") if r.strip()}

    mission_ids = list(args.mission or [])
    if args.all_local_vm4:
        discovered = list_local_vm4_mission_ids()
        logger.info("Discovered %s local mission(s) with VM4 info CSV", len(discovered))
        for mid in discovered:
            if mid not in mission_ids:
                mission_ids.append(mid)

    if not mission_ids:
        logger.error("Provide --mission and/or --all-local-vm4")
        return 2

    with SQLModelSession(sqlite_engine) as session:
        findings = audit_missions(
            session,
            mission_ids,
            station_id=args.station,
            time_window_minutes=args.window_minutes,
        )

        logger.info(
            "Scanned %s mission(s); found %s finding row(s)%s",
            len(mission_ids),
            len(findings),
            f" station={args.station}" if args.station else "",
        )
        for row in findings[:50]:
            logger.info(
                "log#%s %s expected=%s actual=%s reason=%s can_apply=%s was_offloaded=%s vrl=%s",
                row.log_id,
                row.station_id,
                row.expected_mission_id,
                row.actual_mission_id,
                row.reason,
                row.can_apply,
                row.was_offloaded,
                row.vrl_file_name,
            )
        if len(findings) > 50:
            logger.info("... %s more not shown", len(findings) - 50)

        if args.csv:
            csv_path = args.csv
            args.csv.parent.mkdir(parents=True, exist_ok=True)
            try:
                with csv_path.open("w", newline="", encoding="utf-8") as fh:
                    writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
                    writer.writeheader()
                    for row in findings:
                        writer.writerow(row.as_dict())
            except PermissionError:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                csv_path = args.csv.with_name(
                    f"{args.csv.stem}_{stamp}{args.csv.suffix}"
                )
                with csv_path.open("w", newline="", encoding="utf-8") as fh:
                    writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
                    writer.writeheader()
                    for row in findings:
                        writer.writerow(row.as_dict())
                logger.warning(
                    "Could not overwrite %s (file locked?). Wrote %s instead.",
                    args.csv,
                    csv_path,
                )
            else:
                logger.info("Wrote %s", csv_path)

        by_reason: dict[str, int] = {}
        for row in findings:
            by_reason[row.reason] = by_reason.get(row.reason, 0) + 1

        applyable_log_ids = sorted(
            {
                row.log_id
                for row in findings
                if row.can_apply
                and row.log_id is not None
                and row.reason in APPLYABLE_REASONS
            }
        )
        failed_with_vrl_ids = sorted(
            {
                row.log_id
                for row in findings
                if row.reason == "failed_with_vrl" and row.log_id is not None
            }
        )

        summary = {
            "missions_scanned": mission_ids,
            "finding_rows": len(findings),
            "unique_logs": len({r.log_id for r in findings if r.log_id is not None}),
            "applyable_logs": len(applyable_log_ids),
            "applyable_log_ids": applyable_log_ids,
            "failed_with_vrl_log_ids": failed_with_vrl_ids,
            "by_reason": by_reason,
            "stations": sorted({r.station_id for r in findings if r.station_id}),
            "dry_run": not args.apply,
        }
        print(json.dumps(summary, indent=2))

        if not args.apply:
            logger.info(
                "Dry-run only. Re-run with --apply --reasons mission_mismatch,mission_missing "
                "to rewrite blank/sheet mission refs."
            )
            return 0

        result = apply_mission_audit_fixes(
            session,
            findings,
            reasons=apply_reasons,
        )
        logger.info(
            "Updated mission on %s log(s) across %s station(s) (skipped %s)",
            result["updated"],
            len(result["stations"]),
            result["skipped"],
        )
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
