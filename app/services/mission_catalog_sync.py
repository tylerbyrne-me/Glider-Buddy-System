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
from app.core.mission_catalog.audit import (
    finish_reconcile_run,
    start_reconcile_run,
)
from app.core.mission_catalog.live_link import link_catalog_to_live_rows
from app.core.mission_catalog.parity import append_gate_summary, build_gate_report_from_batches
from app.core.mission_catalog.providers_config import (
    ProviderSpec,
    load_providers_manifest,
)
from app.core.mission_catalog.reconcile import reconcile_batches
from app.core.mission_catalog.schemas import DiscoveryBatch, ReconcileResult
from app.core.mission_catalog.sync_lock import (
    DEFAULT_LOCK_TIMEOUT_SECONDS,
    catalog_write_lock,
    last_partial_at,
    mark_partial_run,
    read_lock_state,
)
from app.core.models.database import CatalogMission
from app.core.models.enums import CatalogReconcileRunStatus
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


def catalog_write_lock_status() -> dict:
    return read_lock_state()


def catalog_last_partial_at() -> Optional[datetime]:
    return last_partial_at()


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


def _counts_dict(result: ReconcileResult) -> dict:
    c = result.counts
    return {
        "discovered": getattr(c, "discovered", 0),
        "created": getattr(c, "created", 0),
        "updated": getattr(c, "updated", 0),
        "unchanged": getattr(c, "unchanged", 0),
        "failed": getattr(c, "failed", 0),
        "platforms_upserted": getattr(c, "platforms_upserted", 0),
        "sources_linked": getattr(c, "sources_linked", 0),
        "sources_orphaned": getattr(c, "sources_orphaned", 0),
        "stale_marked": getattr(c, "stale_marked", 0),
    }


def _st_deep_sync_ttl_hours() -> int:
    return max(0, int(getattr(settings, "mission_catalog_st_deep_sync_ttl_hours", 24)))


async def _maybe_deep_st_sync(
    db: Session,
    provision_results,
) -> tuple[int, int]:
    """TTL-gated deep ST sync for provisioned/linked rows (never every 30m blindly)."""
    from app.core.models.database import SensorTrackerDeployment
    from app.services.sensor_tracker_sync_service import SensorTrackerSyncService

    sync_service = SensorTrackerSyncService()
    ttl = _st_deep_sync_ttl_hours()
    now = datetime.now(timezone.utc)
    st_synced = 0
    st_skipped = 0
    for prow in provision_results:
        if not prow.actions or prow.readiness not in ("ready", "completed"):
            continue
        force = False
        existing = db.exec(
            select(SensorTrackerDeployment).where(
                SensorTrackerDeployment.catalog_mission_id == prow.mission_id
            )
        ).first()
        if existing is None:
            force = False  # first sync
        elif ttl <= 0:
            force = False
        else:
            last = existing.last_synced_at
            if last is not None:
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if (now - last) < timedelta(hours=ttl):
                    st_skipped += 1
                    continue
        st_row = await sync_service.get_or_sync_catalog_mission(
            prow.mission_id,
            force_refresh=force,
            session=db,
        )
        if st_row is not None:
            st_synced += 1
    return st_synced, st_skipped


async def sync_mission_catalog(
    *,
    dry_run: bool = False,
    connectors: Optional[Sequence[str]] = None,
    session: Optional[Session] = None,
    link_live_rows: bool = True,
    trigger: str = "scheduler",
    actor: str = "scheduler",
    lock_timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
) -> ReconcileResult:
    """Discover from providers and reconcile into SQLite catalog."""
    batches = await collect_discovery_batches(connectors=connectors)
    gate = build_gate_report_from_batches(batches)
    for line in gate.summary_lines():
        logger.info("CATALOG GATE: %s", line)

    if dry_run:
        return await _sync_mission_catalog_unlocked(
            batches=batches,
            gate=gate,
            dry_run=True,
            session=session,
            link_live_rows=False,
            trigger=trigger,
            actor=actor,
        )

    if not gate.is_clean:
        logger.warning(
            "CATALOG GATE: blockers present; refusing apply. Re-run --dry-run and fix identity."
        )
        owns = session is None
        db = session or Session(sqlite_engine)
        try:
            run = start_reconcile_run(
                db, trigger=trigger, dry_run=True, actor=actor, commit=False
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
            result = append_gate_summary(result, gate)
            finish_reconcile_run(
                db,
                run,
                status=CatalogReconcileRunStatus.REFUSED.value,
                gate_clean=False,
                counts=_counts_dict(result),
                summary=result.summary,
                commit=True,
            )
            return result
        finally:
            if owns:
                db.close()

    try:
        with catalog_write_lock(
            timeout_seconds=lock_timeout_seconds,
            actor=actor,
            detail=f"apply:{trigger}",
        ):
            return await _sync_mission_catalog_unlocked(
                batches=batches,
                gate=gate,
                dry_run=False,
                session=session,
                link_live_rows=link_live_rows,
                trigger=trigger,
                actor=actor,
            )
    except TimeoutError as exc:
        logger.warning("Catalog write lock busy: %s", exc)
        result = ReconcileResult(
            dry_run=True,
            summary=f"Apply skipped; catalog write lock busy ({exc})",
            conflicts=[],
            errors=[str(exc)],
        )
        return result


async def _sync_mission_catalog_unlocked(
    *,
    batches: List[DiscoveryBatch],
    gate,
    dry_run: bool,
    session: Optional[Session],
    link_live_rows: bool,
    trigger: str,
    actor: str,
) -> ReconcileResult:
    manifest = load_providers_manifest()
    owns_session = session is None
    db = session or Session(sqlite_engine)
    provision_acted = 0
    provision_errors = 0
    final_sync_acted = 0
    final_sync_errors = 0
    try:
        run = start_reconcile_run(
            db, trigger=trigger, dry_run=dry_run, actor=actor, commit=False
        )
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
            try:
                from app.core.mission_catalog.provisioning import (
                    provision_enrolled_missions,
                )

                provision_results = provision_enrolled_missions(db, dry_run=False)
                provision_acted = sum(1 for r in provision_results if r.actions)
                provision_errors = sum(1 for r in provision_results if r.errors)
                result.summary = (
                    f"{result.summary}; provision_acted={provision_acted} "
                    f"provision_errors={provision_errors}"
                )
                # Enqueue final-sync for newly completed missions.
                try:
                    from app.core.mission_catalog.final_sync import (
                        ensure_final_sync_work_item,
                        process_due_final_sync_work_items,
                    )
                    from app.core.models.enums import CatalogOperationalState

                    completed = db.exec(
                        select(CatalogMission).where(
                            CatalogMission.operational_state
                            == CatalogOperationalState.COMPLETED.value
                        )
                    ).all()
                    for mission in completed:
                        ensure_final_sync_work_item(
                            db, mission, actor=actor, dry_run=False
                        )
                    db.commit()
                    fs = await process_due_final_sync_work_items(db, actor=actor)
                    final_sync_acted = int(fs.get("acted", 0))
                    final_sync_errors = int(fs.get("errors", 0))
                    result.summary = (
                        f"{result.summary}; final_sync_acted={final_sync_acted} "
                        f"final_sync_errors={final_sync_errors}"
                    )
                except Exception as fs_exc:
                    logger.warning("Post-reconcile final sync failed: %s", fs_exc)
                    result.summary = f"{result.summary}; final_sync_error={fs_exc}"
                    final_sync_errors += 1

                try:
                    st_synced, st_skipped = await _maybe_deep_st_sync(
                        db, provision_results
                    )
                    result.summary = (
                        f"{result.summary}; deep_st_synced={st_synced} "
                        f"deep_st_skipped_ttl={st_skipped}"
                    )
                except Exception as st_exc:
                    logger.warning("Post-provision ST deep sync failed: %s", st_exc)
                    result.summary = f"{result.summary}; deep_st_error={st_exc}"
            except Exception as exc:
                logger.warning("Post-reconcile provisioning failed: %s", exc)
                result.summary = f"{result.summary}; provision_error={exc}"
                provision_errors += 1

            # Membership / enrollment changes → rebuild public map promptly.
            try:
                from app.core.public_map_service import invalidate_public_map_cache

                invalidate_public_map_cache()
            except Exception as inv_exc:
                logger.warning("Public map cache invalidate failed: %s", inv_exc)

        gate_clean = bool(getattr(gate_after if not dry_run else gate, "is_clean", True))
        clean_success = (
            not dry_run
            and gate_clean
            and result.counts.failed == 0
            and provision_errors == 0
            and final_sync_errors == 0
            and not result.errors
        )
        if dry_run:
            status = CatalogReconcileRunStatus.DRY_RUN.value
        elif clean_success:
            status = CatalogReconcileRunStatus.SUCCESS.value
            _mark_success()
        elif result.counts.failed > 0 or not gate_clean:
            status = CatalogReconcileRunStatus.FAILURE.value
            mark_partial_run(result.summary or "failure")
        else:
            status = CatalogReconcileRunStatus.PARTIAL.value
            mark_partial_run(result.summary or "partial")

        finish_reconcile_run(
            db,
            run,
            status=status,
            gate_clean=gate_clean,
            counts=_counts_dict(result),
            provision_acted=provision_acted,
            provision_errors=provision_errors,
            final_sync_acted=final_sync_acted,
            final_sync_errors=final_sync_errors,
            summary=result.summary,
            commit=True,
        )
        result.summary = f"{result.summary}; run_status={status}"
        return result
    finally:
        if owns_session:
            db.close()


def run_mission_catalog_sync(
    *,
    dry_run: bool = False,
    trigger: str = "cli",
    actor: str = "cli",
) -> ReconcileResult:
    """Sync entry point for CLI / scheduler (sync wrapper)."""
    return asyncio.run(
        sync_mission_catalog(dry_run=dry_run, trigger=trigger, actor=actor)
    )


def catalog_mission_count(session: Optional[Session] = None) -> int:
    owns = session is None
    db = session or Session(sqlite_engine)
    try:
        return len(list(db.exec(select(CatalogMission)).all()))
    finally:
        if owns:
            db.close()
