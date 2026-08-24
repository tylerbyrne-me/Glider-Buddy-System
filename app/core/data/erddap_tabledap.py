"""Provider-neutral ERDDAP tabledap helpers.

Wave Glider and Slocum (and future platforms) should call these helpers instead of
platform-named fetch functions when only tabledap access is required.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
from erddapy import ERDDAP

from app.config import settings
from app.platforms.slocum import erddap_client as slocum_erddap

logger = logging.getLogger(__name__)


def list_tabledap_datasets(
    *,
    server: Optional[str] = None,
    dataset_id_filter: Optional[str] = None,
    search_term: Optional[str] = None,
) -> pd.DataFrame:
    """Query ERDDAP allDatasets metadata for tabledap datasets."""
    server_url = (server or settings.slocum_erddap_server).rstrip("/")
    e = ERDDAP(server=server_url, protocol="tabledap")
    e.response = "csv"
    e.dataset_id = "allDatasets"
    constraints: dict[str, str] = {}
    pattern = dataset_id_filter
    if pattern:
        constraints["datasetID=~"] = pattern
    e.constraints = constraints
    e.variables = ["datasetID", "title", "institution", "minTime", "maxTime"]
    logger.debug("Listing tabledap datasets from %s filter=%s", server_url, pattern)
    try:
        df = e.to_pandas(requests_kwargs=slocum_erddap._requests_kwargs())
    except Exception as err:
        logger.warning("ERDDAP allDatasets request failed for %s: %s", server_url, err)
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    if search_term and search_term.strip() and "title" in df.columns:
        term = search_term.strip().lower()
        mask = df["title"].astype(str).str.lower().str.contains(term, na=False)
        df = df.loc[mask]
    return df


def fetch_tabledap_data(
    dataset_id: str,
    *,
    server: Optional[str] = None,
    time_start: Optional[str] = None,
    time_end: Optional[str] = None,
    variables: Optional[list[str]] = None,
    pandas_kwargs: Optional[dict] = None,
    order_by_max_time: bool = False,
    order_by_closest_minutes: Optional[int] = None,
) -> pd.DataFrame:
    """Fetch tabledap CSV rows for any dataset on the given ERDDAP server.

    When ``server`` is omitted, uses the configured Ocean Track Slocum/WG server and
    reuses the battle-tested Slocum client path (variable inventory, retries).
    """
    server_url = (server or settings.slocum_erddap_server).rstrip("/")
    default_server = settings.slocum_erddap_server.rstrip("/")
    if server_url == default_server:
        return slocum_erddap.fetch_slocum_data(
            dataset_id=dataset_id,
            time_start=time_start,
            time_end=time_end,
            variables=variables,
            pandas_kwargs=pandas_kwargs,
            order_by_max_time=order_by_max_time,
            order_by_closest_minutes=order_by_closest_minutes,
        )

    # Alternate ERDDAP servers: lightweight direct fetch without Slocum inventory cache.
    requested = list(variables or slocum_erddap.DEFAULT_VARIABLES)
    e = ERDDAP(server=server_url, protocol="tabledap")
    e.response = "csv"
    e.dataset_id = dataset_id
    constraints: dict[str, str] = {}
    if not order_by_max_time:
        if time_start is not None:
            constraints["time>="] = time_start
        if time_end is not None:
            constraints["time<="] = time_end
    e.constraints = constraints
    e.variables = requested
    server_functions = slocum_erddap._build_server_functions(
        order_by_max_time, order_by_closest_minutes
    )
    to_pandas_kw = {"requests_kwargs": slocum_erddap._requests_kwargs()}
    if pandas_kwargs:
        to_pandas_kw.update(pandas_kwargs)
    try:
        return slocum_erddap._execute_erddap_download(
            e, server_functions, to_pandas_kw, pandas_kwargs
        )
    except Exception as err:
        logger.warning(
            "ERDDAP fetch failed for %s on %s: %s",
            dataset_id,
            server_url,
            err,
        )
        raise


def fetch_tabledap_track(
    dataset_id: str,
    *,
    server: Optional[str] = None,
    time_start: Optional[str] = None,
    time_end: Optional[str] = None,
) -> pd.DataFrame:
    """Fetch time/latitude/longitude track points from any tabledap dataset."""
    return fetch_tabledap_data(
        dataset_id,
        server=server,
        time_start=time_start,
        time_end=time_end,
        variables=["time", "latitude", "longitude"],
    )
