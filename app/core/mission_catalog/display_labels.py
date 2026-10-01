"""Display-only mission labels for navigation UI.

Storage keys, route params, disk folders, and catalog UUIDs stay unchanged.
Labels are derived for human-facing selectors only.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional, Sequence

from sqlmodel import Session, select

from app.core.utils import parse_slocum_dataset_id, slocum_mission_key

_LEGACY_HULL_MISSION = re.compile(
    r"^(?P<hull>\d{3,5})-(?P<code>m\d+)$", re.IGNORECASE
)
_MISSION_CODE = re.compile(r"^m\d+$", re.IGNORECASE)
_SV3_HULL = re.compile(r"^SV3-(?P<hull>\d+)$", re.IGNORECASE)
_FOLDER_STYLE = re.compile(
    r"^(?P<code>m\d+)(?:-(?P<rest>.+))?$", re.IGNORECASE
)
# Slocum nav labels after catalog cutover: m226-Peggy (not ERDDAP storage keys).
_SLOCUM_NAV_LABEL = re.compile(
    r"^m(?P<num>\d+)(?:-(?P<name>.+))?$",
    re.IGNORECASE,
)


def mission_code_from_deployment_number(deployment_number: Optional[int]) -> Optional[str]:
    if deployment_number is None:
        return None
    try:
        return f"m{int(deployment_number)}"
    except (TypeError, ValueError):
        return None


def extract_sv3_hull(platform_name: Optional[str]) -> Optional[str]:
    """Return hull digits from SV3-1070 / SV3-1070 (C34164NS) style names."""
    if not platform_name or not str(platform_name).strip():
        return None
    token = re.split(r"[\s(]", str(platform_name).strip(), maxsplit=1)[0].strip()
    match = _SV3_HULL.match(token)
    if match:
        return match.group("hull")
    # Bare numeric hull when family context is Wave Glider
    if re.fullmatch(r"\d{3,5}", token):
        return token
    return None


def parse_slocum_nav_display_label(raw: str) -> Optional[dict[str, Any]]:
    """
    Parse ``m###`` / ``m###-<GliderName>`` navigation labels (ADR 0009).

    Returns None for ERDDAP dataset ids and other non-label strings so resolvers
    do not confuse storage keys with display-only labels.
    """
    trimmed = (raw or "").strip()
    if not trimmed or parse_slocum_dataset_id(trimmed):
        return None
    match = _SLOCUM_NAV_LABEL.match(trimmed)
    if not match:
        return None
    name = (match.group("name") or "").strip()
    return {
        "deployment_number": int(match.group("num")),
        "glider_name": name or None,
    }


def wave_glider_display_label(
    storage_key: str,
    *,
    deployment_number: Optional[int] = None,
    platform_canonical_name: Optional[str] = None,
) -> str:
    """
    Canonical WG display label: ``m###-SV3-<hull>``.

    Falls back through catalog fields, legacy ``1070-m170`` keys, then the
    unchanged storage key when platform metadata is missing.
    """
    key = (storage_key or "").strip()
    code = mission_code_from_deployment_number(deployment_number)
    hull = extract_sv3_hull(platform_canonical_name)

    if code and hull:
        return f"{code}-SV3-{hull}"

    legacy = _LEGACY_HULL_MISSION.match(key)
    if legacy:
        return f"{legacy.group('code').lower()}-SV3-{legacy.group('hull')}"

    folder = _FOLDER_STYLE.match(key)
    if folder and hull:
        return f"{folder.group('code').lower()}-SV3-{hull}"

    if code and platform_canonical_name:
        # Non-SV3 WG asset: m###-<canonical>
        token = re.split(r"[\s(]", str(platform_canonical_name).strip(), maxsplit=1)[0]
        if token:
            return f"{code}-{token}"

    if code and not key:
        return code
    return key or (code or "")


def slocum_nav_display_label(
    dataset_or_key: str,
    *,
    deployment_number: Optional[int] = None,
    glider_name: Optional[str] = None,
    platform_canonical_name: Optional[str] = None,
) -> str:
    """
    Canonical Slocum display label: ``m###-<GliderName>``.

    Navigation still uses the ERDDAP dataset id (or configured key) as ``key``.
    """
    raw = (dataset_or_key or "").strip()
    parsed = parse_slocum_dataset_id(raw)
    number = deployment_number
    name = (glider_name or platform_canonical_name or "").strip()
    if parsed:
        if number is None:
            number = parsed.get("deployment_number")
        if not name:
            name = str(parsed.get("glider_name") or "").strip()
    # Title-case glider for display (fundy -> Fundy) while keeping acronyms.
    display_name = name
    if name and name.islower():
        display_name = name[:1].upper() + name[1:]
    code = mission_code_from_deployment_number(number)
    if code and display_name:
        return f"{code}-{display_name}"
    if code:
        return code
    return raw


def _catalog_context_for_keys(
    session: Session,
    keys: Sequence[str],
    *,
    platform_family: str,
) -> dict[str, dict[str, Any]]:
    """Map storage key -> {catalog_mission_id, deployment_number, platform_name, glider_name}."""
    from app.core.models.database import (
        CatalogMission,
        CatalogPlatform,
        MissionOverview,
        SlocumDeployment,
    )

    out: dict[str, dict[str, Any]] = {k: {} for k in keys if k}
    if not out:
        return out

    platforms = {
        p.id: p
        for p in session.exec(select(CatalogPlatform)).all()
        if p.id is not None
    }
    missions = {m.id: m for m in session.exec(select(CatalogMission)).all() if m.id}

    if platform_family == "wave_glider":
        for overview in session.exec(select(MissionOverview)).all():
            mid = (overview.mission_id or "").strip()
            if mid not in out:
                continue
            cid = getattr(overview, "catalog_mission_id", None)
            mission = missions.get(cid) if cid else None
            platform = platforms.get(mission.platform_id) if mission and mission.platform_id else None
            out[mid] = {
                "catalog_mission_id": cid,
                "deployment_number": getattr(mission, "deployment_number", None) if mission else None,
                "platform_canonical_name": getattr(platform, "canonical_name", None) if platform else None,
            }
    else:
        for dep in session.exec(select(SlocumDeployment)).all():
            candidates = {
                (dep.erddap_dataset_id or "").strip(),
                (dep.mission_key or "").strip(),
            }
            for key in list(out):
                if key in candidates or slocum_mission_key(key) in candidates:
                    cid = getattr(dep, "catalog_mission_id", None)
                    mission = missions.get(cid) if cid else None
                    platform = (
                        platforms.get(mission.platform_id)
                        if mission and mission.platform_id
                        else None
                    )
                    out[key] = {
                        "catalog_mission_id": cid,
                        "deployment_number": (
                            getattr(mission, "deployment_number", None) if mission else None
                        ),
                        "glider_name": dep.glider_name,
                        "platform_canonical_name": (
                            getattr(platform, "canonical_name", None) if platform else None
                        ),
                    }
    return out


def build_navigation_entries(
    session: Session,
    keys: Iterable[str],
    *,
    platform_family: str,
) -> List[dict[str, Optional[str]]]:
    """
    Build ``{key, label, catalog_mission_id}`` entries for navigation UIs.

    ``key`` is the stable storage / route value; ``label`` is display-only.
    """
    ordered = [str(k).strip() for k in keys if k and str(k).strip()]
    ctx = _catalog_context_for_keys(session, ordered, platform_family=platform_family)
    entries: List[dict[str, Optional[str]]] = []
    for key in ordered:
        meta = ctx.get(key) or {}
        if platform_family == "wave_glider":
            label = wave_glider_display_label(
                key,
                deployment_number=meta.get("deployment_number"),
                platform_canonical_name=meta.get("platform_canonical_name"),
            )
        else:
            label = slocum_nav_display_label(
                key,
                deployment_number=meta.get("deployment_number"),
                glider_name=meta.get("glider_name"),
                platform_canonical_name=meta.get("platform_canonical_name"),
            )
        entries.append(
            {
                "key": key,
                "label": label or key,
                "catalog_mission_id": meta.get("catalog_mission_id"),
            }
        )
    return entries


def inventory_wave_glider_keys(session: Session) -> List[dict[str, Any]]:
    """Read-only WG inventory: stored key, computed label, catalog ambiguity, child hints."""
    from app.core.models.database import (
        CatalogMission,
        CatalogPlatform,
        MissionOverview,
    )

    platforms = {
        p.id: p
        for p in session.exec(select(CatalogPlatform)).all()
        if p.id is not None
    }
    missions = {m.id: m for m in session.exec(select(CatalogMission)).all() if m.id}
    rows: List[dict[str, Any]] = []
    for overview in session.exec(select(MissionOverview)).all():
        key = (overview.mission_id or "").strip()
        if not key:
            continue
        cid = getattr(overview, "catalog_mission_id", None)
        mission = missions.get(cid) if cid else None
        platform = platforms.get(mission.platform_id) if mission and mission.platform_id else None
        label = wave_glider_display_label(
            key,
            deployment_number=getattr(mission, "deployment_number", None) if mission else None,
            platform_canonical_name=getattr(platform, "canonical_name", None) if platform else None,
        )
        is_legacy = bool(_LEGACY_HULL_MISSION.match(key))
        is_bare = bool(_MISSION_CODE.match(key))
        rows.append(
            {
                "key": key,
                "label": label,
                "catalog_mission_id": cid,
                "platform_canonical_name": getattr(platform, "canonical_name", None)
                if platform
                else None,
                "is_legacy_hull_key": is_legacy,
                "is_bare_mission_code": is_bare,
                "label_differs_from_key": label != key,
                "disk_path_hint": f"data/{key}",
            }
        )
    return rows
