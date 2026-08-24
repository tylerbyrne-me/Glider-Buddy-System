"""Orchestrate mission catalog discovery + reconciliation."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Sequence

from sqlmodel import Session, select

from app.config import settings
from app.core.infra.db import sqlite_engine
from app.core.mission_catalog.live_link import link_catalog_to_live_rows
from app.core.mission_catalog.parity import append_gate_summary, build_gate_report_from_batches
from app.core.mission_catalog.providers_config import (
    ProviderSpec,
    load_providers_manifest,
)
from app.core.mission_catalog.reconcile import reconcile_batches
from app.core.mission_catalog.schemas import DiscoveryBatch, ReconcileResult
from app.core.models.database import CatalogMission
from app.services.mission_catalog_providers import (
    discover_erddap,
    discover_legacy_env,
    discover_sensor_tracker,
    discover_wgms_remote,
)

logger = logging.getLogger(__name__)

_LAST_SUCCESS_MARKER = Path("data_store/mission_catalog_last_success.txt")


def _mark_success() -> None:
    _LAST_SUCCESS_MARKER.parent.mkdir(parents=True, exist_ok=True)
    _LAST_SUCCESS_MARKER.write_text(
        datetime.now(timezone.utc).isoformat(),
        encoding="utf-8",
    )


def last_success_at() -> Optional[datetime]:
    if not _LAST_SUCCESS_MARKER.is_file():
        return None
    try:
        return datetime.fromisoformat(_LAST_SUCCESS_MARKER.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def catalog_is_stale(*, max_age_hours: Optional[int] = None) -> bool:
    max_age = max_age_hours
    if max_age is None:
        max_age = int(getattr(settings, "mission_catalog_startup_max_age_hours", 24))
    stamp = last_success_at()
    if stamp is None:
        return True
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - stamp > timedelta(hours=max_age)


def catalog_auto_apply_enabled() -> bool:
    """Leader/startup may write only when this is true (default false)."""
    return bool(getattr(settings, "mission_catalog_auto_apply", False))


async def collect_discovery_batches(
    *,
    connectors: Optional[Sequence[str]] = None,
) -> List[DiscoveryBatch]:
    """Run enabled provider adapters and return discovery batches."""
    manifest = load_providers_manifest()
    wanted = set(connectors) if connectors else None
    batches: List[DiscoveryBatch] = []

    for provider in manifest.providers:
        if not provider.enabled:
            continue
        if wanted is not None and provider.connector not in wanted:
            continue
        started = time.perf_counter()
        try:
            if provider.rate_limit_seconds > 0:
                await asyncio.sleep(min(provider.rate_limit_seconds, 2.0))
            batch = await _run_provider(provider, manifest)
            batches.append(batch)
            logger.info(
                "Catalog provider %s (%s) finished in %.1fs missions=%d orphans=%d errors=%d",
                provider.key,
                provider.connector,
                time.perf_counter() - started,
                len(batch.missions),
                len(batch.orphan_sources),
                len(batch.errors),
            )
        except Exception as exc:
            logger.exception("Catalog provider %s failed", provider.key)
            batches.append(
                DiscoveryBatch(
                    provider_key=provider.key,
                    connector=provider.connector,
                    errors=[str(exc)],
                )
            )
    return batches


async def _run_provider(provider: ProviderSpec, manifest) -> DiscoveryBatch:
    if provider.connector == "sensor_tracker":
        return await discover_sensor_tracker(provider, manifest)
    if provider.connector == "erddap":
        return await asyncio.to_thread(discover_erddap, provider, manifest)
    if provider.connector == "wgms_remote":
        return await discover_wgms_remote(provider, manifest)
    if provider.connector == "legacy_env":
        return await asyncio.to_thread(discover_legacy_env, provider, manifest)
    return DiscoveryBatch(
        provider_key=provider.key,
        connector=provider.connector,
        errors=[f"Unknown connector: {provider.connector}"],
    )


async def sync_mission_catalog(
    *,
    dry_run: bool = False,
    connectors: Optional[Sequence[str]] = None,
    session: Optional[Session] = None,
    link_live_rows: bool = True,
) -> ReconcileResult:
    """Discover from providers and reconcile into SQLite catalog."""
    batches = await collect_discovery_batches(connectors=connectors)
    gate = build_gate_report_from_batches(batches)
    for line in gate.summary_lines():
        logger.info("CATALOG GATE: %s", line)

    if not dry_run and not gate.is_clean:
        logger.warning(
            "CATALOG GATE: blockers present; refusing apply. Re-run --dry-run and fix identity."
        )
        result = ReconcileResult(
            dry_run=True,
            summary=(
                f"Apply refused (gates unclean); dry-run only. "
                f"discovered={sum(len(b.missions)+len(b.orphan_sources) for b in batches)}"
            ),
            conflicts=list(gate.blockers),
            errors=[],
        )
        return append_gate_summary(result, gate)

    manifest = load_providers_manifest()
    owns_session = session is None
    db = session or Session(sqlite_engine)
    try:
        result = reconcile_batches(
            db,
            batches,
            manifest,
            dry_run=dry_run,
        )
        gate_after = build_gate_report_from_batches(batches, session=None if dry_run else db)
        result = append_gate_summary(result, gate_after if not dry_run else gate)

        if not dry_run and link_live_rows and result.counts.failed == 0:
            link_report = link_catalog_to_live_rows(db, dry_run=False)
            result.summary = f"{result.summary}; {link_report.summary}"
            if link_report.skipped_ambiguous:
                result.summary = (
                    f"{result.summary}; ambiguous={link_report.skipped_ambiguous}"
                )

        if not dry_run and result.counts.failed == 0:
            _mark_success()
        elif not dry_run and result.counts.discovered > 0:
            _mark_success()
        return result
    finally:
        if owns_session:
            db.close()


def run_mission_catalog_sync(*, dry_run: bool = False) -> ReconcileResult:
    """Sync entry point for CLI / scheduler (sync wrapper)."""
    return asyncio.run(sync_mission_catalog(dry_run=dry_run))


def catalog_mission_count(session: Optional[Session] = None) -> int:
    owns = session is None
    db = session or Session(sqlite_engine)
    try:
        return len(list(db.exec(select(CatalogMission)).all()))
    finally:
        if owns:
            db.close()
