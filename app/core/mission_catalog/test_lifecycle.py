"""Unit tests for lifecycle derivation (PLANNED without start, ACTIVE after start)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.mission_catalog.lifecycle import derive_operational_state_and_policy
from app.core.models.enums import CatalogOperationalState, CatalogSyncPolicy


def test_no_deployment_number_is_planned() -> None:
    state, policy = derive_operational_state_and_policy(
        start_time=None,
        end_time=None,
        deployment_number=None,
    )
    assert state == CatalogOperationalState.PLANNED
    assert policy == CatalogSyncPolicy.CATALOG_ONLY


def test_numbered_without_start_is_planned() -> None:
    state, policy = derive_operational_state_and_policy(
        start_time=None,
        end_time=None,
        deployment_number=230,
    )
    assert state == CatalogOperationalState.PLANNED
    assert policy == CatalogSyncPolicy.CATALOG_ONLY


def test_future_start_is_planned() -> None:
    now = datetime(2026, 9, 9, tzinfo=timezone.utc)
    state, policy = derive_operational_state_and_policy(
        start_time=now + timedelta(days=2),
        end_time=None,
        deployment_number=231,
        now=now,
    )
    assert state == CatalogOperationalState.PLANNED
    assert policy == CatalogSyncPolicy.CATALOG_ONLY


def test_start_reached_is_active() -> None:
    now = datetime(2026, 9, 9, tzinfo=timezone.utc)
    state, policy = derive_operational_state_and_policy(
        start_time=now - timedelta(hours=1),
        end_time=None,
        deployment_number=231,
        now=now,
    )
    assert state == CatalogOperationalState.ACTIVE
    assert policy == CatalogSyncPolicy.CATALOG_ONLY


def test_end_time_is_completed() -> None:
    now = datetime(2026, 9, 9, tzinfo=timezone.utc)
    state, policy = derive_operational_state_and_policy(
        start_time=now - timedelta(days=10),
        end_time=now - timedelta(days=1),
        deployment_number=231,
        now=now,
    )
    assert state == CatalogOperationalState.COMPLETED
    assert policy == CatalogSyncPolicy.ON_DEMAND
