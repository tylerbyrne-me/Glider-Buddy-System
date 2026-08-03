"""
Wave Glider API path aliasing.

Canonical platform APIs use ``/api/{platform_id}/...``. Legacy Wave Glider routes
remain at ``/api/...``. Requests to ``/api/wave_glider/...`` are rewritten to
``/api/...`` so both prefixes work without duplicating handlers.
"""

from __future__ import annotations

from typing import Optional

from .registry import PLATFORM_WAVE_GLIDER

WG_API_PREFIX = f"/api/{PLATFORM_WAVE_GLIDER}"


def rewrite_wave_glider_api_path(path: str) -> Optional[str]:
    """
    If ``path`` is under ``/api/wave_glider``, return the legacy ``/api/...`` path.
    Otherwise return None (no rewrite).
    """
    if path == WG_API_PREFIX:
        return "/api"
    if path.startswith(WG_API_PREFIX + "/"):
        rest = path[len(WG_API_PREFIX) :]
        return "/api" + rest
    return None
