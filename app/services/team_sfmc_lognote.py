"""In-process SFMC log-note import for Team (and shared helpers for the CLI).

Resolves Slocum deployments via DB/services — no HTTP self-call and no CLI_ADMIN_*.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlmodel import Session as SQLModelSession, select

from app.cli import sfmc_lognote_import as cli
from app.core import models
from app.core.models.schemas import (
    SfmcLognoteImportResult,
    SfmcLognotePreviewItem,
)
from app.core.utils import parse_mission_note_datetime_prefix
from app.platforms.slocum.deployment_service import get_or_create_deployment_for_dataset


def _mission_window_from_db(
    session: SQLModelSession,
    *,
    dataset_id: str,
    deployment: models.SlocumDeployment,
) -> Tuple[Optional[date], Optional[date], str]:
    """Mirror CLI mission_window_from_info using DB rows."""
    from app.core import utils
    from app.core.mission_aliases import resolve_slocum_dataset_id

    resolved = resolve_slocum_dataset_id(dataset_id)
    parsed = utils.parse_slocum_dataset_id(resolved) if resolved else None
    mission_code = f"m{parsed['deployment_number']}" if parsed else None
    sensor = None
    if mission_code:
        sensor = session.exec(
            select(models.SensorTrackerDeployment).where(
                models.SensorTrackerDeployment.mission_id == mission_code
            )
        ).first()

    sensor_dict = {
        "start_time": getattr(sensor, "start_time", None) if sensor else None,
        "end_time": getattr(sensor, "end_time", None) if sensor else None,
    }
    deployment_dict = {"deployment_date": deployment.deployment_date}
    parsed_dict = {"start_date": parsed["start_date"] if parsed else None}
    payload = {
        "sensor_tracker_deployment": sensor_dict,
        "deployment": deployment_dict,
        "parsed_dataset": parsed_dict,
    }
    return cli.mission_window_from_info(payload)


def _existing_note_contents(
    session: SQLModelSession, deployment_id: int
) -> Set[str]:
    notes = session.exec(
        select(models.SlocumDeploymentNote).where(
            models.SlocumDeploymentNote.deployment_id == deployment_id
        )
    ).all()
    return {str(note.content or "") for note in notes if note.content}


def prepare_and_optionally_commit(
    *,
    session: SQLModelSession,
    username: str,
    alias: str,
    json_text: str,
    after: Optional[date] = None,
    before: Optional[date] = None,
    no_date_filter: bool = False,
    include_in_report: bool = True,
    dry_run: bool = True,
) -> SfmcLognoteImportResult:
    """Validate JSON, apply window/dedupe, dry-run or post notes in-process."""
    alias = (alias or "").strip()
    if not alias:
        return SfmcLognoteImportResult(
            alias=alias,
            dry_run=dry_run,
            success=False,
            error="Alias is required.",
            summary="Error: alias is required.",
        )
    if after and before and after > before:
        return SfmcLognoteImportResult(
            alias=alias,
            dry_run=dry_run,
            success=False,
            error=f"--after {after} is after --before {before}.",
            summary="Error: invalid date range.",
        )

    try:
        entries = cli.load_json_array(json_text, source="paste")
    except ValueError as exc:
        return SfmcLognoteImportResult(
            alias=alias,
            dry_run=dry_run,
            success=False,
            error=str(exc),
            summary=f"Error: {exc}",
        )

    if not entries:
        return SfmcLognoteImportResult(
            alias=alias,
            dry_run=dry_run,
            success=True,
            summary="No log notes found in input.",
        )

    loaded: List[Tuple[Dict[str, Any], str]] = [(e, "paste") for e in entries]
    loaded.sort(key=lambda item: cli.sort_key_creation(item[0]))

    # Batch dedupe (first wins) — collect skip items
    seen_ids: Set[int] = set()
    unique: List[Tuple[Dict[str, Any], str]] = []
    batch_dup_items: List[SfmcLognotePreviewItem] = []
    for entry, source in loaded:
        sfmc_id = int(entry["id"])
        if sfmc_id in seen_ids:
            batch_dup_items.append(
                SfmcLognotePreviewItem(
                    sfmc_id=sfmc_id,
                    content="",
                    action="skip_batch_dup",
                    reason="duplicate SFMC id in paste batch",
                )
            )
            continue
        seen_ids.add(sfmc_id)
        unique.append((entry, source))

    prepared: List[Tuple[Dict[str, Any], str, str]] = []
    for entry, source in unique:
        try:
            content = cli.format_note_content(entry)
        except ValueError as exc:
            return SfmcLognoteImportResult(
                alias=alias,
                dry_run=dry_run,
                success=False,
                error=f"Error formatting id={entry.get('id')}: {exc}",
                summary=f"Error formatting id={entry.get('id')}: {exc}",
            )
        if parse_mission_note_datetime_prefix(content) is None:
            return SfmcLognoteImportResult(
                alias=alias,
                dry_run=dry_run,
                success=False,
                error=f"Generated content failed prefix parse for id={entry.get('id')}",
                summary=f"Error: prefix parse failed for id={entry.get('id')}",
            )
        prepared.append((entry, source, content))

    deployment = get_or_create_deployment_for_dataset(
        session,
        alias,
        created_by_username=username,
    )
    if not deployment:
        return SfmcLognoteImportResult(
            alias=alias,
            dry_run=dry_run,
            success=False,
            error=f"No Slocum deployment for alias {alias!r}.",
            summary=f"Error: cannot resolve deployment for {alias!r}.",
        )

    existing_contents = _existing_note_contents(session, deployment.id)

    window_start: Optional[date] = None
    window_end: Optional[date] = None
    window_source = "disabled"
    if no_date_filter:
        window_source = "disabled (no_date_filter)"
    else:
        auto_start, auto_end, auto_source = _mission_window_from_db(
            session, dataset_id=alias, deployment=deployment
        )
        window_start = after if after is not None else auto_start
        window_end = before if before is not None else auto_end
        parts: List[str] = []
        if after is not None:
            parts.append("after override")
        elif auto_start is not None:
            parts.append(auto_source.split("+")[0] if auto_source != "none" else "auto-start")
        if before is not None:
            parts.append("before override")
        elif auto_end is not None:
            parts.append("sensor_tracker.end_time")
        window_source = "+".join(parts) if parts else "none"

    items: List[SfmcLognotePreviewItem] = list(batch_dup_items)
    to_post: List[Tuple[Dict[str, Any], str]] = []
    out_of_range = 0
    server_dup = 0

    for entry, _source, content in prepared:
        sfmc_id = int(entry["id"])
        reason = None
        if not no_date_filter and (window_start is not None or window_end is not None):
            reason = cli.out_of_mission_window_reason(
                entry, start=window_start, end=window_end
            )
        if reason:
            out_of_range += 1
            items.append(
                SfmcLognotePreviewItem(
                    sfmc_id=sfmc_id,
                    content=content,
                    action="skip_out_of_range",
                    reason=reason,
                )
            )
            continue
        if content in existing_contents:
            server_dup += 1
            items.append(
                SfmcLognotePreviewItem(
                    sfmc_id=sfmc_id,
                    content=content,
                    action="skip_server_dup",
                    reason="identical note content already on deployment",
                )
            )
            continue
        items.append(
            SfmcLognotePreviewItem(
                sfmc_id=sfmc_id,
                content=content,
                action="would_post" if dry_run else "posted",
                reason=None,
            )
        )
        to_post.append((entry, content))

    posted = 0
    if not dry_run:
        for _entry, content in to_post:
            note = models.SlocumDeploymentNote(
                deployment_id=deployment.id,
                content=content,
                include_in_report=include_in_report,
                created_by_username=username,
            )
            session.add(note)
            existing_contents.add(content)
            posted += 1
        session.commit()
        for item in items:
            if item.action == "would_post":
                item.action = "posted"

    would_post = len(to_post)
    summary = (
        f"{'Dry-run' if dry_run else 'Import'} summary: alias={alias!r} "
        f"deployment_id={deployment.id} "
        f"{'would_post' if dry_run else 'posted'}={would_post if dry_run else posted} "
        f"out_of_range={out_of_range} server_dup={server_dup} "
        f"batch_dup={len(batch_dup_items)} window={window_start}..{window_end} ({window_source})"
    )
    return SfmcLognoteImportResult(
        alias=alias,
        deployment_id=deployment.id,
        dry_run=dry_run,
        success=True,
        window_start=window_start,
        window_end=window_end,
        window_source=window_source,
        would_post=would_post if dry_run else 0,
        posted=0 if dry_run else posted,
        batch_dup=len(batch_dup_items),
        out_of_range=out_of_range,
        server_dup=server_dup,
        items=items,
        summary=summary,
    )


def prepare_import(
    *,
    session: SQLModelSession,
    username: str,
    alias: str,
    json_text: str,
    after: Optional[date] = None,
    before: Optional[date] = None,
    no_date_filter: bool = False,
    include_in_report: bool = True,
) -> SfmcLognoteImportResult:
    """Dry-run preview (Team / CLI ``--local``)."""
    return prepare_and_optionally_commit(
        session=session,
        username=username,
        alias=alias,
        json_text=json_text,
        after=after,
        before=before,
        no_date_filter=no_date_filter,
        include_in_report=include_in_report,
        dry_run=True,
    )


def commit_import(
    *,
    session: SQLModelSession,
    username: str,
    alias: str,
    json_text: str,
    after: Optional[date] = None,
    before: Optional[date] = None,
    no_date_filter: bool = False,
    include_in_report: bool = True,
) -> SfmcLognoteImportResult:
    """Re-validate payload and post notes in-process."""
    return prepare_and_optionally_commit(
        session=session,
        username=username,
        alias=alias,
        json_text=json_text,
        after=after,
        before=before,
        no_date_filter=no_date_filter,
        include_in_report=include_in_report,
        dry_run=False,
    )
