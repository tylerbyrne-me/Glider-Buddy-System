"""Detect offload_logs whose vrl_file_name looks attached to the wrong attempt."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any, Iterable, Optional

from app.core.stations.vrl_filename import (
    log_reference_timestamp,
    parse_vrl_filename_timestamp,
)

__all__ = [
    "VrlMismatch",
    "audit_offload_logs_for_vrl_issues",
    "classify_vrl_mismatch",
    "find_duplicate_vrl_on_station",
    "log_reference_timestamp",
    "parse_vrl_filename_timestamp",
]


@dataclass(frozen=True)
class VrlMismatch:
    log_id: int
    station_id: str
    vrl_file_name: str
    vrl_stamp_utc: str
    log_ref_utc: str
    delta_hours: float
    was_offloaded: Optional[bool]
    created_by_source: Optional[str]
    reason: str

    def as_dict(self) -> dict:
        return asdict(self)


def classify_vrl_mismatch(
    log: Any,
    *,
    max_delta: timedelta,
) -> Optional[VrlMismatch]:
    """
    Return a mismatch when the VRL stamp and log attempt time disagree beyond max_delta.
    """
    vrl_name = getattr(log, "vrl_file_name", None)
    vrl_ts = parse_vrl_filename_timestamp(vrl_name)
    if vrl_ts is None:
        return None
    log_ts = log_reference_timestamp(log)
    if log_ts is None:
        return None
    delta = abs(vrl_ts - log_ts)
    if delta <= max_delta:
        return None
    return VrlMismatch(
        log_id=int(getattr(log, "id")),
        station_id=str(getattr(log, "station_id")),
        vrl_file_name=str(vrl_name).strip(),
        vrl_stamp_utc=vrl_ts.isoformat(),
        log_ref_utc=log_ts.isoformat(),
        delta_hours=round(delta.total_seconds() / 3600.0, 2),
        was_offloaded=getattr(log, "was_offloaded", None),
        created_by_source=getattr(log, "created_by_source", None),
        reason="vrl_stamp_far_from_log_time",
    )


def find_duplicate_vrl_on_station(logs: Iterable[Any]) -> list[VrlMismatch]:
    """
    Flag logs that share a VRL filename with a closer time-matched sibling on the same station.
    """
    by_key: dict[tuple[str, str], list[Any]] = {}
    for log in logs:
        name = (getattr(log, "vrl_file_name", None) or "").strip()
        if not name:
            continue
        station_id = str(getattr(log, "station_id"))
        by_key.setdefault((station_id, name), []).append(log)

    findings: list[VrlMismatch] = []
    for (station_id, name), group in by_key.items():
        if len(group) < 2:
            continue
        vrl_ts = parse_vrl_filename_timestamp(name)
        scored: list[tuple[float, Any]] = []
        for log in group:
            log_ts = log_reference_timestamp(log)
            if vrl_ts is None or log_ts is None:
                scored.append((float("inf"), log))
            else:
                scored.append((abs((vrl_ts - log_ts).total_seconds()), log))
        scored.sort(key=lambda item: item[0])
        best_delta, _best_log = scored[0]
        for delta_seconds, log in scored[1:]:
            if delta_seconds == best_delta and best_delta != float("inf"):
                continue
            log_ts = log_reference_timestamp(log)
            findings.append(
                VrlMismatch(
                    log_id=int(getattr(log, "id")),
                    station_id=station_id,
                    vrl_file_name=name,
                    vrl_stamp_utc=vrl_ts.isoformat() if vrl_ts else "",
                    log_ref_utc=log_ts.isoformat() if log_ts else "",
                    delta_hours=(
                        round(delta_seconds / 3600.0, 2)
                        if delta_seconds != float("inf")
                        else -1.0
                    ),
                    was_offloaded=getattr(log, "was_offloaded", None),
                    created_by_source=getattr(log, "created_by_source", None),
                    reason="duplicate_vrl_worse_time_match",
                )
            )
    return findings


def audit_offload_logs_for_vrl_issues(
    logs: Iterable[Any],
    *,
    max_delta_hours: float = 48.0,
) -> list[VrlMismatch]:
    """Combine stamp-vs-log and duplicate-VRL findings (deduped by log_id + reason)."""
    max_delta = timedelta(hours=max_delta_hours)
    findings: list[VrlMismatch] = []
    log_list = list(logs)
    for log in log_list:
        mismatch = classify_vrl_mismatch(log, max_delta=max_delta)
        if mismatch:
            findings.append(mismatch)
    findings.extend(find_duplicate_vrl_on_station(log_list))

    seen: set[tuple[int, str]] = set()
    unique: list[VrlMismatch] = []
    for item in findings:
        key = (item.log_id, item.reason)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    unique.sort(key=lambda row: (-row.delta_hours, row.station_id, row.log_id))
    return unique
