"""Slocum sensor summaries: one load per bundle and card-shape parity."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from app.platforms.slocum import summaries as summaries_mod


DATASET_ID = "peggy_20260621_226_realtime"


def _dashboard_df() -> pd.DataFrame:
    times = pd.to_datetime(
        ["2026-09-03T10:00:00Z", "2026-09-03T11:00:00Z", "2026-09-03T12:00:00Z"],
        utc=True,
    )
    return pd.DataFrame(
        {
            "Timestamp": times,
            "MBattery": [14.0, 13.9, 13.8],
            "MCoulombAmphrTotal": [10.0, 11.0, 12.0],
            "MPitch": [1.0, 2.0, 3.0],
            "MRoll": [0.1, 0.2, 0.3],
            "MHeading": [90.0, 91.0, 92.0],
            "MSpeed": [0.4, 0.5, 0.6],
            "MVacuum": [7.0, 7.1, 7.2],
            "MLeakdetectVoltage": [2.4, 2.4, 2.5],
            "SciDmonMsgByteCount": [100, 200, 300],
        }
    )


def _ctd_df() -> pd.DataFrame:
    times = pd.to_datetime(
        ["2026-09-03T11:00:00Z", "2026-09-03T11:00:00Z", "2026-09-03T12:00:00Z"],
        utc=True,
    )
    return pd.DataFrame(
        {
            "Timestamp": times,
            "Depth": [5.0, 1.0, 2.0],
            "Temperature": [8.0, 9.0, 10.0],
            "Salinity": [32.0, 32.1, 32.2],
            "Conductivity": [3.0, 3.1, 3.2],
            "Density": [1025.0, 1025.1, 1025.2],
            "Pressure": [1.0, 0.2, 0.4],
        }
    )


def test_build_summaries_loads_each_bundle_once():
    dashboard = _dashboard_df()
    ctd = _ctd_df()
    load_counts: dict[str, int] = {}

    def fake_load(dataset_id: str, bundle: str):
        assert dataset_id == DATASET_ID
        load_counts[bundle] = load_counts.get(bundle, 0) + 1
        if bundle == "ctd":
            return ctd.copy()
        return dashboard.copy()

    cards = ["ctd", "power", "flight", "navigation", "vehicle_health", "dmon"]
    with patch.object(summaries_mod, "resolve_slocum_dataset_id", side_effect=lambda v: v), patch.object(
        summaries_mod, "load_mirror_df", side_effect=fake_load
    ):
        context = summaries_mod.build_slocum_sensor_summaries(DATASET_ID, cards)

    assert load_counts == {"ctd": 1, "dashboard": 1}
    assert set(context["sensors"].keys()) == set(cards)
    for card in cards:
        payload = context["sensors"][card]
        assert set(payload.keys()) == {
            "values",
            "latest_timestamp_str",
            "time_ago_str",
            "mini_trend",
        }
        assert isinstance(payload["values"], dict)
        assert isinstance(payload["mini_trend"], list)


def test_disabled_cards_skip_bundle_loads():
    load_counts: dict[str, int] = {}

    def fake_load(_dataset_id: str, bundle: str):
        load_counts[bundle] = load_counts.get(bundle, 0) + 1
        return _dashboard_df()

    with patch.object(summaries_mod, "resolve_slocum_dataset_id", side_effect=lambda v: v), patch.object(
        summaries_mod, "load_mirror_df", side_effect=fake_load
    ):
        context = summaries_mod.build_slocum_sensor_summaries(DATASET_ID, ["power"])

    assert load_counts == {"dashboard": 1}
    assert "power" in context["sensors"]
    assert context["ctd_values"] == {}
    assert context["sensors"].get("ctd") is None
    assert context["power_values"].get("MBattery") == 13.8


def test_shared_dashboard_frame_powers_multiple_cards():
    dashboard = _dashboard_df()

    with patch.object(summaries_mod, "resolve_slocum_dataset_id", side_effect=lambda v: v), patch.object(
        summaries_mod, "load_mirror_df", return_value=dashboard
    ):
        context = summaries_mod.build_slocum_sensor_summaries(
            DATASET_ID, ["power", "flight", "navigation"]
        )

    assert context["sensors"]["power"]["values"]["MBattery"] == 13.8
    assert context["sensors"]["flight"]["values"]["MPitch"] == 3.0
    assert context["sensors"]["navigation"]["values"]["MHeading"] == 92.0
    # Flat SSR keys match nested sensors map.
    assert context["power_values"] == context["sensors"]["power"]["values"]
    assert context["flight_info"]["values"] == context["sensors"]["flight"]["values"]


def test_empty_and_malformed_mirrors_return_empty_shells():
    def fake_load(_dataset_id: str, bundle: str):
        if bundle == "ctd":
            raise RuntimeError("corrupt parquet")
        return pd.DataFrame({"not_timestamp": [1]})

    with patch.object(summaries_mod, "resolve_slocum_dataset_id", side_effect=lambda v: v), patch.object(
        summaries_mod, "load_mirror_df", side_effect=fake_load
    ):
        context = summaries_mod.build_slocum_sensor_summaries(DATASET_ID, ["ctd", "power"])

    for card in ("ctd", "power"):
        payload = context["sensors"][card]
        assert payload["values"] == {} or isinstance(payload["values"], dict)
        assert payload["latest_timestamp_str"]
        assert isinstance(payload["mini_trend"], list)
