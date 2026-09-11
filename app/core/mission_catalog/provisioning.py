"""Idempotent post-reconcile provisioning: platform handlers + readiness."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Protocol

from sqlmodel import Session, select

from app.core.models.database import CatalogMission, CatalogPlatform
from app.core.models.enums import CatalogOperationalState, CatalogSyncPolicy

logger = logging.getLogger(__name__)


@dataclass
class ProvisioningResult:
    mission_id: str
    platform_family: Optional[str]
    readiness: str
    reasons: List[str] = field(default_factory=list)
    actions: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


class PlatformProvisioningHandler(Protocol):
    family: str

    def readiness(
        self, session: Session, mission: CatalogMission
    ) -> tuple[str, List[str]]:
        ...

    def provision(
        self, session: Session, mission: CatalogMission, *, dry_run: bool = False
    ) -> ProvisioningResult:
        ...

    def on_completed(
        self, session: Session, mission: CatalogMission, *, dry_run: bool = False
    ) -> ProvisioningResult:
        ...


_HANDLERS: Dict[str, PlatformProvisioningHandler] = {}


def register_handler(handler: PlatformProvisioningHandler) -> None:
    _HANDLERS[handler.family] = handler


def get_handler(family: Optional[str]) -> Optional[PlatformProvisioningHandler]:
    if not family:
        return None
    return _HANDLERS.get(family)


def _platform_family(session: Session, mission: CatalogMission) -> Optional[str]:
    if not mission.platform_id:
        return None
    platform = session.get(CatalogPlatform, mission.platform_id)
    return getattr(platform, "platform_family", None) if platform else None


def provision_mission(
    session: Session,
    mission: CatalogMission,
    *,
    dry_run: bool = False,
) -> ProvisioningResult:
    family = _platform_family(session, mission)
    handler = get_handler(family)
    if handler is None:
        return ProvisioningResult(
            mission_id=mission.id,
            platform_family=family,
            readiness="unsupported_family",
            reasons=[f"no_handler:{family or 'unknown'}"],
        )

    if mission.operational_state == CatalogOperationalState.COMPLETED.value:
        return handler.on_completed(session, mission, dry_run=dry_run)

    if mission.operational_state == CatalogOperationalState.PLANNED.value:
        ready, reasons = handler.readiness(session, mission)
        return ProvisioningResult(
            mission_id=mission.id,
            platform_family=family,
            readiness="waiting_for_start" if "waiting_for_start" not in reasons else ready,
            reasons=list(dict.fromkeys(["waiting_for_start", *reasons])),
        )

    if (
        mission.operational_state == CatalogOperationalState.ACTIVE.value
        and mission.sync_policy != CatalogSyncPolicy.CONTINUOUS.value
    ):
        return ProvisioningResult(
            mission_id=mission.id,
            platform_family=family,
            readiness="not_enrolled",
            reasons=["not_enrolled"],
        )

    return handler.provision(session, mission, dry_run=dry_run)


def provision_enrolled_missions(
    session: Session,
    *,
    dry_run: bool = False,
    limit: Optional[int] = None,
) -> List[ProvisioningResult]:
    """Provision ACTIVE∧CONTINUOUS missions and run completion hooks."""
    # Ensure handlers are registered.
    from app.core.mission_catalog import handlers as _handlers  # noqa: F401

    missions = list(
        session.exec(
            select(CatalogMission).where(
                CatalogMission.operational_state.in_(
                    [
                        CatalogOperationalState.ACTIVE.value,
                        CatalogOperationalState.COMPLETED.value,
                        CatalogOperationalState.PLANNED.value,
                    ]
                )
            )
        ).all()
    )
    results: List[ProvisioningResult] = []
    for mission in missions:
        if limit is not None and len(results) >= limit:
            break
        try:
            result = provision_mission(session, mission, dry_run=dry_run)
            results.append(result)
            if result.actions:
                logger.info(
                    "PROVISION: mission=%s family=%s readiness=%s actions=%s",
                    result.mission_id,
                    result.platform_family,
                    result.readiness,
                    result.actions,
                )
            if result.errors:
                logger.warning(
                    "PROVISION: mission=%s errors=%s",
                    result.mission_id,
                    result.errors,
                )
        except Exception as exc:
            logger.exception("PROVISION failed for %s", mission.id)
            results.append(
                ProvisioningResult(
                    mission_id=mission.id,
                    platform_family=_platform_family(session, mission),
                    readiness="error",
                    errors=[str(exc)],
                )
            )
    return results
