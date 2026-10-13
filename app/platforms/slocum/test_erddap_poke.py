"""ERDDAP poke decision helpers: advanced / unchanged / unavailable / historical."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from app.platforms.slocum.erddap_poke import (
    evaluate_dataset_poke,
    has_new_erddap_data,
)


DATASET_ID = "peggy_20260621_226_realtime"
HISTORICAL_ID = "peggy_20250522_206_delayed"


def _dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


def test_has_new_when_no_mirror():
    assert has_new_erddap_data(_dt("2026-09-03T12:00:00Z"), None, has_mirror=False) is True


def test_has_new_when_erddap_ahead():
    assert (
        has_new_erddap_data(
            _dt("2026-09-03T13:00:00Z"),
            _dt("2026-09-03T12:00:00Z"),
            has_mirror=True,
        )
        is True
    )


def test_unchanged_when_erddap_equal_or_within_epsilon():
    known = _dt("2026-09-03T12:00:00Z")
    assert has_new_erddap_data(known, known, has_mirror=True) is False
    # Sub-second jitter ignored.
    assert (
        has_new_erddap_data(
            _dt("2026-09-03T12:00:00.500Z"),
            known,
            has_mirror=True,
        )
        is False
    )


def test_evaluate_advanced_pending():
    erddap_max = _dt("2026-09-03T14:00:00Z")
    known = _dt("2026-09-03T12:00:00Z")
    with patch(
        "app.platforms.slocum.erddap_poke.is_historical_dataset", return_value=False
    ), patch(
        "app.platforms.slocum.erddap_poke.known_mirror_max_time", return_value=known
    ), patch(
        "app.platforms.slocum.erddap_poke._has_dashboard_mirror", return_value=True
    ), patch(
        "app.platforms.slocum.erddap_poke.resolve_slocum_dataset_id",
        side_effect=lambda v: v,
    ):
        result = evaluate_dataset_poke(DATASET_ID, erddap_max)
    assert result["has_new_data"] is True
    assert result["action"] == "pending"
    assert result["reason"] == "erddap_max_advanced"


def test_evaluate_unchanged_skipped():
    known = _dt("2026-09-03T12:00:00Z")
    with patch(
        "app.platforms.slocum.erddap_poke.is_historical_dataset", return_value=False
    ), patch(
        "app.platforms.slocum.erddap_poke.known_mirror_max_time", return_value=known
    ), patch(
        "app.platforms.slocum.erddap_poke._has_dashboard_mirror", return_value=True
    ), patch(
        "app.platforms.slocum.erddap_poke.resolve_slocum_dataset_id",
        side_effect=lambda v: v,
    ):
        result = evaluate_dataset_poke(DATASET_ID, known)
    assert result["has_new_data"] is False
    assert result["action"] == "skipped"
    assert result["reason"] == "unchanged"


def test_evaluate_unavailable_error():
    with patch(
        "app.platforms.slocum.erddap_poke.is_historical_dataset", return_value=False
    ), patch(
        "app.platforms.slocum.erddap_poke.known_mirror_max_time", return_value=None
    ), patch(
        "app.platforms.slocum.erddap_poke._has_dashboard_mirror", return_value=False
    ), patch(
        "app.platforms.slocum.erddap_poke.resolve_slocum_dataset_id",
        side_effect=lambda v: v,
    ):
        result = evaluate_dataset_poke(DATASET_ID, None)
    assert result["action"] == "error"
    assert result["reason"] == "erddap_max_unavailable"
    assert result["has_new_data"] is False


def test_evaluate_historical_skipped():
    with patch(
        "app.platforms.slocum.erddap_poke.is_historical_dataset", return_value=True
    ), patch(
        "app.platforms.slocum.erddap_poke.resolve_slocum_dataset_id",
        side_effect=lambda v: v,
    ):
        result = evaluate_dataset_poke(HISTORICAL_ID, _dt("2026-09-03T12:00:00Z"))
    assert result["action"] == "skipped"
    assert result["reason"] == "historical"
    assert result["has_new_data"] is False
