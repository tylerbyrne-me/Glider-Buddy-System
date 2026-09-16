"""Helpers to normalize Wave Glider historical mission id lists for UI."""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence

from app.core.utils import deployment_mission_code_from_mission_id

_WG_FOLDER_STYLE = re.compile(r"^m\d+-SV\d+", re.IGNORECASE)
_WG_BARE_CODE = re.compile(r"^m\d+$", re.IGNORECASE)
_WG_LEGACY_SERIAL = re.compile(r"^\d+-m\d+$", re.IGNORECASE)


def _rank_wg_historical_key(mission_id: str) -> tuple[int, str]:
    """Lower rank is preferred for dropdown display / navigation."""
    mid = (mission_id or "").strip()
    if _WG_FOLDER_STYLE.match(mid):
        return (0, mid.lower())
    if _WG_BARE_CODE.match(mid):
        return (1, mid.lower())
    if _WG_LEGACY_SERIAL.match(mid):
        return (2, mid.lower())
    return (3, mid.lower())


def dedupe_wave_glider_historical_keys(keys: Sequence[str]) -> List[str]:
    """Collapse name variants of the same deployment to one preferred key.

    Preference: ``m###-SV3-####`` > bare ``m###`` > ``####-m###`` > other.
    Groups by Sensor Tracker deployment code (``m170``, ``m209``, …).
    """
    best_by_code: dict[str, str] = {}
    leftovers: List[str] = []
    for raw in keys:
        key = (raw or "").strip()
        if not key:
            continue
        code = deployment_mission_code_from_mission_id(key)
        if not code or not re.match(r"^m\d+$", code, re.IGNORECASE):
            leftovers.append(key)
            continue
        code_norm = code.lower()
        existing = best_by_code.get(code_norm)
        if existing is None or _rank_wg_historical_key(key) < _rank_wg_historical_key(
            existing
        ):
            best_by_code[code_norm] = key

    def sort_key(mission_id: str) -> tuple:
        code = deployment_mission_code_from_mission_id(mission_id)
        num = 99999
        if code and code.lower().startswith("m") and code[1:].isdigit():
            num = int(code[1:])
        return (num, mission_id.lower())

    out = sorted(best_by_code.values(), key=sort_key)
    # Preserve unmatched leftovers after numbered missions (stable, unique).
    seen = {k.lower() for k in out}
    for key in leftovers:
        if key.lower() in seen:
            continue
        seen.add(key.lower())
        out.append(key)
    return out


def preferred_wave_glider_historical_key(
    candidates: Iterable[str],
) -> Optional[str]:
    """Pick one preferred key from a set of variants (or None if empty)."""
    deduped = dedupe_wave_glider_historical_keys(list(candidates))
    return deduped[0] if deduped else None
