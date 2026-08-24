"""Derive catalog operational_state and sync_policy from ST dates + mission number."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Tuple

from app.core.models.enums import CatalogOperationalState, CatalogSyncPolicy


def derive_operational_state_and_policy(
    *,
    start_time: Optional[datetime],
    end_time: Optional[datetime],
    deployment_number: Optional[int],
    now: Optional[datetime] = None,
) -> Tuple[CatalogOperationalState, CatalogSyncPolicy]:
    """Map ST lifecycle fields to catalog state/policy.

    Rules (live-key safe cutover):
    - No deployment_number (preemptive staging) → PLANNED + CATALOG_ONLY
    - end_time set → COMPLETED + ON_DEMAND
    - start_time in the future → PLANNED + CATALOG_ONLY
    - otherwise open → ACTIVE + CATALOG_ONLY
      (CONTINUOUS enablement stays behind env ∩ catalog until crossover)
    """
    if deployment_number is None:
        return CatalogOperationalState.PLANNED, CatalogSyncPolicy.CATALOG_ONLY

    if end_time is not None:
        return CatalogOperationalState.COMPLETED, CatalogSyncPolicy.ON_DEMAND

    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)

    if start_time is not None:
        start = start_time
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if start > clock:
            return CatalogOperationalState.PLANNED, CatalogSyncPolicy.CATALOG_ONLY

    return CatalogOperationalState.ACTIVE, CatalogSyncPolicy.CATALOG_ONLY
