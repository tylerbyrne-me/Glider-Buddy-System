"""CLI: dry-run or apply source-neutral mission catalog reconciliation.

Examples:
  python -m app.cli.mission_catalog_sync --dry-run
  python -m app.cli.mission_catalog_sync --apply
  python -m app.cli.mission_catalog_sync --apply --connectors legacy_env,erddap
"""

from __future__ import annotations

import argparse
import logging
import sys

from app.services.mission_catalog_sync import run_mission_catalog_sync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("mission_catalog_sync_cli")


def run_dry_run_checks() -> int:
    """Zero-arg Team ops entry: always dry-run catalog reconciliation."""
    return main(["--dry-run"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Report proposed changes only")
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Write reconciliation to SQLite (refused if identity gates are unclean)",
    )
    parser.add_argument(
        "--connectors",
        default=None,
        help="Comma-separated connector filter (sensor_tracker,erddap,wgms_remote,legacy_env)",
    )
    args = parser.parse_args(argv)

    connectors = None
    if args.connectors:
        connectors = [c.strip() for c in args.connectors.split(",") if c.strip()]

    if connectors:
        import asyncio
        from app.services.mission_catalog_sync import sync_mission_catalog

        result = asyncio.run(
            sync_mission_catalog(dry_run=bool(args.dry_run), connectors=connectors)
        )
    else:
        result = run_mission_catalog_sync(dry_run=bool(args.dry_run))

    print(result.summary)
    if result.conflicts:
        print("Conflicts / blockers:")
        for item in result.conflicts[:50]:
            print(f"  - {item}")
    if result.errors:
        print("Errors:")
        for item in result.errors[:50]:
            print(f"  - {item}")
    # Non-zero when reconcile failed, or apply was refused (conflicts include gate blockers)
    if result.counts.failed:
        return 1
    if args.apply and result.dry_run and result.conflicts:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
