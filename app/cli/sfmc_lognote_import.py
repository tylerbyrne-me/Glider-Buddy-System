"""
One-off CLI: ingest pasted SFMC user-log-note JSON and post as Slocum deployment notes.

SFMC log notes are not available via API; paste HTML/JSON response pages into files
(or stdin) and post them as backdated comments:

    YYYY-MM-DD HH:MM : [authorUsername] userLogNoteText

Target the mission via its env alias from SLOCUM_DATASET_ALIAS_MAP_JSON
(e.g. ``fundy``), not the integer ``slocum_deployments.id``.

Notes outside the mission window are skipped (SFMC archival noise):
  start = Sensor Tracker start_time → deployment_date → parsed dataset start
  end   = Sensor Tracker end_time (if present)
Override with ``--after`` / ``--before`` (YYYY-MM-DD, inclusive UTC dates).

Auth (same as station_cli):
    CLI_ADMIN_API_URL   default http://localhost:8000/api
    CLI_ADMIN_USERNAME
    CLI_ADMIN_PASSWORD

Usage:
    python -m app.cli.sfmc_lognote_import --alias fundy page1.json --dry-run
    python -m app.cli.sfmc_lognote_import --alias fundy page1.json page2.json
    python -m app.cli.sfmc_lognote_import --alias fundy page1.json --after 2026-06-21 --before 2026-08-01
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote

import httpx

from app.core.utils import parse_mission_note_datetime_prefix

BASE_API_URL = os.getenv("CLI_ADMIN_API_URL", "http://localhost:8000/api")
ADMIN_USERNAME = os.getenv("CLI_ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("CLI_ADMIN_PASSWORD")

REQUIRED_FIELDS = ("id", "userLogNoteText", "creationDateTime", "authorUsername")


def get_admin_token(*, base_api_url: str, username: str, password: str) -> str:
    """Obtain a Bearer token via POST /token."""
    token_url = base_api_url.replace("/api", "/token")
    response = httpx.post(
        token_url,
        data={"username": username, "password": password},
        timeout=30.0,
    )
    response.raise_for_status()
    token_data = response.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise RuntimeError("Token response missing access_token")
    return access_token


def truncate_creation_datetime_to_minutes(creation_datetime: str) -> str:
    """
    Convert SFMC creationDateTime (e.g. '2026-07-15 17:33:42') to
    'YYYY-MM-DD HH:MM' for the backdated note prefix.
    """
    raw = (creation_datetime or "").strip()
    if not raw:
        raise ValueError("creationDateTime is empty")
    # Prefer full timestamp with seconds, then minute-only.
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    raise ValueError(f"Unrecognized creationDateTime format: {creation_datetime!r}")


def format_note_content(entry: Dict[str, Any]) -> str:
    """Build backdated note content with embedded SFMC author."""
    prefix = truncate_creation_datetime_to_minutes(str(entry["creationDateTime"]))
    author = str(entry.get("authorUsername") or "").strip() or "unknown"
    text = str(entry.get("userLogNoteText") or "").strip()
    return f"{prefix} : [{author}] {text}"


def validate_entry(entry: Any, *, source: str, index: int) -> Dict[str, Any]:
    if not isinstance(entry, dict):
        raise ValueError(f"{source}[{index}]: expected object, got {type(entry).__name__}")
    missing = [field for field in REQUIRED_FIELDS if field not in entry]
    if missing:
        raise ValueError(f"{source}[{index}]: missing fields {missing}")
    return entry


def load_json_array(raw: str, *, source: str) -> List[Dict[str, Any]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{source}: malformed JSON ({exc})") from exc
    if not isinstance(data, list):
        raise ValueError(f"{source}: expected a JSON array of log notes")
    return [validate_entry(item, source=source, index=i) for i, item in enumerate(data)]


def load_entries_from_paths(paths: Iterable[Path]) -> List[Tuple[Dict[str, Any], str]]:
    """Return list of (entry, source_label)."""
    results: List[Tuple[Dict[str, Any], str]] = []
    for path in paths:
        raw = path.read_text(encoding="utf-8")
        entries = load_json_array(raw, source=str(path))
        for entry in entries:
            results.append((entry, str(path)))
    return results


def load_entries_from_stdin() -> List[Tuple[Dict[str, Any], str]]:
    raw = sys.stdin.read()
    if not raw.strip():
        raise ValueError("No JSON provided on stdin")
    entries = load_json_array(raw, source="stdin")
    return [(entry, "stdin") for entry in entries]


def sort_key_creation(entry: Dict[str, Any]) -> datetime:
    raw = str(entry["creationDateTime"]).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return datetime.min


def parse_cli_date(value: str) -> date:
    """Parse YYYY-MM-DD for --after / --before."""
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Expected YYYY-MM-DD, got {value!r}"
        ) from exc


def coerce_to_utc_date(value: Any) -> Optional[date]:
    """Coerce API ISO timestamps / date strings to a UTC calendar date."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            return value.replace(tzinfo=timezone.utc).date()
        return value.astimezone(timezone.utc).date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        if "T" in raw or "+" in raw[10:] or raw.count("-") > 2:
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
                return parsed.replace(tzinfo=timezone.utc).date()
            return parsed.astimezone(timezone.utc).date()
        return datetime.strptime(raw[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def mission_window_from_info(
    payload: Dict[str, Any],
) -> Tuple[Optional[date], Optional[date], str]:
    """
    Derive inclusive UTC mission window from dataset info.

    Start preference: Sensor Tracker start_time → deployment_date → parsed start_date.
    End: Sensor Tracker end_time only (optional).
    """
    sensor = payload.get("sensor_tracker_deployment") or {}
    deployment = payload.get("deployment") or {}
    parsed = payload.get("parsed_dataset") or {}

    start = (
        coerce_to_utc_date(sensor.get("start_time"))
        or coerce_to_utc_date(deployment.get("deployment_date"))
        or coerce_to_utc_date(parsed.get("start_date"))
    )
    end = coerce_to_utc_date(sensor.get("end_time"))

    sources: List[str] = []
    if coerce_to_utc_date(sensor.get("start_time")):
        sources.append("sensor_tracker.start_time")
    elif coerce_to_utc_date(deployment.get("deployment_date")):
        sources.append("deployment.deployment_date")
    elif coerce_to_utc_date(parsed.get("start_date")):
        sources.append("parsed_dataset.start_date")
    if end is not None:
        sources.append("sensor_tracker.end_time")
    source_label = "+".join(sources) if sources else "none"
    return start, end, source_label


def out_of_mission_window_reason(
    entry: Dict[str, Any],
    *,
    start: Optional[date],
    end: Optional[date],
) -> Optional[str]:
    """
    Return a skip reason when the note's creation date is outside the inclusive window.
    """
    note_day = sort_key_creation(entry).date()
    if note_day.year <= 1:
        return "unparseable creationDateTime"
    if start is not None and note_day < start:
        return f"before mission start {start.isoformat()} (note {note_day.isoformat()})"
    if end is not None and note_day > end:
        return f"after mission end {end.isoformat()} (note {note_day.isoformat()})"
    return None


def dedupe_batch(
    items: List[Tuple[Dict[str, Any], str]],
) -> Tuple[List[Tuple[Dict[str, Any], str]], int]:
    """Skip duplicate SFMC ids within the batch (first occurrence wins)."""
    seen_ids: Set[int] = set()
    unique: List[Tuple[Dict[str, Any], str]] = []
    skipped = 0
    for entry, source in items:
        sfmc_id = int(entry["id"])
        if sfmc_id in seen_ids:
            skipped += 1
            print(f"  skip batch-dup  id={sfmc_id}  source={source}")
            continue
        seen_ids.add(sfmc_id)
        unique.append((entry, source))
    return unique, skipped


def filter_by_mission_window(
    prepared: List[Tuple[Dict[str, Any], str, str]],
    *,
    start: Optional[date],
    end: Optional[date],
) -> Tuple[List[Tuple[Dict[str, Any], str, str]], int]:
    """Drop notes outside the inclusive mission window; print skip lines."""
    if start is None and end is None:
        return prepared, 0
    kept: List[Tuple[Dict[str, Any], str, str]] = []
    skipped = 0
    for entry, source, content in prepared:
        reason = out_of_mission_window_reason(entry, start=start, end=end)
        if reason:
            print(f"  skip out-of-range  id={entry['id']}  {reason}")
            skipped += 1
            continue
        kept.append((entry, source, content))
    return kept, skipped


def fetch_dataset_info(
    *,
    client: httpx.Client,
    base_api_url: str,
    alias: str,
    token: str,
) -> Dict[str, Any]:
    """
    Resolve a Slocum alias (or full dataset id) via GET /slocum/datasets/{id}/info.

    Returns the JSON payload, which includes ``deployment`` and ``notes``.
    """
    encoded = quote(alias.strip(), safe="")
    url = f"{base_api_url.rstrip('/')}/slocum/datasets/{encoded}/info"
    response = client.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=60.0,
    )
    if response.status_code == 404:
        raise RuntimeError(f"Dataset/alias {alias!r} not found (404)")
    response.raise_for_status()
    return response.json()


def resolve_deployment_from_info(payload: Dict[str, Any], *, alias: str) -> Tuple[int, Set[str]]:
    """Extract deployment id and existing note contents from a dataset info payload."""
    deployment = payload.get("deployment")
    if not deployment or deployment.get("id") is None:
        raise RuntimeError(
            f"No Slocum deployment linked for alias {alias!r}. "
            "Open the Slocum dashboard for that mission once so briefing metadata is created."
        )
    deployment_id = int(deployment["id"])
    notes = payload.get("notes") or []
    existing = {str(note.get("content") or "") for note in notes if note.get("content")}
    return deployment_id, existing


def post_note(
    *,
    client: httpx.Client,
    base_api_url: str,
    deployment_id: int,
    token: str,
    content: str,
    include_in_report: bool,
) -> Dict[str, Any]:
    url = f"{base_api_url.rstrip('/')}/slocum/deployments/{deployment_id}/notes"
    response = client.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json={"content": content, "include_in_report": include_in_report},
        timeout=60.0,
    )
    response.raise_for_status()
    return response.json()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Import pasted SFMC user-log-note JSON pages as backdated "
            "Slocum deployment notes."
        )
    )
    parser.add_argument(
        "--alias",
        required=True,
        help=(
            "Slocum mission alias from SLOCUM_DATASET_ALIAS_MAP_JSON "
            "(e.g. fundy), or a full ERDDAP dataset id"
        ),
    )
    parser.add_argument(
        "json_files",
        nargs="*",
        type=Path,
        help="One or more pasted SFMC JSON response files (omit to read stdin)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be posted without calling write APIs",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Set include_in_report=false on created notes",
    )
    parser.add_argument(
        "--after",
        type=parse_cli_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="Override mission start date (inclusive UTC). Suppress notes before this day.",
    )
    parser.add_argument(
        "--before",
        type=parse_cli_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="Override mission end date (inclusive UTC). Suppress notes after this day.",
    )
    parser.add_argument(
        "--no-date-filter",
        action="store_true",
        help="Do not suppress notes outside the mission window",
    )
    parser.add_argument(
        "--base-url",
        default=BASE_API_URL,
        help=f"API base URL ending in /api (default: {BASE_API_URL})",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    include_in_report = not args.no_report
    base_api_url = str(args.base_url).rstrip("/")
    alias = str(args.alias).strip()
    if not alias:
        print("Error: --alias must be a non-empty string.", file=sys.stderr)
        return 1
    if args.after and args.before and args.after > args.before:
        print(
            f"Error: --after {args.after} is after --before {args.before}.",
            file=sys.stderr,
        )
        return 1

    try:
        if args.json_files:
            for path in args.json_files:
                if not path.is_file():
                    raise FileNotFoundError(f"JSON file not found: {path}")
            loaded = load_entries_from_paths(args.json_files)
        else:
            print("Reading SFMC JSON array from stdin (paste, then Ctrl-Z Enter on Windows)...")
            loaded = load_entries_from_stdin()
    except (ValueError, FileNotFoundError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not loaded:
        print("No log notes found in input.")
        return 0

    loaded.sort(key=lambda item: sort_key_creation(item[0]))
    unique_items, batch_dup_count = dedupe_batch(loaded)

    prepared: List[Tuple[Dict[str, Any], str, str]] = []
    for entry, source in unique_items:
        try:
            content = format_note_content(entry)
        except ValueError as exc:
            print(f"Error formatting id={entry.get('id')}: {exc}", file=sys.stderr)
            return 1
        if parse_mission_note_datetime_prefix(content) is None:
            print(
                f"Error: generated content failed prefix parse for id={entry.get('id')}: {content[:80]!r}",
                file=sys.stderr,
            )
            return 1
        prepared.append((entry, source, content))

    print(
        f"Loaded {len(loaded)} note(s); {len(prepared)} unique after batch dedup "
        f"({batch_dup_count} batch duplicate(s)). Target alias={alias!r}"
    )

    has_creds = bool(ADMIN_USERNAME and ADMIN_PASSWORD)
    # Resolve alias whenever we need to post, or when dry-run can use mission dates.
    needs_resolve = (not args.dry_run) or (
        args.dry_run
        and not args.no_date_filter
        and args.after is None
        and has_creds
    )

    info_payload: Optional[Dict[str, Any]] = None
    deployment_id: Optional[int] = None
    existing_contents: Set[str] = set()
    token: Optional[str] = None

    if needs_resolve or not args.dry_run:
        if not has_creds:
            print(
                "Error: CLI_ADMIN_USERNAME and CLI_ADMIN_PASSWORD must be set.",
                file=sys.stderr,
            )
            return 1
        try:
            token = get_admin_token(
                base_api_url=base_api_url,
                username=ADMIN_USERNAME,
                password=ADMIN_PASSWORD,
            )
        except httpx.HTTPStatusError as exc:
            print(
                f"Error: auth failed ({exc.response.status_code}): {exc.response.text}",
                file=sys.stderr,
            )
            return 1
        except (httpx.RequestError, RuntimeError) as exc:
            print(f"Error: auth request failed: {exc}", file=sys.stderr)
            return 1

        with httpx.Client() as client:
            try:
                info_payload = fetch_dataset_info(
                    client=client,
                    base_api_url=base_api_url,
                    alias=alias,
                    token=token,
                )
                deployment_id, existing_contents = resolve_deployment_from_info(
                    info_payload, alias=alias
                )
            except httpx.HTTPStatusError as exc:
                print(
                    f"Error resolving alias {alias!r} ({exc.response.status_code}): {exc.response.text}",
                    file=sys.stderr,
                )
                return 1
            except (httpx.RequestError, RuntimeError) as exc:
                print(f"Error resolving alias {alias!r}: {exc}", file=sys.stderr)
                return 1

        dep = (info_payload or {}).get("deployment") or {}
        print(
            f"Resolved alias={alias!r} -> deployment_id={deployment_id} "
            f"name={dep.get('name')!r} mission_key={dep.get('mission_key')!r} "
            f"existing_notes={len(existing_contents)}"
        )

    # Mission window: CLI overrides win; else auto from resolved info.
    window_start: Optional[date] = None
    window_end: Optional[date] = None
    window_source = "disabled"
    if args.no_date_filter:
        window_source = "disabled (--no-date-filter)"
    else:
        auto_start: Optional[date] = None
        auto_end: Optional[date] = None
        auto_source = "none"
        if info_payload is not None:
            auto_start, auto_end, auto_source = mission_window_from_info(info_payload)
        window_start = args.after if args.after is not None else auto_start
        window_end = args.before if args.before is not None else auto_end
        parts: List[str] = []
        if args.after is not None:
            parts.append("--after")
        elif auto_start is not None:
            parts.append(auto_source.split("+")[0] if auto_source != "none" else "auto-start")
        if args.before is not None:
            parts.append("--before")
        elif auto_end is not None:
            parts.append("sensor_tracker.end_time")
        window_source = "+".join(parts) if parts else "none"
        if window_start is None and window_end is None and not args.dry_run:
            print(
                "Warning: no mission start/end dates found; date filter inactive. "
                "Pass --after/--before or sync Sensor Tracker metadata."
            )
        elif window_start is None and window_end is None and args.dry_run and not has_creds:
            print(
                "Warning: dry-run without credentials and without --after/--before; "
                "date filter inactive."
            )

    print(
        f"Mission window: start={window_start}  end={window_end}  source={window_source}"
    )
    prepared, range_skip_count = filter_by_mission_window(
        prepared, start=window_start, end=window_end
    )

    if args.dry_run:
        posted = 0
        for entry, source, content in prepared:
            preview = content.replace("\n", "\\n")
            if len(preview) > 120:
                preview = preview[:117] + "..."
            print(f"  would-post  id={entry['id']}  {preview}")
            posted += 1
        print(
            f"Dry-run summary: alias={alias!r}  deployment_id={deployment_id}  "
            f"would_post={posted}  out_of_range={range_skip_count}  "
            f"batch_dup={batch_dup_count}  server_dup=n/a"
        )
        return 0

    assert token is not None and deployment_id is not None

    posted_count = 0
    skipped_server_count = 0

    with httpx.Client() as client:
        for entry, source, content in prepared:
            sfmc_id = entry["id"]
            if content in existing_contents:
                print(f"  skip server-dup  id={sfmc_id}")
                skipped_server_count += 1
                continue
            try:
                created = post_note(
                    client=client,
                    base_api_url=base_api_url,
                    deployment_id=deployment_id,
                    token=token,
                    content=content,
                    include_in_report=include_in_report,
                )
            except httpx.HTTPStatusError as exc:
                print(
                    f"Error posting id={sfmc_id} ({exc.response.status_code}): {exc.response.text}",
                    file=sys.stderr,
                )
                return 1
            except httpx.RequestError as exc:
                print(f"Error posting id={sfmc_id}: {exc}", file=sys.stderr)
                return 1

            note_id = created.get("id")
            preview = content.replace("\n", "\\n")
            if len(preview) > 100:
                preview = preview[:97] + "..."
            print(f"  posted  sfmc_id={sfmc_id}  note_id={note_id}  {preview}")
            posted_count += 1
            existing_contents.add(content)

    print(
        f"Summary: alias={alias!r}  deployment_id={deployment_id}  "
        f"posted={posted_count}  out_of_range={range_skip_count}  "
        f"server_dup={skipped_server_count}  batch_dup={batch_dup_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
