"""
Persist and refresh SFMC-derived checklist autofill per Slocum deployment.

One snapshot row per deployment is upserted by a leader-only background job
(and by the pilot-facing force-refresh endpoint). Checklist template reads
prefer the cache so page loads do not wait on live SFMC HTTP.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from . import models
from .sfmc_client import load_sfmc_checklist_values, sfmc_is_configured
from .sfmc_transforms import merge_connection_durations, normalize_dmon_asc_files
from app.platforms.slocum.mirror_service import is_historical_dataset

logger = logging.getLogger(__name__)

_CONNECTION_DURATIONS_KEY = "connection_durations"
_CONNECTION_DURATIONS_MAX_DAYS = 90
_DMON_ASC_FILES_KEY = "dmon_asc_files"


def _deployment_linked_to_historical(deployment: models.SlocumDeployment) -> bool:
    """True when this briefing points at a config-listed historical ERDDAP mission."""
    if deployment.erddap_dataset_id and is_historical_dataset(deployment.erddap_dataset_id):
        return True
    if deployment.mission_key and is_historical_dataset(deployment.mission_key):
        return True
    return False

def _parse_values_json(raw: Optional[str]) -> dict[str, Any]:
    if not raw or not str(raw).strip():
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if key == _CONNECTION_DURATIONS_KEY:
            if isinstance(value, list):
                out[key] = value
            elif isinstance(value, str) and value.strip():
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        out[key] = parsed
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass
            continue
        if key == _DMON_ASC_FILES_KEY:
            if isinstance(value, dict):
                out[key] = value
            elif isinstance(value, list):
                # Legacy / raw entry list → normalize
                out[key] = normalize_dmon_asc_files(value)
            elif isinstance(value, str) and value.strip():
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, dict):
                        out[key] = parsed
                    elif isinstance(parsed, list):
                        out[key] = normalize_dmon_asc_files(parsed)
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass
            continue
        text = str(value).strip()
        if text:
            out[str(key)] = text
    return out


def _dump_values_json(values: dict[str, Any]) -> str:
    cleaned: dict[str, Any] = {}
    for key, value in (values or {}).items():
        if value is None:
            continue
        if key == _CONNECTION_DURATIONS_KEY:
            if isinstance(value, list):
                cleaned[key] = value
            continue
        if key == _DMON_ASC_FILES_KEY:
            if isinstance(value, dict):
                cleaned[key] = value
            elif isinstance(value, list):
                cleaned[key] = normalize_dmon_asc_files(value)
            continue
        text = str(value).strip()
        if text:
            cleaned[str(key)] = text
    return json.dumps(cleaned, ensure_ascii=True, sort_keys=True)


def get_cached_sfmc_values(
    session: Session,
    deployment_id: Optional[int],
) -> tuple[dict[str, Any], Optional[datetime], Optional[str]]:
    """
    Return ``(values, fetched_at_utc, fetch_error)`` for a deployment.

    Missing row → ``({}, None, None)``.
    """
    if deployment_id is None:
        return {}, None, None
    row = session.exec(
        select(models.SlocumSfmcSnapshot).where(
            models.SlocumSfmcSnapshot.deployment_id == deployment_id
        )
    ).first()
    if row is None:
        return {}, None, None
    return _parse_values_json(row.values_json), row.fetched_at_utc, row.fetch_error


def get_cached_connection_durations(
    session: Session,
    deployment_id: Optional[int],
) -> tuple[list[dict[str, Any]], Optional[datetime], Optional[str], bool]:
    """
    Return ``(durations, fetched_at_utc, fetch_error, sfmc_configured)``.
    """
    configured = sfmc_is_configured()
    values, fetched_at, fetch_error = get_cached_sfmc_values(session, deployment_id)
    durations = values.get(_CONNECTION_DURATIONS_KEY) if isinstance(values, dict) else None
    if not isinstance(durations, list):
        durations = []
    return durations, fetched_at, fetch_error, configured


def get_cached_dmon_asc_files(
    session: Session,
    deployment_id: Optional[int],
) -> tuple[dict[str, Any], Optional[datetime], Optional[str], bool]:
    """
    Return ``(dmon_asc_payload, fetched_at_utc, fetch_error, sfmc_configured)``.

    ``dmon_asc_payload`` is the normalized dict from ``normalize_dmon_asc_files``
    (or empty dict when missing).
    """
    configured = sfmc_is_configured()
    values, fetched_at, fetch_error = get_cached_sfmc_values(session, deployment_id)
    payload = values.get(_DMON_ASC_FILES_KEY) if isinstance(values, dict) else None
    if not isinstance(payload, dict):
        payload = {}
    return payload, fetched_at, fetch_error, configured


def _get_or_create_snapshot(
    session: Session,
    deployment: models.SlocumDeployment,
) -> models.SlocumSfmcSnapshot:
    row = session.exec(
        select(models.SlocumSfmcSnapshot).where(
            models.SlocumSfmcSnapshot.deployment_id == deployment.id
        )
    ).first()
    if row is not None:
        return row
    row = models.SlocumSfmcSnapshot(
        deployment_id=int(deployment.id),
        glider_name=(deployment.glider_name or "").strip(),
        values_json="{}",
        fetched_at_utc=None,
        fetch_error=None,
        updated_at_utc=datetime.now(timezone.utc),
    )
    session.add(row)
    session.flush()
    return row


async def refresh_sfmc_snapshot(
    session: Session,
    deployment: models.SlocumDeployment,
) -> models.SlocumSfmcSnapshot:
    """
    Fetch live SFMC checklist values and upsert the deployment snapshot.

    On failure, records ``fetch_error`` and keeps the previous ``values_json``
    (last-known-good). Caller is responsible for committing when desired.
    Connection durations are merged with prior history (capped to ~90 days).
    """
    glider = (deployment.glider_name or "").strip()
    row = _get_or_create_snapshot(session, deployment)
    row.glider_name = glider
    row.updated_at_utc = datetime.now(timezone.utc)

    if not glider:
        row.fetch_error = "Deployment has no glider_name"
        session.add(row)
        session.commit()
        session.refresh(row)
        return row

    # Placeholder / sandbox briefings are not SFMC vehicles (legacy local "Testing" row).
    if glider.lower() in {"testing", "test", "dummy"}:
        row.fetch_error = f"Skipping SFMC for placeholder glider_name={glider!r}"
        session.add(row)
        session.commit()
        session.refresh(row)
        return row

    if not (deployment.erddap_dataset_id or "").strip():
        row.fetch_error = "Skipping SFMC: deployment has no erddap_dataset_id"
        session.add(row)
        session.commit()
        session.refresh(row)
        return row

    if not sfmc_is_configured():
        row.fetch_error = "SFMC is not configured"
        session.add(row)
        session.commit()
        session.refresh(row)
        return row

    try:
        values = await load_sfmc_checklist_values(glider)
        previous = _parse_values_json(row.values_json)
        incoming_durations = values.pop(_CONNECTION_DURATIONS_KEY, None) if isinstance(values, dict) else None
        incoming_dmon_asc = values.pop(_DMON_ASC_FILES_KEY, None) if isinstance(values, dict) else None
        merged_durations = merge_connection_durations(
            previous.get(_CONNECTION_DURATIONS_KEY),
            incoming_durations,
            max_days=_CONNECTION_DURATIONS_MAX_DAYS,
        )
        payload = dict(values or {})
        if merged_durations:
            payload[_CONNECTION_DURATIONS_KEY] = merged_durations
        elif previous.get(_CONNECTION_DURATIONS_KEY):
            payload[_CONNECTION_DURATIONS_KEY] = previous.get(_CONNECTION_DURATIONS_KEY)
        # ASC listing is a rolling window — replace on each successful refresh.
        if isinstance(incoming_dmon_asc, dict):
            payload[_DMON_ASC_FILES_KEY] = incoming_dmon_asc
        elif isinstance(incoming_dmon_asc, list):
            payload[_DMON_ASC_FILES_KEY] = normalize_dmon_asc_files(incoming_dmon_asc)
        elif previous.get(_DMON_ASC_FILES_KEY):
            payload[_DMON_ASC_FILES_KEY] = previous.get(_DMON_ASC_FILES_KEY)
        row.values_json = _dump_values_json(payload)
        row.fetched_at_utc = datetime.now(timezone.utc)
        row.fetch_error = None
    except Exception as err:
        logger.warning(
            "SFMC snapshot refresh failed for deployment %s (%s): %s",
            deployment.id,
            glider,
            err,
        )
        # Keep previous values_json; surface the error for UI freshness notes.
        row.fetch_error = str(err)[:2000]
        row.updated_at_utc = datetime.now(timezone.utc)

    session.add(row)
    session.commit()
    session.refresh(row)
    return row


async def refresh_all_active_sfmc_snapshots(session: Session) -> dict[str, Any]:
    """
    Refresh SFMC snapshots for every non-soft-deleted deployment with a glider name.

    Skips deployments linked to config historical datasets.
    Per-deployment failures are isolated. Returns summary counts.
    """
    if not sfmc_is_configured():
        return {
            "skipped": True,
            "reason": "sfmc_not_configured",
            "attempted": 0,
            "succeeded": 0,
            "failed": 0,
        }

    deployments = session.exec(
        select(models.SlocumDeployment).where(
            models.SlocumDeployment.is_active == True  # noqa: E712
        )
    ).all()

    attempted = 0
    succeeded = 0
    failed = 0
    for deployment in deployments:
        if _deployment_linked_to_historical(deployment):
            continue
        glider = (deployment.glider_name or "").strip()
        if not glider or glider.lower() in {"testing", "test", "dummy"}:
            continue
        if not (deployment.erddap_dataset_id or "").strip():
            continue
        attempted += 1
        try:
            row = await refresh_sfmc_snapshot(session, deployment)
            if row.fetch_error:
                failed += 1
            else:
                succeeded += 1
        except Exception as err:
            failed += 1
            logger.warning(
                "SFMC snapshot job failed for deployment %s (%s): %s",
                getattr(deployment, "id", None),
                glider,
                err,
            )

    return {
        "skipped": False,
        "attempted": attempted,
        "succeeded": succeeded,
        "failed": failed,
    }
