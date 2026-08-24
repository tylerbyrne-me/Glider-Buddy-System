"""ERDDAP allDatasets discovery adapter."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from app.core.mission_catalog.naming import (
    classify_platform_family,
    parse_erddap_dataset_id,
)
from app.core.mission_catalog.providers_config import (
    ProviderSpec,
    ProvidersManifest,
    resolve_provider_base_url,
)
from app.core.mission_catalog.schemas import DiscoveredSource, DiscoveryBatch
from app.core.models.enums import CatalogSourceKind, CatalogSourceVariant

logger = logging.getLogger(__name__)


def _parse_dt(value) -> Optional[datetime]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return pd.to_datetime(value, utc=True).to_pydatetime()
    except Exception:
        return None


def _variant_from_mode(mode: Optional[str]) -> CatalogSourceVariant:
    if mode == "realtime":
        return CatalogSourceVariant.REALTIME
    if mode == "delayed":
        return CatalogSourceVariant.DELAYED
    return CatalogSourceVariant.UNKNOWN


def discover_erddap(
    provider: ProviderSpec,
    manifest: ProvidersManifest,
) -> DiscoveryBatch:
    """Fetch allDatasets once and emit orphan/track sources."""
    from app.core.data.erddap_tabledap import list_tabledap_datasets

    batch = DiscoveryBatch(provider_key=provider.key, connector=provider.connector)
    server = resolve_provider_base_url(provider)
    if not server:
        batch.errors.append(f"No base URL for provider {provider.key}")
        return batch

    try:
        df = list_tabledap_datasets(
            server=server,
            dataset_id_filter=provider.dataset_id_filter,
        )
    except Exception as exc:
        logger.exception("ERDDAP allDatasets failed for %s", provider.key)
        batch.errors.append(str(exc))
        return batch

    if df is None or df.empty:
        logger.info("ERDDAP discovery %s: empty inventory", provider.key)
        return batch

    colmap = {str(c).split(" ")[0].lower(): c for c in df.columns}
    id_col = colmap.get("datasetid")
    title_col = colmap.get("title")
    min_col = colmap.get("mintime")
    max_col = colmap.get("maxtime")
    if not id_col:
        batch.errors.append("allDatasets response missing datasetID column")
        return batch

    for _, row in df.iterrows():
        dataset_id = str(row[id_col]).strip()
        if not dataset_id or dataset_id.lower() == "nan":
            continue
        parsed = parse_erddap_dataset_id(dataset_id)
        family = None
        if parsed:
            family = classify_platform_family(
                parsed["prefix"],
                wave_glider_prefixes=manifest.wave_glider_prefixes,
                slocum_known_names=manifest.slocum_known_names,
            )
            if family is None:
                if parsed["prefix"].isupper() or parsed["prefix"].upper() in {
                    p.upper() for p in manifest.wave_glider_prefixes
                }:
                    family = "wave_glider"
                else:
                    family = "slocum"

        start_time = None
        end_time = None
        if parsed and parsed.get("start_date"):
            start_time = datetime(
                parsed["start_date"].year,
                parsed["start_date"].month,
                parsed["start_date"].day,
                tzinfo=timezone.utc,
            )
        if min_col is not None:
            start_time = _parse_dt(row[min_col]) or start_time
        if max_col is not None:
            end_time = _parse_dt(row[max_col])

        title = str(row[title_col]).strip() if title_col is not None else None
        batch.orphan_sources.append(
            DiscoveredSource(
                provider_key=provider.key,
                source_kind=CatalogSourceKind.ERDDAP,
                collection="tabledap",
                external_ref=dataset_id,
                source_variant=_variant_from_mode(parsed.get("mode") if parsed else None),
                capabilities=["track"],
                priority=50 if (parsed and parsed.get("mode") == "realtime") else 60,
                is_verified=True,
                platform_hint=parsed["prefix"] if parsed else None,
                platform_family_hint=family,
                deployment_number=parsed["deployment_number"] if parsed else None,
                start_time=start_time,
                end_time=end_time,
                title=title,
                owner_organization=provider.organization,
                metadata={"server": server},
            )
        )

    logger.info(
        "ERDDAP discovery %s: %d datasets",
        provider.key,
        len(batch.orphan_sources),
    )
    return batch
