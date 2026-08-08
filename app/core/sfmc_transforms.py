"""
Pure transforms from SFMC web/API payload shapes → Slocum checklist field values.

No HTTP here — feed payloads from ``sfmc_client`` or saved exploration samples.
``u_alt_min_depth_val`` is intentionally omitted (pilot-entered / prior checklist).
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Any, Optional

_GOTO_NAME_RE = re.compile(
    r"^.+_goto_.+\.ma$",
    re.IGNORECASE,
)
_GOTO_STAMP_RE = re.compile(
    r"^(?P<stamp>\d{8}T\d{6})_",
    re.IGNORECASE,
)
_INITIAL_WPT_RE = re.compile(
    r"b_arg:\s*initial_wpt\s*\(\s*enum\s*\)\s*(-?\d+)",
    re.IGNORECASE,
)
_OFFLOAD_CMD_RE = re.compile(
    r"(?:!dockzr|\bs\s+\*\.(?:scd|tcd|asc)\b)",
    re.IGNORECASE,
)
_NETWORK_LOG_RE = re.compile(
    r"^(?P<stamp>\d{8}T\d{6})_?.*_network_net_\d+\.log$",
    re.IGNORECASE,
)
# Also: peggy_20260720T162013_network_net_0.log
_NETWORK_LOG_NAMED_RE = re.compile(
    r"^(?P<glider>[A-Za-z0-9_-]+)_(?P<stamp>\d{8}T\d{6})_network_net_\d+\.log$",
    re.IGNORECASE,
)
_DEVICES_TMS_RE = re.compile(
    r"devices:\(t/m/s\)\s*"
    r"errs:\s*(?P<te>\d+)\s*/\s*(?P<me>\d+)\s*/\s*(?P<se>\d+)\s*"
    r"warn:\s*(?P<tw>\d+)\s*/\s*(?P<mw>\d+)\s*/\s*(?P<sw>\d+)\s*"
    r"odd:\s*(?P<to>\d+)\s*/\s*(?P<mo>\d+)\s*/\s*(?P<so>\d+)",
    re.IGNORECASE,
)
_ABORT_HISTORY_RE = re.compile(
    r"ABORT HISTORY:\s*total since reset:\s*(?P<count>\d+)",
    re.IGNORECASE,
)
_MISSION_NAME_RE = re.compile(
    r"MissionName:\s*(?P<name>\S+\.mi)",
    re.IGNORECASE,
)
_BECAUSE_RE = re.compile(
    r"Because:\s*(?P<reason>.+?)(?:\r?\n)",
    re.IGNORECASE,
)
_SENSOR_LINE_RE = re.compile(
    r"sensor:(?P<name>[A-Za-z0-9_]+)\([^)]*\)=(?P<value>\S+)",
    re.IGNORECASE,
)

_INITIAL_WPT_LABELS = {
    -2: "closest",
    -1: "after last achieved",
    0: "first waypoint (index 0)",
}


def pick_typical_hours_since(hours_map: Any) -> Optional[float]:
    """
    Choose the common / most frequent \"Time Since Prior\" from ``hoursSinceMap``.

    Skips near-zero double-surface values (< 0.1 h). Prefers the modal value
    rounded to 0.1 h; if every value is unique, uses the median.
    """
    if not isinstance(hours_map, dict) or not hours_map:
        return None
    vals: list[float] = []
    for value in hours_map.values():
        try:
            hours = float(value)
        except (TypeError, ValueError):
            continue
        if hours >= 0.1:
            vals.append(hours)
    if not vals:
        return None

    from collections import Counter

    rounded = [round(v, 1) for v in vals]
    counts = Counter(rounded)
    best = max(counts.values())
    if best == 1:
        ordered = sorted(vals)
        return ordered[len(ordered) // 2]
    modes = sorted(h for h, c in counts.items() if c == best)
    return modes[len(modes) // 2]


def _parse_sfmc_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        # Epoch seconds or milliseconds
        ts = float(value)
        if ts > 1e12:
            ts = ts / 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return _parse_sfmc_dt(int(text))
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y%m%d%H%M%S",
        "%Y%m%d%H%M",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%fZ",
    ):
        try:
            cleaned = text.replace("Z", "")
            dt = datetime.strptime(cleaned[:26], fmt.replace("Z", ""))
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def script_basename(dock_server_script_name: str) -> str:
    """``.../scripts//TC_safe_g3s.xml`` → ``TC_safe_g3s.xml``."""
    name = PurePosixPath(str(dock_server_script_name).replace("\\", "/")).name
    return name or str(dock_server_script_name).strip()


def format_initial_wpt(value: int) -> str:
    label = _INITIAL_WPT_LABELS.get(value)
    if label:
        return f"{value} ({label})"
    if value > 0:
        return f"{value} (waypoint index {value})"
    return str(value)


def parse_goto_ma(text: str) -> dict[str, Any]:
    """
    Parse a Slocum goto list ``.ma`` file (any ``*_goto_*.ma`` variant).

    Returns ``initial_wpt`` (int|None), ``display`` for ``goto_state_val``, and
    ``num_waypoints`` when present.
    """
    match = _INITIAL_WPT_RE.search(text or "")
    initial_wpt: Optional[int] = int(match.group(1)) if match else None
    num_match = re.search(
        r"b_arg:\s*num_waypoints\s*\(\s*nodim\s*\)\s*(-?\d+)",
        text or "",
        re.IGNORECASE,
    )
    num_waypoints = int(num_match.group(1)) if num_match else None
    display = format_initial_wpt(initial_wpt) if initial_wpt is not None else None
    return {
        "initial_wpt": initial_wpt,
        "num_waypoints": num_waypoints,
        "display": display,
    }


# Back-compat alias
parse_goto_l10_ma = parse_goto_ma


def pick_latest_goto_archive_filename(names: list[str]) -> Optional[str]:
    """
    Choose the newest archive goto file matching ``*_goto_*.ma``.

    Prefers ``YYYYMMDDTHHMMSS_*_goto_*.ma`` by stamp (e.g.
    ``20260624T115617_goto_l10.ma``, ``20260701T120000_goto_l1.ma``).
    If no stamped names match, falls back to lexicographic max of ``*_goto_*.ma``.
    """
    stamped: list[tuple[str, str]] = []
    unstamped: list[str] = []
    for name in names:
        base = PurePosixPath(str(name).replace("\\", "/")).name
        if not _GOTO_NAME_RE.match(base):
            continue
        stamp_match = _GOTO_STAMP_RE.match(base)
        if stamp_match:
            stamped.append((stamp_match.group("stamp"), base))
        else:
            unstamped.append(base)
    if stamped:
        stamped.sort(key=lambda item: item[0], reverse=True)
        return stamped[0][1]
    if unstamped:
        return sorted(unstamped)[-1]
    return None


def pick_latest_network_log_filename(names: list[str]) -> Optional[str]:
    """Newest ``{glider}_YYYYMMDDTHHMMSS_network_net_N.log`` by stamp."""
    best_name: Optional[str] = None
    best_stamp: Optional[str] = None
    for name in names:
        base = PurePosixPath(str(name).replace("\\", "/")).name
        match = _NETWORK_LOG_NAMED_RE.match(base) or _NETWORK_LOG_RE.match(base)
        if not match:
            continue
        stamp = match.group("stamp")
        if best_stamp is None or stamp > best_stamp:
            best_stamp = stamp
            best_name = base
    return best_name


def parse_surface_dialog_log(text: str) -> dict[str, str]:
    """
    Parse glider surface dialog / network log tail → checklist fields.

    Expects the ``Glider … at surface.`` block including Device Status (t/m/s):

    ``devices:(t/m/s) errs: t/m/s warn: t/m/s odd: t/m/s``
    """
    out: dict[str, str] = {}
    if not text or not str(text).strip():
        return out

    # Prefer the last (most recent) surface status block in the tail.
    blocks = re.split(r"(?=Glider\s+\S+\s+at surface\.)", text, flags=re.IGNORECASE)
    block = ""
    for candidate in reversed(blocks):
        if re.search(r"Glider\s+\S+\s+at surface\.", candidate, re.IGNORECASE):
            block = candidate
            break
    if not block:
        block = text

    mission = _MISSION_NAME_RE.search(block) or _MISSION_NAME_RE.search(text)
    if mission:
        out["mission_file_running_val"] = mission.group("name").strip()

    devices = _DEVICES_TMS_RE.search(block) or _DEVICES_TMS_RE.search(text)
    abort_hist = _ABORT_HISTORY_RE.search(block) or _ABORT_HISTORY_RE.search(text)
    because = _BECAUSE_RE.search(block) or _BECAUSE_RE.search(text)

    if devices or abort_hist or because:
        bits: list[str] = []
        abort_count = int(abort_hist.group("count")) if abort_hist else None
        if abort_count is None:
            bits.append("Abort history N/A")
        elif abort_count == 0:
            bits.append("No abort (history 0)")
        else:
            bits.append(f"ABORT HISTORY since reset: {abort_count}")

        if devices:
            bits.append(
                "Device Status (t/m/s): "
                f"errs {devices.group('te')}/{devices.group('me')}/{devices.group('se')}; "
                f"warn {devices.group('tw')}/{devices.group('mw')}/{devices.group('sw')}; "
                f"odd {devices.group('to')}/{devices.group('mo')}/{devices.group('so')}"
            )
        if because:
            reason = because.group("reason").strip()
            if reason:
                bits.append(f"last surface: {reason}")
        out["aborts_oddities_val"] = "; ".join(bits)

    # Sensor dump from full tail (last block may omit older lines).
    sensors: dict[str, str] = {}
    for match in _SENSOR_LINE_RE.finditer(text):
        sensors[match.group("name")] = match.group("value")
    if sensors.get("m_battery"):
        out["_dialog_m_battery"] = sensors["m_battery"]
    if sensors.get("u_alt_min_depth"):
        out["_dialog_u_alt_min_depth"] = sensors["u_alt_min_depth"]

    return out


def dialog_values_for_checklist(parsed: dict[str, str]) -> dict[str, str]:
    """Public checklist keys only (drops ``_dialog_*`` internals)."""
    return {
        key: value
        for key, value in (parsed or {}).items()
        if not key.startswith("_") and value
    }


_MS_TO_KNOTS = 3600.0 / 1852.0


def sfmc_dm_to_decimal_degrees(value: Any) -> Optional[float]:
    """Convert SFMC GPS ``DDMM.mmm`` / ``DDDMM.mmm`` (signed) to decimal degrees."""
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(raw):
        return None
    sign = -1.0 if raw < 0 else 1.0
    av = abs(raw)
    degrees = int(av // 100.0)
    minutes = av - degrees * 100.0
    if minutes >= 60.0:
        return None
    return sign * (degrees + minutes / 60.0)


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2.0) ** 2
    )
    return 2.0 * 6371.0 * math.asin(math.sqrt(a))


def extract_surface_speed_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract Surfacings Speed & Distance rows from an SFMC surface-events payload.

    Expects DevTools / UI shape with ``surfaceEventsPage.content`` plus optional
    ``speedMap`` / ``distanceTraveledMap`` / ``hoursSinceMap`` keyed by event id.
    Speeds are m/s in SFMC; ``speed_kt`` is derived. When a map entry is missing,
    speed/distance are recomputed from consecutive GPS fixes.

    The public Bearer ``/sfmc/api/v1/active-deployment/{glider}`` path does **not**
    currently return these maps — this helper is for captured UI payloads and a
    future UI/API wire-up.
    """
    if not isinstance(payload, dict):
        return []
    page = payload.get("surfaceEventsPage") or {}
    content = page.get("content") if isinstance(page, dict) else None
    if not isinstance(content, list) or not content:
        return []

    speed_map = payload.get("speedMap") if isinstance(payload.get("speedMap"), dict) else {}
    distance_map = (
        payload.get("distanceTraveledMap")
        if isinstance(payload.get("distanceTraveledMap"), dict)
        else {}
    )
    hours_map = payload.get("hoursSinceMap") if isinstance(payload.get("hoursSinceMap"), dict) else {}

    rows: list[dict[str, Any]] = []
    for raw in content:
        if not isinstance(raw, dict):
            continue
        event_id = raw.get("id")
        lat = sfmc_dm_to_decimal_degrees(raw.get("gpsLat"))
        lon = sfmc_dm_to_decimal_degrees(raw.get("gpsLon"))
        when = _parse_sfmc_dt(raw.get("surfaceDateTime") or raw.get("gpsDateTime"))
        if lat is None or lon is None or when is None:
            continue
        key = str(event_id) if event_id is not None else ""
        speed_ms = None
        distance_km = None
        hours_since = None
        if key and key in speed_map:
            try:
                speed_ms = float(speed_map[key])
            except (TypeError, ValueError):
                speed_ms = None
        if key and key in distance_map:
            try:
                distance_km = float(distance_map[key])
            except (TypeError, ValueError):
                distance_km = None
        if key and key in hours_map:
            try:
                hours_since = float(hours_map[key])
            except (TypeError, ValueError):
                hours_since = None
        rows.append(
            {
                "id": event_id,
                "surface_time": when,
                "latitude": lat,
                "longitude": lon,
                "speed_m_s": speed_ms,
                "speed_kt": (speed_ms * _MS_TO_KNOTS) if speed_ms is not None else None,
                "distance_km": distance_km,
                "hours_since": hours_since,
            }
        )

    rows.sort(key=lambda row: row["surface_time"])
    for i in range(1, len(rows)):
        prev = rows[i - 1]
        cur = rows[i]
        if cur.get("distance_km") is not None and cur.get("speed_m_s") is not None:
            continue
        dist_km = _haversine_km(
            prev["latitude"], prev["longitude"], cur["latitude"], cur["longitude"]
        )
        dt_h = (cur["surface_time"] - prev["surface_time"]).total_seconds() / 3600.0
        if cur.get("distance_km") is None:
            cur["distance_km"] = dist_km
        if cur.get("hours_since") is None and dt_h > 0:
            cur["hours_since"] = dt_h
        if cur.get("speed_m_s") is None and dt_h > 0:
            cur["speed_m_s"] = (dist_km * 1000.0) / (dt_h * 3600.0)
            cur["speed_kt"] = cur["speed_m_s"] * _MS_TO_KNOTS
    return rows


def extract_from_surface_events_payload(payload: dict[str, Any]) -> dict[str, str]:
    """Map SFMC surface-events / deployment page JSON → checklist fields."""
    out: dict[str, str] = {}
    if not isinstance(payload, dict):
        return out

    missions = payload.get("missionExecutionsMap") or {}
    if isinstance(missions, dict):
        active = None
        for entry in missions.values():
            if not isinstance(entry, dict):
                continue
            if entry.get("endDateTime") is None and not entry.get("complete"):
                active = entry
                break
        if active is None:
            for entry in missions.values():
                if isinstance(entry, dict):
                    active = entry
                    break
        if isinstance(active, dict) and active.get("missionName"):
            out["mission_file_running_val"] = str(active["missionName"]).strip()

    page = payload.get("surfaceEventsPage") or {}
    content = page.get("content") if isinstance(page, dict) else None
    latest = content[0] if isinstance(content, list) and content else None
    hours_map = payload.get("hoursSinceMap") or {}

    # Prefer the typical / modal dive-cycle interval, not the latest (often a
    # near-zero double-surface) and not GPS age.
    typical_hours = pick_typical_hours_since(hours_map)
    if typical_hours is not None:
        out["surfacing_hours_val"] = f"{typical_hours:.1f}".rstrip("0").rstrip(".")

    if isinstance(latest, dict):
        abort = bool(latest.get("abort"))
        warnings = latest.get("totalWarnings")
        oddities = latest.get("totalOddities")
        reason = (latest.get("reason") or "").strip()
        details = (latest.get("moreDetails") or "").strip()
        abort_bit = (
            f"ABORT @ {latest.get('abortDateTime')}"
            if abort
            else "No abort"
        )
        bits = [abort_bit, f"{warnings} warnings", f"{oddities} oddities"]
        if reason:
            detail_bit = reason
            if details:
                detail_bit = f"{reason} ({details})"
            bits.append(f"last surface: {detail_bit}")
        out["aborts_oddities_val"] = "; ".join(str(b) for b in bits if b is not None)

        bearing = latest.get("nextWaypointBearingInDeg")
        range_m = latest.get("nextWaypointRangeInM")
        if bearing is not None and range_m is not None:
            # Supplemental only — full goto_state comes from archive .ma
            out.setdefault(
                "goto_state_val",
                f"next wpt {float(range_m):.0f} m @ {float(bearing):.0f}°",
            )

    # Live v1 active-deployment is flat: bearing/range live at top level.
    if "goto_state_val" not in out:
        bearing = payload.get("nextWaypointBearingInDeg")
        range_m = payload.get("nextWaypointRangeInM")
        if bearing is not None and range_m is not None:
            try:
                out["goto_state_val"] = (
                    f"next wpt {float(range_m):.0f} m @ {float(bearing):.0f}°"
                )
            except (TypeError, ValueError):
                pass

    # Do NOT use GPS age as surfacing hours — that is \"time since last fix\",
    # not SFMC \"Time Since Prior\" (dive-cycle interval).

    # Live script assignment on flat active-deployment.
    script_name = payload.get("currentScriptName")
    if isinstance(script_name, str) and script_name.strip():
        display = script_basename(script_name)
        if payload.get("isCurrentScriptRunning") is False:
            display = f"{display} (not running)"
        out.setdefault("script_running_val", display)

    connections = payload.get("connectionsMap") or {}
    if isinstance(connections, dict):
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        recent = False
        for conn in connections.values():
            if not isinstance(conn, dict):
                continue
            for key in ("endDateTime", "startDateTime"):
                dt = _parse_sfmc_dt(conn.get(key))
                if dt is not None and dt >= cutoff:
                    recent = True
                    break
            if recent:
                break
        if recent:
            out.setdefault("offloaded_24h_val", "Yes")

    return out


def extract_from_dockserver_commands(
    commands: list[dict[str, Any]],
    *,
    now: Optional[datetime] = None,
) -> dict[str, str]:
    """Map dockserver command log → script + offload checklist fields."""
    out: dict[str, str] = {}
    if not commands:
        return out

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    # Newest command first when sortable
    ordered = sorted(
        (c for c in commands if isinstance(c, dict)),
        key=lambda c: _parse_sfmc_dt(c.get("submissionDateTime")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    for entry in ordered:
        script_path = entry.get("dockServerScriptName")
        if script_path:
            out["script_running_val"] = script_basename(str(script_path))
            break

    offload_hit = False
    for entry in ordered:
        cmd = str(entry.get("command") or "")
        if not _OFFLOAD_CMD_RE.search(cmd):
            continue
        dt = _parse_sfmc_dt(entry.get("submissionDateTime"))
        if dt is None or dt >= cutoff:
            offload_hit = True
            break

    if offload_hit:
        out["offloaded_24h_val"] = "Yes"
    elif ordered:
        # Had command history but no offload cmds in 24h
        out.setdefault("offloaded_24h_val", "No — manual offload ASAP")

    return out


def merge_sfmc_checklist_values(*parts: dict[str, str]) -> dict[str, str]:
    """Merge SFMC-derived maps; later non-empty values win."""
    merged: dict[str, str] = {}
    for part in parts:
        for key, value in (part or {}).items():
            if key.startswith("_"):
                continue
            if key in ("connection_durations", "dmon_asc_files"):
                continue
            if value is None:
                continue
            text = str(value).strip()
            if text:
                merged[key] = text
    # Never autofill pilot altitude min depth from SFMC
    merged.pop("u_alt_min_depth_val", None)
    return merged


DMON_ASC_GAP_HOURS = 16.0
DMON_ASC_WINDOW_HOURS = 48.0


def normalize_dmon_asc_files(
    entries: Any,
    *,
    now: Optional[datetime] = None,
    window_hours: float = DMON_ASC_WINDOW_HOURS,
    window_start: Optional[datetime] = None,
    gap_hours: float = DMON_ASC_GAP_HOURS,
) -> dict[str, Any]:
    """
    Normalize SFMC folder entries into a DMON ASC summary for dashboard/checklist.

    Returns::
        {
          "files": [{fileName, dateTimeModified, fileSize, gap_after_prev_hours?}],
          "hours_since_last": float | None,
          "has_gap_over_16h": bool,
          "file_count": int,
          "summary": str,
        }

    Optional per-file ``thruster_since_prev`` (bool | None) is added later by
    ``enrich_dmon_asc_with_thruster`` (dashboard telemetry), not by this normalize.

    When ``window_start`` is set, files are kept for ``[window_start, now]``.
    Otherwise files are kept for the rolling ``window_hours`` ending at ``now``.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    start_bound: Optional[datetime] = None
    if window_start is not None:
        start_bound = window_start
        if start_bound.tzinfo is None:
            start_bound = start_bound.replace(tzinfo=timezone.utc)

    parsed: list[dict[str, Any]] = []
    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict):
                continue
            name = (
                item.get("fileName")
                or item.get("filename")
                or item.get("name")
                or item.get("path")
            )
            if not name:
                continue
            name_s = str(name).strip()
            if not name_s.lower().endswith(".asc"):
                continue
            modified_raw = (
                item.get("dateTimeModified")
                or item.get("lastModified")
                or item.get("modified")
                or item.get("mtime")
            )
            modified_dt = _parse_sfmc_dt(modified_raw)
            if modified_dt is None:
                continue
            size = item.get("fileSize")
            try:
                size_n = int(size) if size is not None else None
            except (TypeError, ValueError):
                size_n = None
            parsed.append(
                {
                    "fileName": name_s,
                    "dateTimeModified": modified_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "fileSize": size_n,
                    "_dt": modified_dt,
                }
            )

    parsed.sort(key=lambda row: row["_dt"])

    if start_bound is not None:
        in_window = [row for row in parsed if start_bound <= row["_dt"] <= now]
    else:
        window_cutoff = now - timedelta(hours=max(0.0, float(window_hours)))
        in_window = [row for row in parsed if row["_dt"] >= window_cutoff]
    # If nothing in window but we have older files (fallback listing), keep newest only
    # so hours_since_last still works.
    using_fallback = not in_window and bool(parsed)
    files_src = in_window if in_window else (parsed[-1:] if parsed else [])

    files_out: list[dict[str, Any]] = []
    has_inter_gap = False
    prev_dt: Optional[datetime] = None
    for row in files_src:
        gap_after: Optional[float] = None
        if prev_dt is not None:
            gap_after = round((row["_dt"] - prev_dt).total_seconds() / 3600.0, 2)
            if gap_after is not None and gap_after > gap_hours:
                has_inter_gap = True
        entry = {
            "fileName": row["fileName"],
            "dateTimeModified": row["dateTimeModified"],
            "fileSize": row["fileSize"],
        }
        if gap_after is not None:
            entry["gap_after_prev_hours"] = gap_after
            entry["gap_over_threshold"] = gap_after > gap_hours
        files_out.append(entry)
        prev_dt = row["_dt"]

    hours_since_last: Optional[float] = None
    if parsed:
        hours_since_last = round((now - parsed[-1]["_dt"]).total_seconds() / 3600.0, 2)

    has_gap = bool(
        (hours_since_last is not None and hours_since_last > gap_hours) or has_inter_gap
    )

    if not files_out:
        summary = "No *.asc files found in SFMC from-glider."
    else:
        newest = files_out[-1]["fileName"]
        age = f"{hours_since_last:.1f}h ago" if hours_since_last is not None else "unknown age"
        gap_note = f" - GAP >{gap_hours:.0f}h" if has_gap else ""
        if using_fallback:
            summary = (
                f"No *.asc in report window; newest overall: {newest}, {age}{gap_note}"
                if start_bound is not None
                else f"No *.asc in last {window_hours:.0f}h; newest overall: {newest}, {age}{gap_note}"
            )
        elif start_bound is not None:
            summary = (
                f"{len(files_out)} *.asc in report window "
                f"(newest: {newest}, {age}){gap_note}"
            )
        else:
            summary = (
                f"{len(files_out)} *.asc in last {window_hours:.0f}h "
                f"(newest: {newest}, {age}){gap_note}"
            )

    return {
        "files": files_out,
        "hours_since_last": hours_since_last,
        "has_gap_over_16h": has_gap,
        "file_count": len(files_out),
        "summary": summary,
    }


def _parse_dmon_asc_timestamps(entries: Any) -> list[datetime]:
    """Extract sorted UTC timestamps from raw SFMC folder listing entries."""
    parsed: list[datetime] = []
    if not isinstance(entries, list):
        return parsed
    for item in entries:
        if not isinstance(item, dict):
            continue
        name = (
            item.get("fileName")
            or item.get("filename")
            or item.get("name")
            or item.get("path")
        )
        if not name or not str(name).strip().lower().endswith(".asc"):
            continue
        modified_raw = (
            item.get("dateTimeModified")
            or item.get("lastModified")
            or item.get("modified")
            or item.get("mtime")
        )
        modified_dt = _parse_sfmc_dt(modified_raw)
        if modified_dt is None:
            continue
        parsed.append(modified_dt)
    parsed.sort()
    return parsed


def _utc_days_overlapping_interval(
    start: datetime,
    end: datetime,
    *,
    window_start: datetime,
    window_end: datetime,
) -> set[date]:
    """Return UTC calendar dates in [window_start, window_end] overlapping [start, end)."""
    if end <= start:
        return set()
    clip_start = max(start, window_start)
    clip_end = min(end, window_end)
    if clip_end <= clip_start:
        return set()
    days: set[date] = set()
    cursor = clip_start.astimezone(timezone.utc).date()
    last = (clip_end - timedelta(microseconds=1)).astimezone(timezone.utc).date()
    while cursor <= last:
        days.add(cursor)
        cursor = cursor + timedelta(days=1)
    return days


def count_dmon_asc_gap_days(
    entries: Any,
    *,
    window_start: datetime,
    window_end: datetime,
    gap_hours: float = DMON_ASC_GAP_HOURS,
) -> int:
    """
    Count UTC calendar days in the report window that fall inside an ASC gap > ``gap_hours``.

    Gaps are intervals between consecutive ``*.asc`` file timestamps (and a trailing gap
    from the last file to ``window_end`` when that span exceeds the threshold). Days are
    only counted when they overlap both the gap interval and ``[window_start, window_end]``.
    """
    if window_end <= window_start:
        return 0
    if window_start.tzinfo is None:
        window_start = window_start.replace(tzinfo=timezone.utc)
    else:
        window_start = window_start.astimezone(timezone.utc)
    if window_end.tzinfo is None:
        window_end = window_end.replace(tzinfo=timezone.utc)
    else:
        window_end = window_end.astimezone(timezone.utc)

    timestamps = _parse_dmon_asc_timestamps(entries)
    if not timestamps:
        # Entire window is an uncovered gap when no ASC files exist.
        span_h = (window_end - window_start).total_seconds() / 3600.0
        if span_h > gap_hours:
            return len(
                _utc_days_overlapping_interval(
                    window_start,
                    window_end,
                    window_start=window_start,
                    window_end=window_end,
                )
            )
        return 0

    gap_days: set[date] = set()
    # Include a file just before the window so a gap that starts earlier is visible.
    lookback = [t for t in timestamps if t < window_start]
    in_or_after = [t for t in timestamps if t >= window_start]
    sequence = (lookback[-1:] if lookback else []) + in_or_after

    prev: Optional[datetime] = None
    for ts in sequence:
        if prev is not None:
            gap_h = (ts - prev).total_seconds() / 3600.0
            if gap_h > gap_hours:
                gap_days |= _utc_days_overlapping_interval(
                    prev,
                    ts,
                    window_start=window_start,
                    window_end=window_end,
                )
        prev = ts

    if sequence:
        last_ts = sequence[-1]
        trailing_h = (window_end - last_ts).total_seconds() / 3600.0
        if trailing_h > gap_hours:
            gap_days |= _utc_days_overlapping_interval(
                last_ts,
                window_end,
                window_start=window_start,
                window_end=window_end,
            )
    return len(gap_days)


def extract_connection_durations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Extract surface-call connection durations from SFMC ``connectionsMap``.

    Returns list of ``{start, end, duration_seconds}`` (ISO UTC start/end).
    Incomplete connections (no end) are omitted.
    """
    if not isinstance(payload, dict):
        return []
    connections = payload.get("connectionsMap") or {}
    if not isinstance(connections, dict):
        return []

    out: list[dict[str, Any]] = []
    for conn in connections.values():
        if not isinstance(conn, dict):
            continue
        start_dt = _parse_sfmc_dt(conn.get("startDateTime"))
        end_dt = _parse_sfmc_dt(conn.get("endDateTime"))
        if start_dt is None or end_dt is None:
            continue
        if end_dt < start_dt:
            continue
        duration_seconds = (end_dt - start_dt).total_seconds()
        out.append(
            {
                "start": start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end": end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "duration_seconds": round(duration_seconds, 1),
            }
        )
    out.sort(key=lambda row: row["start"])
    return out


def merge_connection_durations(
    existing: Any,
    incoming: Any,
    *,
    max_days: int = 90,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """
    Merge connection-duration lists keyed by ``start``, retaining ~``max_days``.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(1, int(max_days)))

    by_start: dict[str, dict[str, Any]] = {}
    for source in (existing, incoming):
        if not isinstance(source, list):
            continue
        for row in source:
            if not isinstance(row, dict):
                continue
            start = str(row.get("start") or "").strip()
            if not start:
                continue
            start_dt = _parse_sfmc_dt(start)
            if start_dt is not None and start_dt < cutoff:
                continue
            duration = row.get("duration_seconds")
            try:
                duration_f = float(duration) if duration is not None else None
            except (TypeError, ValueError):
                duration_f = None
            end = str(row.get("end") or "").strip() or None
            by_start[start] = {
                "start": start if start.endswith("Z") else f"{start}Z" if "T" in start and "+" not in start else start,
                "end": end,
                "duration_seconds": duration_f,
            }

    merged = sorted(by_start.values(), key=lambda row: str(row.get("start") or ""))
    return merged