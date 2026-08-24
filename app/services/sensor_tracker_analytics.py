"""Live Sensor Tracker service-time analytics (days at sea / attached).

Calibration age and lifetime expectations are intentionally not computed yet;
callers should surface ``CALIBRATION_NOTE`` until Tracker fields or a local
overlay exist.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

Interval = Tuple[datetime, datetime]

SECONDS_PER_DAY = 86400.0
CALIBRATION_NOTE = (
    "Days since calibration and lifetime expectations are not computed yet."
)


def parse_window_time(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text.replace(" ", "T", 1))
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def interval_from_window(
    start: Any,
    end: Any,
    as_of: datetime,
) -> Optional[Interval]:
    start_dt = parse_window_time(start)
    if start_dt is None:
        return None
    end_dt = parse_window_time(end) or as_of
    if end_dt <= start_dt:
        return None
    return (start_dt, end_dt)


def merge_intervals(intervals: Sequence[Interval]) -> List[Interval]:
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda item: item[0])
    merged: List[Interval] = [ordered[0]]
    for start, end in ordered[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
            continue
        merged.append((start, end))
    return merged


def total_days(intervals: Sequence[Interval]) -> float:
    total = 0.0
    for start, end in merge_intervals(intervals):
        total += (end - start).total_seconds() / SECONDS_PER_DAY
    return round(total, 1)


def intersect_intervals(
    left: Sequence[Interval],
    right: Sequence[Interval],
) -> List[Interval]:
    out: List[Interval] = []
    for a0, a1 in merge_intervals(left):
        for b0, b1 in merge_intervals(right):
            start = max(a0, b0)
            end = min(a1, b1)
            if end > start:
                out.append((start, end))
    return merge_intervals(out)


def windows_to_intervals(
    windows: Iterable[Tuple[Any, Any]],
    as_of: datetime,
) -> List[Interval]:
    intervals: List[Interval] = []
    for start, end in windows:
        interval = interval_from_window(start, end, as_of)
        if interval is not None:
            intervals.append(interval)
    return intervals


def is_current_at(windows: Iterable[Tuple[Any, Any]], as_of: datetime) -> bool:
    for start, end in windows:
        start_dt = parse_window_time(start)
        if start_dt is None or start_dt > as_of:
            continue
        end_dt = parse_window_time(end)
        if end_dt is None or end_dt > as_of:
            return True
    return False


def open_windows(
    windows: Iterable[Tuple[Any, Any]],
    as_of: datetime,
) -> List[Tuple[Any, Any]]:
    """Keep relationship windows that are still open (or ending after) ``as_of``."""
    return [window for window in windows if is_current_at([window], as_of)]


def format_days(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value:.1f}"


def metric(key: str, label: str, value: Optional[str]) -> Dict[str, str]:
    return {"key": key, "label": label, "value": value if value is not None else "—"}


def build_analytics_payload(
    *,
    as_of: datetime,
    metrics: Sequence[Dict[str, str]],
    notes: Optional[Sequence[str]] = None,
    truncated: bool = False,
) -> Dict[str, Any]:
    payload_notes = list(notes or [])
    if CALIBRATION_NOTE not in payload_notes:
        payload_notes.append(CALIBRATION_NOTE)
    if truncated:
        payload_notes.append(
            "History capped at 500 Tracker rows; totals may be low."
        )
    return {
        "as_of": as_of.strftime("%Y-%m-%d %H:%M UTC"),
        "metrics": list(metrics),
        "notes": payload_notes,
        "truncated": truncated,
    }
