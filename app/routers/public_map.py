"""
Unauthenticated public login-map API.

Kill-switched by feature toggle ``public_login_map``. Mission allowlist is
active config ∩ DB ``public_map_enabled`` (see ``public_map_service``).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse

from ..core.infra.db import get_db_session, SQLModelSession
from ..core.infra.feature_toggles import is_feature_enabled
from ..core.infra.rate_limit import enforce_rate_limit
from ..core.public_map_service import (
    generate_public_kml_from_bundle,
    get_or_build_public_map_bundle,
    get_public_mission_allowlist,
    is_public_login_map_enabled,
    resolve_latest_weekly_report_disk_path,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Public Map"])

PlatformId = Literal["wave_glider", "slocum"]

_SAFE_RESOURCE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _require_public_map_enabled() -> None:
    if not is_public_login_map_enabled():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _parse_refresh_flag(refresh: Optional[str]) -> bool:
    if refresh is None:
        return False
    return str(refresh).strip().lower() in {"1", "true", "yes", "on"}


@router.get("/api/public/map/bundle")
async def get_public_map_bundle(
    request: Request,
    refresh: Optional[str] = Query(None, description="Set to 1 to bypass disk cache"),
    session: SQLModelSession = Depends(get_db_session),
):
    """Return allowlisted public tracks (lat/lon/timestamp only)."""
    _require_public_map_enabled()
    enforce_rate_limit(
        request,
        bucket="public_map_bundle",
        max_requests=60,
        window_seconds=60,
    )
    force = _parse_refresh_flag(refresh)
    if force:
        enforce_rate_limit(
            request,
            bucket="public_map_force_refresh",
            max_requests=6,
            window_seconds=3600,
        )

    try:
        bundle = await get_or_build_public_map_bundle(session, force_refresh=force)
    except Exception as exc:
        logger.error("PUBLICMAP: bundle endpoint failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Public map data temporarily unavailable.",
        ) from exc

    return JSONResponse(
        content=bundle,
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/api/public/map/kml")
async def get_public_map_kml(
    request: Request,
    refresh: Optional[str] = Query(None, description="Set to 1 to bypass disk cache"),
    session: SQLModelSession = Depends(get_db_session),
):
    """Static snapshot KML for all public allowlisted missions."""
    _require_public_map_enabled()
    enforce_rate_limit(
        request,
        bucket="public_map_kml",
        max_requests=10,
        window_seconds=3600,
    )
    force = _parse_refresh_flag(refresh)
    if force:
        enforce_rate_limit(
            request,
            bucket="public_map_force_refresh",
            max_requests=6,
            window_seconds=3600,
        )

    try:
        bundle = await get_or_build_public_map_bundle(session, force_refresh=force)
    except Exception as exc:
        logger.error("PUBLICMAP: kml endpoint failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Public map data temporarily unavailable.",
        ) from exc

    kml = generate_public_kml_from_bundle(bundle)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"public_gliders_{day}.kml"
    return Response(
        content=kml,
        media_type="application/vnd.google-earth.kml+xml",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "public, max-age=300",
        },
    )


@router.get("/api/public/reports/{platform}/{resource_id}/latest")
async def get_public_latest_weekly_report(
    platform: str,
    resource_id: str,
    request: Request,
    session: SQLModelSession = Depends(get_db_session),
):
    """Stream the latest weekly PDF when public_weekly_report_enabled is set."""
    _require_public_map_enabled()
    enforce_rate_limit(
        request,
        bucket="public_map_report",
        max_requests=20,
        window_seconds=3600,
    )

    if platform not in ("wave_glider", "slocum"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if not _SAFE_RESOURCE_ID.fullmatch(resource_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    if platform == "slocum" and not is_feature_enabled("slocum_platform"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    allowlist = get_public_mission_allowlist(session)
    match = None
    for ref in allowlist:
        if ref.platform != platform:
            continue
        if ref.report_resource_id == resource_id or ref.mission_id == resource_id:
            match = ref
            break
    if match is None or not match.public_weekly_report_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    pdf_path = resolve_latest_weekly_report_disk_path(
        platform,  # type: ignore[arg-type]
        match.report_resource_id,
        session=session,
    )
    if pdf_path is None or not Path(pdf_path).is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=Path(pdf_path).name,
        content_disposition_type="inline",
        headers={"Cache-Control": "public, max-age=300"},
    )
