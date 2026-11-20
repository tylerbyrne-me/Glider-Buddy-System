"""Combine VRL + mission offload audits into one operator-facing summary."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Optional

from app.services.offload_mission_audit import APPLYABLE_REASONS, MissionAuditFinding
from app.services.offload_vrl_audit import VrlMismatch

__all__ = [
    "build_consistency_summary",
]


def build_consistency_summary(
    *,
    vrl_findings: Iterable[VrlMismatch],
    mission_findings: Iterable[MissionAuditFinding],
    scanned_with_vrl: int,
    missions_scanned: list[str],
    dry_run: bool = True,
) -> dict[str, Any]:
    """
    Build a single JSON-friendly summary for log / VRL / mission consistency.

    Does not invent a third matcher — counts come from the existing audits only.
    """
    vrl_rows = list(vrl_findings)
    mission_rows = list(mission_findings)

    vrl_by_reason = dict(Counter(row.reason for row in vrl_rows))
    mission_by_reason = dict(Counter(row.reason for row in mission_rows))

    applyable_mission = [
        row
        for row in mission_rows
        if row.can_apply and row.reason in APPLYABLE_REASONS and row.log_id is not None
    ]
    failed_with_vrl = [
        row.log_id
        for row in mission_rows
        if row.reason == "failed_with_vrl" and row.log_id is not None
    ]
    stamp_mismatch_ids = sorted(
        {
            row.log_id
            for row in vrl_rows
            if row.reason == "vrl_stamp_far_from_log_time"
        }
    )

    return {
        "dry_run": dry_run,
        "vrl": {
            "scanned_with_vrl": scanned_with_vrl,
            "suspect_rows": len(vrl_rows),
            "unique_logs": len({row.log_id for row in vrl_rows}),
            "stamp_mismatch_logs": len(stamp_mismatch_ids),
            "stamp_mismatch_log_ids": stamp_mismatch_ids,
            "by_reason": vrl_by_reason,
            "stations": sorted({row.station_id for row in vrl_rows}),
        },
        "mission": {
            "missions_scanned": list(missions_scanned),
            "finding_rows": len(mission_rows),
            "unique_logs": len({row.log_id for row in mission_rows if row.log_id is not None}),
            "applyable_logs": len({row.log_id for row in applyable_mission}),
            "applyable_log_ids": sorted({row.log_id for row in applyable_mission if row.log_id}),
            "failed_with_vrl_log_ids": sorted(set(failed_with_vrl)),
            "by_reason": mission_by_reason,
            "no_matching_log": mission_by_reason.get("no_matching_log", 0),
            "no_station": mission_by_reason.get("no_station", 0),
            "stations": sorted(
                {row.station_id for row in mission_rows if row.station_id}
            ),
        },
        "highlights": {
            "vrl_stamp_mismatch": len(stamp_mismatch_ids),
            "mission_missing": mission_by_reason.get("mission_missing", 0),
            "mission_mismatch": mission_by_reason.get("mission_mismatch", 0),
            "failed_with_vrl": len(set(failed_with_vrl)),
            "no_matching_log": mission_by_reason.get("no_matching_log", 0),
            "no_station": mission_by_reason.get("no_station", 0),
            "mission_applyable": len({row.log_id for row in applyable_mission}),
        },
    }


def optional_station_filter_note(station_id: Optional[str]) -> str:
    return f" station={station_id}" if station_id else ""
