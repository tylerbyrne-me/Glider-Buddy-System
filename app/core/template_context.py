"""
Template context processor for adding global context variables to all templates.
"""
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from pathlib import Path
import json

from .infra.feature_toggles import get_feature_context
from .platforms import (
    PLATFORM_WAVE_GLIDER,
    PRODUCT_FAVICON_PATH,
    PRODUCT_FAVICON_SVG_PATH,
    PRODUCT_NAME_FULL,
    PRODUCT_NAME_SHORT,
    TEAM_DISPLAY_NAME,
    TEAM_HOME_URL,
    buddy_title_for,
    display_name_for,
    home_url_for,
    is_known_platform,
    is_team_path,
    platform_labels_map,
    resolve_platform_from_path,
    team_buddy_title,
)
from ..config import settings


def _get_static_version_token() -> str:
    """Build a cache-busting token from key static asset mtimes."""
    try:
        repo_root = Path(__file__).resolve().parents[2]
        static = repo_root / "web" / "static"
        tracked_files = [
            static / "js" / "dashboard.js",
            static / "js" / "datetime_utils.js",
            static / "js" / "wg_vm4.js",
            static / "js" / "auth.js",
            static / "js" / "ui_preferences.js",
            static / "js" / "user_settings.js",
            static / "css" / "themes.css",
            static / "css" / "custom.css",
        ]
        mtimes = [str(int(path.stat().st_mtime)) for path in tracked_files if path.exists()]
        if mtimes:
            return "-".join(mtimes)
    except Exception:
        pass
    return "1.0.0"


def _brand_context(platform: Optional[str] = None) -> Dict[str, Any]:
    """Product + platform-aware brand strings for templates."""
    display = display_name_for(platform) if is_known_platform(platform) else None
    return {
        "app_name": PRODUCT_NAME_FULL,
        "app_name_short": PRODUCT_NAME_SHORT,
        "app_favicon": PRODUCT_FAVICON_PATH,
        "app_favicon_svg": PRODUCT_FAVICON_SVG_PATH,
        "platform_buddy_title": buddy_title_for(platform),
        "platform_display_name": display,
        "platform_labels_json": json.dumps(platform_labels_map()),
    }


def _team_brand_context() -> Dict[str, Any]:
    """Banner/brand strings for the Team area (not a vehicle PlatformSpec)."""
    return {
        "app_name": PRODUCT_NAME_FULL,
        "app_name_short": PRODUCT_NAME_SHORT,
        "app_favicon": PRODUCT_FAVICON_PATH,
        "app_favicon_svg": PRODUCT_FAVICON_SVG_PATH,
        "platform": None,
        "is_team_area": True,
        "platform_home_url": TEAM_HOME_URL,
        "platform_buddy_title": team_buddy_title(),
        "platform_display_name": TEAM_DISPLAY_NAME,
        "platform_labels_json": json.dumps(platform_labels_map()),
        "show_banner_nav": True,
    }


def get_platform_context_from_request(request: Any) -> Dict[str, Any]:
    """
    Derive platform and platform_home_url from request path for platform-aware nav.
    URL is source of truth; no session/cookie for current platform.
    """
    url = getattr(request, "url", None)
    path = (url.path if url is not None else "") or getattr(request, "path", "") or ""
    if is_team_path(path):
        return _team_brand_context()
    platform = resolve_platform_from_path(path)
    home = home_url_for(platform) if platform else home_url_for(PLATFORM_WAVE_GLIDER)
    ctx = {
        "platform": platform,
        "is_team_area": False,
        "platform_home_url": home,
    }
    ctx.update(_brand_context(platform))
    return ctx


def resolve_admin_platform_context(platform: Optional[str] = None) -> Dict[str, Any]:
    """Banner context for shared admin pages (?platform=wave_glider|slocum)."""
    normalized = platform if is_known_platform(platform) else PLATFORM_WAVE_GLIDER
    ctx = {
        "platform": normalized,
        "platform_home_url": home_url_for(normalized),
        "show_banner_nav": True,
    }
    ctx.update(_brand_context(normalized))
    return ctx


def get_global_template_context() -> Dict[str, Any]:
    """
    Get global context variables that should be available in all templates.
    
    Returns:
        dict: Global template context variables
    """
    context = get_feature_context()
    
    context.update({
        **_brand_context(None),
        "is_team_area": False,
        "app_version": _get_static_version_token(),
        "current_year": datetime.now().year,
        "current_utc": datetime.now(timezone.utc),
        
        "active_missions": settings.active_realtime_missions,
        "mission_count": len(settings.active_realtime_missions),
        "forms_storage_mode": settings.forms_storage_mode,
        
        "is_production": not settings.jwt_secret_key.startswith("CHANGE_THIS"),
        "is_development": settings.jwt_secret_key.startswith("CHANGE_THIS"),
        
        "feature_summary": {
            "enabled_count": context.get("feature_count", 0),
            "total_count": context.get("total_features", 0),
            "has_admin_features": context.get("has_admin_features", False),
            "has_user_features": context.get("has_user_features", False),
        }
    })
    
    return context


def get_template_context(**kwargs) -> Dict[str, Any]:
    """
    Helper function to create template context with feature toggles and global context.
    If 'request' is in kwargs, adds platform and platform_home_url from request path.
    
    Args:
        **kwargs: Additional context variables (e.g. request, current_user, active_missions)
        
    Returns:
        dict: Template context with feature toggles and global context
    """
    context = get_global_template_context()
    request = kwargs.pop("request", None)
    if request is not None:
        context["request"] = request
        context.update(get_platform_context_from_request(request))
    context.update(kwargs)
    if context.get("is_team_area"):
        context.update(_team_brand_context())
        if "show_banner_nav" in kwargs:
            context["show_banner_nav"] = kwargs["show_banner_nav"]
    elif "platform" in context:
        context.update(_brand_context(context.get("platform")))
    return context


def get_minimal_template_context(**kwargs) -> Dict[str, Any]:
    """
    Get minimal template context without feature toggles (for performance-critical templates).
    
    Args:
        **kwargs: Additional context variables
        
    Returns:
        dict: Minimal template context
    """
    platform = kwargs.get("platform")
    return {
        **_brand_context(platform if isinstance(platform, str) else None),
        "current_year": datetime.now().year,
        **kwargs
    }


def get_admin_template_context(**kwargs) -> Dict[str, Any]:
    """
    Get template context specifically for admin pages with additional admin context.
    
    Args:
        **kwargs: Additional context variables
        
    Returns:
        dict: Admin template context
    """
    context = get_global_template_context()
    
    context.update({
        "is_admin_page": True,
        "admin_features": {
            "user_management": context.get("is_admin_management_enabled", False),
            "announcements": context.get("is_admin_management_enabled", False),
            "mission_overviews": context.get("is_admin_management_enabled", False),
            "scheduler_status": context.get("is_admin_management_enabled", False),
        }
    })
    
    context.update(kwargs)
    if "platform" in context:
        context.update(_brand_context(context.get("platform")))
    return context


def get_user_template_context(**kwargs) -> Dict[str, Any]:
    """
    Get template context specifically for user pages with user-relevant features.
    
    Args:
        **kwargs: Additional context variables
        
    Returns:
        dict: User template context
    """
    context = get_global_template_context()
    
    context.update({
        "is_user_page": True,
        "user_features": {
            "pic_management": context.get("is_pic_management_enabled", False),
            "forms": context.get("is_forms_enabled", False),
            "station_offloads": context.get("is_station_offloads_enabled", False),
        }
    })
    
    context.update(kwargs)
    if "platform" in context:
        context.update(_brand_context(context.get("platform")))
    return context
