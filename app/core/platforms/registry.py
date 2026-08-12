"""
Central platform + product brand registry.

New platforms should be registered here and follow:
  platform_id   snake_case
  url_prefix    /{kebab(id)}
  api_prefix    /api/{platform_id}
  feature_gate  {platform_id}_platform  (None = always on; Wave Glider exception)
  kb_toggle     {platform_id}_knowledge_base
  acl column    can_access_{platform_id}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


PRODUCT_NAME_FULL = "Glider Buddy System"
PRODUCT_NAME_SHORT = "GBS"
PRODUCT_LOGO_PATH = "/static/images/gbs_logo.svg"
PRODUCT_FAVICON_PATH = "/static/favicon.ico"
PRODUCT_FAVICON_SVG_PATH = "/static/images/gbs_favicon.svg"
PLATFORM_PLACEHOLDER_LOGO = "/static/images/platforms/placeholder.svg"

PLATFORM_WAVE_GLIDER = "wave_glider"
PLATFORM_SLOCUM = "slocum"

# Parallel product area (not a vehicle PlatformSpec / not in PLATFORMS).
AREA_TEAM = "team"
TEAM_DISPLAY_NAME = "Team"
TEAM_HOME_URL = "/team"
TEAM_URL_PREFIX = "/team"


@dataclass(frozen=True)
class PlatformSpec:
    """Display and routing metadata for one vehicle platform."""

    id: str
    display_name: str
    buddy_title: str
    url_prefix: str
    home_url: str
    api_prefix: str
    feature_toggle: Optional[str]
    kb_toggle: str
    access_attr: str
    logo_path: str = PLATFORM_PLACEHOLDER_LOGO


def _buddy_title(display_name: str) -> str:
    """Build in-platform brand: 'Wave Glider Buddy System' / 'Slocum Glider Buddy System'."""
    if display_name.endswith("Glider"):
        return f"{display_name} Buddy System"
    return f"{display_name} Glider Buddy System"


def _spec(
    platform_id: str,
    display_name: str,
    *,
    feature_toggle: Optional[str] = None,
    logo_path: str = PLATFORM_PLACEHOLDER_LOGO,
) -> PlatformSpec:
    url_prefix = "/" + platform_id.replace("_", "-")
    return PlatformSpec(
        id=platform_id,
        display_name=display_name,
        buddy_title=_buddy_title(display_name),
        url_prefix=url_prefix,
        home_url=f"{url_prefix}/home",
        api_prefix=f"/api/{platform_id}",
        feature_toggle=feature_toggle,
        kb_toggle=f"{platform_id}_knowledge_base",
        access_attr=f"can_access_{platform_id}",
        logo_path=logo_path,
    )


PLATFORMS: Dict[str, PlatformSpec] = {
    PLATFORM_WAVE_GLIDER: _spec(
        PLATFORM_WAVE_GLIDER,
        "Wave Glider",
        logo_path=PRODUCT_LOGO_PATH,
    ),
    PLATFORM_SLOCUM: _spec(
        PLATFORM_SLOCUM,
        "Slocum",
        feature_toggle="slocum_platform",
    ),
}


def known_platform_ids() -> List[str]:
    return list(PLATFORMS.keys())


def is_known_platform(platform_id: Optional[str]) -> bool:
    return bool(platform_id) and platform_id in PLATFORMS


def get_platform(platform_id: str) -> PlatformSpec:
    try:
        return PLATFORMS[platform_id]
    except KeyError as exc:
        raise KeyError(f"Unknown platform id: {platform_id!r}") from exc


def url_prefix_for(platform_id: str) -> str:
    return get_platform(platform_id).url_prefix


def home_url_for(platform_id: str) -> str:
    return get_platform(platform_id).home_url


def team_buddy_title() -> str:
    """In-area brand: 'Team Glider Buddy System' (same modifier rule as Slocum)."""
    return _buddy_title(TEAM_DISPLAY_NAME)


def is_team_path(path: str) -> bool:
    path = path or ""
    return path == TEAM_URL_PREFIX or path.startswith(TEAM_URL_PREFIX + "/")


def buddy_title_for(platform_id: Optional[str]) -> str:
    if platform_id == AREA_TEAM:
        return team_buddy_title()
    if not platform_id or platform_id not in PLATFORMS:
        return PRODUCT_NAME_FULL
    return PLATFORMS[platform_id].buddy_title


def display_name_for(platform_id: str) -> str:
    return get_platform(platform_id).display_name


def platform_labels_map() -> Dict[str, str]:
    """id -> display_name for admin UI filters."""
    return {pid: spec.display_name for pid, spec in PLATFORMS.items()}


def resolve_platform_from_path(path: str) -> Optional[str]:
    """
    Return platform id for a request path, or None when no platform is selected
    (e.g. /platform splash, login).
    """
    path = path or ""
    # Longer / more specific prefixes first if we ever add nested platforms
    ordered = sorted(PLATFORMS.values(), key=lambda s: len(s.url_prefix), reverse=True)
    for spec in ordered:
        prefix = spec.url_prefix
        if path == prefix or path.startswith(prefix + "/") or prefix in path:
            return spec.id
    return None


def html_path_for(platform_id: str, page: str) -> str:
    """Build a canonical HTML path under the platform URL prefix.

    ``page`` may be ``chatbot.html`` or ``/chatbot.html``.
    """
    page = page.lstrip("/")
    return f"{url_prefix_for(platform_id)}/{page}"


def platform_page_context(platform_id: str, **extra: object) -> dict:
    """Standard template context keys for a platform-scoped HTML page."""
    return {
        "platform": platform_id,
        "platform_home_url": home_url_for(platform_id),
        "show_banner_nav": True,
        "app_name": PRODUCT_NAME_FULL,
        "app_name_short": PRODUCT_NAME_SHORT,
        "platform_buddy_title": buddy_title_for(platform_id),
        "platform_display_name": display_name_for(platform_id),
        **extra,
    }
