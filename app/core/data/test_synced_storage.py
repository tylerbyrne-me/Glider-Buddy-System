"""Tests for trusted synced local reads (PIC form path)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from app.core.data.data_service import resolve_synced_mission_dir


def test_resolve_synced_mission_dir_finds_code_and_rejects_traversal(tmp_path: Path):
    base = tmp_path / "data"
    mission = base / "m227"
    mission.mkdir(parents=True)

    with patch("app.core.data.data_service.settings") as settings:
        settings.local_data_base_path = base
        assert resolve_synced_mission_dir("m227") == mission.resolve()
        assert resolve_synced_mission_dir("1070-m227") == mission.resolve()
        # Path-like / traversal segments are rejected; only bare mission folder names join.
        assert resolve_synced_mission_dir("../etc") is None
        assert resolve_synced_mission_dir("..\\etc") is None
        assert resolve_synced_mission_dir("missing") is None
        # Embedded mission-code extraction may still map to the safe folder under base.
        assert resolve_synced_mission_dir("m227/../..") == mission.resolve()


def test_load_from_synced_storage_uses_base_only(tmp_path: Path):
    from app.core.data import data_service as ds

    base = tmp_path / "data"
    (base / "m227").mkdir(parents=True)

    async def fake_load_report(report_type, mission_id, base_path=None, **kwargs):
        assert Path(base_path).resolve() == base.resolve()
        assert mission_id == "m227"
        return pd.DataFrame({"a": [1]}), None

    async def _run():
        with patch.object(ds.settings, "local_data_base_path", base), patch(
            "app.core.data.data_service.loaders.load_report", side_effect=fake_load_report
        ):
            return await ds._load_from_synced_storage("power", "m227")

    df, path, _mtime = asyncio.run(_run())
    assert df is not None and not df.empty
    assert path.startswith("Synced:")
