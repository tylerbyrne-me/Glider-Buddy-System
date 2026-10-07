"""Mirror cache-status must stay metadata-only (no parquet parse on poll)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from app.platforms.slocum import mirror_service
from app.platforms.slocum.bundle_registry import DEFAULT_MIRROR_BUNDLES, get_bundle_spec


DATASET_ID = "peggy_20260621_226_realtime"


@pytest.fixture()
def mirror_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "slocum_cache"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mirror_service, "get_mirror_root", lambda: root)
    mirror_service.invalidate_memory_cache()
    yield root
    mirror_service.invalidate_memory_cache()


def _write_parquet(dataset_id: str, bundle: str, df: pd.DataFrame) -> Path:
    path = mirror_service._parquet_path(dataset_id, bundle)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return path


def _dashboard_df(last_ts: str = "2026-09-03T12:00:00Z") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Timestamp": pd.to_datetime([last_ts], utc=True),
            "MBattery": [14.2],
        }
    )


def test_cache_status_does_not_load_parquet(mirror_root: Path):
    df = _dashboard_df()
    path = _write_parquet(DATASET_ID, "dashboard", df)
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    mirror_service._write_meta(
        DATASET_ID,
        {
            "dataset_id": DATASET_ID,
            "last_data_timestamp": "2026-09-03T12:00:00+00:00",
            "bundles": {
                "dashboard": {
                    "row_count": 1,
                    "last_data_timestamp": "2026-09-03T12:00:00+00:00",
                    "schema_version": 14,
                    "file_mtime": mtime.isoformat(),
                }
            },
        },
    )

    with patch.object(
        mirror_service,
        "load_mirror_df",
        side_effect=AssertionError("cache-status must not parse parquet"),
    ):
        status = mirror_service.get_mirror_cache_status(DATASET_ID)

    assert status["dashboard"]["cached"] is True
    assert status["dashboard"]["row_count"] == 1
    assert status["dashboard"]["last_data_timestamp"] == "2026-09-03T12:00:00+00:00"
    assert status["dashboard"]["cache_timestamp"] is not None


def test_mtime_only_rewrite_advances_cache_timestamp(mirror_root: Path):
    path = _write_parquet(DATASET_ID, "dashboard", _dashboard_df())
    mirror_service._write_meta(
        DATASET_ID,
        {
            "dataset_id": DATASET_ID,
            "last_data_timestamp": "2026-09-03T12:00:00+00:00",
            "bundles": {
                "dashboard": {
                    "row_count": 1,
                    "last_data_timestamp": "2026-09-03T12:00:00+00:00",
                    "schema_version": 14,
                }
            },
        },
    )
    before = mirror_service.get_mirror_cache_status(DATASET_ID)["dashboard"]["cache_timestamp"]
    assert before is not None

    # Touch file without advancing the data tail (schema rebuild / rewrite case).
    new_mtime = path.stat().st_mtime + 5
    import os

    os.utime(path, (new_mtime, new_mtime))

    after = mirror_service.get_mirror_cache_status(DATASET_ID)["dashboard"]["cache_timestamp"]
    assert after is not None
    assert datetime.fromisoformat(after) > datetime.fromisoformat(before)
    assert (
        mirror_service.get_mirror_cache_status(DATASET_ID)["dashboard"]["last_data_timestamp"]
        == "2026-09-03T12:00:00+00:00"
    )


def test_legacy_meta_without_bundles_is_readable(mirror_root: Path):
    _write_parquet(DATASET_ID, "dashboard", _dashboard_df())
    # Pre-upgrade shape: dataset-level last_data only, no per-bundle map.
    mirror_service._write_meta(
        DATASET_ID,
        {
            "dataset_id": DATASET_ID,
            "last_data_timestamp": "2026-09-03T12:00:00+00:00",
            "last_sync_timestamp": "2026-09-03T12:05:00+00:00",
        },
    )

    with patch.object(
        mirror_service,
        "load_mirror_df",
        side_effect=AssertionError("legacy status must not parse parquet"),
    ):
        status = mirror_service.get_mirror_cache_status(DATASET_ID)

    assert status["dashboard"]["cached"] is True
    assert status["dashboard"]["last_data_timestamp"] == "2026-09-03T12:00:00+00:00"
    assert status["dashboard"]["row_count"] is None
    assert status["dashboard"]["cache_timestamp"] is not None


def test_failed_bundle_sync_preserves_prior_metadata(mirror_root: Path):
    path = _write_parquet(DATASET_ID, "dashboard", _dashboard_df("2026-09-03T10:00:00Z"))
    prior_meta = {
        "dataset_id": DATASET_ID,
        "last_data_timestamp": "2026-09-03T10:00:00+00:00",
        "bundles": {
            "dashboard": {
                "row_count": 1,
                "last_data_timestamp": "2026-09-03T10:00:00+00:00",
                "schema_version": 14,
                "file_mtime": datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                ).isoformat(),
            }
        },
        "bundle_schema_versions": {
            name: get_bundle_spec(name).schema_version for name in DEFAULT_MIRROR_BUNDLES
        },
    }
    mirror_service._write_meta(DATASET_ID, prior_meta)

    async def boom(*_args, **_kwargs):
        raise RuntimeError("erddap down")

    with patch.object(mirror_service, "resolve_slocum_dataset_id", side_effect=lambda v: v), patch.object(
        mirror_service, "is_historical_dataset", return_value=False
    ), patch.object(
        mirror_service, "_fetch_raw_bundle", side_effect=boom
    ), patch.object(
        mirror_service, "load_mirror_df", return_value=_dashboard_df("2026-09-03T10:00:00Z")
    ):
        summary = asyncio.run(mirror_service.sync_dataset_mirror(DATASET_ID, force=False))

    assert "error" in summary["bundles"]["dashboard"]
    meta = json.loads(mirror_service._meta_path(DATASET_ID).read_text(encoding="utf-8"))
    assert meta["bundles"]["dashboard"]["last_data_timestamp"] == "2026-09-03T10:00:00+00:00"
    assert meta["bundles"]["dashboard"]["row_count"] == 1
    assert meta["last_data_timestamp"] == "2026-09-03T10:00:00+00:00"
