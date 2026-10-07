"""Deterministic Wave Glider dashboard load-path regressions."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pandas as pd

from app.core.data import data_service as ds


def _frame(n: int = 3) -> pd.DataFrame:
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    return pd.DataFrame(
        {
            "Timestamp": [base] * n,
            "BatteryWattHours": [100.0] * n,
        }
    )


def test_auto_source_prefers_synced_then_remote():
    """Dashboard default (source_preference=None) tries synced before remote."""
    calls = []

    async def fake_synced(report_type, mission_id):
        calls.append(("synced", report_type))
        return None, "Synced: missing", None

    async def fake_remote(report_type, mission_id, current_user=None):
        calls.append(("remote", report_type))
        return _frame(), "Remote: example", datetime.now(timezone.utc)

    service = ds.DataService()
    ds.data_cache.clear()

    async def _run():
        with patch.object(ds, "_load_from_synced_storage", side_effect=fake_synced), patch.object(
            ds, "_load_from_remote_sources", side_effect=fake_remote
        ), patch.object(ds, "update_user_activity"), patch.object(ds, "update_cache_stats"):
            df, path, _ = await service.load("power", "m227", source_preference=None, hours_back=72)
            return df, path

    df, path = asyncio.run(_run())
    assert calls == [("synced", "power"), ("remote", "power")]
    assert path.startswith("Remote:")
    assert df is not None and not df.empty


def test_explicit_remote_skips_synced():
    calls = []

    async def fake_synced(*args, **kwargs):
        calls.append("synced")
        return _frame(), "Synced: should-not-run", None

    async def fake_remote(report_type, mission_id, current_user=None):
        calls.append("remote")
        return _frame(), "Remote: ok", datetime.now(timezone.utc)

    service = ds.DataService()
    ds.data_cache.clear()

    async def _run():
        with patch.object(ds, "_load_from_synced_storage", side_effect=fake_synced), patch.object(
            ds, "_load_from_remote_sources", side_effect=fake_remote
        ), patch.object(ds, "update_user_activity"), patch.object(ds, "update_cache_stats"):
            await service.load("power", "m227", source_preference="remote", hours_back=72)

    asyncio.run(_run())
    assert calls == ["remote"]


def test_force_refresh_uses_remote():
    calls = []

    async def fake_synced(*args, **kwargs):
        calls.append("synced")
        return _frame(), "Synced: no", None

    async def fake_remote(report_type, mission_id, current_user=None):
        calls.append("remote")
        return _frame(), "Remote: refresh", datetime.now(timezone.utc)

    service = ds.DataService()
    ds.data_cache.clear()

    async def _run():
        with patch.object(ds, "_load_from_synced_storage", side_effect=fake_synced), patch.object(
            ds, "_load_from_remote_sources", side_effect=fake_remote
        ), patch.object(ds, "update_user_activity"), patch.object(ds, "update_cache_stats"):
            await service.load(
                "power", "m227", source_preference=None, force_refresh=True, hours_back=72
            )

    asyncio.run(_run())
    assert calls == ["remote"]


def test_synced_cache_hit_reloads_when_mtime_changes(tmp_path: Path):
    service = ds.DataService()
    ds.data_cache.clear()

    mission = tmp_path / "m227"
    mission.mkdir()
    csv_path = mission / "Amps Power Summary Report.csv"
    csv_path.write_text("a\n1\n", encoding="utf-8")
    old_mtime = datetime(2026, 1, 1, tzinfo=timezone.utc)
    new_mtime = datetime(2026, 6, 1, tzinfo=timezone.utc)

    cache_key = ds.create_time_aware_cache_key(
        "power", "m227", None, None, 72, None, None
    )
    ds.data_cache[cache_key] = (
        _frame(),
        f"Synced: {mission}",
        old_mtime,
        old_mtime,
        old_mtime,
    )

    reload_calls = []

    async def fake_synced(report_type, mission_id):
        reload_calls.append(report_type)
        return _frame(5), f"Synced: {mission}", new_mtime

    async def _run():
        with patch.object(ds, "resolve_synced_mission_dir", return_value=mission), patch.object(
            ds, "_synced_file_mtime", return_value=new_mtime
        ), patch.object(ds, "_load_from_synced_storage", side_effect=fake_synced), patch.object(
            ds, "_load_from_remote_sources", new=AsyncMock(side_effect=AssertionError("no remote"))
        ), patch.object(ds, "update_user_activity"), patch.object(ds, "update_cache_stats"):
            df, path, mtime = await service.load(
                "power", "m227", source_preference=None, hours_back=72
            )
            return df, path, mtime

    df, path, mtime = asyncio.run(_run())
    assert reload_calls == ["power"]
    assert path.startswith("Synced:")
    assert mtime == new_mtime
    assert len(df) == 5


def test_synced_cache_hit_unchanged_mtime_skips_reload(tmp_path: Path):
    service = ds.DataService()
    ds.data_cache.clear()

    mission = tmp_path / "m227"
    mission.mkdir()
    mtime = datetime(2026, 6, 1, tzinfo=timezone.utc)
    cache_key = ds.create_time_aware_cache_key(
        "power", "m227", None, None, 72, None, None
    )
    ds.data_cache[cache_key] = (
        _frame(2),
        f"Synced: {mission}",
        mtime,
        mtime,
        mtime,
    )

    async def boom(*args, **kwargs):
        raise AssertionError("should not reload")

    async def _run():
        with patch.object(ds, "resolve_synced_mission_dir", return_value=mission), patch.object(
            ds, "_synced_file_mtime", return_value=mtime
        ), patch.object(ds, "_load_from_synced_storage", side_effect=boom), patch.object(
            ds, "update_user_activity"
        ), patch.object(ds, "update_cache_stats"):
            df, path, _ = await service.load(
                "power", "m227", source_preference=None, hours_back=72
            )
            return df, path

    df, path = asyncio.run(_run())
    assert path.startswith("Synced:")
    assert len(df) == 2


def test_get_synced_file_change_token(tmp_path: Path):
    mission = tmp_path / "m227"
    mission.mkdir()
    csv_path = mission / "Amps Power Summary Report.csv"
    csv_path.write_text("x\n1\n", encoding="utf-8")

    with patch.object(ds, "resolve_synced_mission_dir", return_value=mission):
        token = ds.get_synced_file_change_token("power", "m227")
    assert token is not None
    assert "T" in token


def test_dashboard_bounded_hours_constant():
    assert ds.DASHBOARD_BOUNDED_HOURS == 72
