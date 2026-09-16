"""Export catalog-derived sync keys for rollback / parity checks.

  python -m app.cli.mission_catalog_export_keys
  python -m app.cli.mission_catalog_export_keys --json > catalog_keys.json
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

from sqlmodel import Session

from app.config import settings
from app.core.infra.db import sqlite_engine
from app.core.mission_catalog.enablement import (
    env_slocum_active_keys,
    env_slocum_historical_keys,
    env_wave_glider_active_keys,
    list_catalog_sync_targets,
)


def build_export(session: Session) -> Dict[str, Any]:
    catalog_wg = list_catalog_sync_targets("wave_glider", session)
    catalog_sl_active = list_catalog_sync_targets(
        "slocum", session, operational_state="active"
    )
    catalog_sl_hist = list_catalog_sync_targets(
        "slocum", session, operational_state="completed"
    )
    return {
        "env": {
            "active_realtime_missions": env_wave_glider_active_keys(),
            "active_slocum_datasets": env_slocum_active_keys(),
            "historical_slocum_datasets": env_slocum_historical_keys(),
        },
        "catalog": {
            "wave_glider_active": catalog_wg,
            "slocum_active": catalog_sl_active,
            "slocum_historical": catalog_sl_hist,
        },
        "flags": {
            "mission_catalog_auto_apply": bool(
                getattr(settings, "mission_catalog_auto_apply", False)
            ),
            "mission_catalog_wg_sync_from_catalog": bool(
                getattr(settings, "mission_catalog_wg_sync_from_catalog", False)
            ),
            "mission_catalog_slocum_warm_from_catalog": bool(
                getattr(settings, "mission_catalog_slocum_warm_from_catalog", False)
            ),
            "mission_catalog_public_map_from_catalog": bool(
                getattr(settings, "mission_catalog_public_map_from_catalog", False)
            ),
        },
        "rollback_hint": {
            "steps": [
                "Capture this export before changing flags.",
                "Set mission_catalog_wg_sync_from_catalog=false",
                "Set mission_catalog_slocum_warm_from_catalog=false",
                "Set mission_catalog_public_map_from_catalog=false",
                "Set mission_catalog_auto_apply=false",
                "Restore ACTIVE_REALTIME_MISSIONS / ACTIVE_SLOCUM_DATASETS / "
                "HISTORICAL_SLOCUM_DATASETS from env section (or prior export).",
                "Reactivate any catalog-completed Slocum live rows required by "
                "the restored ACTIVE_SLOCUM_DATASETS list.",
                "Invalidate public-map cache and restart gliderbuddy.",
            ]
        },
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON (default pretty text)",
    )
    args = parser.parse_args(argv)
    with Session(sqlite_engine) as session:
        payload = build_export(session)
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print("=== Catalog key export (rollback aid) ===")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
