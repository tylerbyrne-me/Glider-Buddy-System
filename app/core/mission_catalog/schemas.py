"""Pydantic DTOs for mission catalog discovery and resolution."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.core.models.enums import (
    CatalogIdentityKind,
    CatalogMatchStatus,
    CatalogOperationalState,
    CatalogSourceKind,
    CatalogSourceVariant,
    CatalogSyncPolicy,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DiscoveredPlatform(BaseModel):
    """Normalized platform asset observation from a provider."""

    canonical_name: str
    platform_family: Optional[str] = None
    owner_organization: Optional[str] = None
    data_prefix: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DiscoveredIdentity(BaseModel):
    provider_key: str
    identity_kind: CatalogIdentityKind
    external_id: str
    is_canonical: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DiscoveredSource(BaseModel):
    """Normalized data-location observation from a provider."""

    provider_key: str
    source_kind: CatalogSourceKind
    collection: str = ""
    external_ref: str
    source_variant: CatalogSourceVariant = CatalogSourceVariant.UNKNOWN
    capabilities: List[str] = Field(default_factory=list)
    priority: int = 100
    is_verified: bool = False
    platform_hint: Optional[str] = None
    platform_family_hint: Optional[str] = None
    deployment_number: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    title: Optional[str] = None
    owner_organization: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DiscoveredMission(BaseModel):
    """Normalized mission observation (may include nested sources/identities)."""

    provider_key: str
    title: Optional[str] = None
    deployment_number: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    operational_state: CatalogOperationalState = CatalogOperationalState.ACTIVE
    sync_policy: CatalogSyncPolicy = CatalogSyncPolicy.CATALOG_ONLY
    platform: Optional[DiscoveredPlatform] = None
    identities: List[DiscoveredIdentity] = Field(default_factory=list)
    sources: List[DiscoveredSource] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DiscoveryBatch(BaseModel):
    """All observations returned by one provider adapter run."""

    provider_key: str
    connector: str
    missions: List[DiscoveredMission] = Field(default_factory=list)
    orphan_sources: List[DiscoveredSource] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=_utcnow)


class MissionCatalogQuery(BaseModel):
    platform_family: Optional[str] = None
    operational_state: Optional[str] = None
    sync_policy: Optional[str] = None
    source_kind: Optional[str] = None
    provider_key: Optional[str] = None
    capability: Optional[str] = None
    match_status: Optional[str] = None
    include_unmatched_sources: bool = False
    limit: Optional[int] = None


class CatalogSourceRead(BaseModel):
    id: Optional[int] = None
    mission_id: Optional[str] = None
    provider_key: str
    source_kind: str
    collection: str
    external_ref: str
    source_variant: str
    capabilities: List[str] = Field(default_factory=list)
    priority: int = 100
    enabled: bool = True
    match_status: str = CatalogMatchStatus.UNMATCHED.value
    is_verified: bool = False


class UnmatchedSourceRead(BaseModel):
    """Flat review DTO for orphan catalog sources (admin UI)."""

    id: Optional[int] = None
    provider_key: str
    source_kind: str
    collection: str = ""
    external_ref: str
    source_variant: str
    match_status: str = CatalogMatchStatus.UNMATCHED.value
    enabled: bool = True
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    provider_url: Optional[str] = None


class CatalogMissionRead(BaseModel):
    id: str
    title: Optional[str] = None
    deployment_number: Optional[int] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    operational_state: str
    sync_policy: str
    platform_family: Optional[str] = None
    platform_name: Optional[str] = None
    owner_organization: Optional[str] = None
    sources: List[CatalogSourceRead] = Field(default_factory=list)


class MissionSourceRequest(BaseModel):
    mission_id: Optional[str] = None
    identity_kind: Optional[str] = None
    identity_value: Optional[str] = None
    required_capability: str = "track"
    preferred_source_kind: Optional[str] = None
    preferred_variant: Optional[str] = None
    provider_key: Optional[str] = None
    allow_unverified: bool = False


class MissionSourceResolution(BaseModel):
    mission_id: Optional[str] = None
    selected: Optional[CatalogSourceRead] = None
    alternates: List[CatalogSourceRead] = Field(default_factory=list)
    explanation: str = ""


class ReconcileCounts(BaseModel):
    discovered: int = 0
    platforms_upserted: int = 0
    missions_created: int = 0
    missions_updated: int = 0
    identities_upserted: int = 0
    sources_linked: int = 0
    sources_unmatched: int = 0
    conflicts: int = 0
    stale: int = 0
    failed: int = 0


class ReconcileResult(BaseModel):
    dry_run: bool
    counts: ReconcileCounts = Field(default_factory=ReconcileCounts)
    conflicts: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    summary: str = ""
