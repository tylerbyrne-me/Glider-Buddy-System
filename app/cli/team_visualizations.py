"""CLI: rebuild Team Visualizations gallery charts from Sensor Tracker.

Examples:
  python -m app.cli.team_visualizations --chart all
  python -m app.cli.team_visualizations --chart platform_share
  python -m app.cli.team_visualizations --chart all --reuse-snapshot
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from app.services.team_visualizations import (
    CHART_SPECS,
    generate_all_charts,
    generate_chart,
    list_chart_specs,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("team_visualizations_cli")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    slugs = ["all", *sorted(CHART_SPECS.keys())]
    parser.add_argument(
        "--chart",
        default="all",
        choices=slugs,
        help="Chart slug to rebuild, or all (default)",
    )
    parser.add_argument(
        "--reuse-snapshot",
        action="store_true",
        help="Reuse data_store/team_viz_cache/fleet_snapshot.json if present",
    )
    args = parser.parse_args(argv)

    async def _run() -> dict:
        if args.chart == "all":
            return await generate_all_charts(reuse_snapshot=args.reuse_snapshot)
        return {
            "success": True,
            "charts": [
                await generate_chart(args.chart, reuse_snapshot=args.reuse_snapshot)
            ],
        }

    try:
        result = asyncio.run(_run())
    except Exception as exc:
        logger.exception("Team visualizations rebuild failed")
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    charts = result.get("charts") or []
    ok = True
    for item in charts:
        status = "OK" if item.get("success") else "FAIL"
        if not item.get("success"):
            ok = False
        print(
            f"[{status}] {item.get('slug')}: "
            f"{item.get('error') or item.get('generated_at') or ''} "
            f"({item.get('duration_ms', 0)} ms)"
        )
        for note in item.get("notes") or []:
            print(f"  note: {note}")
    if args.chart == "all":
        print(
            f"Snapshot as_of={result.get('snapshot_as_of')} "
            f"fetched={result.get('snapshot_fetched_at')}"
        )
    if not charts:
        print("No charts registered:", ", ".join(s.slug for s in list_chart_specs()))
        return 1
    return 0 if ok and result.get("success", ok) else 2


if __name__ == "__main__":
    raise SystemExit(main())
