"""Team hub: platform-agnostic admin sandbox (ops scripts + form tools)."""

import asyncio
import logging
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse
from sqlmodel import Session as SQLModelSession

from ..core import models
from ..core.auth import get_current_admin_user
from ..core.infra.db import get_db_session
from ..core.infra.feature_guards import require_feature_dep
from ..core.template_context import get_template_context
from ..core.templates import templates
from ..services.team_ops_catalog import get_ops_script, list_ops_scripts, run_ops_script
from ..services.team_sfmc_lognote import prepare_and_optionally_commit
from ..services.team_telemetry_hexbin import (
    generate_hexbin_sync,
    output_path_for,
    safe_output_filename,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Team"],
    dependencies=[
        Depends(require_feature_dep("team_hub")),
        Depends(get_current_admin_user),
    ],
)


@router.get("/team", response_class=HTMLResponse, include_in_schema=False)
async def get_team_hub_page(
    request: Request,
    current_user: models.User = Depends(get_current_admin_user),
):
    context = get_template_context(
        request=request,
        current_user=current_user,
        show_banner_nav=True,
        ops_scripts=list_ops_scripts(),
    )
    return templates.TemplateResponse("team/home.html", context)


@router.get("/team/sfmc-lognotes", response_class=HTMLResponse, include_in_schema=False)
async def get_sfmc_lognotes_page(
    request: Request,
    current_user: models.User = Depends(get_current_admin_user),
):
    context = get_template_context(
        request=request,
        current_user=current_user,
        show_banner_nav=True,
    )
    return templates.TemplateResponse("team/sfmc_lognotes.html", context)


@router.get("/team/telemetry-hexbin", response_class=HTMLResponse, include_in_schema=False)
async def get_telemetry_hexbin_page(
    request: Request,
    current_user: models.User = Depends(get_current_admin_user),
):
    context = get_template_context(
        request=request,
        current_user=current_user,
        show_banner_nav=True,
    )
    return templates.TemplateResponse("team/telemetry_hexbin.html", context)


@router.get("/api/team/scripts", response_model=List[models.OpsScriptInfo])
async def list_team_ops_scripts():
    return [
        models.OpsScriptInfo(
            id=spec.id,
            label=spec.label,
            description=spec.description,
            kind=spec.kind,
            href=spec.href,
        )
        for spec in list_ops_scripts()
    ]


@router.post("/api/team/scripts/{script_id}/run", response_model=models.OpsScriptRunResult)
async def run_team_ops_script(script_id: str):
    try:
        spec = get_ops_script(script_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown ops script: {script_id}",
        )
    if spec.kind != "run":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Script {script_id} is a tool page; open {spec.href}",
        )
    return await asyncio.to_thread(run_ops_script, script_id)


@router.post(
    "/api/team/sfmc-lognotes/dry-run",
    response_model=models.SfmcLognoteImportResult,
)
async def sfmc_lognotes_dry_run(
    body: models.SfmcLognoteImportRequest,
    current_user: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    return prepare_and_optionally_commit(
        session=session,
        username=current_user.username,
        alias=body.alias,
        json_text=body.json_text,
        after=body.after,
        before=body.before,
        no_date_filter=body.no_date_filter,
        include_in_report=body.include_in_report,
        dry_run=True,
    )


@router.post(
    "/api/team/sfmc-lognotes/post",
    response_model=models.SfmcLognoteImportResult,
)
async def sfmc_lognotes_post(
    body: models.SfmcLognoteImportRequest,
    current_user: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    return prepare_and_optionally_commit(
        session=session,
        username=current_user.username,
        alias=body.alias,
        json_text=body.json_text,
        after=body.after,
        before=body.before,
        no_date_filter=body.no_date_filter,
        include_in_report=body.include_in_report,
        dry_run=False,
    )


@router.post(
    "/api/team/telemetry-hexbin/generate",
    response_model=models.TelemetryHexbinResult,
)
async def telemetry_hexbin_generate(body: models.TelemetryHexbinRequest):
    return await asyncio.to_thread(
        generate_hexbin_sync,
        center_lat=body.center_lat,
        center_lon=body.center_lon,
        size_km=body.size_km,
        lon_min=body.lon_min,
        lon_max=body.lon_max,
        lat_min=body.lat_min,
        lat_max=body.lat_max,
        gridsize=body.gridsize,
        missions=body.missions,
        refresh=body.refresh,
        include_bathymetry=body.include_bathymetry,
        max_missions=body.max_missions,
    )


@router.get("/api/team/telemetry-hexbin/outputs/{filename}", include_in_schema=False)
async def telemetry_hexbin_download(filename: str):
    safe = safe_output_filename(filename)
    if not safe:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = output_path_for(safe)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, media_type="image/png", filename=safe)
