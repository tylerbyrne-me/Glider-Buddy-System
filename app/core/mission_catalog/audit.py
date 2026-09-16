"""Append-only catalog mission events and reconcile-run persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.core.models.database import (
    CatalogMissionEvent,
    CatalogReconcileRun,
)
from app.core.models.enums import (
    CatalogMissionEventType,
    CatalogReconcileRunStatus,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def record_mission_event(
    session: Session,
    *,
    catalog_mission_id: str,
    event_type: str,
    actor: str = "system",
    source: str = "reconcile",
    before: Optional[Dict[str, Any]] = None,
    after: Optional[Dict[str, Any]] = None,
    message: Optional[str] = None,
    commit: bool = False,
) -> CatalogMissionEvent:
    """Persist one append-only catalog mission event."""
    event = CatalogMissionEvent(
        catalog_mission_id=catalog_mission_id,
        event_type=event_type,
        actor=actor or "system",
        source=source or "reconcile",
        before_json=before,
        after_json=after,
        message=message,
        created_at_utc=_utcnow(),
    )
    session.add(event)
    if commit:
        session.commit()
        session.refresh(event)
    else:
        session.flush()
    return event


def start_reconcile_run(
    session: Session,
    *,
    trigger: str = "scheduler",
    dry_run: bool = True,
    actor: str = "scheduler",
    commit: bool = False,
) -> CatalogReconcileRun:
    run = CatalogReconcileRun(
        started_at_utc=_utcnow(),
        trigger=trigger,
        dry_run=dry_run,
        status=(
            CatalogReconcileRunStatus.DRY_RUN.value
            if dry_run
            else CatalogReconcileRunStatus.SUCCESS.value
        ),
        actor=actor or trigger,
    )
    session.add(run)
    if commit:
        session.commit()
        session.refresh(run)
    else:
        session.flush()
    return run


def finish_reconcile_run(
    session: Session,
    run: CatalogReconcileRun,
    *,
    status: str,
    gate_clean: Optional[bool] = None,
    counts: Optional[Dict[str, Any]] = None,
    provision_acted: int = 0,
    provision_errors: int = 0,
    final_sync_acted: int = 0,
    final_sync_errors: int = 0,
    summary: Optional[str] = None,
    commit: bool = True,
) -> CatalogReconcileRun:
    run.finished_at_utc = _utcnow()
    run.status = status
    run.gate_clean = gate_clean
    run.counts_json = counts
    run.provision_acted = int(provision_acted)
    run.provision_errors = int(provision_errors)
    run.final_sync_acted = int(final_sync_acted)
    run.final_sync_errors = int(final_sync_errors)
    run.summary = summary
    session.add(run)
    if commit:
        session.commit()
        session.refresh(run)
    else:
        session.flush()
    return run


def list_mission_events(
    session: Session,
    catalog_mission_id: str,
    *,
    limit: int = 50,
) -> List[CatalogMissionEvent]:
    rows = session.exec(
        select(CatalogMissionEvent)
        .where(CatalogMissionEvent.catalog_mission_id == catalog_mission_id)
        .order_by(CatalogMissionEvent.created_at_utc.desc())
        .limit(max(1, min(limit, 200)))
    ).all()
    return list(rows)


def list_recent_reconcile_runs(
    session: Session,
    *,
    limit: int = 20,
) -> List[CatalogReconcileRun]:
    rows = session.exec(
        select(CatalogReconcileRun)
        .order_by(CatalogReconcileRun.started_at_utc.desc())
        .limit(max(1, min(limit, 100)))
    ).all()
    return list(rows)


def event_to_dict(event: CatalogMissionEvent) -> Dict[str, Any]:
    return {
        "id": event.id,
        "catalog_mission_id": event.catalog_mission_id,
        "event_type": event.event_type,
        "actor": event.actor,
        "source": event.source,
        "before": event.before_json,
        "after": event.after_json,
        "message": event.message,
        "created_at_utc": (
            event.created_at_utc.isoformat() if event.created_at_utc else None
        ),
    }


def reconcile_run_to_dict(run: CatalogReconcileRun) -> Dict[str, Any]:
    return {
        "id": run.id,
        "started_at_utc": (
            run.started_at_utc.isoformat() if run.started_at_utc else None
        ),
        "finished_at_utc": (
            run.finished_at_utc.isoformat() if run.finished_at_utc else None
        ),
        "trigger": run.trigger,
        "dry_run": run.dry_run,
        "status": run.status,
        "gate_clean": run.gate_clean,
        "counts": run.counts_json,
        "provision_acted": run.provision_acted,
        "provision_errors": run.provision_errors,
        "final_sync_acted": run.final_sync_acted,
        "final_sync_errors": run.final_sync_errors,
        "summary": run.summary,
        "actor": run.actor,
    }


# Re-export event type constants for callers
EVENT_ENROLLMENT = CatalogMissionEventType.ENROLLMENT_OVERRIDE.value
EVENT_SYNC_POLICY = CatalogMissionEventType.SYNC_POLICY.value
EVENT_STATE = CatalogMissionEventType.OPERATIONAL_STATE.value
EVENT_PROVISION = CatalogMissionEventType.PROVISION.value
EVENT_LIVE_LINK = CatalogMissionEventType.LIVE_LINK.value
EVENT_FINAL_SYNC = CatalogMissionEventType.FINAL_SYNC.value
EVENT_RECONCILE = CatalogMissionEventType.RECONCILE.value
