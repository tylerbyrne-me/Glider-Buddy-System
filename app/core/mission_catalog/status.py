"""Read-only mission catalog ops status for Team / health."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.config import settings
from app.services.mission_catalog_sync import (
    catalog_auto_apply_enabled,
    catalog_is_stale,
    last_success_at,
)


def build_catalog_status_report() -> Dict[str, Any]:
    """Safe operational flags + last reconcile stamp (no secrets)."""
    stamp = last_success_at()
    now = datetime.now(timezone.utc)
    age_seconds: Optional[float] = None
    if stamp is not None:
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age_seconds = (now - stamp).total_seconds()

    interval = int(getattr(settings, "mission_catalog_sync_interval_minutes", 30) or 0)
    cron_hour = int(getattr(settings, "mission_catalog_sync_cron_hour", 6))

    is_leader: Optional[bool] = None
    try:
        from app.core.infra.startup_leader import is_startup_leader

        is_leader = bool(is_startup_leader())
    except Exception:
        is_leader = None

    return {
        "auto_apply": catalog_auto_apply_enabled(),
        "enrollment_shadow": bool(
            getattr(settings, "mission_catalog_enrollment_shadow", False)
        ),
        "wg_sync_from_catalog": bool(
            getattr(settings, "mission_catalog_wg_sync_from_catalog", False)
        ),
        "slocum_warm_from_catalog": bool(
            getattr(settings, "mission_catalog_slocum_warm_from_catalog", False)
        ),
        "public_map_from_catalog": bool(
            getattr(settings, "mission_catalog_public_map_from_catalog", False)
        ),
        "sync_interval_minutes": interval,
        "sync_cron_hour_utc": cron_hour if interval <= 0 else None,
        "cadence": (
            f"every {interval} minutes" if interval > 0 else f"daily {cron_hour:02d}:10 UTC"
        ),
        "last_success_at": stamp.isoformat() if stamp else None,
        "last_success_age_seconds": age_seconds,
        "is_stale": catalog_is_stale(),
        "is_startup_leader": is_leader,
    }
