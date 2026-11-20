"""
Audit (and optionally clear) offload_logs VRL filenames that look mis-attached.

Dry-run by default. Example:

  conda activate WorkPython
  python -m app.cli.audit_offload_vrl_attach
  python -m app.cli.audit_offload_vrl_attach --station HFX273
  python -m app.cli.audit_offload_vrl_attach --apply --station HFX273
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlmodel import select

from app.core import models
from app.core.infra.db import SQLModelSession, sqlite_engine
from app.services.offload_vrl_audit import audit_offload_logs_for_vrl_issues

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("offload_vrl_audit")


def _load_logs(
    session: SQLModelSession,
    *,
    station_id: Optional[str],
) -> list[models.OffloadLog]:
    stmt = select(models.OffloadLog).where(models.OffloadLog.vrl_file_name.is_not(None))
    if station_id:
        stmt = stmt.where(models.OffloadLog.station_id == station_id)
    return list(session.exec(stmt).all())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit VRL filenames that disagree with offload log attempt times."
    )
    parser.add_argument("--station", help="Limit to one station_id")
    parser.add_argument(
        "--max-delta-hours",
        type=float,
        default=48.0,
        help="Flag when |VRL stamp - log time| exceeds this many hours (default 48).",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        help="Write findings to CSV path",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Clear vrl_file_name on flagged rows (default is dry-run).",
    )
    parser.add_argument(
        "--reasons",
        default="vrl_stamp_far_from_log_time,duplicate_vrl_worse_time_match",
        help="Comma-separated reasons to include when applying cleanup.",
    )
    args = parser.parse_args()
    apply_reasons = {r.strip() for r in args.reasons.split(",") if r.strip()}

    with SQLModelSession(sqlite_engine) as session:
        logs = _load_logs(session, station_id=args.station)
        findings = audit_offload_logs_for_vrl_issues(
            logs, max_delta_hours=args.max_delta_hours
        )

        logger.info(
            "Scanned %s logs with VRL names; found %s suspect row(s)%s",
            len(logs),
            len(findings),
            f" for station={args.station}" if args.station else "",
        )
        for row in findings[:50]:
            logger.info(
                "log#%s %s vrl=%s delta_h=%.2f reason=%s was_offloaded=%s",
                row.log_id,
                row.station_id,
                row.vrl_file_name,
                row.delta_hours,
                row.reason,
                row.was_offloaded,
            )
        if len(findings) > 50:
            logger.info("... %s more not shown", len(findings) - 50)

        unique_log_ids = sorted({row.log_id for row in findings})
        stamp_log_ids = sorted(
            {
                row.log_id
                for row in findings
                if row.reason == "vrl_stamp_far_from_log_time"
            }
        )

        if args.csv:
            fieldnames = (
                list(findings[0].as_dict().keys())
                if findings
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
            csv_path = args.csv
            args.csv.parent.mkdir(parents=True, exist_ok=True)
            try:
                with csv_path.open("w", newline="", encoding="utf-8") as fh:
                    writer = csv.DictWriter(fh, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in findings:
                        writer.writerow(row.as_dict())
            except PermissionError:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                csv_path = args.csv.with_name(
                    f"{args.csv.stem}_{stamp}{args.csv.suffix}"
                )
                with csv_path.open("w", newline="", encoding="utf-8") as fh:
                    writer = csv.DictWriter(fh, fieldnames=fieldnames)
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

        summary = {
            "scanned_with_vrl": len(logs),
            "suspect_rows": len(findings),
            "unique_logs": len(unique_log_ids),
            "stamp_mismatch_logs": len(stamp_log_ids),
            "stamp_mismatch_log_ids": stamp_log_ids,
            "by_reason": {},
            "stations": sorted({f.station_id for f in findings}),
            "dry_run": not args.apply,
        }
        for row in findings:
            summary["by_reason"][row.reason] = (
                summary["by_reason"].get(row.reason, 0) + 1
            )
        print(json.dumps(summary, indent=2))

        if not args.apply:
            logger.info("Dry-run only. Re-run with --apply to clear flagged VRL names.")
            return 0

        cleared = 0
        touched_stations: set[str] = set()
        now = datetime.now(timezone.utc)
        for row in findings:
            if row.reason not in apply_reasons:
                continue
            log = session.get(models.OffloadLog, row.log_id)
            if not log or not log.vrl_file_name:
                continue
            note = (
                f"[VRL_AUDIT_CLEARED {now.isoformat()}] "
                f"removed mis-attached vrl_file_name={log.vrl_file_name!r} "
                f"reason={row.reason} delta_hours={row.delta_hours}"
            )
            existing = (log.parser_notes or "").strip()
            log.parser_notes = f"{existing}\n{note}".strip() if existing else note
            log.vrl_file_name = None
            log.updated_by_source = "vrl_audit"
            log.updated_at_utc = now
            session.add(log)
            cleared += 1
            touched_stations.add(row.station_id)
        session.commit()
        logger.info(
            "Cleared vrl_file_name on %s log(s) across %s station(s)",
            cleared,
            len(touched_stations),
        )
        print(json.dumps({"cleared": cleared, "stations": sorted(touched_stations)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
