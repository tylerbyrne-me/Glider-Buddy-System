"""Overage loader: interactive partial-mirror shortcut vs report full-window fetch."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pandas as pd

from app.platforms.slocum.overage_cache import (
    OverageRequest,
    _IN_FLIGHT,
    get_bundle_dataframe,
)

DATASET_ID = "peggy_20260621_226_realtime"


def _hourly_df(start: datetime, end: datetime, *, power: float) -> pd.DataFrame:
    times = pd.date_range(start, end, freq="1h", tz="UTC")
    return pd.DataFrame({"Timestamp": times, "MThrusterPower": power})


def _run_partial_mirror_request(*, context: str):
    """7-day request against a 72h rolling mirror; overage populate is mocked."""
    end = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
    start = end - timedelta(days=7)
    mirror_start = end - timedelta(hours=72)
    mirror_df = _hourly_df(mirror_start, end, power=0.0)
    overage_df = _hourly_df(start, end, power=1.0)
    populate_calls: list[dict] = []

    async def fake_populate(**kwargs):
        populate_calls.append(kwargs)
        return overage_df.copy(), {
            "created_at": "2026-09-03T12:00:00+00:00",
            "expires_at": "2026-09-04T12:00:00+00:00",
            "populated_from": "erddap_overage",
        }

    async def _run():
        _IN_FLIGHT.clear()
        request = OverageRequest(
            dataset_id=DATASET_ID,
            bundle="dashboard",
            start_utc=start,
            end_utc=end,
            context=context,  # type: ignore[arg-type]
        )
        try:
            return await get_bundle_dataframe(request, ensure_mirror=True)
        finally:
            _IN_FLIGHT.clear()

    with patch(
        "app.platforms.slocum.overage_cache.resolve_slocum_dataset_id",
        side_effect=lambda value: value,
    ), patch(
        "app.platforms.slocum.overage_cache.load_mirror_df",
        return_value=mirror_df,
    ), patch(
        "app.platforms.slocum.overage_cache.ensure_mirror_synced",
        new_callable=AsyncMock,
    ), patch(
        "app.platforms.slocum.overage_cache._load_cached_entry",
        return_value=None,
    ), patch(
        "app.platforms.slocum.overage_cache._populate_overage_entry",
        side_effect=fake_populate,
    ):
        result = asyncio.run(_run())
    return result, populate_calls, start, end, mirror_start


def test_interactive_context_returns_partial_mirror_without_erddap():
    result, populate_calls, _start, end, mirror_start = _run_partial_mirror_request(
        context="interactive"
    )
    assert populate_calls == []
    assert result.metadata.get("data_source") == "mirror"
    assert not result.df.empty
    ts = pd.to_datetime(result.df["Timestamp"], utc=True)
    assert ts.min() >= mirror_start
    span_hours = (ts.max() - ts.min()).total_seconds() / 3600.0
    assert span_hours <= 72.0 + 1e-6
    assert ts.max() <= end


def test_report_context_fetches_full_window_via_overage():
    result, populate_calls, start, end, _mirror_start = _run_partial_mirror_request(
        context="report"
    )
    assert len(populate_calls) == 1
    assert result.metadata.get("data_source") == "erddap_overage"
    assert not result.df.empty
    ts = pd.to_datetime(result.df["Timestamp"], utc=True)
    assert ts.min() <= start + timedelta(hours=1)
    span_hours = (ts.max() - ts.min()).total_seconds() / 3600.0
    assert span_hours >= 7 * 24 - 1
    assert ts.max() <= end
