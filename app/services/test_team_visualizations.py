"""Unit tests for Team Visualizations aggregations (fake snapshots only)."""

from __future__ import annotations

from app.core.mission_catalog.providers_config import ProvidersManifest
from app.core.sensor_tracker.platform_display import enrich_rows_platform_names
from app.services.team_visualizations import (
    _platform_key,
    aggregate_platform_share,
    aggregate_sensor_days_by_platform,
    aggregate_use_over_time,
    classify_glider_platform_family,
    filter_snapshot_to_glider_platforms,
    resolve_instrument_attachments,
)


def _manifest() -> ProvidersManifest:
    return ProvidersManifest(
        providers=[],
        wave_glider_prefixes=["SV3", "DL", "SV2"],
        slocum_known_names=["fundy", "unit_2002"],
        allowed_platform_models={
            "Slocum Glider G3": "slocum",
            "Wave Glider SV3": "wave_glider",
        },
    )


def _fake_snapshot() -> dict:
    return {
        "as_of": "2024-07-01T00:00:00Z",
        "fetched_at": "2024-07-01T00:00:00Z",
        "truncated": False,
        "notes": [],
        "counts": {},
        "platforms": [
            {
                "id": 1,
                "name": "SV3-1001",
                "serial": "1001",
                "platform_family": "wave_glider",
                "model": "Wave Glider SV3",
            },
            {
                "id": 2,
                "name": "unit_2002",
                "serial": "2002",
                "platform_family": "slocum",
                "model": "Slocum Glider G3",
            },
        ],
        "deployments": [
            {
                "id": 10,
                "platform_id": 1,
                "platform_name": "SV3-1001",
                "start_time": "2024-01-01T00:00:00Z",
                "end_time": "2024-01-11T00:00:00Z",  # 10 days
            },
            {
                "id": 11,
                "platform_id": 1,
                "platform_name": "SV3-1001",
                "start_time": "2024-06-01T00:00:00Z",
                "end_time": "2024-06-06T00:00:00Z",  # 5 days
            },
            {
                "id": 20,
                "platform_id": 2,
                "platform_name": "unit_2002",
                "start_time": "2024-03-01T00:00:00Z",
                "end_time": "2024-03-21T00:00:00Z",  # 20 days
            },
        ],
        "instrument_attachments": [
            {
                "instrument_id": 100,
                "instrument_identifier": "GPCTD",
                "platform_id": 1,
                "platform_name": "SV3-1001",
                "start_time": "2023-01-01T00:00:00Z",
                "end_time": None,
                "via_logger": False,
            },
            {
                "instrument_id": 200,
                "instrument_identifier": "GPCTD",
                "platform_id": 2,
                "platform_name": "unit_2002",
                "start_time": "2023-01-01T00:00:00Z",
                "end_time": None,
                "via_logger": True,
            },
        ],
        "sensor_on_instrument": [
            {
                "sensor_id": 1,
                "sensor_identifier": "SBE43F",
                "instrument_id": 100,
                "instrument_identifier": "GPCTD",
                "start_time": "2023-01-01T00:00:00Z",
                "end_time": None,
            },
            {
                "sensor_id": 2,
                "sensor_identifier": "FLBBCD",
                "instrument_id": 100,
                "instrument_identifier": "GPCTD",
                "start_time": "2023-01-01T00:00:00Z",
                "end_time": None,
            },
            {
                "sensor_id": 3,
                "sensor_identifier": "SBE43F",
                "instrument_id": 200,
                "instrument_identifier": "GPCTD",
                "start_time": "2023-01-01T00:00:00Z",
                "end_time": None,
            },
        ],
    }


def test_classify_glider_platform_family_allowlist_and_heuristic():
    manifest = _manifest()
    assert (
        classify_glider_platform_family(
            platform_name="anything",
            model_name="Wave Glider SV3",
            manifest=manifest,
        )
        == "wave_glider"
    )
    assert (
        classify_glider_platform_family(
            platform_name="anything",
            model_name="Slocum Glider G3",
            manifest=manifest,
        )
        == "slocum"
    )
    # Model present but not allowlisted → exclude
    assert (
        classify_glider_platform_family(
            platform_name="SV3-9999",
            model_name="Mooring Buoy",
            manifest=manifest,
        )
        is None
    )
    # Model missing → name heuristic
    assert (
        classify_glider_platform_family(
            platform_name="SV3-1070 (C34164NS)",
            model_name=None,
            manifest=manifest,
        )
        == "wave_glider"
    )
    assert (
        classify_glider_platform_family(
            platform_name="fundy",
            model_name=None,
            manifest=manifest,
        )
        == "slocum"
    )
    assert (
        classify_glider_platform_family(
            platform_name="random-buoy",
            model_name=None,
            manifest=manifest,
        )
        is None
    )


def test_platform_key_prefers_name_then_numeric_id():
    assert _platform_key(288, "SV3-1071") == "SV3-1071"
    assert _platform_key(288, None) == "288"
    assert _platform_key(None, None) == "unknown"


def test_aggregate_platform_share_uses_enriched_hull_name():
    snap = _fake_snapshot()
    snap["deployments"] = [
        {
            "id": 50,
            "platform_id": 288,
            "platform_name": None,
            "start_time": "2024-01-01T00:00:00Z",
            "end_time": "2024-01-11T00:00:00Z",
        }
    ]
    snap["platforms"].append(
        {
            "id": 288,
            "name": "SV3-1071",
            "platform_family": "wave_glider",
            "model": "Wave Glider SV3",
        }
    )
    enrich_rows_platform_names(
        snap["deployments"],
        {288: "SV3-1071"},
    )
    data = aggregate_platform_share(snap)
    by_name = {r["platform"]: r for r in data["rows"]}
    assert "SV3-1071" in by_name
    assert "288" not in by_name
    assert "platform#288" not in by_name


def test_aggregate_platform_share_falls_back_to_numeric_id():
    snap = _fake_snapshot()
    snap["deployments"] = [
        {
            "id": 51,
            "platform_id": 9999,
            "platform_name": None,
            "start_time": "2024-01-01T00:00:00Z",
            "end_time": "2024-01-02T00:00:00Z",
        }
    ]
    data = aggregate_platform_share(snap)
    assert data["rows"][0]["platform"] == "9999"


def test_filter_snapshot_drops_non_glider_platforms():
    snap = _fake_snapshot()
    snap["platforms"].append(
        {
            "id": 99,
            "name": "buoy-1",
            "platform_family": None,
            "model": "Mooring Buoy",
        }
    )
    snap["deployments"].append(
        {
            "id": 99,
            "platform_id": 99,
            "platform_name": "buoy-1",
            "start_time": "2024-01-01T00:00:00Z",
            "end_time": "2024-02-01T00:00:00Z",
        }
    )
    snap["instrument_attachments"].append(
        {
            "instrument_id": 999,
            "platform_id": 99,
            "platform_name": "buoy-1",
            "start_time": "2023-01-01T00:00:00Z",
            "end_time": None,
        }
    )
    snap["sensor_on_instrument"].append(
        {
            "sensor_id": 9,
            "sensor_identifier": "BUOYTEMP",
            "instrument_id": 999,
            "start_time": "2023-01-01T00:00:00Z",
            "end_time": None,
        }
    )
    filtered = filter_snapshot_to_glider_platforms(snap)
    assert {p["id"] for p in filtered["platforms"]} == {1, 2}
    assert all(d["platform_id"] != 99 for d in filtered["deployments"])
    assert all(a["platform_id"] != 99 for a in filtered["instrument_attachments"])
    assert all(s["instrument_id"] != 999 for s in filtered["sensor_on_instrument"])
    assert filtered["counts"]["platforms"] == 2


def test_aggregate_platform_share_counts_and_days():
    data = aggregate_platform_share(_fake_snapshot())
    by_name = {r["platform"]: r for r in data["rows"]}
    assert by_name["SV3-1001"]["deployment_count"] == 2
    assert by_name["SV3-1001"]["days_at_sea"] == 15.0
    assert by_name["unit_2002"]["deployment_count"] == 1
    assert by_name["unit_2002"]["days_at_sea"] == 20.0
    # Sorted by days desc
    assert data["rows"][0]["platform"] == "unit_2002"


def test_aggregate_sensor_days_by_platform_stacks():
    data = aggregate_sensor_days_by_platform(_fake_snapshot(), top_n=12)
    assert "SV3-1001" in data["platforms"]
    assert "unit_2002" in data["platforms"]
    assert "SBE43F" in data["series"]
    assert "FLBBCD" in data["series"]
    idx_1001 = data["platforms"].index("SV3-1001")
    idx_2002 = data["platforms"].index("unit_2002")
    # Both sensors on SV3-1001 for full 15 deployment days
    assert data["series"]["SBE43F"][idx_1001] == 15.0
    assert data["series"]["FLBBCD"][idx_1001] == 15.0
    # Only SBE43F on unit_2002 for 20 days
    assert data["series"]["SBE43F"][idx_2002] == 20.0
    assert data["series"]["FLBBCD"][idx_2002] == 0.0


def test_aggregate_sensor_days_other_bucket():
    snap = _fake_snapshot()
    # Many unique sensors so top_n=1 forces Other
    for i in range(5):
        snap["sensor_on_instrument"].append(
            {
                "sensor_id": 100 + i,
                "sensor_identifier": f"EXTRA{i}",
                "instrument_id": 100,
                "start_time": "2023-01-01T00:00:00Z",
                "end_time": None,
            }
        )
    data = aggregate_sensor_days_by_platform(snap, top_n=1)
    assert "Other" in data["series"]
    assert sum(data["series"]["Other"]) > 0


def test_aggregate_use_over_time_monthly_and_grid():
    data = aggregate_use_over_time(_fake_snapshot())
    assert "2024-01" in data["months"]
    assert "2024-03" in data["months"]
    assert "2024-06" in data["months"]
    by_month = dict(zip(data["months"], data["values"]))
    assert by_month["2024-01"] == 10.0
    assert by_month["2024-03"] == 20.0
    assert by_month["2024-06"] == 5.0
    assert "2024" in data["years"]
    year_idx = data["years"].index("2024")
    # January = index 0, March = 2, June = 5
    assert data["grid"][year_idx][0] == 10.0
    assert data["grid"][year_idx][2] == 20.0
    assert data["grid"][year_idx][5] == 5.0


def test_resolve_instrument_attachments_logger_mounted():
    as_of = __import__("datetime").datetime(2024, 7, 1, tzinfo=__import__("datetime").timezone.utc)
    on_platform = []
    on_logger = [
        {
            "instrument": {"id": 50, "identifier": "CTD"},
            "data_logger": {"id": 7, "identifier": "science"},
            "start_time": "2024-01-01T00:00:00Z",
            "end_time": "2024-02-01T00:00:00Z",
        }
    ]
    logger_on_platform = [
        {
            "data_logger": {"id": 7, "identifier": "science"},
            "platform": {"id": 2, "name": "unit_2002"},
            "start_time": "2023-01-01T00:00:00Z",
            "end_time": None,
        }
    ]
    resolved = resolve_instrument_attachments(
        on_platform, on_logger, logger_on_platform, as_of
    )
    assert len(resolved) == 1
    assert resolved[0]["via_logger"] is True
    assert resolved[0]["platform_name"] == "unit_2002"
    assert resolved[0]["instrument_id"] == 50
