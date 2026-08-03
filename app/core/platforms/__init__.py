"""
Platform and product brand registry for Glider Buddy System.

Canonical machine IDs stay snake_case (wave_glider, slocum). URL prefixes are
kebab-case. Import helpers from here rather than scattering string literals.
"""

from .registry import (
    PLATFORM_PLACEHOLDER_LOGO,
    PLATFORM_SLOCUM,
    PLATFORM_WAVE_GLIDER,
    PLATFORMS,
    PRODUCT_FAVICON_PATH,
    PRODUCT_FAVICON_SVG_PATH,
    PRODUCT_LOGO_PATH,
    PRODUCT_NAME_FULL,
    PRODUCT_NAME_SHORT,
    PlatformSpec,
    buddy_title_for,
    display_name_for,
    get_platform,
    home_url_for,
    html_path_for,
    is_known_platform,
    known_platform_ids,
    platform_labels_map,
    platform_page_context,
    resolve_platform_from_path,
    url_prefix_for,
)

__all__ = [
    "PLATFORM_PLACEHOLDER_LOGO",
    "PLATFORM_SLOCUM",
    "PLATFORM_WAVE_GLIDER",
    "PLATFORMS",
    "PRODUCT_FAVICON_PATH",
    "PRODUCT_FAVICON_SVG_PATH",
    "PRODUCT_LOGO_PATH",
    "PRODUCT_NAME_FULL",
    "PRODUCT_NAME_SHORT",
    "PlatformSpec",
    "buddy_title_for",
    "display_name_for",
    "get_platform",
    "home_url_for",
    "html_path_for",
    "is_known_platform",
    "known_platform_ids",
    "platform_labels_map",
    "platform_page_context",
    "resolve_platform_from_path",
    "url_prefix_for",
]
