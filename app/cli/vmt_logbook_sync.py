"""CLI: sync VMT log book units from Sensor Tracker (identifier=vmt).

Examples:
  python -m app.cli.vmt_logbook_sync --dry-run
  python -m app.cli.vmt_logbook_sync --apply
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import List, Optional

from sqlmodel import Session as SQLModelSession

from app.core.infra.db import sqlite_engine
from app.services.team_vmt_logbook import sync_vmt_units_from_sensor_tracker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("vmt_logbook_sync")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--username", default="cli")
    args = parser.parse_args(argv)

    with SQLModelSession(sqlite_engine) as session:
        result = asyncio.run(
            sync_vmt_units_from_sensor_tracker(
                session,
                username=args.username,
                dry_run=bool(args.dry_run),
            )
        )
    print(result.summary)
    for item in result.items:
        if item.action in ("create", "update", "link_lost", "error"):
            print(
                f"  [{item.action}] serial={item.serial_number} "
                f"st_id={item.sensor_tracker_instrument_id} "
                f"{item.detail or ''}"
            )
    return 0 if result.errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
