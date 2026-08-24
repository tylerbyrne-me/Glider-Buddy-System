"""WGMS folder resolution shared by sync and data loaders."""

from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, select

from app.config import settings
from app.core.infra.db import sqlite_engine
from app.core.models.database import CatalogExternalIdentity, CatalogMissionSource
from app.core.models.enums import CatalogIdentityKind
from app.core import utils

logger = logging.getLogger(__name__)


def resolve_wgms_folder_from_env(mission_id: str) -> Optional[str]:
    """Legacy REMOTE_MISSION_FOLDER_MAP_JSON lookup (exact + fuzzy)."""
    remote_mission_folder = settings.remote_mission_folder_map.get(mission_id)
    if remote_mission_folder is not None:
        return remote_mission_folder

    if "-" in mission_id:
        parts = mission_id.split("-", 1)
        if len(parts) == 2:
            lookup_key = f"{parts[0]} {parts[1]}"
            remote_mission_folder = settings.remote_mission_folder_map.get(lookup_key)
            if remote_mission_folder:
                return remote_mission_folder

    mission_base = utils.deployment_mission_code_from_mission_id(mission_id)
    for key, value in settings.remote_mission_folder_map.items():
        if (
            key.endswith(f" {mission_base}")
            or key.endswith(mission_base)
            or key == mission_base
            or f" {mission_base}" in key
            or key.endswith(f"-{mission_base}")
            or utils.deployment_mission_code_from_mission_id(key) == mission_base
        ):
            return value
    return None


def resolve_wgms_folder(
    mission_id: str,
    *,
    session: Optional[Session] = None,
    prefer_collection: Optional[str] = None,
) -> Optional[str]:
    """Resolve WGMS remote folder via catalog first, then legacy env map.

    ``prefer_collection`` may be ``output_realtime_missions`` or ``output_past_missions``.
    """
    owns = session is None
    db = session or Session(sqlite_engine)
    try:
        code = utils.deployment_mission_code_from_mission_id(mission_id) or mission_id
        identity = db.exec(
            select(CatalogExternalIdentity).where(
                CatalogExternalIdentity.identity_kind.in_(
                    [
                        CatalogIdentityKind.DEPLOYMENT_CODE.value,
                        CatalogIdentityKind.LEGACY_ENV_KEY.value,
                        CatalogIdentityKind.WGMS_FOLDER.value,
                    ]
                ),
                CatalogExternalIdentity.external_id.in_([mission_id, code]),
            )
        ).first()
        mission_uuid = identity.mission_id if identity else None
        if mission_uuid:
            sources = list(
                db.exec(
                    select(CatalogMissionSource).where(
                        CatalogMissionSource.mission_id == mission_uuid,
                        CatalogMissionSource.source_kind == "wgms_remote",
                        CatalogMissionSource.enabled == True,  # noqa: E712
                    )
                ).all()
            )
            if prefer_collection:
                preferred = [
                    s for s in sources if (s.collection or "") == prefer_collection
                ]
                if preferred:
                    sources = preferred + [s for s in sources if s not in preferred]
            sources.sort(key=lambda s: int(s.priority or 100))
            if sources:
                return sources[0].external_ref
            # Identity may itself be a folder
            folder_identity = db.exec(
                select(CatalogExternalIdentity).where(
                    CatalogExternalIdentity.mission_id == mission_uuid,
                    CatalogExternalIdentity.identity_kind
                    == CatalogIdentityKind.WGMS_FOLDER.value,
                )
            ).first()
            if folder_identity:
                return folder_identity.external_id
    except Exception as exc:
        logger.debug("Catalog WGMS folder resolve failed for %s: %s", mission_id, exc)
    finally:
        if owns:
            db.close()

    return resolve_wgms_folder_from_env(mission_id)
