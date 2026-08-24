"""Source-neutral mission catalog package.

Separates mission identity from Sensor Tracker / ERDDAP / WGMS discovery providers.
"""

from app.core.mission_catalog.service import (
    list_catalog_missions,
    resolve_mission_sources,
)
from app.core.mission_catalog.enablement import list_catalog_sync_targets
from app.core.mission_catalog.schemas import (
    CatalogMissionRead,
    DiscoveryBatch,
    MissionCatalogQuery,
    MissionSourceRequest,
    MissionSourceResolution,
)

__all__ = [
    "CatalogMissionRead",
    "DiscoveryBatch",
    "MissionCatalogQuery",
    "MissionSourceRequest",
    "MissionSourceResolution",
    "list_catalog_missions",
    "list_catalog_sync_targets",
    "resolve_mission_sources",
]
