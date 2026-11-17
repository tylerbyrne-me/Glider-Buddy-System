"""Station offload progress map: overview rows → GeoJSON for Leaflet overlays."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.core import models
from app.core.stations.station_registry_policy import offload_log_matches_season_year
from app.services.station_history_service import (
    is_awaiting_first_offload_after_swap,
    latest_hardware_swap_ts_by_station,
)
from app.services.station_overview import (
    build_status_overview_row,
    station_status_rows_to_geojson,
)
from app.services.station_season_service import StationSeasonService


def _resolve_station_flag_state(
    events: List[models.StationFlagEvent],
    *,
    target_year: Optional[int],
    season_is_closed: bool,
) -> Dict[str, Dict[str, Any]]:
    state_by_station: Dict[str, Dict[str, Any]] = {}
    for event in sorted(events, key=lambda e: e.changed_at_utc):
        include_event = False
        if target_year is None:
            include_event = event.field_season_year is None
        elif offload_log_matches_season_year(
            log_season=event.field_season_year,
            target_year=target_year,
            season_is_closed=season_is_closed,
        ):
            include_event = True
        if not include_event:
            continue
        state_by_station[event.station_id] = {
            "is_flagged": bool(event.is_flagged),
            "flag_note": event.note,
            "changed_at_utc": event.changed_at_utc,
        }
    return state_by_station


def resolve_overview_season_context(
    session: Session,
    *,
    season_year: Optional[int] = None,
) -> Tuple[Optional[int], bool, str]:
    """Resolve (target_year, season_is_closed, source) for overview / map queries."""
    if season_year is not None:
        season_row = StationSeasonService.get_season_by_year(session, season_year)
        season_is_closed = bool(season_row and season_row.closed_at_utc) or (
            season_row is None
        )
        return season_year, season_is_closed, "explicit"
    return StationSeasonService.resolve_operational_season_context(session)


def list_station_status_overview(
    session: Session,
    *,
    season_year: Optional[int] = None,
    include_retired: bool = False,
) -> List[Dict[str, Any]]:
    """Live registry rows with season-scoped offload status (same as status_overview API).

    When ``season_year`` is omitted, uses
    :meth:`StationSeasonService.resolve_operational_season_context` (active open
    season, else most recent closed season).
    """
    statement = (
        select(models.StationMetadata)
        .options(selectinload(models.StationMetadata.offload_logs))
        .where(models.StationMetadata.is_archived == False)
        .order_by(models.StationMetadata.station_id)
    )
    if not include_retired:
        statement = statement.where(models.StationMetadata.is_retired == False)
    stations_metadata = list(session.exec(statement).all())

    station_ids = [s.station_id for s in stations_metadata]
    hardware_rows: List[models.StationHardwareHistory] = []
    if station_ids:
        hardware_rows = list(
            session.exec(
                select(models.StationHardwareHistory).where(
                    models.StationHardwareHistory.station_id.in_(station_ids)
                )
            ).all()
        )
    latest_swap_by_station = latest_hardware_swap_ts_by_station(hardware_rows)

    target_year, season_is_closed, _source = resolve_overview_season_context(
        session,
        season_year=season_year,
    )

    all_flag_events = list(session.exec(select(models.StationFlagEvent)).all())
    flag_state_by_station = _resolve_station_flag_state(
        all_flag_events,
        target_year=target_year,
        season_is_closed=season_is_closed,
    )

    overview_list: List[Dict[str, Any]] = []
    for station in stations_metadata:
        if target_year is None:
            relevant_logs = [
                log
                for log in station.offload_logs
                if log.field_season_year is None
            ]
        else:
            relevant_logs = [
                log
                for log in station.offload_logs
                if offload_log_matches_season_year(
                    log_season=log.field_season_year,
                    target_year=target_year,
                    season_is_closed=season_is_closed,
                )
            ]
        flag_state = flag_state_by_station.get(station.station_id, {})
        swap_ts = latest_swap_by_station.get(station.station_id)
        overview_list.append(
            build_status_overview_row(
                station,
                relevant_logs,
                is_flagged_for_scope=bool(flag_state.get("is_flagged")),
                flag_note=flag_state.get("flag_note"),
                awaiting_first_offload_after_swap=is_awaiting_first_offload_after_swap(
                    station.offload_logs,
                    swap_ts,
                ),
            )
        )
    return overview_list


def build_station_offload_status_geojson(
    session: Session,
    *,
    season_year: Optional[int] = None,
    include_retired: bool = False,
) -> Dict[str, Any]:
    target_year, season_is_closed, source = resolve_overview_season_context(
        session,
        season_year=season_year,
    )
    # Pass the resolved year explicitly so open vs closed matching is consistent
    # (operational resolve may fall back to a closed year when nothing is active).
    rows = list_station_status_overview(
        session,
        season_year=target_year,
        include_retired=include_retired,
    )
    collection = station_status_rows_to_geojson(rows)
    meta = dict(collection.get("meta") or {})
    meta.update(
        {
            "season_year": target_year,
            "season_is_closed": season_is_closed,
            "season_source": source,
        }
    )
    collection["meta"] = meta
    return collection
