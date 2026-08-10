"""
Scheduler Management Module

Provides access to the APScheduler instance without circular dependencies.
The scheduler is initialized in app.py and registered here for access.

Also tracks last-run outcomes for admin scheduler status (in-memory + disk).
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_SUBMITTED, JobEvent
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.core.models.enums import JobPlatformEnum, JobRunOutcomeEnum, JobStatusEnum
from app.core.utils import (
    project_root,
    replace_path_with_retries,
    unique_sibling_tmp_path,
)

logger = logging.getLogger(__name__)

# Global scheduler instance - will be set by app.py during startup
_scheduler: Optional[AsyncIOScheduler] = None

# Explicit platform catalog for admin scheduler UI (source of truth for known jobs).
JOB_PLATFORM_BY_ID: dict[str, JobPlatformEnum] = {
    "wave_glider_active_mission_refresh_job": JobPlatformEnum.WAVE_GLIDER,
    "wave_glider_weekly_report_job": JobPlatformEnum.WAVE_GLIDER,
    "slocum_warm_cache_job": JobPlatformEnum.SLOCUM,
    "slocum_weekly_report_job": JobPlatformEnum.SLOCUM,
    "slocum_overage_cleanup_job": JobPlatformEnum.SLOCUM,
    "slocum_sfmc_cache_refresh_job": JobPlatformEnum.SLOCUM,
    "slocum_auto_checklist_submit_job": JobPlatformEnum.SLOCUM,
    "system_weather_map_prefetch_job": JobPlatformEnum.SYSTEM,
    "system_weather_map_cleanup_job": JobPlatformEnum.SYSTEM,
    "system_bathy_cache_cleanup_job": JobPlatformEnum.SYSTEM,
    "system_iridium_tle_prefetch_job": JobPlatformEnum.SYSTEM,
    "system_iridium_tle_cleanup_job": JobPlatformEnum.SYSTEM,
    "system_navwarn_prefetch_job": JobPlatformEnum.SYSTEM,
    "system_navwarn_cleanup_job": JobPlatformEnum.SYSTEM,
    "system_dmon_review_prefetch_job": JobPlatformEnum.SYSTEM,
}

_OUTCOMES_FILENAME = "scheduler_job_outcomes.json"
_outcomes_lock = threading.RLock()
_outcomes: dict[str, "JobOutcomeRecord"] = {}
_active_runs: dict[str, datetime] = {}  # job_id -> scheduled_run_time for in-flight run
_listeners_attached = False
_outcomes_loaded = False


@dataclass
class JobOutcomeRecord:
    """Latest recorded execution result for a scheduled job."""

    outcome: str
    message: Optional[str] = None
    run_at: Optional[str] = None  # ISO UTC
    scheduled_run_time: Optional[str] = None  # ISO UTC
    source: str = "self"  # self | listener
    counts: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload.get("counts") is None:
            payload.pop("counts", None)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JobOutcomeRecord":
        return cls(
            outcome=str(data.get("outcome") or JobRunOutcomeEnum.ERROR.value),
            message=data.get("message"),
            run_at=data.get("run_at"),
            scheduled_run_time=data.get("scheduled_run_time"),
            source=str(data.get("source") or "self"),
            counts=data.get("counts") if isinstance(data.get("counts"), dict) else None,
        )


def resolve_job_platform(job_id: str) -> JobPlatformEnum:
    """Resolve a job's platform from the catalog, then ID prefix fallback."""
    known = JOB_PLATFORM_BY_ID.get(job_id)
    if known is not None:
        return known

    job_id_str = str(job_id or "")
    if job_id_str.startswith("system_"):
        return JobPlatformEnum.SYSTEM
    if job_id_str.startswith("slocum_"):
        return JobPlatformEnum.SLOCUM
    if job_id_str.startswith("wave_glider_"):
        return JobPlatformEnum.WAVE_GLIDER
    return JobPlatformEnum.SYSTEM


def set_scheduler(scheduler: AsyncIOScheduler) -> None:
    """
    Register the scheduler instance.
    Called by app.py during startup.

    Args:
        scheduler: The AsyncIOScheduler instance
    """
    global _scheduler
    _scheduler = scheduler


def get_scheduler() -> AsyncIOScheduler:
    """
    Get the scheduler instance.

    Returns:
        The AsyncIOScheduler instance

    Raises:
        RuntimeError: If scheduler has not been initialized
    """
    if _scheduler is None:
        raise RuntimeError("Scheduler has not been initialized. This should be set during app startup.")
    return _scheduler


def _outcomes_path() -> Path:
    return project_root() / "data_store" / _OUTCOMES_FILENAME


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ensure_outcomes_loaded() -> None:
    global _outcomes_loaded
    with _outcomes_lock:
        if _outcomes_loaded:
            return
        path = _outcomes_path()
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                jobs = raw.get("jobs") if isinstance(raw, dict) else None
                if isinstance(jobs, dict):
                    for job_id, payload in jobs.items():
                        if isinstance(payload, dict):
                            _outcomes[str(job_id)] = JobOutcomeRecord.from_dict(payload)
            except Exception as exc:
                logger.warning("Failed to load scheduler job outcomes: %s", exc)
        _outcomes_loaded = True


def _persist_outcomes_unlocked() -> None:
    path = _outcomes_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": _to_iso(_utcnow()),
            "jobs": {job_id: record.to_dict() for job_id, record in _outcomes.items()},
        }
        tmp_path = unique_sibling_tmp_path(path)
        try:
            with tmp_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
                handle.flush()
            replace_path_with_retries(tmp_path, path)
        except Exception:
            try:
                if tmp_path.is_file():
                    tmp_path.unlink()
            except OSError:
                pass
            raise
    except Exception as exc:
        logger.warning("Failed to persist scheduler job outcomes: %s", exc)


def get_job_outcome(job_id: str) -> Optional[JobOutcomeRecord]:
    """Return the latest stored outcome for a job, if any."""
    _ensure_outcomes_loaded()
    with _outcomes_lock:
        return _outcomes.get(job_id)


def record_job_outcome(
    job_id: str,
    outcome: str | JobRunOutcomeEnum,
    message: Optional[str] = None,
    counts: Optional[dict[str, Any]] = None,
    *,
    source: str = "self",
    scheduled_run_time: Optional[datetime] = None,
) -> JobOutcomeRecord:
    """
    Record the latest run outcome for a job.

    Jobs should call this on every exit path. APScheduler listeners also call it
    for uncaught errors and for jobs that do not self-report.
    """
    _ensure_outcomes_loaded()
    outcome_value = (
        outcome.value if isinstance(outcome, JobRunOutcomeEnum) else str(outcome or "").strip().lower()
    )
    if outcome_value not in {e.value for e in JobRunOutcomeEnum}:
        outcome_value = JobRunOutcomeEnum.ERROR.value

    with _outcomes_lock:
        active_scheduled = scheduled_run_time or _active_runs.get(job_id)
        record = JobOutcomeRecord(
            outcome=outcome_value,
            message=message,
            run_at=_to_iso(_utcnow()),
            scheduled_run_time=_to_iso(active_scheduled),
            source=source,
            counts=counts,
        )
        _outcomes[job_id] = record
        _persist_outcomes_unlocked()
        return record


def derive_job_status(
    *,
    next_run_time: Optional[datetime],
    now: Optional[datetime] = None,
    outcome: Optional[JobOutcomeRecord] = None,
) -> JobStatusEnum:
    """
    Compose admin badge status from schedule timing + last-run outcome.

    Priority: overdue > failed > warning > never_run > ok
    """
    now_utc = now or _utcnow()
    if next_run_time is not None:
        nrt = next_run_time
        if nrt.tzinfo is None:
            nrt = nrt.replace(tzinfo=timezone.utc)
        if nrt < now_utc:
            return JobStatusEnum.OVERDUE

    if outcome is None:
        return JobStatusEnum.NEVER_RUN

    outcome_value = (outcome.outcome or "").lower()
    if outcome_value in (JobRunOutcomeEnum.FAILED.value, JobRunOutcomeEnum.ERROR.value):
        return JobStatusEnum.FAILED
    if outcome_value == JobRunOutcomeEnum.PARTIAL.value:
        return JobStatusEnum.WARNING
    # success, skipped (and any unknown treated as ok once recorded)
    return JobStatusEnum.OK


def _on_job_submitted(event: JobEvent) -> None:
    job_id = getattr(event, "job_id", None)
    scheduled = getattr(event, "scheduled_run_time", None)
    if not job_id:
        return
    with _outcomes_lock:
        if isinstance(scheduled, datetime):
            if scheduled.tzinfo is None:
                scheduled = scheduled.replace(tzinfo=timezone.utc)
            _active_runs[str(job_id)] = scheduled.astimezone(timezone.utc)
        else:
            _active_runs[str(job_id)] = _utcnow()


def _outcome_covers_run(existing: JobOutcomeRecord, scheduled: Optional[datetime]) -> bool:
    """True if an existing self-reported outcome already covers this scheduled run."""
    if existing.source != "self":
        return False
    if scheduled is None:
        return True
    existing_sched = _parse_iso(existing.scheduled_run_time)
    if existing_sched is not None and existing_sched == scheduled.astimezone(timezone.utc):
        return True
    run_at = _parse_iso(existing.run_at)
    if run_at is None:
        return False
    scheduled_utc = scheduled.astimezone(timezone.utc)
    return run_at >= scheduled_utc and (run_at - scheduled_utc).total_seconds() < 6 * 3600


def _on_job_executed(event: JobEvent) -> None:
    job_id = getattr(event, "job_id", None)
    if not job_id:
        return
    job_id = str(job_id)
    scheduled = getattr(event, "scheduled_run_time", None)
    if isinstance(scheduled, datetime) and scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=timezone.utc)

    _ensure_outcomes_loaded()
    with _outcomes_lock:
        existing = _outcomes.get(job_id)
        if existing and _outcome_covers_run(existing, scheduled if isinstance(scheduled, datetime) else None):
            _active_runs.pop(job_id, None)
            return
        _active_runs.pop(job_id, None)

    record_job_outcome(
        job_id,
        JobRunOutcomeEnum.SUCCESS,
        message="Completed without self-reported outcome",
        source="listener",
        scheduled_run_time=scheduled if isinstance(scheduled, datetime) else None,
    )


def _on_job_error(event: JobEvent) -> None:
    job_id = getattr(event, "job_id", None)
    if not job_id:
        return
    job_id = str(job_id)
    scheduled = getattr(event, "scheduled_run_time", None)
    if isinstance(scheduled, datetime) and scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=timezone.utc)
    exc = getattr(event, "exception", None)
    message = str(exc) if exc is not None else "Job raised an unhandled exception"
    record_job_outcome(
        job_id,
        JobRunOutcomeEnum.ERROR,
        message=message,
        source="listener",
        scheduled_run_time=scheduled if isinstance(scheduled, datetime) else None,
    )
    with _outcomes_lock:
        _active_runs.pop(job_id, None)


def attach_job_listeners(scheduler: AsyncIOScheduler) -> None:
    """Register APScheduler listeners that feed the outcome store (idempotent)."""
    global _listeners_attached
    _ensure_outcomes_loaded()
    if _listeners_attached:
        return
    scheduler.add_listener(_on_job_submitted, EVENT_JOB_SUBMITTED)
    scheduler.add_listener(_on_job_executed, EVENT_JOB_EXECUTED)
    scheduler.add_listener(_on_job_error, EVENT_JOB_ERROR)
    _listeners_attached = True
    logger.info("Scheduler job outcome listeners attached")


def reset_outcome_store_for_tests() -> None:
    """Clear in-memory outcome state (unit tests only)."""
    global _outcomes_loaded, _listeners_attached
    with _outcomes_lock:
        _outcomes.clear()
        _active_runs.clear()
        _outcomes_loaded = False
        _listeners_attached = False
