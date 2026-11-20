"""Tests for unified offload consistency summary."""

from app.services.offload_consistency_audit import build_consistency_summary
from app.services.offload_mission_audit import MissionAuditFinding
from app.services.offload_vrl_audit import VrlMismatch


def test_build_consistency_summary_counts_highlights():
    vrl = [
        VrlMismatch(
            log_id=1,
            station_id="HFX273",
            vrl_file_name="VR4-UWM_1_20260101000000.vrl",
            vrl_stamp_utc="2026-01-01T00:00:00+00:00",
            log_ref_utc="2025-01-01T00:00:00+00:00",
            delta_hours=8760.0,
            was_offloaded=False,
            created_by_source="user",
            reason="vrl_stamp_far_from_log_time",
        ),
        VrlMismatch(
            log_id=2,
            station_id="HFX273",
            vrl_file_name="VR4-UWM_1_20260101000000.vrl",
            vrl_stamp_utc="2026-01-01T00:00:00+00:00",
            log_ref_utc="2026-01-01T01:00:00+00:00",
            delta_hours=1.0,
            was_offloaded=True,
            created_by_source="user",
            reason="duplicate_vrl_worse_time_match",
        ),
    ]
    mission = [
        MissionAuditFinding(
            expected_mission_id="m227-SV3-1071",
            reason="mission_missing",
            station_id="HFX231",
            log_id=10,
            actual_mission_id=None,
            vrl_file_name="a.vrl",
            was_offloaded=True,
            session_ref_utc="2026-11-01T00:00:00+00:00",
            log_ref_utc="2026-11-01T00:01:00+00:00",
            serial_number="250644",
            can_apply=True,
        ),
        MissionAuditFinding(
            expected_mission_id="m219-SV3-1121",
            reason="no_station",
            station_id=None,
            log_id=None,
            actual_mission_id=None,
            vrl_file_name="b.vrl",
            was_offloaded=None,
            session_ref_utc="2026-05-01T00:00:00+00:00",
            log_ref_utc=None,
            serial_number="250483",
            can_apply=False,
        ),
        MissionAuditFinding(
            expected_mission_id="m227-SV3-1071",
            reason="no_matching_log",
            station_id="GULMPA02",
            log_id=None,
            actual_mission_id=None,
            vrl_file_name="c.vrl",
            was_offloaded=None,
            session_ref_utc="2026-11-04T00:00:00+00:00",
            log_ref_utc=None,
            serial_number="250418",
            can_apply=False,
        ),
        MissionAuditFinding(
            expected_mission_id="m227-SV3-1071",
            reason="failed_with_vrl",
            station_id="HFX001",
            log_id=99,
            actual_mission_id="m227-SV3-1071",
            vrl_file_name="d.vrl",
            was_offloaded=False,
            session_ref_utc="2026-11-02T00:00:00+00:00",
            log_ref_utc="2026-11-02T00:01:00+00:00",
            serial_number="1",
            can_apply=False,
        ),
    ]

    summary = build_consistency_summary(
        vrl_findings=vrl,
        mission_findings=mission,
        scanned_with_vrl=5,
        missions_scanned=["m227-SV3-1071", "m219-SV3-1121"],
        dry_run=True,
    )

    assert summary["dry_run"] is True
    assert summary["vrl"]["scanned_with_vrl"] == 5
    assert summary["vrl"]["stamp_mismatch_logs"] == 1
    assert summary["mission"]["applyable_logs"] == 1
    assert summary["mission"]["no_station"] == 1
    assert summary["mission"]["no_matching_log"] == 1
    assert summary["highlights"] == {
        "vrl_stamp_mismatch": 1,
        "mission_missing": 1,
        "mission_mismatch": 0,
        "failed_with_vrl": 1,
        "no_matching_log": 1,
        "no_station": 1,
        "mission_applyable": 1,
    }
