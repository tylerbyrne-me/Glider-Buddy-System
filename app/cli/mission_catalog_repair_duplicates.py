"""Report (and optionally repair) duplicate catalog live-row links and Slocum mission_key orphans.

Run before Alembic ``20260911_catalog_ops`` / ``20260915_slocum_mission_key`` unique indexes.

  python -m app.cli.mission_catalog_repair_duplicates
  python -m app.cli.mission_catalog_repair_duplicates --apply
  python -m app.cli.mission_catalog_repair_duplicates --wg-inventory
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session, select

from app.core.infra.db import sqlite_engine
from app.core.mission_catalog.display_labels import inventory_wave_glider_keys
from app.core.mission_catalog.live_link import (
    prefer_slocum_deployment,
    prefer_wave_glider_overview,
)
from app.core.models.database import (
    MissionOverview,
    SlocumDeployment,
    SlocumDeploymentGoal,
    SlocumDeploymentMedia,
    SlocumDeploymentNote,
)
from app.core.utils import slocum_mission_key

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("mission_catalog_repair_duplicates")


def find_overview_duplicates(session: Session) -> Dict[str, List[MissionOverview]]:
    by_catalog: Dict[str, List[MissionOverview]] = defaultdict(list)
    for row in session.exec(select(MissionOverview)).all():
        cid = getattr(row, "catalog_mission_id", None)
        if cid:
            by_catalog[cid].append(row)
    return {k: v for k, v in by_catalog.items() if len(v) > 1}


def find_active_slocum_duplicates(session: Session) -> Dict[str, List[SlocumDeployment]]:
    by_catalog: Dict[str, List[SlocumDeployment]] = defaultdict(list)
    for row in session.exec(select(SlocumDeployment)).all():
        cid = getattr(row, "catalog_mission_id", None)
        if not cid:
            continue
        if not bool(getattr(row, "is_active", True)):
            continue
        by_catalog[cid].append(row)
    return {k: v for k, v in by_catalog.items() if len(v) > 1}


def _normalized_mission_key(dep: SlocumDeployment) -> Optional[str]:
    raw = (dep.mission_key or "").strip()
    if raw:
        return slocum_mission_key(raw) or raw
    erddap = (dep.erddap_dataset_id or "").strip()
    if erddap:
        return slocum_mission_key(erddap) or None
    return None


def _child_counts(session: Session, deployment_id: int) -> Dict[str, int]:
    goals = session.exec(
        select(SlocumDeploymentGoal).where(
            SlocumDeploymentGoal.deployment_id == deployment_id
        )
    ).all()
    notes = session.exec(
        select(SlocumDeploymentNote).where(
            SlocumDeploymentNote.deployment_id == deployment_id
        )
    ).all()
    media = session.exec(
        select(SlocumDeploymentMedia).where(
            SlocumDeploymentMedia.deployment_id == deployment_id
        )
    ).all()
    return {
        "goals": len(goals),
        "notes": len(notes),
        "media": len(media),
    }


def _has_briefing_metadata(dep: SlocumDeployment, counts: Dict[str, int]) -> bool:
    if any(counts.get(k, 0) > 0 for k in ("goals", "notes", "media")):
        return True
    if dep.document_url or dep.weekly_report_url or dep.end_of_mission_report_url:
        return True
    if dep.robots4whales_url:
        return True
    if dep.notes and str(dep.notes).strip():
        return True
    if dep.checklist_reference_values and str(dep.checklist_reference_values).strip() not in (
        "",
        "{}",
        "null",
    ):
        return True
    # enabled_sensor_cards defaults empty / ["ctd"] alone do not count as owned metadata
    return False


def _is_empty_orphan(dep: SlocumDeployment, counts: Dict[str, int]) -> bool:
    if getattr(dep, "catalog_mission_id", None):
        return False
    if _has_briefing_metadata(dep, counts):
        return False
    return True


def find_mission_key_groups(
    session: Session,
) -> Dict[str, List[Dict[str, Any]]]:
    """Group all SlocumDeployments by normalized mission_key (active + inactive)."""
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for dep in session.exec(select(SlocumDeployment)).all():
        key = _normalized_mission_key(dep)
        if not key:
            continue
        counts = _child_counts(session, dep.id) if dep.id is not None else {
            "goals": 0,
            "notes": 0,
            "media": 0,
        }
        groups[key].append(
            {
                "deployment": dep,
                "counts": counts,
                "has_metadata": _has_briefing_metadata(dep, counts),
                "is_empty_orphan": _is_empty_orphan(dep, counts),
            }
        )
    return {k: v for k, v in groups.items() if len(v) > 1}


def classify_mission_key_group(
    items: List[Dict[str, Any]],
) -> Tuple[str, Optional[SlocumDeployment], List[SlocumDeployment]]:
    """
    Return (status, owner, orphans_to_remove).

    Safe auto-repair: exactly one inactive catalog-linked metadata owner plus
    one or more empty active orphans.
    """
    deps = [i["deployment"] for i in items]
    owners = [
        i
        for i in items
        if getattr(i["deployment"], "catalog_mission_id", None)
        and i["has_metadata"]
        and not bool(getattr(i["deployment"], "is_active", True))
    ]
    empty_active = [
        i
        for i in items
        if i["is_empty_orphan"] and bool(getattr(i["deployment"], "is_active", True))
    ]
    metadata_rows = [i for i in items if i["has_metadata"]]

    if len(owners) == 1 and empty_active and len(metadata_rows) == 1:
        return (
            "safe_auto",
            owners[0]["deployment"],
            [i["deployment"] for i in empty_active],
        )
    if len(metadata_rows) > 1:
        return ("ambiguous_metadata", None, [])
    return ("manual", None, [])


def report_mission_key_groups(session: Session) -> Dict[str, List[Dict[str, Any]]]:
    groups = find_mission_key_groups(session)
    for key, items in groups.items():
        status, owner, orphans = classify_mission_key_group(items)
        logger.info(
            "mission_key=%s status=%s rows=%d owner_id=%s orphan_ids=%s",
            key,
            status,
            len(items),
            getattr(owner, "id", None),
            [o.id for o in orphans],
        )
        for item in items:
            dep = item["deployment"]
            logger.info(
                "  id=%s active=%s catalog=%s erddap=%s meta=%s counts=%s",
                dep.id,
                dep.is_active,
                getattr(dep, "catalog_mission_id", None),
                dep.erddap_dataset_id,
                item["has_metadata"],
                item["counts"],
            )
    return groups


def repair_mission_key_orphans(session: Session, *, apply: bool) -> int:
    """Remove empty active orphans when a single completed metadata owner exists."""
    fixed = 0
    groups = find_mission_key_groups(session)
    for key, items in groups.items():
        status, owner, orphans = classify_mission_key_group(items)
        if status != "safe_auto" or owner is None or not orphans:
            if status == "ambiguous_metadata":
                logger.warning(
                    "Ambiguous mission_key=%s has metadata on multiple rows — resolve manually",
                    key,
                )
            elif status == "manual":
                logger.warning(
                    "mission_key=%s needs manual review (not a safe empty-orphan case)",
                    key,
                )
            continue
        for orphan in orphans:
            logger.info(
                "Would delete empty active orphan SlocumDeployment id=%s "
                "(mission_key=%s) keeping owner id=%s",
                orphan.id,
                key,
                owner.id,
            )
            if apply:
                session.delete(orphan)
                fixed += 1
    return fixed


def repair_overviews(
    session: Session, dups: Dict[str, List[MissionOverview]], *, apply: bool
) -> int:
    fixed = 0
    for catalog_id, siblings in dups.items():
        preferred = prefer_wave_glider_overview(siblings)
        if preferred is None:
            logger.warning(
                "Ambiguous WG overviews for %s: %s — resolve manually",
                catalog_id,
                [o.mission_id for o in siblings],
            )
            continue
        for overview in siblings:
            if overview.mission_id == preferred.mission_id:
                continue
            logger.info(
                "Would unlink overview %s from catalog %s (keep %s)",
                overview.mission_id,
                catalog_id,
                preferred.mission_id,
            )
            if apply:
                overview.catalog_mission_id = None
                session.add(overview)
                fixed += 1
    return fixed


def repair_slocum(
    session: Session, dups: Dict[str, List[SlocumDeployment]], *, apply: bool
) -> int:
    fixed = 0
    for catalog_id, siblings in dups.items():
        preferred = prefer_slocum_deployment(siblings)
        if preferred is None:
            logger.warning(
                "Ambiguous active Slocum for %s: %s — resolve manually",
                catalog_id,
                [d.id for d in siblings],
            )
            continue
        for dep in siblings:
            if dep.id == preferred.id:
                continue
            logger.info(
                "Would deactivate Slocum %s (dataset=%s) for catalog %s (keep %s)",
                dep.id,
                dep.erddap_dataset_id,
                catalog_id,
                preferred.id,
            )
            if apply:
                dep.is_active = False
                dep.status = "completed"
                session.add(dep)
                fixed += 1
    return fixed


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write repairs (default is report-only)",
    )
    parser.add_argument(
        "--wg-inventory",
        action="store_true",
        help="Print read-only Wave Glider key/label inventory and exit",
    )
    args = parser.parse_args(argv)

    with Session(sqlite_engine) as session:
        if args.wg_inventory:
            rows = inventory_wave_glider_keys(session)
            logger.info("WG inventory rows=%d", len(rows))
            for row in rows:
                logger.info(
                    "  key=%s label=%s catalog=%s platform=%s legacy=%s bare=%s differs=%s disk=%s",
                    row.get("key"),
                    row.get("label"),
                    row.get("catalog_mission_id"),
                    row.get("platform_canonical_name"),
                    row.get("is_legacy_hull_key"),
                    row.get("is_bare_mission_code"),
                    row.get("label_differs_from_key"),
                    row.get("disk_path_hint"),
                )
            return 0

        overview_dups = find_overview_duplicates(session)
        slocum_dups = find_active_slocum_duplicates(session)
        mission_key_groups = report_mission_key_groups(session)

        if not overview_dups and not slocum_dups and not mission_key_groups:
            logger.info("No duplicate live-row catalog links or mission_key groups found.")
            return 0

        logger.info(
            "Found %d overview duplicate groups, %d active Slocum catalog duplicate groups, "
            "%d mission_key duplicate groups",
            len(overview_dups),
            len(slocum_dups),
            len(mission_key_groups),
        )
        for cid, rows in overview_dups.items():
            logger.info(
                "  overview catalog=%s -> %s",
                cid,
                [o.mission_id for o in rows],
            )
        for cid, rows in slocum_dups.items():
            logger.info(
                "  slocum catalog=%s -> %s",
                cid,
                [(d.id, d.erddap_dataset_id, d.is_active) for d in rows],
            )

        fixed_o = repair_overviews(session, overview_dups, apply=args.apply)
        fixed_s = repair_slocum(session, slocum_dups, apply=args.apply)
        fixed_k = repair_mission_key_orphans(session, apply=args.apply)
        if args.apply:
            session.commit()
            logger.info(
                "Applied repairs: overviews=%d slocum_catalog=%d mission_key_orphans=%d",
                fixed_o,
                fixed_s,
                fixed_k,
            )
        else:
            logger.info("Dry-run only. Re-run with --apply to write.")

        remaining_o = find_overview_duplicates(session) if args.apply else overview_dups
        remaining_s = (
            find_active_slocum_duplicates(session) if args.apply else slocum_dups
        )
        remaining_k = find_mission_key_groups(session) if args.apply else mission_key_groups
        unsafe_k = {
            k: v
            for k, v in remaining_k.items()
            if classify_mission_key_group(v)[0] != "safe_auto"
        }
        # After apply, safe_auto groups should be gone; any remaining mission_key
        # duplicates block the uniqueness migration.
        if remaining_o or remaining_s or (args.apply and remaining_k) or (
            not args.apply and unsafe_k and not remaining_o and not remaining_s
        ):
            # Dry-run with only safe_auto pending is OK (exit 0 with message).
            if not args.apply and not remaining_o and not remaining_s:
                only_safe = all(
                    classify_mission_key_group(v)[0] == "safe_auto"
                    for v in remaining_k.values()
                )
                if only_safe:
                    logger.info(
                        "Only safe mission_key orphan groups remain; re-run with --apply."
                    )
                    return 0
            if remaining_o or remaining_s or remaining_k:
                logger.error(
                    "Duplicates remain; unique-index migrations will fail until resolved."
                )
                return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
