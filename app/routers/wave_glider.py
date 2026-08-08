"""
Wave Glider dashboard APIs (sensor summaries soft-refresh, etc.).

Routes register under ``/api/...`` so the existing ``/api/wave_glider/...`` alias
middleware rewrites preferred client URLs to these handlers.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from ..core.auth import get_current_active_user, require_platform_access
from ..core import models
from ..core.infra.db import get_db_session, SQLModelSession
from app.platforms.wave_glider.summaries import (
    build_wave_glider_sensor_summaries,
    resolve_enabled_sensor_cards,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api",
    tags=["wave-glider"],
)


@router.get("/sensor-summaries/{mission_id}")
async def get_wave_glider_sensor_summaries(
    mission_id: str,
    source: Optional[str] = Query(
        None,
        description="Source preference for cache lookup (local/remote).",
    ),
    local_path: Optional[str] = Query(
        None,
        description="Local path when source=local.",
    ),
    current_user: models.User = Depends(get_current_active_user),
    _wg_access: models.User = Depends(require_platform_access("wave_glider")),
    session: SQLModelSession = Depends(get_db_session),
):
    """
    Left-nav sensor card summaries (values + mini_trend) for enabled WG cards.

    Used for soft refresh when cache last_data advances without a full page reload.
    Prefer calling via ``/api/wave_glider/sensor-summaries/{mission_id}``.
    """
    enabled_cards = resolve_enabled_sensor_cards(session, mission_id)
    summaries = await build_wave_glider_sensor_summaries(
        mission_id,
        enabled_cards,
        source_preference=source,
        custom_local_path=local_path if source == "local" else None,
        current_user=current_user,
        session=session,
    )
    return summaries.get("sensors") or {}
