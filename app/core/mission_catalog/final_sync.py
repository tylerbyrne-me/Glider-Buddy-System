"""Bounded durable final-sync work items for completed catalog missions."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.config import settings
from app.core.mission_catalog.audit import (
    EVENT_FINAL_SYNC,
    record_mission_event,
)
from app.core.models.database import (
    CatalogMission,
    CatalogMissionSource,
    CatalogMissionWorkItem,
    CatalogPlatform,
    MissionOverview,
    SlocumDeployment,
)
from app.core.models.enums import (
    CatalogMatchStatus,
    CatalogOperationalState,
    CatalogSourceVariant,
    CatalogWorkItemStatus,
    CatalogWorkItemType,
)

logger = logging.getLogger(__name__)

WORK_TYPE = CatalogWorkItemType.FINAL_SYNC.value


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _max_attempts() -> int:
    return max(1, int(getattr(settings, "mission_catalog_final_sync_max_attempts", 10)))


def _max_age_days() -> int:
    return max(1, int(getattr(settings, "mission_catalog_final_sync_max_age_days", 14)))


def _batch_limit() -> int:
    return max(1, int(getattr(settings, "mission_catalog_final_sync_batch_limit", 5)))


def _backoff_seconds(attempts: int) -> int:
    # 2^attempts minutes, capped at 6 hours
    minutes = min(360, 2 ** max(0, attempts))
    return int(minutes * 60)


def ensure_final_sync_work_item(
    session: Session,
    mission: CatalogMission,
    *,
    actor: str = "scheduler",
    dry_run: bool = False,
) -> Optional[CatalogMissionWorkItem]:
    """Create or reset a final_sync work item when ST first completes a mission."""
    if mission.operational_state != CatalogOperationalState.COMPLETED.value:
        return None
    existing = session.exec(
        select(CatalogMissionWorkItem).where(
            CatalogMissionWorkItem.catalog_mission_id == mission.id,
            CatalogMissionWorkItem.work_type == WORK_TYPE,
        )
    ).first()
    if existing is not None:
        if existing.status in (
            CatalogWorkItemStatus.DONE.value,
            CatalogWorkItemStatus.PENDING.value,
            CatalogWorkItemStatus.RUNNING.value,
        ):
            return existing
        # Failed/exhausted: leave for manual retry unless freshly completed again
        return existing

    if dry_run:
        return None

    item = CatalogMissionWorkItem(
        catalog_mission_id=mission.id,
        work_type=WORK_TYPE,
        status=CatalogWorkItemStatus.PENDING.value,
        attempts=0,
        max_attempts=_max_attempts(),
        next_retry_at_utc=_utcnow(),
        created_at_utc=_utcnow(),
        updated_at_utc=_utcnow(),
    )
    session.add(item)
    session.flush()
    record_mission_event(
        session,
        catalog_mission_id=mission.id,
        event_type=EVENT_FINAL_SYNC,
        actor=actor,
        source="final_sync",
        after={"status": item.status, "work_item_id": item.id},
        message="final_sync_enqueued",
    )
    return item


def request_final_sync_retry(
    session: Session,
    mission_id: str,
    *,
    actor: str = "operator",
) -> CatalogMissionWorkItem:
    item = session.exec(
        select(CatalogMissionWorkItem).where(
            CatalogMissionWorkItem.catalog_mission_id == mission_id,
            CatalogMissionWorkItem.work_type == WORK_TYPE,
        )
    ).first()
    if item is None:
        mission = session.get(CatalogMission, mission_id)
        if mission is None:
            raise ValueError("Catalog mission not found")
        item = CatalogMissionWorkItem(
            catalog_mission_id=mission_id,
            work_type=WORK_TYPE,
            status=CatalogWorkItemStatus.PENDING.value,
            attempts=0,
            max_attempts=_max_attempts(),
            next_retry_at_utc=_utcnow(),
            created_at_utc=_utcnow(),
            updated_at_utc=_utcnow(),
        )
        session.add(item)
    else:
        item.status = CatalogWorkItemStatus.PENDING.value
        item.next_retry_at_utc = _utcnow()
        item.last_error = None
        item.updated_at_utc = _utcnow()
        # Manual retry resets exhaustion but keeps attempt count for audit.
        if item.attempts >= item.max_attempts:
            item.max_attempts = item.attempts + _max_attempts()
        session.add(item)
    session.flush()
    record_mission_event(
        session,
        catalog_mission_id=mission_id,
        event_type=EVENT_FINAL_SYNC,
        actor=actor,
        source="team_api",
        after={"status": item.status, "work_item_id": item.id},
        message="final_sync_manual_retry",
    )
    session.commit()
    session.refresh(item)
    return item


def _fresh_sources(
    session: Session,
    mission_id: str,
    *,
    source_kind: str,
) -> List[CatalogMissionSource]:
    rows = list(
        session.exec(
            select(CatalogMissionSource).where(
                CatalogMissionSource.mission_id == mission_id,
                CatalogMissionSource.source_kind == source_kind,
                CatalogMissionSource.enabled == True,  # noqa: E712
            )
        ).all()
    )
    return [
        s
        for s in rows
        if (s.match_status or "").lower()
        not in (
            CatalogMatchStatus.STALE.value,
            CatalogMatchStatus.CONFLICT.value,
        )
    ]


def _platform_family(session: Session, mission: CatalogMission) -> str:
    if not mission.platform_id:
        return ""
    platform = session.get(CatalogPlatform, mission.platform_id)
    return ((platform.platform_family if platform else "") or "").strip().lower()


async def _run_wave_glider_final_sync(
    session: Session,
    mission: CatalogMission,
) -> Dict[str, Any]:
    from app.core.sync_service import sync_past_mission

    overviews = list(
        session.exec(
            select(MissionOverview).where(
                MissionOverview.catalog_mission_id == mission.id
            )
        ).all()
    )
    if not overviews:
        return {"ok": False, "error": "no_overview", "retryable": True}

    sources = _fresh_sources(session, mission.id, source_kind="wgms_remote")
    past = [
        s
        for s in sources
        if "past" in (s.collection or "").lower()
        or (s.source_variant or "").lower()
        in (CatalogSourceVariant.DELAYED.value, "past")
    ]
    if not past:
        return {"ok": False, "error": "waiting_for_past_source", "retryable": True}

    mission_id = overviews[0].mission_id
    synced, errors = await sync_past_mission(mission_id)
    if errors:
        return {
            "ok": False,
            "error": f"sync_past_errors={errors}",
            "retryable": True,
            "synced": synced,
        }
    return {"ok": True, "synced": synced, "mission_id": mission_id}


async def _run_slocum_final_sync(
    session: Session,
    mission: CatalogMission,
) -> Dict[str, Any]:
    from app.platforms.slocum.mirror_service import sync_dataset_mirror

    deployments = list(
        session.exec(
            select(SlocumDeployment).where(
                SlocumDeployment.catalog_mission_id == mission.id
            )
        ).all()
    )
    if not deployments:
        return {"ok": False, "error": "no_slocum_deployment", "retryable": True}

    sources = _fresh_sources(session, mission.id, source_kind="erddap")
    delayed = [
        s
        for s in sources
        if (s.source_variant or "").lower() == CatalogSourceVariant.DELAYED.value
        or "delayed" in (s.external_ref or "").lower()
    ]
    realtime = [
        s
        for s in sources
        if (s.source_variant or "").lower() == CatalogSourceVariant.REALTIME.value
        or "realtime" in (s.external_ref or "").lower()
    ]

    # Prefer delayed dataset when present; otherwise bounded incremental on linked row.
    preferred_ref: Optional[str] = None
    if delayed:
        preferred_ref = (delayed[0].external_ref or "").strip() or None
    elif realtime:
        preferred_ref = (realtime[0].external_ref or "").strip() or None

    deployment = deployments[0]
    dataset_id = preferred_ref or (deployment.erddap_dataset_id or "").strip()
    if not dataset_id:
        return {"ok": False, "error": "missing_dataset_id", "retryable": True}

    if preferred_ref and deployment.erddap_dataset_id != preferred_ref:
        deployment.erddap_dataset_id = preferred_ref
        deployment.updated_at_utc = _utcnow()
        session.add(deployment)
        session.flush()

    # Bounded: use warm hours window, never unbounded historical pull.
    hours = int(getattr(settings, "slocum_warm_hours", 24) or 24)
    result = await sync_dataset_mirror(dataset_id, hours_back=hours)
    if isinstance(result, dict) and result.get("error"):
        return {
            "ok": False,
            "error": str(result.get("error")),
            "retryable": True,
            "result": result,
        }
    return {"ok": True, "dataset_id": dataset_id, "result": result}


async def process_final_sync_work_item(
    session: Session,
    item: CatalogMissionWorkItem,
    *,
    actor: str = "scheduler",
) -> Dict[str, Any]:
    mission = session.get(CatalogMission, item.catalog_mission_id)
    if mission is None:
        item.status = CatalogWorkItemStatus.EXHAUSTED.value
        item.last_error = "mission_missing"
        item.updated_at_utc = _utcnow()
        session.add(item)
        session.commit()
        return {"ok": False, "error": "mission_missing"}

    # Completion lifecycle must remain completed even if final sync fails.
    age_limit = _utcnow() - timedelta(days=_max_age_days())
    if item.created_at_utc and item.created_at_utc.replace(tzinfo=timezone.utc) < age_limit:
        item.status = CatalogWorkItemStatus.EXHAUSTED.value
        item.last_error = "max_age_exceeded"
        item.updated_at_utc = _utcnow()
        session.add(item)
        record_mission_event(
            session,
            catalog_mission_id=mission.id,
            event_type=EVENT_FINAL_SYNC,
            actor=actor,
            source="final_sync",
            after={"status": item.status},
            message="final_sync_exhausted_age",
        )
        session.commit()
        return {"ok": False, "error": "max_age_exceeded"}

    item.status = CatalogWorkItemStatus.RUNNING.value
    item.attempts = int(item.attempts or 0) + 1
    item.last_attempt_at_utc = _utcnow()
    item.updated_at_utc = _utcnow()
    session.add(item)
    session.commit()

    family = _platform_family(session, mission)
    try:
        if family in ("wave_glider", "wg", "wave"):
            outcome = await _run_wave_glider_final_sync(session, mission)
        elif family == "slocum":
            outcome = await _run_slocum_final_sync(session, mission)
        else:
            outcome = {
                "ok": False,
                "error": f"unsupported_family:{family or 'unknown'}",
                "retryable": False,
            }
    except Exception as exc:
        logger.exception("Final sync failed for %s", mission.id)
        outcome = {"ok": False, "error": str(exc), "retryable": True}

    item.result_json = {
        k: v for k, v in outcome.items() if k != "result" or isinstance(v, (dict, list, str, int, float, bool, type(None)))
    }
    item.updated_at_utc = _utcnow()
    if outcome.get("ok"):
        item.status = CatalogWorkItemStatus.DONE.value
        item.last_error = None
        item.next_retry_at_utc = None
        message = "final_sync_done"
    else:
        item.last_error = str(outcome.get("error") or "unknown")
        retryable = bool(outcome.get("retryable", True))
        if (not retryable) or item.attempts >= int(item.max_attempts or _max_attempts()):
            item.status = CatalogWorkItemStatus.EXHAUSTED.value
            message = "final_sync_exhausted"
        else:
            item.status = CatalogWorkItemStatus.FAILED.value
            item.next_retry_at_utc = _utcnow() + timedelta(
                seconds=_backoff_seconds(item.attempts)
            )
            message = "final_sync_failed_retryable"
    session.add(item)
    record_mission_event(
        session,
        catalog_mission_id=mission.id,
        event_type=EVENT_FINAL_SYNC,
        actor=actor,
        source="final_sync",
        after={
            "status": item.status,
            "attempts": item.attempts,
            "error": item.last_error,
        },
        message=message,
    )
    session.commit()
    session.refresh(item)
    return outcome


async def process_due_final_sync_work_items(
    session: Session,
    *,
    actor: str = "scheduler",
    limit: Optional[int] = None,
) -> Dict[str, int]:
    now = _utcnow()
    cap = limit if limit is not None else _batch_limit()
    due = list(
        session.exec(
            select(CatalogMissionWorkItem)
            .where(
                CatalogMissionWorkItem.work_type == WORK_TYPE,
                CatalogMissionWorkItem.status.in_(
                    [
                        CatalogWorkItemStatus.PENDING.value,
                        CatalogWorkItemStatus.FAILED.value,
                    ]
                ),
            )
            .order_by(CatalogMissionWorkItem.next_retry_at_utc.asc())
            .limit(cap * 3)
        ).all()
    )
    acted = 0
    errors = 0
    for item in due:
        if acted >= cap:
            break
        nxt = item.next_retry_at_utc
        if nxt is not None:
            if nxt.tzinfo is None:
                nxt = nxt.replace(tzinfo=timezone.utc)
            if nxt > now:
                continue
        outcome = await process_final_sync_work_item(session, item, actor=actor)
        acted += 1
        if not outcome.get("ok"):
            errors += 1
    return {"acted": acted, "errors": errors}


def work_item_to_dict(item: Optional[CatalogMissionWorkItem]) -> Optional[Dict[str, Any]]:
    if item is None:
        return None
    return {
        "id": item.id,
        "catalog_mission_id": item.catalog_mission_id,
        "work_type": item.work_type,
        "status": item.status,
        "attempts": item.attempts,
        "max_attempts": item.max_attempts,
        "next_retry_at_utc": (
            item.next_retry_at_utc.isoformat() if item.next_retry_at_utc else None
        ),
        "last_attempt_at_utc": (
            item.last_attempt_at_utc.isoformat() if item.last_attempt_at_utc else None
        ),
        "last_error": item.last_error,
        "result": item.result_json,
        "created_at_utc": (
            item.created_at_utc.isoformat() if item.created_at_utc else None
        ),
        "updated_at_utc": (
            item.updated_at_utc.isoformat() if item.updated_at_utc else None
        ),
    }


def get_final_sync_work_item(
    session: Session, catalog_mission_id: str
) -> Optional[CatalogMissionWorkItem]:
    return session.exec(
        select(CatalogMissionWorkItem).where(
            CatalogMissionWorkItem.catalog_mission_id == catalog_mission_id,
            CatalogMissionWorkItem.work_type == WORK_TYPE,
        )
    ).first()
