"""Tests for DMON ASC thruster surface-burst filter and subsurface stats."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from app.platforms.slocum.dmon_asc_thruster import (
    MIN_SAMPLE_DWELL,
    analyze_thruster_in_interval,
    build_thruster_event_pdf_rows,
    enrich_dmon_asc_with_thruster,
    format_thruster_event_hhmm,
    format_thruster_since_prev_detail,
    format_thruster_since_prev_summary,
)


def _ts(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(2026, 9, 1, hour, minute, second, tzinfo=timezone.utc)


def _dash_rows(rows: list[tuple[datetime, float | None, float | None, float | None]]) -> pd.DataFrame:
    """Build a dashboard frame: (Timestamp, MDepth, MThrusterPower, CThrusterOn)."""
    return pd.DataFrame(
        [
            {
                "Timestamp": ts,
                "MDepth": depth,
                "MThrusterPower": power,
                "CThrusterOn": cmd,
            }
            for ts, depth, power, cmd in rows
        ]
    )


def test_surface_only_thruster_is_no():
    start, end = _ts(10), _ts(12)
    df = _dash_rows(
        [
            (_ts(10, 30), 1.0, None, None),  # depth sample
            (_ts(10, 30, 5), None, 3.0, None),  # thruster near surface
        ]
    )
    stats = analyze_thruster_in_interval(df, start, end)
    assert stats.thruster_since_prev is False
    assert stats.thruster_event_count == 0
    assert stats.thruster_on_minutes_gt3m is None
    assert stats.thruster_events == []


def test_deep_only_thruster_is_yes_with_floor_minutes():
    start, end = _ts(10), _ts(12)
    df = _dash_rows(
        [
            (_ts(10, 30), 15.0, None, None),
            (_ts(10, 30, 5), None, 2.5, None),
        ]
    )
    stats = analyze_thruster_in_interval(df, start, end)
    assert stats.thruster_since_prev is True
    assert stats.thruster_event_count == 1
    assert stats.thruster_on_minutes_gt3m == round(MIN_SAMPLE_DWELL.total_seconds() / 60.0, 2)
    assert stats.thruster_depth_min_m == 15.0
    assert stats.thruster_depth_max_m == 15.0


def test_mixed_surface_and_deep_counts_deep_only():
    start, end = _ts(10), _ts(14)
    df = _dash_rows(
        [
            (_ts(10, 30), 1.2, None, None),
            (_ts(10, 30, 5), None, 3.0, None),  # surface burst
            (_ts(11, 0), 18.0, None, None),
            (_ts(11, 0, 10), None, 4.0, None),  # deep
            (_ts(11, 0, 40), None, 4.0, None),  # deep +30s same cluster
        ]
    )
    stats = analyze_thruster_in_interval(df, start, end)
    assert stats.thruster_since_prev is True
    assert stats.thruster_on_minutes_gt3m == round(30.0 / 60.0, 2)
    assert stats.thruster_depth_min_m == 18.0
    assert stats.thruster_depth_max_m == 18.0


def test_thruster_on_without_nearby_depth_is_no():
    start, end = _ts(10), _ts(12)
    # Depth sample more than 60s away from thruster-on.
    df = _dash_rows(
        [
            (_ts(10, 0), 20.0, None, None),
            (_ts(10, 30), None, 5.0, None),
        ]
    )
    stats = analyze_thruster_in_interval(df, start, end)
    assert stats.thruster_since_prev is False


def test_empty_interval_is_none():
    start, end = _ts(10), _ts(12)
    df = _dash_rows([(_ts(8), 10.0, 1.0, None)])
    stats = analyze_thruster_in_interval(df, start, end)
    assert stats.thruster_since_prev is None


def test_cluster_two_deep_samples_thirty_seconds():
    start, end = _ts(10), _ts(12)
    t0 = _ts(10, 45)
    t1 = t0 + timedelta(seconds=30)
    df = _dash_rows(
        [
            (t0, 12.0, 1.0, None),
            (t1, 14.0, 1.0, None),
        ]
    )
    stats = analyze_thruster_in_interval(df, start, end)
    assert stats.thruster_since_prev is True
    assert stats.thruster_on_minutes_gt3m == round(30.0 / 60.0, 2)
    assert stats.thruster_depth_min_m == 12.0
    assert stats.thruster_depth_max_m == 14.0
    assert len(stats.thruster_events) == 1
    assert stats.thruster_events[0]["start_utc"] == "2026-09-01T10:45:00Z"
    assert stats.thruster_events[0]["end_utc"] == "2026-09-01T10:45:30Z"
    assert stats.thruster_events[0]["hours_after_prev_asc"] == 0.75


def test_two_separated_clusters_emit_two_events():
    start, end = _ts(10), _ts(14)
    df = _dash_rows(
        [
            (_ts(11, 0), 12.0, 2.0, None),
            (_ts(13, 0), 25.0, 2.0, None),
        ]
    )
    stats = analyze_thruster_in_interval(df, start, end)
    assert stats.thruster_since_prev is True
    assert stats.thruster_event_count == 2
    assert len(stats.thruster_events) == 2
    assert stats.thruster_events[0]["start_utc"] == "2026-09-01T11:00:00Z"
    assert stats.thruster_events[0]["depth_min_m"] == 12.0
    assert stats.thruster_events[0]["hours_after_prev_asc"] == 1.0
    assert stats.thruster_events[1]["start_utc"] == "2026-09-01T13:00:00Z"
    assert stats.thruster_events[1]["depth_min_m"] == 25.0
    assert stats.thruster_events[1]["hours_after_prev_asc"] == 3.0
    assert stats.thruster_on_minutes_gt3m == round(30.0 / 60.0, 2)  # two 15s floors
    label0 = format_thruster_event_hhmm(stats.thruster_events[0])
    assert label0.startswith("11:00Z")
    assert "12 m" in label0
    assert "+1.0h" in label0


def test_enrich_and_format_detail():
    start = _ts(10)
    mid = _ts(11)
    end = _ts(12)
    df = _dash_rows(
        [
            (start + timedelta(minutes=10), 20.0, None, None),
            (start + timedelta(minutes=10, seconds=5), None, 2.0, None),
        ]
    )
    payload = {
        "files": [
            {"fileName": "a.asc", "dateTimeModified": start.strftime("%Y-%m-%dT%H:%M:%SZ")},
            {
                "fileName": "b.asc",
                "dateTimeModified": mid.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "gap_after_prev_hours": 1.0,
            },
            {
                "fileName": "c.asc",
                "dateTimeModified": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "gap_after_prev_hours": 1.0,
            },
        ]
    }
    out = enrich_dmon_asc_with_thruster(payload, df)
    first, second, third = out["files"]
    assert first["thruster_since_prev"] is None
    assert first.get("thruster_events") == []
    assert format_thruster_since_prev_detail(first, has_previous=False) == "—"
    assert second["thruster_since_prev"] is True
    assert second["thruster_event_count"] == 1
    assert len(second["thruster_events"]) == 1
    assert second["thruster_events"][0]["start_utc"].endswith("T10:10:05Z")
    label = format_thruster_since_prev_summary(second, has_previous=True)
    assert label.startswith("Yes · 1 event · ")
    assert "min" in label and "m" in label
    assert format_thruster_since_prev_detail(second, has_previous=True) == label
    assert third["thruster_since_prev"] is None
    assert format_thruster_since_prev_detail(third, has_previous=True) == "No data"


def test_many_clusters_emit_event_count_and_pdf_rows():
    start = _ts(0)
    end = start + timedelta(hours=24)
    dash_rows: list[tuple[datetime, float | None, float | None, float | None]] = []
    for i in range(50):
        t = start + timedelta(seconds=10 + i * 121)
        dash_rows.append((t, 12.0 + i, 2.0, None))
    df = _dash_rows(dash_rows)
    stats = analyze_thruster_in_interval(df, start, end)
    assert stats.thruster_since_prev is True
    assert stats.thruster_event_count == 50
    assert len(stats.thruster_events) == 50

    asc_files = [
        {
            "fileName": "many.asc",
            "gap_after_prev_hours": 1.0,
            "thruster_since_prev": True,
            "thruster_event_count": 50,
            "thruster_events": stats.thruster_events,
        }
    ]
    pdf_rows = build_thruster_event_pdf_rows(asc_files)
    assert len(pdf_rows) == 50
    assert pdf_rows[0]["event_num"] == 1
    assert pdf_rows[-1]["event_num"] == 50
    summary = format_thruster_since_prev_summary(
        {
            "thruster_since_prev": True,
            "thruster_event_count": 50,
            "thruster_on_minutes_gt3m": 12.5,
            "thruster_depth_min_m": 12.0,
            "thruster_depth_max_m": 61.0,
        },
        has_previous=True,
    )
    assert "50 events" in summary


def test_pdf_timing_table_builds_with_many_rows():
    from io import BytesIO

    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate

    from app.core.reporting.styling import build_paragraph_styles, styled_data_table

    events = [
        {
            "start_utc": "2026-09-01T10:00:00Z",
            "end_utc": "2026-09-01T10:00:15Z",
            "duration_s": 15.0,
            "depth_min_m": 12.0,
            "depth_max_m": 12.0,
            "hours_after_prev_asc": 1.0,
        }
        for _ in range(100)
    ]
    asc_files = [{"fileName": "stress.asc", "thruster_events": events}]
    rows = build_thruster_event_pdf_rows(asc_files)
    assert len(rows) == 100

    styles = build_paragraph_styles()
    table = styled_data_table(
        ["File", "Event #", "Time", "Duration", "Depth", "Offset"],
        [
            [
                r["file"],
                str(r["event_num"]),
                r["time_utc"],
                r["duration"],
                r["depth"],
                r["hours_after_prev_asc"],
            ]
            for r in rows
        ],
        styles=styles,
    )
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter)
    doc.build([table])
    assert len(buf.getvalue()) > 1000
