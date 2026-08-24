"""Load mission data provider manifest (non-secret)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class ProviderSpec:
    key: str
    connector: str
    organization: str
    enabled: bool = True
    base_url_setting: Optional[str] = None
    dataset_id_filter: Optional[str] = None
    collections: List[str] = field(default_factory=list)
    rate_limit_seconds: float = 1.0
    naming: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""


@dataclass(frozen=True)
class ProvidersManifest:
    providers: List[ProviderSpec]
    wave_glider_prefixes: List[str]
    slocum_known_names: List[str]
    # ST Platforms model name -> platform_family (wave_glider | slocum).
    allowed_platform_models: Dict[str, str] = field(default_factory=dict)
    stale_miss_threshold: int = 3

    def get(self, key: str) -> Optional[ProviderSpec]:
        for provider in self.providers:
            if provider.key == key:
                return provider
        return None

    def enabled_connectors(self, connector: str) -> List[ProviderSpec]:
        return [p for p in self.providers if p.enabled and p.connector == connector]

    def family_for_model(self, model_name: Optional[str]) -> Optional[str]:
        if not model_name:
            return None
        raw = str(model_name).strip()
        if raw in self.allowed_platform_models:
            return self.allowed_platform_models[raw]
        lowered = {k.lower(): v for k, v in self.allowed_platform_models.items()}
        return lowered.get(raw.lower())


def _resolve_manifest_path(path: Optional[Path] = None) -> Path:
    configured = Path(path or settings.mission_data_providers_file)
    if configured.is_absolute():
        return configured
    return _PROJECT_ROOT / configured


def load_providers_manifest(path: Optional[Path] = None) -> ProvidersManifest:
    """Load provider manifest; fall back to built-in CEOTR defaults if missing."""
    resolved = _resolve_manifest_path(path)
    if not resolved.is_file():
        logger.warning("Mission providers manifest missing at %s; using defaults", resolved)
        return ProvidersManifest(
            providers=[
                ProviderSpec(
                    key="ceotr_sensor_tracker",
                    connector="sensor_tracker",
                    organization="ceotr",
                    base_url_setting="sensor_tracker_host",
                ),
                ProviderSpec(
                    key="oceantrack_erddap",
                    connector="erddap",
                    organization="ceotr",
                    base_url_setting="slocum_erddap_server",
                    dataset_id_filter=r".*(_realtime|_delayed)$",
                    naming={
                        "wave_glider_preferred_variant": "realtime",
                        "slocum_variants": ["realtime", "delayed"],
                    },
                ),
                ProviderSpec(
                    key="ceotr_wgms_remote",
                    connector="wgms_remote",
                    organization="ceotr",
                    base_url_setting="remote_data_url",
                    collections=["output_realtime_missions", "output_past_missions"],
                ),
                ProviderSpec(
                    key="legacy_env",
                    connector="legacy_env",
                    organization="ceotr",
                ),
            ],
            wave_glider_prefixes=["SV3", "DL", "SV2"],
            slocum_known_names=[],
            allowed_platform_models={
                "Slocum Glider G1": "slocum",
                "Slocum Glider G2": "slocum",
                "Slocum Glider G3": "slocum",
                "Slocum Glider G3S": "slocum",
                "Wave Glider SV2": "wave_glider",
                "Wave Glider SV3": "wave_glider",
            },
            stale_miss_threshold=int(
                getattr(settings, "mission_catalog_stale_miss_threshold", 3)
            ),
        )

    raw = json.loads(resolved.read_text(encoding="utf-8"))
    providers: List[ProviderSpec] = []
    for item in raw.get("providers") or []:
        if not isinstance(item, dict) or not item.get("key") or not item.get("connector"):
            continue
        providers.append(
            ProviderSpec(
                key=str(item["key"]).strip(),
                connector=str(item["connector"]).strip(),
                organization=str(item.get("organization") or "unknown").strip(),
                enabled=bool(item.get("enabled", True)),
                base_url_setting=(
                    str(item["base_url_setting"]).strip()
                    if item.get("base_url_setting")
                    else None
                ),
                dataset_id_filter=(
                    str(item["dataset_id_filter"]).strip()
                    if item.get("dataset_id_filter")
                    else None
                ),
                collections=[str(c) for c in (item.get("collections") or []) if c],
                rate_limit_seconds=float(item.get("rate_limit_seconds") or 1.0),
                naming=dict(item.get("naming") or {}),
                notes=str(item.get("notes") or ""),
            )
        )
    rules = raw.get("platform_name_rules") or {}
    allowed_raw = raw.get("allowed_platform_models") or {}
    allowed: Dict[str, str] = {}
    if isinstance(allowed_raw, dict):
        for model_name, family in allowed_raw.items():
            if model_name and family:
                allowed[str(model_name).strip()] = str(family).strip()
    threshold = int(
        raw.get("stale_miss_threshold")
        or getattr(settings, "mission_catalog_stale_miss_threshold", 3)
    )
    return ProvidersManifest(
        providers=providers,
        wave_glider_prefixes=[str(p) for p in (rules.get("wave_glider_prefixes") or ["SV3", "DL", "SV2"])],
        slocum_known_names=[str(n) for n in (rules.get("slocum_known_names") or [])],
        allowed_platform_models=allowed,
        stale_miss_threshold=threshold,
    )


def resolve_provider_base_url(provider: ProviderSpec) -> Optional[str]:
    """Resolve a provider base URL from settings by setting attribute name."""
    if not provider.base_url_setting:
        return None
    value = getattr(settings, provider.base_url_setting, None)
    if value is None:
        return None
    return str(value).rstrip("/")
