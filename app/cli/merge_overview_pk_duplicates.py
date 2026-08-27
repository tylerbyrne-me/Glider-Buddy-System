"""One-off: merge legacy ####-m### MissionOverview children onto canonical PKs.

Default is --dry-run (print every row that would move/delete). Pass --apply to write.

Merges (plan Phase 4):
  1070-m211 → m211
  1070-m216 → m216

Deletes (empty duplicates after verify):
  1071-m169, 1071-m209, stray 1071

Leaves alone: single legacy ####-m### rows, _test/_offloads, m204_realtime.

Outbox caution: pending_review / approved rows on the source PK are reported and
block --apply unless --force-outbox is set (rewriting mission_id can re-queue
work). Historical synced/rejected/failed rows are rewritten with a warning.

Examples:
  python -m app.cli.merge_overview_pk_duplicates --dry-run
  python -m app.cli.merge_overview_pk_duplicates --apply
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlmodel import Session, select

from app.core.infra.db import SQLModelSession, sqlite_engine
from app.core.models.database import (
    MissionGoal,
    MissionMedia,
    MissionNote,
    MissionOverview,
    SensorTrackerDeployment,
    SensorTrackerOutbox,
    SubmittedForm,
    Vm4ProcessingCheckpoint,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("merge_overview_pk_duplicates")

# Pending statuses that could re-trigger outbox processing after a PK rewrite.
_OUTBOX_BLOCKING_STATUSES = frozenset({"pending_review", "approved"})

MERGE_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("1070-m211", "m211"),
    ("1070-m216", "m216"),
)

DELETE_EMPTY: Tuple[str, ...] = (
    "1071-m169",
    "1071-m209",
    "1071",
)


@dataclass
class MergePlan:
    lines: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    move_counts: Dict[str, int] = field(default_factory=dict)
    delete_ids: List[str] = field(default_factory=list)

    def note(self, message: str) -> None:
        self.lines.append(message)
        logger.info(message)

    def block(self, message: str) -> None:
        self.blockers.append(message)
        logger.warning("BLOCKER: %s", message)


def _count_children(session: Session, mission_id: str) -> Dict[str, int]:
    return {
        "goals": len(
            list(session.exec(select(MissionGoal).where(MissionGoal.mission_id == mission_id)).all())
        ),
        "notes": len(
            list(session.exec(select(MissionNote).where(MissionNote.mission_id == mission_id)).all())
        ),
        "media": len(
            list(
                session.exec(select(MissionMedia).where(MissionMedia.mission_id == mission_id)).all()
            )
        ),
        "forms": len(
            list(
                session.exec(
                    select(SubmittedForm).where(SubmittedForm.mission_id == mission_id)
                ).all()
            )
        ),
        "outbox": len(
            list(
                session.exec(
                    select(SensorTrackerOutbox).where(
                        SensorTrackerOutbox.mission_id == mission_id
                    )
                ).all()
            )
        ),
        "vm4_checkpoints": len(
            list(
                session.exec(
                    select(Vm4ProcessingCheckpoint).where(
                        Vm4ProcessingCheckpoint.mission_id == mission_id
                    )
                ).all()
            )
        ),
        "st_deployments": len(
            list(
                session.exec(
                    select(SensorTrackerDeployment).where(
                        SensorTrackerDeployment.mission_id == mission_id
                    )
                ).all()
            )
        ),
    }


def _outbox_rows(session: Session, mission_id: str) -> List[SensorTrackerOutbox]:
    return list(
        session.exec(
            select(SensorTrackerOutbox).where(SensorTrackerOutbox.mission_id == mission_id)
        ).all()
    )


def _rewrite_mission_id(
    session: Session,
    *,
    model: Any,
    source_id: str,
    target_id: str,
    dry_run: bool,
    plan: MergePlan,
    label: str,
) -> int:
    rows = list(session.exec(select(model).where(model.mission_id == source_id)).all())
    if not rows:
        return 0
    plan.note(f"  {label}: move {len(rows)} row(s) {source_id} → {target_id}")
    plan.move_counts[label] = plan.move_counts.get(label, 0) + len(rows)
    if dry_run:
        return len(rows)
    for row in rows:
        row.mission_id = target_id
        session.add(row)
    return len(rows)


def _plan_merge(
    session: Session,
    *,
    source_id: str,
    target_id: str,
    dry_run: bool,
    force_outbox: bool,
    plan: MergePlan,
) -> None:
    plan.note(f"MERGE {source_id} → {target_id}")
    source = session.get(MissionOverview, source_id)
    target = session.get(MissionOverview, target_id)
    if source is None:
        plan.note(f"  skip: source overview {source_id!r} missing")
        return
    if target is None:
        plan.block(f"target overview {target_id!r} missing; refuse merge of {source_id}")
        return

    source_counts = _count_children(session, source_id)
    target_counts = _count_children(session, target_id)
    plan.note(f"  source children: {source_counts}")
    plan.note(f"  target children: {target_counts}")

    outbox = _outbox_rows(session, source_id)
    if outbox:
        by_status: Dict[str, int] = {}
        for row in outbox:
            by_status[row.status] = by_status.get(row.status, 0) + 1
        plan.note(f"  outbox by status on source: {by_status}")
        blocking = [r for r in outbox if (r.status or "") in _OUTBOX_BLOCKING_STATUSES]
        if blocking and not force_outbox:
            plan.block(
                f"{source_id}: {len(blocking)} outbox row(s) in "
                f"{sorted(_OUTBOX_BLOCKING_STATUSES)}; refuse rewrite "
                f"(pass --force-outbox after review)"
            )
            return
        if blocking and force_outbox:
            plan.note(
                f"  WARNING: --force-outbox: will rewrite {len(blocking)} "
                f"pending/approved outbox row(s)"
            )

    # SensorTrackerDeployment.mission_id is unique — cannot move if target exists.
    st_src = session.exec(
        select(SensorTrackerDeployment).where(
            SensorTrackerDeployment.mission_id == source_id
        )
    ).all()
    st_tgt = session.exec(
        select(SensorTrackerDeployment).where(
            SensorTrackerDeployment.mission_id == target_id
        )
    ).all()
    if st_src and st_tgt:
        plan.block(
            f"{source_id}: SensorTrackerDeployment exists on both source and "
            f"target; resolve manually before merge"
        )
        return
    if st_src and not st_tgt:
        plan.note(
            f"  sensor_tracker_deployments: move {len(st_src)} row(s) "
            f"{source_id} → {target_id}"
        )
        if not dry_run:
            for row in st_src:
                row.mission_id = target_id
                session.add(row)

    movers: Sequence[Tuple[Any, str]] = (
        (MissionGoal, "goals"),
        (MissionNote, "notes"),
        (MissionMedia, "media"),
        (SubmittedForm, "submitted_forms"),
        (SensorTrackerOutbox, "sensor_tracker_outbox"),
        (Vm4ProcessingCheckpoint, "vm4_checkpoints"),
    )
    for model, label in movers:
        _rewrite_mission_id(
            session,
            model=model,
            source_id=source_id,
            target_id=target_id,
            dry_run=dry_run,
            plan=plan,
            label=label,
        )

    # Prefer keeping target overview fields; copy sparse source fields if target empty.
    if not dry_run:
        for attr in (
            "weekly_report_url",
            "end_of_mission_report_url",
            "document_url",
            "comments",
            "enabled_sensor_cards",
            "catalog_mission_id",
        ):
            if getattr(target, attr, None) in (None, "") and getattr(source, attr, None) not in (
                None,
                "",
            ):
                setattr(target, attr, getattr(source, attr))
                plan.note(f"  copy overview.{attr} from source → target")
        session.add(target)
        session.delete(source)
        plan.note(f"  delete emptied overview {source_id}")
    else:
        plan.note(f"  would delete emptied overview {source_id}")
    plan.delete_ids.append(source_id)


def _plan_delete_empty(
    session: Session,
    *,
    mission_id: str,
    dry_run: bool,
    plan: MergePlan,
) -> None:
    plan.note(f"DELETE empty duplicate {mission_id}")
    overview = session.get(MissionOverview, mission_id)
    if overview is None:
        plan.note(f"  skip: overview {mission_id!r} missing")
        return
    counts = _count_children(session, mission_id)
    plan.note(f"  children: {counts}")
    nonempty = {k: v for k, v in counts.items() if v}
    if nonempty:
        plan.block(f"{mission_id}: not empty ({nonempty}); refuse delete")
        return
    if dry_run:
        plan.note(f"  would delete overview {mission_id}")
    else:
        session.delete(overview)
        plan.note(f"  deleted overview {mission_id}")
    plan.delete_ids.append(mission_id)


def run_merge(*, dry_run: bool, force_outbox: bool) -> MergePlan:
    plan = MergePlan()
    plan.note(f"mode={'dry-run' if dry_run else 'APPLY'} force_outbox={force_outbox}")
    with SQLModelSession(sqlite_engine) as session:
        for source_id, target_id in MERGE_PAIRS:
            _plan_merge(
                session,
                source_id=source_id,
                target_id=target_id,
                dry_run=dry_run,
                force_outbox=force_outbox,
                plan=plan,
            )
        for mission_id in DELETE_EMPTY:
            _plan_delete_empty(
                session, mission_id=mission_id, dry_run=dry_run, plan=plan
            )
        if plan.blockers:
            plan.note(f"Aborting write: {len(plan.blockers)} blocker(s)")
            session.rollback()
            return plan
        if dry_run:
            plan.note("Dry-run complete (no writes).")
            session.rollback()
        else:
            session.commit()
            plan.note("Apply committed.")
    return plan


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Print planned moves/deletes (default)",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Write merges/deletes to SQLite",
    )
    parser.add_argument(
        "--force-outbox",
        action="store_true",
        help="Allow rewriting pending_review/approved outbox mission_id values",
    )
    args = parser.parse_args(argv)
    dry_run = not bool(args.apply)
    plan = run_merge(dry_run=dry_run, force_outbox=bool(args.force_outbox))
    print("--- summary ---")
    for line in plan.lines:
        print(line)
    if plan.blockers:
        print("Blockers:")
        for item in plan.blockers:
            print(f"  - {item}")
        # Dry-run still succeeds (report-only); apply refuses.
        return 0 if dry_run else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
