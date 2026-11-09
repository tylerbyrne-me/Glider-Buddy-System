"""
Template configuration for the Wave Glider Buddy System.
"""
from typing import Any, Mapping, Optional

from fastapi.templating import Jinja2Templates as _Jinja2Templates
from pathlib import Path
from starlette.background import BackgroundTask
from starlette.requests import Request

# Path configuration
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "web" / "templates"


class Jinja2Templates(_Jinja2Templates):
    """
    Starlette 1.x requires TemplateResponse(request, name, context=...).

    The app historically called TemplateResponse(name, context) with
    ``context['request']`` set (via get_template_context). Accept both.
    """

    def TemplateResponse(
        self,
        name_or_request: Any,
        name_or_context: Any = None,
        context: Optional[dict[str, Any]] = None,
        status_code: int = 200,
        headers: Optional[Mapping[str, str]] = None,
        media_type: Optional[str] = None,
        background: Optional[BackgroundTask] = None,
    ):
        if isinstance(name_or_request, Request):
            return super().TemplateResponse(
                name_or_request,
                name_or_context,
                context=context,
                status_code=status_code,
                headers=headers,
                media_type=media_type,
                background=background,
            )

        # Legacy: TemplateResponse("page.html", {"request": request, ...})
        name = name_or_request
        ctx = name_or_context if isinstance(name_or_context, dict) else (context or {})
        request = ctx.get("request")
        if not isinstance(request, Request):
            raise TypeError(
                "TemplateResponse legacy call requires context['request'] "
                "(a starlette Request). Prefer TemplateResponse(request, name, context)."
            )
        return super().TemplateResponse(
            request,
            name,
            context=ctx,
            status_code=status_code,
            headers=headers,
            media_type=media_type,
            background=background,
        )


# Initialize Jinja2 templates (Starlette 1.x: directory path uses select_autoescape())
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
