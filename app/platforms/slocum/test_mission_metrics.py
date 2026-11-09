"""Tests for persisted Slocum mission distance metrics."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.core.models.database import SlocumMissionMetrics
from app.platforms.slocum import mission_metrics as mm


def _track_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "latitude": [44.0, 44.01, 44.02],
            "longitude": [-63.0, -63.0, -63.0],
            "lastLocationFix": pd.to_datetime(
                [
                    "2026-06-01T12:00:00Z",
                    "2026-06-01T13:00:00Z",
                    "2026-06-01T14:00:00Z",
                ],
                utc=True,
            ),
            "depth": [10.0, 12.0, 11.0],
        }
    )


def test_compute_slocum_total_distance_km_positive():
    km = mm.compute_slocum_total_distance_km(_track_frame())
    assert km is not None and km > 0


def test_upsert_from_track_frame_persists_row():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine, tables=[SlocumMissionMetrics.__table__])
    session = Session(engine)

    with patch(
        "app.platforms.slocum.mission_metrics._mirror_dashboard_last_ts",
        return_value=datetime(2026, 6, 1, 14, tzinfo=timezone.utc),
    ):
        row = mm.upsert_from_track_frame(
            session,
            mission_key="sable_20260621_224",
            dataset_id="sable_20260621_224_realtime",
            track_df=_track_frame(),
        )

    assert row.mission_key == "sable_20260621_224"
    assert row.total_distance_km is not None and row.total_distance_km > 0
    assert row.distance_method == mm.DISTANCE_METHOD
    assert row.source_erddap_dataset_id == "sable_20260621_224_realtime"
    assert row.calculation_version == mm.CALCULATION_VERSION


def test_refresh_skips_unchanged_tail():
    row = MagicMock()
    row.total_distance_km = 12.5
    row.calculation_version = mm.CALCULATION_VERSION
    row.source_erddap_dataset_id = "sable_20260621_224_realtime"
    row.dashboard_last_data_timestamp = datetime(2026, 6, 1, 14, tzinfo=timezone.utc)
    row.computed_at_utc = datetime(2026, 6, 1, 15, tzinfo=timezone.utc)

    session = MagicMock()
    session.get.return_value = row

    async def _run():
        with patch(
            "app.platforms.slocum.mission_metrics.resolved_slocum_mission_key",
            return_value="sable_20260621_224",
        ), patch(
            "app.platforms.slocum.mission_metrics.resolve_slocum_dataset_id",
            side_effect=lambda v: v,
        ), patch(
            "app.platforms.slocum.mission_metrics._mirror_dashboard_last_ts",
            return_value=row.dashboard_last_data_timestamp,
        ), patch(
            "app.platforms.slocum.mission_metrics.load_mission_track_dataframe",
            new=AsyncMock(),
        ) as load_track:
            out = await mm.refresh_slocum_mission_metrics(
                "sable_20260621_224_realtime", session=session, force=False
            )
            load_track.assert_not_awaited()
            assert out is row

    asyncio.run(_run())


def test_refresh_forces_on_dataset_change():
    row = MagicMock()
    row.total_distance_km = 12.5
    row.calculation_version = mm.CALCULATION_VERSION
    row.source_erddap_dataset_id = "sable_20260621_224_realtime"
    row.dashboard_last_data_timestamp = datetime(2026, 6, 1, 14, tzinfo=timezone.utc)
    row.computed_at_utc = datetime(2026, 6, 1, 15, tzinfo=timezone.utc)

    session = MagicMock()
    session.get.return_value = row
    updated = MagicMock()
    updated.total_distance_km = 20.0
    updated.computed_at_utc = datetime(2026, 6, 2, tzinfo=timezone.utc)

    async def _run():
        with patch(
            "app.platforms.slocum.mission_metrics.resolved_slocum_mission_key",
            return_value="sable_20260621_224",
        ), patch(
            "app.platforms.slocum.mission_metrics.resolve_slocum_dataset_id",
            side_effect=lambda v: v,
        ), patch(
            "app.platforms.slocum.mission_metrics._mirror_dashboard_last_ts",
            return_value=row.dashboard_last_data_timestamp,
        ), patch(
            "app.platforms.slocum.mission_metrics.load_mission_track_dataframe",
            new=AsyncMock(return_value=_track_frame()),
        ), patch(
            "app.platforms.slocum.mission_metrics.upsert_from_track_frame",
            return_value=updated,
        ) as upsert:
            out = await mm.refresh_slocum_mission_metrics(
                "sable_20260621_224_delayed", session=session, force=False
            )
            upsert.assert_called_once()
            assert out is updated

    asyncio.run(_run())


def test_resolve_mission_distance_db_only():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine, tables=[SlocumMissionMetrics.__table__])
    session = Session(engine)
    session.add(
        SlocumMissionMetrics(
            mission_key="sable_20260621_224",
            total_distance_km=123.4,
            calculation_version=1,
            computed_at_utc=datetime.now(timezone.utc),
        )
    )
    session.commit()

    with patch(
        "app.platforms.slocum.mission_metrics.resolved_slocum_mission_key",
        return_value="sable_20260621_224",
    ):
        assert mm.resolve_slocum_mission_distance_km(
            session, "sable_20260621_224_realtime"
        ) == pytest.approx(123.4)
