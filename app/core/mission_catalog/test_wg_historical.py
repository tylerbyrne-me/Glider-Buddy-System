"""Tests for Wave Glider historical key dedupe."""

from __future__ import annotations

from app.core.mission_catalog.wg_historical import (
    dedupe_wave_glider_historical_keys,
    preferred_wave_glider_historical_key,
)


def test_dedupe_prefers_folder_style_over_legacy_and_bare() -> None:
    keys = [
        "1070-m170",
        "m170-SV3-1070",
        "m170",
        "m209",
        "m209-SV3-1071",
        "1121-m171",
        "m171-SV3-1121",
    ]
    out = dedupe_wave_glider_historical_keys(keys)
    assert out == [
        "m170-SV3-1070",
        "m171-SV3-1121",
        "m209-SV3-1071",
    ]


def test_dedupe_keeps_single_legacy_when_no_folder_style() -> None:
    assert dedupe_wave_glider_historical_keys(["1070-m176", "m176"]) == [
        "m176"
    ]


def test_preferred_picks_best() -> None:
    assert (
        preferred_wave_glider_historical_key(["1071-m182", "m182-SV3-1071"])
        == "m182-SV3-1071"
    )
