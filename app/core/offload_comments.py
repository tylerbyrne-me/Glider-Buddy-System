"""Merge and normalize offload comment fields on offload_logs rows."""

from __future__ import annotations

from typing import Any, Optional

PARSER_OFFLOAD_NOTES_PREFIX = "Auto-generated from WG-VM4 data"
STATION_OFFLOAD_SHEET_MARKER = ":station_offload_sheet:"


def _trimmed(value: Optional[str]) -> str:
    return (value or "").strip()


def is_parser_generated_offload_notes(text: Optional[str]) -> bool:
    return _trimmed(text).startswith(PARSER_OFFLOAD_NOTES_PREFIX)


def merge_legacy_offload_notes_into_user_notes(
    user_notes: Optional[str],
    offload_notes_file_size: Optional[str],
) -> Optional[str]:
    """Combine user_notes and legacy offload_notes_file_size for migration or writes."""
    user = _trimmed(user_notes)
    legacy = _trimmed(offload_notes_file_size)

    parts: list[str] = []
    if user:
        parts.append(user)
    if legacy and not is_parser_generated_offload_notes(legacy):
        if legacy != user and legacy not in user:
            parts.append(legacy)
    return "\n\n".join(parts) if parts else None


def get_offload_comments(log: Any) -> Optional[str]:
    """Merged view of user_notes + legacy user content in offload_notes_file_size."""
    return merge_legacy_offload_notes_into_user_notes(
        getattr(log, "user_notes", None),
        getattr(log, "offload_notes_file_size", None),
    )


def apply_user_offload_comments(log: Any, comments: Optional[str]) -> None:
    """Write canonical offload comments to user_notes; clear legacy user offload_notes_file_size."""
    normalized = _trimmed(comments) or None
    log.user_notes = normalized
    legacy = _trimmed(getattr(log, "offload_notes_file_size", None))
    if legacy and not is_parser_generated_offload_notes(legacy):
        log.offload_notes_file_size = None


def normalize_offload_log_write_data(data: dict) -> dict:
    """Normalize create/update payloads to canonical user_notes storage."""
    result = dict(data)
    offload_comments = result.pop("offload_comments", None)
    user_notes = result.get("user_notes")
    legacy_notes = result.get("offload_notes_file_size")

    if offload_comments is not None:
        merged = _trimmed(offload_comments) or None
    else:
        merged = merge_legacy_offload_notes_into_user_notes(user_notes, legacy_notes)

    result["user_notes"] = merged
    if legacy_notes is not None and not is_parser_generated_offload_notes(legacy_notes):
        result["offload_notes_file_size"] = None
    return result


def is_station_offload_sheet_session_ref(ref: Optional[str]) -> bool:
    return STATION_OFFLOAD_SHEET_MARKER in _trimmed(ref)


def mission_id_from_offload_log(log: Any) -> Optional[str]:
    """
    Per-log mission attribution for UI/API.

    Prefers sheet refs ``{mission}:station_offload_sheet:{station}``; otherwise the
    first segment of ``parser_session_ref`` / ``parser_run_id`` (parser pipelines).
    """
    ref = _trimmed(getattr(log, "parser_session_ref", None))
    if ref:
        if is_station_offload_sheet_session_ref(ref):
            prefix = ref.split(":", 1)[0].strip()
            return prefix or None
        prefix = ref.split(":", 1)[0].strip()
        return prefix or None
    run_id = _trimmed(getattr(log, "parser_run_id", None))
    if run_id:
        prefix = run_id.split(":", 1)[0].strip()
        return prefix or None
    return None


def apply_mission_id_to_offload_log(
    log: Any,
    mission_id: Optional[str],
    *,
    station_id: str,
) -> None:
    """
    Persist per-log mission on ``parser_session_ref`` for sheet/user attribution.

    Only rewrites empty refs or existing ``station_offload_sheet`` refs so VM4
    parser session keys are not clobbered. Clearing mission clears sheet refs only.
    """
    mid = _trimmed(mission_id) or None
    ref = _trimmed(getattr(log, "parser_session_ref", None))
    can_rewrite = (not ref) or is_station_offload_sheet_session_ref(ref)
    if not can_rewrite:
        return
    if mid is None:
        log.parser_session_ref = None
        return
    log.parser_session_ref = f"{mid}{STATION_OFFLOAD_SHEET_MARKER}{station_id}"


def enrich_offload_log_read(log: Any) -> dict:
    """Return offload log dict with computed offload_comments for API responses."""
    if hasattr(log, "model_dump"):
        payload = log.model_dump()
    elif isinstance(log, dict):
        payload = dict(log)
    else:
        payload = {
            key: getattr(log, key)
            for key in (
                "id",
                "station_id",
                "logged_by_username",
                "log_timestamp_utc",
                "arrival_date",
                "distance_command_sent_m",
                "time_first_command_sent_utc",
                "offload_start_time_utc",
                "offload_end_time_utc",
                "departure_date",
                "was_offloaded",
                "vrl_file_name",
                "vrl_verified_on_rudics",
                "offload_notes_file_size",
                "field_season_year",
                "remote_health_model_id",
                "remote_health_serial_number",
                "remote_health_modem_address",
                "remote_health_temperature_c",
                "remote_health_tilt_rad",
                "remote_health_humidity",
                "remote_health_report_date",
                "parser_notes",
                "user_notes",
                "created_by_source",
                "updated_by_source",
                "updated_at_utc",
                "parser_run_id",
                "parser_session_ref",
                "client_submission_id",
            )
            if hasattr(log, key)
        }
    payload["offload_comments"] = get_offload_comments(log)
    payload["mission_id"] = mission_id_from_offload_log(log)
    return payload
