"""Team hub: platform-agnostic admin sandbox (ops scripts + form tools)."""

import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, HTMLResponse
from sqlmodel import Session as SQLModelSession

from ..core import models
from ..core.auth import get_current_admin_user
from ..core.infra.db import get_db_session
from ..core.infra.feature_guards import require_feature_dep
from ..core.mission_catalog.service import list_unmatched_sources
from ..core.template_context import get_template_context
from ..core.templates import templates
from ..services.team_ops_catalog import get_ops_script, list_ops_scripts, run_ops_script
from ..services.team_sfmc_lognote import prepare_and_optionally_commit
from ..services.team_telemetry_hexbin import (
    generate_hexbin_sync,
    output_path_for,
    safe_output_filename,
)
from ..services.team_visualizations import (
    chart_png_path,
    gallery_catalog,
    generate_all_charts,
    generate_chart,
    safe_chart_slug,
)
from ..services.sensor_tracker_query import (
    ENTITY_REGISTRY,
    SensorTrackerQueryError,
    get_entity_detail,
    list_entities,
    list_entity_meta,
    list_related,
    lookup_buddy_deployment,
    get_entity_analytics,
)
from ..services import team_vmt_logbook as vmt_logbook

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


@router.get("/team/sensor-tracker", response_class=HTMLResponse, include_in_schema=False)
async def get_sensor_tracker_browser_page(
    request: Request,
    current_user: models.User = Depends(get_current_admin_user),
):
    context = get_template_context(
        request=request,
        current_user=current_user,
        show_banner_nav=True,
    )
    return templates.TemplateResponse("team/sensor_tracker.html", context)


@router.get("/team/visualizations", response_class=HTMLResponse, include_in_schema=False)
async def get_visualizations_page(
    request: Request,
    current_user: models.User = Depends(get_current_admin_user),
):
    context = get_template_context(
        request=request,
        current_user=current_user,
        show_banner_nav=True,
    )
    return templates.TemplateResponse("team/visualizations.html", context)


@router.get("/team/mission-catalog", response_class=HTMLResponse, include_in_schema=False)
async def get_mission_catalog_page(
    request: Request,
    current_user: models.User = Depends(get_current_admin_user),
):
    context = get_template_context(
        request=request,
        current_user=current_user,
        show_banner_nav=True,
    )
    return templates.TemplateResponse("team/mission_catalog.html", context)


@router.get("/api/team/mission-catalog/status")
async def get_catalog_status_report():
    from app.core.mission_catalog.status import build_catalog_status_report

    return build_catalog_status_report()


@router.get("/api/team/mission-catalog/missions")
async def list_catalog_workspace_missions(
    operational_state: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    session: SQLModelSession = Depends(get_db_session),
):
    from app.core.mission_catalog.workspace import (
        build_mission_list_item,
        list_workspace_missions,
    )

    missions = list_workspace_missions(
        session, operational_state=operational_state, limit=limit
    )
    return [build_mission_list_item(session, m) for m in missions]


@router.get("/api/team/mission-catalog/missions/{catalog_mission_id}")
async def get_catalog_workspace_mission(
    catalog_mission_id: str,
    session: SQLModelSession = Depends(get_db_session),
):
    from app.core.mission_catalog.workspace import (
        build_workspace_payload,
        get_catalog_mission,
    )

    mission = get_catalog_mission(session, catalog_mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Catalog mission not found")
    return build_workspace_payload(session, mission)


@router.post("/api/team/mission-catalog/missions/{catalog_mission_id}/enrollment")
async def set_catalog_enrollment_override(
    catalog_mission_id: str,
    override: str = Query(..., description="automatic | forced_on | forced_off"),
    session: SQLModelSession = Depends(get_db_session),
):
    from app.core.mission_catalog.workspace import (
        get_catalog_mission,
        set_enrollment_override,
    )

    mission = get_catalog_mission(session, catalog_mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Catalog mission not found")
    try:
        updated = set_enrollment_override(session, mission, override)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "id": updated.id,
        "enrollment_override": updated.enrollment_override,
        "sync_policy": updated.sync_policy,
        "operational_state": updated.operational_state,
    }


@router.post("/api/team/mission-catalog/missions/{catalog_mission_id}/provision")
async def retry_catalog_provisioning(
    catalog_mission_id: str,
    session: SQLModelSession = Depends(get_db_session),
):
    from app.core.mission_catalog.provisioning import provision_mission
    from app.core.mission_catalog.workspace import get_catalog_mission
    from app.services.sensor_tracker_sync_service import SensorTrackerSyncService

    mission = get_catalog_mission(session, catalog_mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="Catalog mission not found")
    result = provision_mission(session, mission, dry_run=False)
    st_synced = False
    try:
        sync_service = SensorTrackerSyncService()
        st_row = await sync_service.get_or_sync_catalog_mission(
            catalog_mission_id,
            force_refresh=True,
            session=session,
        )
        st_synced = st_row is not None
        if st_synced:
            result.actions.append("deep_st_sync")
    except Exception as exc:
        result.errors.append(f"deep_st_sync:{exc}")
    return {
        "mission_id": result.mission_id,
        "platform_family": result.platform_family,
        "readiness": result.readiness,
        "reasons": result.reasons,
        "actions": result.actions,
        "errors": result.errors,
        "st_synced": st_synced,
    }


@router.get("/api/team/mission-catalog/health")
async def get_catalog_health_report(
    session: SQLModelSession = Depends(get_db_session),
):
    from app.core.mission_catalog.health import build_catalog_health_report

    return build_catalog_health_report(session)


@router.get("/api/team/mission-catalog/unmatched-sources")
async def get_catalog_unmatched_sources(
    source_kind: Optional[str] = Query("erddap"),
    session: SQLModelSession = Depends(get_db_session),
):
    rows = list_unmatched_sources(session, source_kind=source_kind or "")
    return [row.model_dump(mode="json") for row in rows]


@router.get("/team/vmt-logbook", response_class=HTMLResponse, include_in_schema=False)
async def get_vmt_logbook_page(
    request: Request,
    current_user: models.User = Depends(get_current_admin_user),
):
    context = get_template_context(
        request=request,
        current_user=current_user,
        show_banner_nav=True,
    )
    return templates.TemplateResponse("team/vmt_logbook.html", context)


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
        source_filter=body.source_filter,
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


@router.get(
    "/api/team/visualizations",
    response_model=models.TeamVizGalleryResponse,
)
async def team_visualizations_catalog():
    return models.TeamVizGalleryResponse.model_validate(gallery_catalog())


@router.post(
    "/api/team/visualizations/generate-all",
    response_model=models.TeamVizGenerateAllResult,
)
async def team_visualizations_generate_all(
    body: Optional[models.TeamVizGenerateRequest] = None,
):
    req = body or models.TeamVizGenerateRequest()
    try:
        payload = await generate_all_charts(reuse_snapshot=req.reuse_snapshot)
    except SensorTrackerQueryError as exc:
        _raise_st_query_error(exc)
    except Exception as exc:
        logger.exception("Team visualizations generate-all failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc
    return models.TeamVizGenerateAllResult.model_validate(payload)


@router.post(
    "/api/team/visualizations/{slug}/generate",
    response_model=models.TeamVizChartGenerateResult,
)
async def team_visualizations_generate_one(
    slug: str,
    body: Optional[models.TeamVizGenerateRequest] = None,
):
    if safe_chart_slug(slug) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown chart: {slug}",
        )
    req = body or models.TeamVizGenerateRequest()
    try:
        payload = await generate_chart(slug, reuse_snapshot=req.reuse_snapshot)
    except SensorTrackerQueryError as exc:
        _raise_st_query_error(exc)
    except Exception as exc:
        logger.exception("Team visualizations generate failed for %s", slug)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc
    return models.TeamVizChartGenerateResult.model_validate(payload)


@router.get("/api/team/visualizations/{slug}/image", include_in_schema=False)
async def team_visualizations_image(slug: str):
    safe = safe_chart_slug(slug)
    if not safe:
        raise HTTPException(status_code=400, detail="Invalid chart slug")
    path = chart_png_path(safe)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Chart image not generated yet")
    return FileResponse(
        path,
        media_type="image/png",
        filename=f"{safe}.png",
        headers={"Cache-Control": "no-cache"},
    )


def _raise_st_query_error(exc: SensorTrackerQueryError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/api/team/sensor-tracker/meta", response_model=models.SensorTrackerMetaResponse)
async def sensor_tracker_meta():
    try:
        payload = await list_entity_meta()
    except SensorTrackerQueryError as exc:
        _raise_st_query_error(exc)
    return models.SensorTrackerMetaResponse.model_validate(payload)


@router.get("/api/team/sensor-tracker/{entity}", response_model=models.SensorTrackerListResponse)
async def sensor_tracker_list(
    entity: str,
    q: Optional[str] = None,
    page: int = 1,
    page_size: int = 25,
    platform_name: Optional[str] = None,
):
    if entity not in ENTITY_REGISTRY:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown entity: {entity}")
    extra = {}
    if platform_name:
        extra["platform_name"] = platform_name
    try:
        payload = await list_entities(
            entity,
            q=q,
            page=page,
            page_size=page_size,
            extra_filters=extra or None,
        )
    except SensorTrackerQueryError as exc:
        _raise_st_query_error(exc)
    return models.SensorTrackerListResponse.model_validate(payload)


@router.get(
    "/api/team/sensor-tracker/{entity}/{resource_id}",
    response_model=models.SensorTrackerDetailResponse,
)
async def sensor_tracker_detail(
    entity: str,
    resource_id: int,
    session: SQLModelSession = Depends(get_db_session),
):
    if entity not in ENTITY_REGISTRY:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown entity: {entity}")
    try:
        payload = await get_entity_detail(entity, resource_id)
    except SensorTrackerQueryError as exc:
        _raise_st_query_error(exc)
    buddy = None
    rec_id = payload.get("id")
    if entity == "deployment" and rec_id is not None:
        buddy = lookup_buddy_deployment(session, int(rec_id))
    payload["buddy"] = buddy
    return models.SensorTrackerDetailResponse.model_validate(payload)


@router.get(
    "/api/team/sensor-tracker/{entity}/{resource_id}/analytics",
    response_model=models.SensorTrackerAnalyticsResponse,
)
async def sensor_tracker_analytics(
    entity: str,
    resource_id: int,
):
    if entity not in ENTITY_REGISTRY:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown entity: {entity}")
    try:
        payload = await get_entity_analytics(entity, resource_id)
    except SensorTrackerQueryError as exc:
        _raise_st_query_error(exc)
    return models.SensorTrackerAnalyticsResponse.model_validate(payload)


@router.get(
    "/api/team/sensor-tracker/{entity}/{resource_id}/related/{relation}",
    response_model=models.SensorTrackerRelatedResponse,
)
async def sensor_tracker_related(
    entity: str,
    resource_id: int,
    relation: str,
    as_of: Optional[str] = Query(None),
    current: bool = Query(True),
    page: int = 1,
    page_size: int = 25,
):
    if entity not in ENTITY_REGISTRY:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown entity: {entity}")
    try:
        payload = await list_related(
            entity,
            resource_id,
            relation,
            as_of=as_of,
            current=current,
            page=page,
            page_size=page_size,
        )
    except SensorTrackerQueryError as exc:
        _raise_st_query_error(exc)
    return models.SensorTrackerRelatedResponse.model_validate(payload)


def _raise_vmt_error(exc: vmt_logbook.VmtLogbookError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get(
    "/api/team/vmt-logbook/units",
    response_model=models.VmtUnitListResponse,
)
async def vmt_logbook_list_units(
    include_inactive: bool = Query(False),
    session: SQLModelSession = Depends(get_db_session),
):
    try:
        return await vmt_logbook.list_units_with_overlay(
            session, include_inactive=include_inactive
        )
    except SensorTrackerQueryError as exc:
        _raise_st_query_error(exc)


@router.get(
    "/api/team/vmt-logbook/units/{unit_id}",
    response_model=models.VmtUnitDetail,
)
async def vmt_logbook_get_unit(
    unit_id: int,
    session: SQLModelSession = Depends(get_db_session),
):
    try:
        return await vmt_logbook.get_unit_detail_with_overlay(session, unit_id)
    except vmt_logbook.VmtLogbookError as exc:
        _raise_vmt_error(exc)
    except SensorTrackerQueryError as exc:
        _raise_st_query_error(exc)


@router.post(
    "/api/team/vmt-logbook/units",
    response_model=models.VmtUnitDetail,
    status_code=status.HTTP_201_CREATED,
)
async def vmt_logbook_create_unit(
    body: models.VmtUnitCreate,
    current_user: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    try:
        unit = vmt_logbook.create_unit(
            session, body, username=current_user.username
        )
        return await vmt_logbook.get_unit_detail_with_overlay(session, unit.id)
    except vmt_logbook.VmtLogbookError as exc:
        _raise_vmt_error(exc)


@router.patch(
    "/api/team/vmt-logbook/units/{unit_id}",
    response_model=models.VmtUnitDetail,
)
async def vmt_logbook_update_unit(
    unit_id: int,
    body: models.VmtUnitUpdate,
    current_user: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    try:
        vmt_logbook.update_unit(
            session, unit_id, body, username=current_user.username
        )
        return await vmt_logbook.get_unit_detail_with_overlay(session, unit_id)
    except vmt_logbook.VmtLogbookError as exc:
        _raise_vmt_error(exc)


@router.post(
    "/api/team/vmt-logbook/units/{unit_id}/battery-checks",
    response_model=models.VmtBatteryCheckRead,
    status_code=status.HTTP_201_CREATED,
)
async def vmt_logbook_add_battery_check(
    unit_id: int,
    body: models.VmtBatteryCheckCreate,
    current_user: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    try:
        row = vmt_logbook.append_battery_check(
            session, unit_id, body, username=current_user.username
        )
        return models.VmtBatteryCheckRead.model_validate(row)
    except vmt_logbook.VmtLogbookError as exc:
        _raise_vmt_error(exc)


@router.post(
    "/api/team/vmt-logbook/units/{unit_id}/service-events",
    response_model=models.VmtServiceEventRead,
    status_code=status.HTTP_201_CREATED,
)
async def vmt_logbook_add_service_event(
    unit_id: int,
    body: models.VmtServiceEventCreate,
    current_user: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    try:
        row = vmt_logbook.append_service_event(
            session, unit_id, body, username=current_user.username
        )
        return models.VmtServiceEventRead.model_validate(row)
    except vmt_logbook.VmtLogbookError as exc:
        _raise_vmt_error(exc)


@router.post(
    "/api/team/vmt-logbook/sync-from-sensor-tracker",
    response_model=models.VmtSyncResult,
)
async def vmt_logbook_sync_from_st(
    dry_run: bool = Query(True),
    current_user: models.User = Depends(get_current_admin_user),
    session: SQLModelSession = Depends(get_db_session),
):
    try:
        return await vmt_logbook.sync_vmt_units_from_sensor_tracker(
            session, username=current_user.username, dry_run=dry_run
        )
    except SensorTrackerQueryError as exc:
        _raise_st_query_error(exc)


@router.get(
    "/api/team/vmt-logbook/units/{unit_id}/st-accounting",
    response_model=models.VmtStAccountingResponse,
)
async def vmt_logbook_st_accounting(
    unit_id: int,
    session: SQLModelSession = Depends(get_db_session),
):
    try:
        return await vmt_logbook.get_st_accounting(session, unit_id)
    except vmt_logbook.VmtLogbookError as exc:
        _raise_vmt_error(exc)
    except SensorTrackerQueryError as exc:
        _raise_st_query_error(exc)
