"""Dry-run / apply gate reports for live-key-safe catalog cutover."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set

from sqlmodel import Session, select

from app.config import settings
from app.core.mission_aliases import (
    configured_slocum_dataset_keys,
    resolve_slocum_dataset_id,
)
from app.core.mission_catalog.schemas import DiscoveryBatch, ReconcileResult
from app.core.models.database import (
    CatalogExternalIdentity,
    CatalogMission,
    CatalogPlatform,
)
from app.core.models.enums import CatalogIdentityKind, CatalogOperationalState
from app.core.utils import deployment_mission_code_from_mission_id, slocum_mission_key


@dataclass
class CatalogGateReport:
    st_preemptive_no_mission_id: int = 0
    st_open_with_number: int = 0
    duplicate_deployment_codes: List[str] = field(default_factory=list)
    platforms_sharing_prefix_as_identity: List[str] = field(default_factory=list)
    env_wg_keys: List[str] = field(default_factory=list)
    env_wg_matched: List[str] = field(default_factory=list)
    env_wg_missing: List[str] = field(default_factory=list)
    env_slocum_keys: List[str] = field(default_factory=list)
    env_slocum_matched: List[str] = field(default_factory=list)
    env_slocum_missing: List[str] = field(default_factory=list)
    catalog_extras_with_number: List[str] = field(default_factory=list)
    proposed_app_keys: Dict[str, str] = field(default_factory=dict)
    blockers: List[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.blockers

    def summary_lines(self) -> List[str]:
        lines = [
            (
                f"Gates: preemptive_no_mid={self.st_preemptive_no_mission_id} "
                f"st_open_with_number={self.st_open_with_number} "
                f"dup_codes={len(self.duplicate_deployment_codes)} "
                f"prefix_identity_issues={len(self.platforms_sharing_prefix_as_identity)}"
            ),
            (
                f"Env WG: total={len(self.env_wg_keys)} matched={len(self.env_wg_matched)} "
                f"missing={len(self.env_wg_missing)}"
            ),
            (
                f"Env Slocum: total={len(self.env_slocum_keys)} "
                f"matched={len(self.env_slocum_matched)} "
                f"missing={len(self.env_slocum_missing)}"
            ),
            f"Catalog extras (m{{n}} not in env): {len(self.catalog_extras_with_number)}",
        ]
        if self.blockers:
            lines.append("BLOCKERS:")
            lines.extend(f"  - {b}" for b in self.blockers[:40])
        else:
            lines.append("Gates: CLEAN (safe to consider --apply)")
        return lines


def _codes_from_batches(batches: Sequence[DiscoveryBatch]) -> Counter:
    counter: Counter = Counter()
    for batch in batches:
        for mission in batch.missions:
            if mission.deployment_number is None:
                continue
            counter[f"m{int(mission.deployment_number)}"] += 1
    return counter


def build_gate_report_from_batches(
    batches: Sequence[DiscoveryBatch],
    *,
    session: Optional[Session] = None,
) -> CatalogGateReport:
    """Build gate report from discovery batches (works for dry-run before DB write)."""
    report = CatalogGateReport()
    report.env_wg_keys = [
        m.strip() for m in (settings.active_realtime_missions or []) if m and str(m).strip()
    ]
    report.env_slocum_keys = configured_slocum_dataset_keys(settings.active_slocum_datasets) + (
        configured_slocum_dataset_keys(settings.historical_slocum_datasets)
    )

    env_codes = {
        deployment_mission_code_from_mission_id(k).lower()
        for k in report.env_wg_keys
        if deployment_mission_code_from_mission_id(k)
    }
    env_slocum_mkeys = set()
    for key in report.env_slocum_keys:
        canonical = resolve_slocum_dataset_id(key)
        env_slocum_mkeys.add(slocum_mission_key(canonical) or canonical)

    seen_codes: Dict[str, int] = defaultdict(int)
    platform_names_by_prefix: Dict[str, Set[str]] = defaultdict(set)
    discovered_codes: Set[str] = set()
    discovered_slocum_keys: Set[str] = set()

    for batch in batches:
        for mission in batch.missions:
            if mission.deployment_number is None:
                # Count ST preemptive only
                if batch.connector == "sensor_tracker" or (
                    mission.metadata or {}
                ).get("st_preemptive"):
                    report.st_preemptive_no_mission_id += 1
                continue

            code = f"m{int(mission.deployment_number)}"
            discovered_codes.add(code)
            seen_codes[code] += 1
            if batch.connector == "sensor_tracker":
                if mission.end_time is None:
                    report.st_open_with_number += 1
                report.proposed_app_keys[code] = code

            if mission.platform and mission.platform.data_prefix:
                platform_names_by_prefix[mission.platform.data_prefix].add(
                    mission.platform.canonical_name
                )

            for identity in mission.identities:
                kind = (
                    identity.identity_kind.value
                    if hasattr(identity.identity_kind, "value")
                    else str(identity.identity_kind)
                )
                if kind == CatalogIdentityKind.ERDDAP_MISSION_KEY.value:
                    discovered_slocum_keys.add(identity.external_id)

    # Duplicates across providers for same code are expected to merge — count
    # only when the same provider emits the code twice, or when we would create
    # multiple ST missions for one code.
    st_codes: Counter = Counter()
    for batch in batches:
        if batch.connector != "sensor_tracker":
            continue
        for mission in batch.missions:
            if mission.deployment_number is None:
                continue
            st_codes[f"m{int(mission.deployment_number)}"] += 1
    report.duplicate_deployment_codes = sorted(
        [c for c, n in st_codes.items() if n > 1]
    )

    for prefix, names in platform_names_by_prefix.items():
        if len(names) > 1:
            # Multiple vehicles sharing a naming prefix is OK; identity must
            # not collapse them. Flag only if we detect identical canonical names.
            pass

    for key in report.env_wg_keys:
        code = deployment_mission_code_from_mission_id(key)
        if code and code.lower() in {c.lower() for c in discovered_codes}:
            report.env_wg_matched.append(key)
            # Proposed app key must equal env key string when overview uses folder form —
            # enablement returns the env string unchanged.
            report.proposed_app_keys[key] = key
        else:
            report.env_wg_missing.append(key)

    for key in report.env_slocum_keys:
        canonical = resolve_slocum_dataset_id(key)
        mkey = slocum_mission_key(canonical) or canonical
        if mkey in discovered_slocum_keys or canonical in discovered_slocum_keys:
            report.env_slocum_matched.append(key)
            report.proposed_app_keys[key] = key
        else:
            # Legacy env / ST may still match by deployment number embedded in dataset id
            from app.core.mission_catalog.naming import parse_erddap_dataset_id

            parsed = parse_erddap_dataset_id(canonical)
            if parsed and f"m{parsed['deployment_number']}" in discovered_codes:
                report.env_slocum_matched.append(key)
                report.proposed_app_keys[key] = key
            else:
                report.env_slocum_missing.append(key)

    report.catalog_extras_with_number = sorted(
        c for c in discovered_codes if c.lower() not in env_codes
    )

    if report.duplicate_deployment_codes:
        report.blockers.append(
            f"Duplicate ST deployment_code within ST batch: {report.duplicate_deployment_codes}"
        )
    if report.env_wg_missing:
        report.blockers.append(
            f"Env WG keys not discovered in catalog providers: {report.env_wg_missing}"
        )
    # Slocum env missing is a warning during early apply if only ST ran — only
    # block when legacy_env was among batches and still missing.
    connectors = {b.connector for b in batches}
    if "legacy_env" in connectors and report.env_slocum_missing:
        report.blockers.append(
            f"Env Slocum keys not discovered: {report.env_slocum_missing}"
        )

    if session is not None:
        # Post-apply: check platforms were not merged by prefix
        by_prefix: Dict[str, List[str]] = defaultdict(list)
        for platform in session.exec(select(CatalogPlatform)).all():
            if platform.data_prefix:
                by_prefix[platform.data_prefix].append(platform.canonical_name)
        for prefix, names in by_prefix.items():
            unique = sorted(set(names))
            if len(unique) < len(names):
                report.platforms_sharing_prefix_as_identity.append(prefix)
                report.blockers.append(
                    f"Platform rows collapsed under data_prefix={prefix}: {names}"
                )

        # Duplicate global deployment_code across different missions
        code_missions: Dict[str, Set[str]] = defaultdict(set)
        for identity in session.exec(
            select(CatalogExternalIdentity).where(
                CatalogExternalIdentity.identity_kind
                == CatalogIdentityKind.DEPLOYMENT_CODE.value
            )
        ).all():
            code_missions[identity.external_id.lower()].add(identity.mission_id)
        for code, mission_ids in code_missions.items():
            if len(mission_ids) > 1:
                report.duplicate_deployment_codes.append(code)
                report.blockers.append(
                    f"deployment_code {code} maps to {len(mission_ids)} catalog missions"
                )

    return report


def append_gate_summary(result: ReconcileResult, report: CatalogGateReport) -> ReconcileResult:
    extra = " | ".join(report.summary_lines()[:4])
    result.summary = f"{result.summary}; {extra}"
    return result
