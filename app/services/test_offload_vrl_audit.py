"""Unit tests for VRL attach audit heuristics."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.offload_vrl_audit import (
    audit_offload_logs_for_vrl_issues,
    parse_vrl_filename_timestamp,
)


def test_parse_vrl_filename_timestamp():
    ts = parse_vrl_filename_timestamp("VR4-UWM_250866_20261109190155.vrl")
    assert ts == datetime(2026, 11, 9, 19, 1, 55, tzinfo=timezone.utc)


def test_audit_flags_april_log_with_november_vrl():
    april = SimpleNamespace(
        id=353,
        station_id="HFX273",
        vrl_file_name="VR4-UWM_250866_20261109190155.vrl",
        offload_end_time_utc=None,
        offload_start_time_utc=datetime(2026, 4, 24, 22, 40, tzinfo=timezone.utc),
        time_first_command_sent_utc=None,
        arrival_date=None,
        log_timestamp_utc=datetime(2026, 4, 24, 22, 51, tzinfo=timezone.utc),
        was_offloaded=False,
        created_by_source="user",
    )
    nov = SimpleNamespace(
        id=1021,
        station_id="HFX273",
        vrl_file_name="VR4-UWM_250866_20261109190155.vrl",
        offload_end_time_utc=datetime(2026, 11, 9, 19, 3, tzinfo=timezone.utc),
        offload_start_time_utc=datetime(2026, 11, 9, 19, 1, tzinfo=timezone.utc),
        time_first_command_sent_utc=None,
        arrival_date=None,
        log_timestamp_utc=datetime(2026, 11, 9, 19, 8, tzinfo=timezone.utc),
        was_offloaded=True,
        created_by_source="user",
    )
    findings = audit_offload_logs_for_vrl_issues([april, nov], max_delta_hours=48)
    by_id = {f.log_id: f for f in findings}
    assert 353 in by_id
    assert by_id[353].reason in {
        "vrl_stamp_far_from_log_time",
        "duplicate_vrl_worse_time_match",
    }
    # Successful November attempt should not be flagged as a stamp mismatch.
    stamp_flags = [f for f in findings if f.log_id == 1021 and f.reason == "vrl_stamp_far_from_log_time"]
    assert stamp_flags == []
