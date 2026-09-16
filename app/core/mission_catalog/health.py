"""Read-only catalog health report for Team / ops."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from app.core.models.database import (
    CatalogMission,
    CatalogMissionSource,
    CatalogMissionWorkItem,
    MissionOverview,
    SlocumDeployment,
)
from app.core.models.enums import (
    CatalogEnrollmentOverride,
    CatalogOperationalState,
    CatalogSyncPolicy,
    CatalogWorkItemStatus,
    CatalogWorkItemType,
)

# Readiness reasons that are expected (source-late / not yet numbered) vs faults.
_EXPECTED_READINESS = {
    "waiting_for_source",
    "waiting_for_start",
    "waiting_for_deployment_number",
    "waiting_for_live_row",
}


def _issue_severity(issue: str, reasons: Optional[List[str]] = None) -> str:
    if issue in (
        "enrolled_but_not_ready",
        "missing_source_links",
        "completed_final_sync_pending",
    ):
        reasons = reasons or []
        if reasons and all(r in _EXPECTED_READINESS for r in reasons):
            return "expected"
        if issue == "completed_final_sync_pending":
            return "expected"
        if issue == "enrolled_but_not_ready" and any(
            r in _EXPECTED_READINESS for r in reasons
        ):
            return "expected"
    if issue in (
        "completed_final_sync_failed",
        "completed_final_sync_exhausted",
        "duplicate_overviews",
        "duplicate_active_slocum_deployments",
        "completed_still_continuous",
        "forced_off_but_continuous",
        "stale_last_success",
    ):
        return "fault"
    return "warning"


def build_catalog_health_report(session: Session) -> Dict[str, Any]:
    from app.core.mission_catalog.status import build_catalog_status_report
    from app.core.mission_catalog.workspace import mission_readiness

    missions = list(session.exec(select(CatalogMission)).all())
    by_state: Dict[str, int] = {}
    by_policy: Dict[str, int] = {}
    issues: List[Dict[str, Any]] = []

    for mission in missions:
        by_state[mission.operational_state] = by_state.get(mission.operational_state, 0) + 1
        by_policy[mission.sync_policy] = by_policy.get(mission.sync_policy, 0) + 1

        if (
            mission.operational_state == CatalogOperationalState.COMPLETED.value
            and mission.sync_policy == CatalogSyncPolicy.CONTINUOUS.value
        ):
            issues.append(
                {
                    "mission_id": mission.id,
                    "title": mission.title,
                    "issue": "completed_still_continuous",
                    "severity": _issue_severity("completed_still_continuous"),
                }
            )
        if (
            mission.operational_state == CatalogOperationalState.ACTIVE.value
            and not mission.start_time
            and mission.deployment_number is not None
        ):
            issues.append(
                {
                    "mission_id": mission.id,
                    "title": mission.title,
                    "issue": "active_without_start_time",
                    "severity": _issue_severity("active_without_start_time"),
                }
            )
        if (
            (mission.enrollment_override or "")
            == CatalogEnrollmentOverride.FORCED_OFF.value
            and mission.sync_policy == CatalogSyncPolicy.CONTINUOUS.value
            and mission.operational_state == CatalogOperationalState.ACTIVE.value
        ):
            issues.append(
                {
                    "mission_id": mission.id,
                    "title": mission.title,
                    "issue": "forced_off_but_continuous",
                    "severity": _issue_severity("forced_off_but_continuous"),
                }
            )

        overviews = list(
            session.exec(
                select(MissionOverview).where(
                    MissionOverview.catalog_mission_id == mission.id
                )
            ).all()
        )
        slocum = list(
            session.exec(
                select(SlocumDeployment).where(
                    SlocumDeployment.catalog_mission_id == mission.id
                )
            ).all()
        )
        sources = list(
            session.exec(
                select(CatalogMissionSource).where(
                    CatalogMissionSource.mission_id == mission.id
                )
            ).all()
        )

        if (
            mission.operational_state == CatalogOperationalState.ACTIVE.value
            and mission.sync_policy == CatalogSyncPolicy.CONTINUOUS.value
        ):
            readiness, reasons, _family = mission_readiness(session, mission)
            if readiness != "ready":
                issues.append(
                    {
                        "mission_id": mission.id,
                        "title": mission.title,
                        "issue": "enrolled_but_not_ready",
                        "readiness": readiness,
                        "reasons": reasons,
                        "severity": _issue_severity(
                            "enrolled_but_not_ready", reasons
                        ),
                    }
                )
            if not sources:
                issues.append(
                    {
                        "mission_id": mission.id,
                        "title": mission.title,
                        "issue": "missing_source_links",
                        "severity": _issue_severity("missing_source_links"),
                    }
                )

        if mission.operational_state == CatalogOperationalState.COMPLETED.value:
            active_live = [d for d in slocum if d.is_active]
            if active_live:
                issues.append(
                    {
                        "mission_id": mission.id,
                        "title": mission.title,
                        "issue": "completed_without_archived_live_row",
                        "deployment_ids": [d.id for d in active_live],
                        "severity": _issue_severity(
                            "completed_without_archived_live_row"
                        ),
                    }
                )
            work = session.exec(
                select(CatalogMissionWorkItem).where(
                    CatalogMissionWorkItem.catalog_mission_id == mission.id,
                    CatalogMissionWorkItem.work_type
                    == CatalogWorkItemType.FINAL_SYNC.value,
                )
            ).first()
            if work is None or work.status in (
                CatalogWorkItemStatus.PENDING.value,
                CatalogWorkItemStatus.RUNNING.value,
            ):
                issues.append(
                    {
                        "mission_id": mission.id,
                        "title": mission.title,
                        "issue": "completed_final_sync_pending",
                        "work_status": work.status if work else None,
                        "severity": _issue_severity("completed_final_sync_pending"),
                    }
                )
            elif work.status == CatalogWorkItemStatus.FAILED.value:
                issues.append(
                    {
                        "mission_id": mission.id,
                        "title": mission.title,
                        "issue": "completed_final_sync_failed",
                        "last_error": work.last_error,
                        "severity": _issue_severity("completed_final_sync_failed"),
                    }
                )
            elif work.status == CatalogWorkItemStatus.EXHAUSTED.value:
                issues.append(
                    {
                        "mission_id": mission.id,
                        "title": mission.title,
                        "issue": "completed_final_sync_exhausted",
                        "last_error": work.last_error,
                        "severity": _issue_severity(
                            "completed_final_sync_exhausted"
                        ),
                    }
                )

        if len(overviews) > 1:
            issues.append(
                {
                    "mission_id": mission.id,
                    "title": mission.title,
                    "issue": "duplicate_overviews",
                    "overview_ids": [o.mission_id for o in overviews],
                    "severity": _issue_severity("duplicate_overviews"),
                }
            )
        active_slocum = [d for d in slocum if d.is_active]
        if len(active_slocum) > 1:
            issues.append(
                {
                    "mission_id": mission.id,
                    "title": mission.title,
                    "issue": "duplicate_active_slocum_deployments",
                    "deployment_ids": [d.id for d in active_slocum],
                    "severity": _issue_severity(
                        "duplicate_active_slocum_deployments"
                    ),
                }
            )

    enrolled_active = [
        m
        for m in missions
        if m.operational_state == CatalogOperationalState.ACTIVE.value
        and m.sync_policy == CatalogSyncPolicy.CONTINUOUS.value
    ]
    orphan_sources = list(
        session.exec(
            select(CatalogMissionSource).where(
                CatalogMissionSource.mission_id == None  # noqa: E711
            )
        ).all()
    )
    unmatched_sources = list(
        session.exec(
            select(CatalogMissionSource).where(
                CatalogMissionSource.match_status == "unmatched"
            )
        ).all()
    )

    linked_overviews = len(
        list(
            session.exec(
                select(MissionOverview).where(
                    MissionOverview.catalog_mission_id != None  # noqa: E711
                )
            ).all()
        )
    )
    linked_slocum = len(
        list(
            session.exec(
                select(SlocumDeployment).where(
                    SlocumDeployment.catalog_mission_id != None  # noqa: E711
                )
            ).all()
        )
    )

    status = build_catalog_status_report()
    if status.get("is_stale"):
        issues.append(
            {
                "mission_id": None,
                "title": None,
                "issue": "stale_last_success",
                "last_success_at": status.get("last_success_at"),
                "severity": _issue_severity("stale_last_success"),
            }
        )

    fault_count = sum(1 for i in issues if i.get("severity") == "fault")
    expected_count = sum(1 for i in issues if i.get("severity") == "expected")
    warning_count = sum(1 for i in issues if i.get("severity") == "warning")

    return {
        "mission_count": len(missions),
        "by_operational_state": by_state,
        "by_sync_policy": by_policy,
        "enrolled_active_count": len(enrolled_active),
        "linked_overviews": linked_overviews,
        "linked_slocum_deployments": linked_slocum,
        "orphan_sources": len(orphan_sources),
        "unmatched_sources": len(unmatched_sources),
        "status": status,
        "issues": issues[:200],
        "issue_count": len(issues),
        "fault_count": fault_count,
        "expected_count": expected_count,
        "warning_count": warning_count,
        "overall_severity": (
            "fault" if fault_count else ("warning" if warning_count else "ok")
        ),
    }
