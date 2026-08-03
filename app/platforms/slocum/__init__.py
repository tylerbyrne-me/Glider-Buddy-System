"""
Slocum platform package — ERDDAP, mirrors, checklists, deployments.

HTTP routers remain under ``app.routers.slocum*`` and import from here.
"""

from .bundle_registry import BUNDLE_SCHEMA_VERSION, get_bundle_spec, list_bundle_names
from .erddap_client import fetch_slocum_data, list_slocum_datasets

__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "fetch_slocum_data",
    "get_bundle_spec",
    "list_bundle_names",
    "list_slocum_datasets",
]
