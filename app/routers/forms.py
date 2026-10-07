from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from typing import List, Optional
import logging
from pathlib import Path
from sqlmodel import select
from ..core import models
from ..core.infra.db import get_db_session, SQLModelSession
from ..core.infra.logging_config import get_request_id
from ..core.auth import get_current_active_user, get_optional_current_user
from ..config import settings
import json
from ..forms.form_definitions import get_static_form_schema
from ..core.templates import templates
from ..core.template_context import get_template_context
from ..core.platforms import PLATFORM_WAVE_GLIDER, html_path_for, platform_page_context
from ..core.forms.submission_queries import (
    DEFAULT_MISSION_LIST_DAYS,
    DEFAULT_MY_PIC_DAYS,
    PILOT_ALL_FORMS_HOURS,
    RECENT_PIC_HOURS,
    effective_days_window,
    list_submitted_form_summaries,
    submission_cutoff_for_days,
    submission_cutoff_for_hours,
)
from ..core.forms.pic_handoff_compare import build_pic_handoff_compare_current_values
from ..core.forms.pic_handoff_autofill import build_pic_handoff_autofilled_schema
from ..core.forms.pic_submit_service import (
    FormSubmitValidationError,
    persist_form_submission,
    update_form_submission,
)

router = APIRouter(tags=["Forms"])
logger = logging.getLogger(__name__)

# --- In-memory/local storage helpers (if using local_json mode) ---
DATA_STORE_DIR = Path(__file__).resolve().parent.parent.parent / "data_store"
LOCAL_FORMS_DB_FILE = DATA_STORE_DIR / "submitted_forms.json"
mission_forms_db: dict = {}

def _save_forms_to_local_json():
    if settings.forms_storage_mode == "local_json":
        DATA_STORE_DIR.mkdir(parents=True, exist_ok=True)
        serializable_db = {
            json.dumps(list(k)): v.model_dump(mode="json")
            for k, v in mission_forms_db.items()
        }
        try:
            with open(LOCAL_FORMS_DB_FILE, "w") as f:
                json.dump(serializable_db, f, indent=4)
            logger.info(f"Forms database saved to {LOCAL_FORMS_DB_FILE}")
        except IOError as e:
            logger.error(f"Error saving forms database to {LOCAL_FORMS_DB_FILE}: {e}")
        except TypeError as e:
            logger.error(f"TypeError saving forms database (serialization issue): {e}")
    elif settings.forms_storage_mode == "sqlite":
        logger.debug("Forms storage mode is 'sqlite'. JSON save skipped.")
    else:
        logger.warning(f"Unknown forms_storage_mode: {settings.forms_storage_mode}. Forms not saved to JSON.")

# --- API Endpoints ---
@router.get("/api/forms/all", response_model=models.SubmittedFormListResponse)
async def get_all_submitted_forms(
    days: Optional[int] = Query(
        None,
        description="Day window for non-pilot roles (default 7). Ignored for pilots (fixed 72h). Use 0 for no time filter.",
    ),
    limit: Optional[int] = Query(None, description="Page size (default 100, max 500)."),
    offset: Optional[int] = Query(None, description="Pagination offset."),
    session: SQLModelSession = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user),
):
    if current_user.role == models.UserRoleEnum.pilot:
        cutoff = submission_cutoff_for_hours(PILOT_ALL_FORMS_HOURS)
        # Echo days≈3 for UI; pilot window is hour-based.
        echo_days = max(1, PILOT_ALL_FORMS_HOURS // 24)
        return list_submitted_form_summaries(
            session,
            cutoff=cutoff,
            days=echo_days,
            limit=limit if limit is not None else 100,
            offset=offset if offset is not None else 0,
        )

    resolved_days = effective_days_window(days, default_days=DEFAULT_MISSION_LIST_DAYS)
    cutoff = submission_cutoff_for_days(resolved_days)
    return list_submitted_form_summaries(
        session,
        cutoff=cutoff,
        days=resolved_days,
        limit=limit if limit is not None else 100,
        offset=offset if offset is not None else 0,
    )

# Item IDs excluded from "changes since last PIC" highlighting (expected to change over time)
PIC_HANDOFF_EXCLUDED_CHANGE_IDS = {
    "current_mos_val",
    "current_pic_val",
    "last_pic_val",
    "current_battery_wh_val",
    "percent_battery_val",
    "tracker_battery_v_val",
    "tracker_last_update_val",
}

# Only compare these items: they are the ones the form template fills with current live data.
# User-filled fields (e.g. Light Status, Mission Status) are not compared, so they are never highlighted.
PIC_HANDOFF_COMPARABLE_ITEM_IDS = {
    "glider_id_val",
    "mission_title_val",
    "total_battery_val",
    "boats_in_area_val",
    "vessel_standoff_m_val",
    "recent_errors_val",
}


def _normalize_submitted_value(item: dict) -> str:
    """Normalize a submitted form item to a comparable string."""
    sub_val = item.get("value")
    sub_checked = item.get("is_checked")
    if sub_val is not None and str(sub_val).strip() != "":
        return str(sub_val).strip()
    if sub_checked is not None:
        return "true" if sub_checked else "false"
    return ""


@router.get("/api/forms/id/{form_db_id}", response_model=models.SubmittedForm)
async def get_submitted_form_by_id(
    form_db_id: int,
    session: SQLModelSession = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user)
):
    db_form = session.get(models.SubmittedForm, form_db_id)
    if not db_form:
        raise HTTPException(status_code=404, detail="Form not found")
    return db_form


@router.get("/api/forms/id/{form_db_id}/with-changes")
async def get_submitted_form_with_changes(
    form_db_id: int,
    session: SQLModelSession = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user),
):
    """Return the form and which item IDs have changed since submission. changed_item_ids is non-empty only when this form is the most recent PIC handoff for its mission."""
    db_form = session.get(models.SubmittedForm, form_db_id)
    if not db_form:
        raise HTTPException(status_code=404, detail="Form not found")
    if db_form.form_type != "pic_handoff_checklist":
        return {"form": db_form, "changed_item_ids": []}

    latest = session.exec(
        select(models.SubmittedForm)
        .where(
            models.SubmittedForm.form_type == "pic_handoff_checklist",
            models.SubmittedForm.mission_id == db_form.mission_id,
        )
        .order_by(models.SubmittedForm.submission_timestamp.desc())
        .limit(1)
    ).first()
    if not latest or latest.id != db_form.id:
        return {"form": db_form, "changed_item_ids": []}

    current_values = await build_pic_handoff_compare_current_values(
        db_form.mission_id, session, current_user
    )

    changed_item_ids: List[str] = []
    for section in db_form.sections_data or []:
        for item in section.get("items") or []:
            iid = item.get("id")
            if not iid or iid in PIC_HANDOFF_EXCLUDED_CHANGE_IDS:
                continue
            # Only compare items that the template populates with current data (live AIS, errors, mission title, sensors, etc.).
            # User-filled fields (Light Status, Mission Status, etc.) are not in this set, so they are never highlighted.
            if iid not in PIC_HANDOFF_COMPARABLE_ITEM_IDS and not (
                iid.startswith("sensor_") and iid.endswith("_status")
            ):
                continue
            submitted_str = _normalize_submitted_value(item)
            current_str = current_values.get(iid, "")
            if submitted_str != current_str:
                changed_item_ids.append(iid)

    return {"form": db_form, "changed_item_ids": changed_item_ids}


@router.get("/api/forms/pic_handoffs/my", response_model=models.SubmittedFormListResponse)
async def get_my_pic_handoff_submissions(
    days: Optional[int] = Query(
        None,
        description="Day window (default 90). Use 0 for no time filter.",
    ),
    limit: Optional[int] = Query(None, description="Page size (default 100, max 500)."),
    offset: Optional[int] = Query(None, description="Pagination offset."),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    resolved_days = effective_days_window(days, default_days=DEFAULT_MY_PIC_DAYS)
    cutoff = submission_cutoff_for_days(resolved_days)
    return list_submitted_form_summaries(
        session,
        form_type="pic_handoff_checklist",
        submitted_by_username=current_user.username,
        cutoff=cutoff,
        days=resolved_days,
        limit=limit if limit is not None else 100,
        offset=offset if offset is not None else 0,
    )


@router.get("/api/forms/pic_handoffs/recent", response_model=models.SubmittedFormListResponse)
async def get_recent_pic_handoff_submissions(
    limit: Optional[int] = Query(None, description="Page size (default 100, max 500)."),
    offset: Optional[int] = Query(None, description="Pagination offset."),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    cutoff = submission_cutoff_for_hours(RECENT_PIC_HOURS)
    return list_submitted_form_summaries(
        session,
        form_type="pic_handoff_checklist",
        cutoff=cutoff,
        days=1,
        limit=limit if limit is not None else 100,
        offset=offset if offset is not None else 0,
    )


@router.get(
    "/api/forms/pic_handoffs/mission/{mission_id}",
    response_model=models.SubmittedFormListResponse,
)
async def get_pic_handoff_submissions_for_mission(
    mission_id: str,
    days: Optional[int] = Query(
        None,
        description="Day window (default 7). Use 0 for no time filter (still paginated).",
    ),
    limit: Optional[int] = Query(None, description="Page size (default 100, max 500)."),
    offset: Optional[int] = Query(None, description="Pagination offset."),
    current_user: models.User = Depends(get_current_active_user),
    session: SQLModelSession = Depends(get_db_session),
):
    resolved_days = effective_days_window(days, default_days=DEFAULT_MISSION_LIST_DAYS)
    cutoff = submission_cutoff_for_days(resolved_days)
    return list_submitted_form_summaries(
        session,
        form_type="pic_handoff_checklist",
        mission_id=mission_id,
        cutoff=cutoff,
        days=resolved_days,
        limit=limit if limit is not None else 100,
        offset=offset if offset is not None else 0,
    )


@router.get("/api/forms/{mission_id}/template/{form_type}")
async def get_form_template(
    mission_id: str,
    form_type: str,
    refresh: bool = Query(
        False,
        description="When true (PIC only), force remote WGMS refresh. Default uses synced disk.",
    ),
    session: SQLModelSession = Depends(get_db_session),
    current_user: Optional[models.User] = Depends(get_optional_current_user),
):
    """
    Return a form schema. PIC handoff autofills from leader-synced disk by default;
    pass ``refresh=true`` to check upstream WGMS in parallel.
    """
    try:
        schema_obj = get_static_form_schema(form_type)
        if not schema_obj:
            raise HTTPException(status_code=404, detail="Form template not found")

        if form_type == "pic_handoff_checklist":
            if current_user is None:
                raise HTTPException(status_code=401, detail="Authentication required")
            return await build_pic_handoff_autofilled_schema(
                mission_id,
                session,
                current_user,
                refresh_upstream=bool(refresh),
            )

        return schema_obj.model_dump(mode="python")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in get_form_template")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {e} (request {get_request_id()})",
        )


def _can_edit_submitted_form(db_form: models.SubmittedForm, current_user: models.User) -> bool:
    return (
        current_user.role == models.UserRoleEnum.admin
        or db_form.submitted_by_username == current_user.username
    )


@router.put("/api/forms/id/{form_db_id}", response_model=models.SubmittedForm)
async def update_submitted_form(
    form_db_id: int,
    form_data: models.SubmittedFormUpdate,
    session: SQLModelSession = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user),
):
    """Update an existing submitted form in place. Original submitter or admin only."""
    db_form = session.get(models.SubmittedForm, form_db_id)
    if not db_form:
        raise HTTPException(status_code=404, detail="Form not found")
    if not _can_edit_submitted_form(db_form, current_user):
        raise HTTPException(status_code=403, detail="Not authorized to edit this form")

    try:
        return update_form_submission(
            session,
            db_form,
            sections_data=form_data.sections_data,
            form_title=form_data.form_title,
            current_user=current_user,
        )
    except FormSubmitValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error updating submitted form")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update form (request {get_request_id()})",
        ) from exc


@router.post("/api/forms/{mission_id}", response_model=models.SubmittedFormSubmitResponse)
async def submit_form(
    mission_id: str,
    form_data: models.SubmittedFormCreate,
    session: SQLModelSession = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user),
):
    """
    Accept a submitted form for a mission and save it to SQLite.

    Idempotent when ``client_submission_id`` is provided (scoped to submitter).
    Maps SQLite lock exhaustion to HTTP 503 with Retry-After.
    """
    try:
        submitted_form = persist_form_submission(
            session,
            mission_id=mission_id,
            form_type=form_data.form_type,
            form_title=form_data.form_title,
            sections_data=form_data.sections_data,
            current_user=current_user,
            catalog_mission_id=form_data.catalog_mission_id,
            client_submission_id=form_data.client_submission_id,
        )
        return models.SubmittedFormSubmitResponse(
            message="Form submitted successfully",
            id=int(submitted_form.id),
            mission_id=submitted_form.mission_id,
            catalog_mission_id=submitted_form.catalog_mission_id,
            submitted_by_username=submitted_form.submitted_by_username,
            submission_timestamp=submitted_form.submission_timestamp.isoformat(),
            client_submission_id=submitted_form.client_submission_id,
            request_id=get_request_id(),
        )
    except FormSubmitValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Error saving submitted form")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save form (request {get_request_id()})",
        ) from exc


# --- HTML Endpoints ---
def _wg_forms_page(request: Request, current_user, template_name: str, log_path: str):
    username_for_log = (
        current_user.username if current_user else "anonymous/unauthenticated"
    )
    logger.info(f"User '{username_for_log}' accessing {log_path}.")
    context = get_template_context(request=request, current_user=current_user)
    context.update(platform_page_context(PLATFORM_WAVE_GLIDER))
    return templates.TemplateResponse(template_name, context)


@router.get("/wave-glider/view_forms.html", response_class=HTMLResponse)
async def get_view_forms_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user),
):
    return _wg_forms_page(request, current_user, "view_forms.html", "/wave-glider/view_forms.html")


@router.get("/view_forms.html", response_class=HTMLResponse, include_in_schema=False)
async def get_view_forms_page_legacy():
    return RedirectResponse(url=html_path_for(PLATFORM_WAVE_GLIDER, "view_forms.html"), status_code=302)


@router.get("/wave-glider/my_pic_handoffs.html", response_class=HTMLResponse)
async def get_my_pic_handoffs_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    return _wg_forms_page(request, current_user, "my_pic_handoffs.html", "/wave-glider/my_pic_handoffs.html")


@router.get("/my_pic_handoffs.html", response_class=HTMLResponse, include_in_schema=False)
async def get_my_pic_handoffs_page_legacy():
    return RedirectResponse(url=html_path_for(PLATFORM_WAVE_GLIDER, "my_pic_handoffs.html"), status_code=302)


@router.get("/wave-glider/view_pic_handoffs.html", response_class=HTMLResponse)
async def get_view_pic_handoffs_page(
    request: Request,
    current_user: Optional[models.User] = Depends(get_optional_current_user)
):
    return _wg_forms_page(request, current_user, "view_pic_handoffs.html", "/wave-glider/view_pic_handoffs.html")


@router.get("/view_pic_handoffs.html", response_class=HTMLResponse, include_in_schema=False)
async def get_view_pic_handoffs_page_legacy():
    return RedirectResponse(url=html_path_for(PLATFORM_WAVE_GLIDER, "view_pic_handoffs.html"), status_code=302)
