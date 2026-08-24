"""ERDDAP dataset naming helpers for catalog candidate generation."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import List, Optional, Tuple

from app.core.utils import parse_slocum_dataset_id

_WG_DATASET_PATTERN = re.compile(
    r"^(?P<prefix>[A-Za-z0-9]+)_(?P<start>\d{8})_(?P<num>\d+)(?:_(?P<mode>realtime|delayed))?$"
)


def normalize_platform_prefix(name: Optional[str]) -> Optional[str]:
    """Extract ERDDAP-style prefix from a platform name.

    Examples:
      DL -> DL
      SV3-1070 (C34164NS) -> SV3
      fundy -> fundy
    """
    if not name or not str(name).strip():
        return None
    raw = str(name).strip()
    # Prefer leading token before space/paren
    token = re.split(r"[\s(]", raw, maxsplit=1)[0].strip()
    if not token:
        return None
    # SV3-1070 -> SV3 for Wave Glider serial style; keep short letter codes as-is
    if re.match(r"^SV\d+", token, re.IGNORECASE):
        return token.split("-", 1)[0].upper()
    if re.match(r"^[A-Za-z]{1,4}$", token):
        return token.upper()
    # Slocum-style glider names stay lowercase
    return token.lower()


def classify_platform_family(
    platform_name: Optional[str],
    *,
    wave_glider_prefixes: Optional[List[str]] = None,
    slocum_known_names: Optional[List[str]] = None,
) -> Optional[str]:
    """Heuristic platform family classification from a platform name.

    Prefer ST Platforms ``model`` via ``ProvidersManifest.family_for_model`` when
    available; this is the fallback when model metadata is missing.
    """
    if not platform_name:
        return None
    name = str(platform_name).strip()
    upper = name.upper()
    wg_prefixes = [p.upper() for p in (wave_glider_prefixes or ["SV3", "DL", "SV2"])]
    for prefix in wg_prefixes:
        if upper.startswith(prefix):
            return "wave_glider"
    known = {n.lower() for n in (slocum_known_names or [])}
    token = re.split(r"[\s(]", name, maxsplit=1)[0].strip().lower()
    if token in known:
        return "slocum"
    # Slocum Glider / Wave Glider model-style strings
    if "WAVE GLIDER" in upper:
        return "wave_glider"
    if "SLOCUM" in upper:
        return "slocum"
    return None


def classify_family_from_model(
    model_name: Optional[str],
    *,
    allowed_platform_models: Optional[dict] = None,
) -> Optional[str]:
    """Return platform_family for an allowlisted ST model name, else None."""
    if not model_name:
        return None
    raw = str(model_name).strip()
    mapping = allowed_platform_models or {}
    if raw in mapping:
        return str(mapping[raw])
    lowered = {str(k).lower(): v for k, v in mapping.items()}
    hit = lowered.get(raw.lower())
    return str(hit) if hit else None


def format_start_yyyymmdd(value: Optional[datetime | date]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    return value.strftime("%Y%m%d")


def build_erddap_dataset_candidates(
    *,
    platform_prefix: str,
    start: datetime | date,
    deployment_number: int,
    platform_family: Optional[str] = None,
    preferred_wg_variant: str = "realtime",
    slocum_variants: Optional[List[str]] = None,
) -> List[str]:
    """Generate ERDDAP dataset ID candidates (naming formula, not identity)."""
    prefix = normalize_platform_prefix(platform_prefix) or str(platform_prefix).strip()
    stamp = format_start_yyyymmdd(start)
    if not prefix or not stamp or deployment_number is None:
        return []
    base = f"{prefix}_{stamp}_{int(deployment_number)}"
    variants: List[str]
    if platform_family == "wave_glider":
        preferred = (preferred_wg_variant or "realtime").strip().lower()
        # Always probe both suffixes so legacy delayed WG datasets are not missed.
        variants = [preferred]
        for other in ("realtime", "delayed"):
            if other not in variants:
                variants.append(other)
    elif platform_family == "slocum":
        variants = list(slocum_variants or ["realtime", "delayed"])
    else:
        variants = ["realtime", "delayed"]
    return [f"{base}_{v}" for v in variants if v]


def parse_erddap_dataset_id(dataset_id: str) -> Optional[dict]:
    """Parse Slocum or Wave Glider ERDDAP dataset IDs sharing the same pattern."""
    parsed = parse_slocum_dataset_id(dataset_id)
    if parsed:
        return {
            "prefix": parsed["glider_name"],
            "start_date": parsed["start_date"],
            "deployment_number": parsed["deployment_number"],
            "mode": parsed["mode"],
        }
    if not dataset_id or not str(dataset_id).strip():
        return None
    match = _WG_DATASET_PATTERN.match(str(dataset_id).strip())
    if not match:
        return None
    try:
        start_date = datetime.strptime(match.group("start"), "%Y%m%d").date()
    except ValueError:
        return None
    return {
        "prefix": match.group("prefix"),
        "start_date": start_date,
        "deployment_number": int(match.group("num")),
        "mode": match.group("mode"),
    }


def mission_fingerprint(
    *,
    owner_organization: Optional[str],
    platform_prefix: Optional[str],
    start: Optional[datetime | date],
    deployment_number: Optional[int],
) -> Optional[str]:
    """Deterministic fingerprint for high-confidence mission matching."""
    prefix = normalize_platform_prefix(platform_prefix)
    stamp = format_start_yyyymmdd(start)
    if not owner_organization or not prefix or not stamp or deployment_number is None:
        return None
    return f"{owner_organization.strip().lower()}|{prefix}|{stamp}|{int(deployment_number)}"


def parse_wgms_folder_name(folder: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (deployment_code, vehicle_hint) from m209-C34167NS-style folders."""
    if not folder:
        return None, None
    name = str(folder).strip().rstrip("/")
    match = re.match(r"^(?P<code>m\d+)(?:-(?P<rest>.+))?$", name, re.IGNORECASE)
    if not match:
        return None, None
    code = match.group("code").lower()
    rest = match.group("rest")
    return code, rest
