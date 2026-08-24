"""Mission catalog discovery provider adapters."""

from app.services.mission_catalog_providers.erddap import discover_erddap
from app.services.mission_catalog_providers.legacy_env import discover_legacy_env
from app.services.mission_catalog_providers.sensor_tracker import discover_sensor_tracker
from app.services.mission_catalog_providers.wgms import discover_wgms_remote

__all__ = [
    "discover_erddap",
    "discover_legacy_env",
    "discover_sensor_tracker",
    "discover_wgms_remote",
]
