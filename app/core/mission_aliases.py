"""
Env-backed mission/dataset alias maps (Slocum + future platforms).

Wave Glider uses ``REMOTE_MISSION_FOLDER_MAP_JSON`` (mission key → remote folder).
Slocum uses ``SLOCUM_DATASET_ALIAS_MAP_JSON`` (alias → ERDDAP dataset id).
Additional platforms register maps via ``MISSION_ALIAS_MAPS_JSON``.
"""

from __future__ import annotations

from typing import Iterable, Optional

from app.config import settings
from app.core.utils import slocum_mission_key

PLATFORM_SLOCUM = "slocum"


def _alias_map_for(platform_id: str) -> dict[str, str]:
    if platform_id == PLATFORM_SLOCUM:
        return settings.slocum_dataset_alias_map
    extra = getattr(settings, "mission_alias_maps", None) or {}
    platform_map = extra.get(platform_id)
    if isinstance(platform_map, dict):
        return {str(k): str(v) for k, v in platform_map.items() if k and v}
    return {}


def resolve_platform_mission_id(platform_id: str, key: str) -> str:
    """Resolve a configured alias to the canonical mission/dataset id for a platform."""
    trimmed = (key or "").strip()
    if not trimmed:
        return trimmed
    alias_map = _alias_map_for(platform_id)
    if trimmed in alias_map:
        return alias_map[trimmed].strip()
    lowered = trimmed.lower()
    for alias, canonical in alias_map.items():
        if alias.lower() == lowered:
            return canonical.strip()
    return trimmed


def resolve_slocum_dataset_id(key: str) -> str:
    return resolve_platform_mission_id(PLATFORM_SLOCUM, key)


def resolve_slocum_dataset_ids(keys: Iterable[str] | None) -> list[str]:
    return [
        resolve_slocum_dataset_id(k)
        for k in (keys or [])
        if k and str(k).strip()
    ]


def configured_slocum_dataset_keys(keys: Iterable[str] | None) -> list[str]:
    """Return trimmed configured keys from env lists (aliases preserved)."""
    return [str(k).strip() for k in (keys or []) if k and str(k).strip()]


def reverse_slocum_alias(canonical_id: str) -> Optional[str]:
    """Return the configured alias for a canonical dataset id, if mapped."""
    trimmed = (canonical_id or "").strip()
    if not trimmed:
        return None
    for alias, canonical in _alias_map_for(PLATFORM_SLOCUM).items():
        if canonical.strip() == trimmed:
            return alias.strip()
    return None


def equivalent_slocum_dataset_keys(canonical_id: str) -> set[str]:
    """
    All configured keys that refer to the same Slocum ERDDAP mission as ``canonical_id``.

    Includes the resolved canonical id, suffix-agnostic mission_key, realtime/delayed
    siblings, and every alias / active / historical list entry that resolves to it.
    """
    canonical = resolve_slocum_dataset_id(canonical_id).strip()
    if not canonical:
        return set()
    keys: set[str] = {canonical}
    mission_key = slocum_mission_key(canonical)
    if mission_key:
        keys.add(mission_key)
        keys.add(f"{mission_key}_realtime")
        keys.add(f"{mission_key}_delayed")
    for alias, target in _alias_map_for(PLATFORM_SLOCUM).items():
        if resolve_slocum_dataset_id(alias).strip() == canonical:
            keys.add(alias.strip())
    for configured in (
        *(settings.active_slocum_datasets or []),
        *(settings.historical_slocum_datasets or []),
    ):
        key = str(configured).strip()
        if key and resolve_slocum_dataset_id(key).strip() == canonical:
            keys.add(key)
    return keys


def resolved_slocum_mission_key(key: str) -> str:
    """Resolve env alias, then compute suffix-agnostic Slocum mission_key."""
    canonical = resolve_slocum_dataset_id(key)
    return slocum_mission_key(canonical) or canonical.strip()


def slocum_report_storage_dir_names(
    dataset_id: str,
    *,
    deployment_mission_key: Optional[str] = None,
    deployment_erddap_dataset_id: Optional[str] = None,
) -> list[str]:
    """
    Directory names under ``mission_reports/slocum/`` to search, best match first.

    Covers canonical mission_key dirs plus legacy alias-only names from before
    alias renames.
    """
    ordered: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        safe = (raw or "").strip().replace("/", "_").replace("\\", "_")
        if safe and safe not in seen:
            seen.add(safe)
            ordered.append(safe)

    canonical = resolve_slocum_dataset_id(dataset_id)
    add(resolved_slocum_mission_key(dataset_id))
    for key in equivalent_slocum_dataset_keys(canonical):
        add(slocum_mission_key(resolve_slocum_dataset_id(key)) or key)
    for raw in (deployment_mission_key, deployment_erddap_dataset_id):
        if raw:
            add(slocum_mission_key(resolve_slocum_dataset_id(raw)) or raw)
    return ordered


def slocum_display_label(configured_key: str, *, fallback: Optional[str] = None) -> str:
    """Human-facing label: prefer alias when the key is mapped in .env."""
    key = (configured_key or "").strip()
    if not key:
        return fallback or ""
    if key in _alias_map_for(PLATFORM_SLOCUM):
        return key
    alias = reverse_slocum_alias(key)
    if alias:
        return alias
    return fallback or key
