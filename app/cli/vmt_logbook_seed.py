"""Seed the Team VMT log book from the historical spreadsheet inventory.

Idempotent upsert by serial_number. Battery checks and InnovaSea service
columns are appended only when no matching seed row already exists.

Examples:
  python -m app.cli.vmt_logbook_seed --dry-run
  python -m app.cli.vmt_logbook_seed --apply
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlmodel import Session as SQLModelSession, select

from app.core.infra.db import sqlite_engine
from app.core.models.database import VmtBatteryCheck, VmtServiceEvent, VmtUnit
from app.core.models.enums import (
    VmtCreatedVia,
    VmtCustodyStatus,
    VmtSensorTrackerLinkStatus,
    VmtServiceEventType,
)
from app.services.team_vmt_logbook import DEFAULT_CODE_MAP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("vmt_logbook_seed")

# Spreadsheet inventory (SN, ID, location, days, percent, checked, always_tx, comments,
# innovasea_2021, innovasea_2023, innovasea_2024, innovasea_2026)
_SEED_ROWS: List[Dict[str, Any]] = [
    {
        "serial": "1188712",
        "tag_id": "25026",
        "location": "On Loan",
        "days": 189,
        "percent": 62,
        "checked": "2026-06-19",
        "always_tx": True,
        "comments": (
            "DFO WASP loaner. Jan 2026 - Started new study, erased data. "
            "Set to not log every Tx."
        ),
        "svc_2021": "Head replacement & batt",
        "svc_2026": "Head replacement & batt",
    },
    {
        "serial": "1188719",
        "tag_id": "25033",
        "location": "Innovasea",
        "days": 42,
        "percent": 14,
        "checked": "2026-01-13",
        "always_tx": True,
        "comments": "Needs rebattery 2026",
    },
    {
        "serial": "1272212",
        "tag_id": "13886",
        "location": "On Loan",
        "days": 209,
        "percent": 68,
        "checked": "2026-01-13",
        "always_tx": False,
        "comments": (
            "Alseamar - Set to Never Tx, offloaded, erased data and started "
            "new study Jan 2026."
        ),
    },
    {
        "serial": "1272213",
        "tag_id": "13887",
        "location": "On Loan",
        "days": 230,
        "percent": 75,
        "checked": "2026-01-13",
        "always_tx": False,
        "comments": (
            "Alseamar - Set to Never Tx, offloaded, erased data and started "
            "new study Jan 2026."
        ),
    },
    {
        "serial": "1272214",
        "tag_id": "13884",
        "location": "Innovasea",
        "days": 43,
        "percent": 14,
        "checked": "2026-01-13",
        "always_tx": False,
        "comments": "Needs rebattery 2026",
        "svc_2021": "Head replacement & batt",
        "svc_2023": "Rebattery",
    },
    {
        "serial": "1272215",
        "tag_id": "13885",
        "location": "COVE",
        "days": 136,
        "percent": 37,
        "checked": "2026-01-13",
        "always_tx": False,
        "comments": "Jan 2026 - Started new study, erased data.",
        "svc_2021": "Head replacement & batt",
        "svc_2024": "Replaced mainboard, hydrophone and battery.",
    },
    {
        "serial": "1282444",
        "tag_id": "11808",
        "location": "Peggy",
        "days": 200,
        "percent": 65,
        "checked": "2026-04-24",
        "always_tx": True,
        "comments": "Offloaded and battery checked after MARLOA mission",
        "svc_2021": "code space update only",
        "svc_2023": "Rebattery",
    },
    {
        "serial": "1282445",
        "tag_id": "11809",
        "location": "SV3-1071",
        "days": 156,
        "percent": 51,
        "checked": "2026-07-06",
        "always_tx": False,
        "comments": (
            "July 2026 - Started new study, erased data. Set to Never Tx for Wave Glider."
        ),
        "svc_2021": "code space update only",
        "svc_2023": "Replaced mainboard, hydrophone and battery.",
    },
    {
        "serial": "1282450",
        "tag_id": "11814",
        "location": "COVE",
        "days": 116,
        "percent": 38,
        "checked": "2026-01-13",
        "always_tx": True,
        "comments": "Jan 2026 - Started new study, erased data. Set to log every Tx.",
        "svc_2021": "Rebattery only",
        "svc_2023": "Replaced hydrophone and battery.",
    },
    {
        "serial": "1282455",
        "tag_id": "11819",
        "location": "COVE",
        "days": 116,
        "percent": 38,
        "checked": "2026-01-13",
        "always_tx": True,
        "comments": "Jan 2026 - Started new study, erased data. Set to log every Tx.",
        "svc_2021": "Head replacement",
        "svc_2023": "MB replacement (manufacturer error) and rebattery.",
    },
    {
        "serial": "1360646",
        "tag_id": "1800",
        "location": "COVE",
        "days": 121,
        "percent": 39,
        "checked": "2026-01-13",
        "always_tx": True,
        "comments": "Jan 2026 - Started new study, erased data. Set to log every Tx.",
        "svc_2024": "Rebattery",
    },
    {
        "serial": "1360647",
        "tag_id": "1801",
        "location": "On Loan",
        "days": 240,
        "percent": 79,
        "checked": "2026-06-16",
        "always_tx": False,
        "comments": (
            "June 16- offloaded DAVIES mission, erased data, started new study, "
            "Aug 16 loaned to CPAWS for vmt kayak"
        ),
        "svc_2024": "Rebattery",
    },
    {
        "serial": "1360656",
        "tag_id": "1810",
        "location": "COVE",
        "days": 130,
        "percent": 42,
        "checked": "2026-01-13",
        "always_tx": True,
        "comments": "Jan 2026 - Started new study, erased data. Set to log every Tx.",
        "svc_2023": "MB replacement (manufacturer error).",
    },
    {
        "serial": "1360668",
        "tag_id": "1822",
        "location": "Fundy",
        "days": 275,
        "percent": 90,
        "checked": "2026-01-13",
        "always_tx": True,
        "comments": "Jan 2026 - Started new study, erased data. Set to log every Tx.",
        "svc_2024": "Rebattery",
    },
    {
        "serial": "1360669",
        "tag_id": "1823",
        "location": "Sable",
        "days": 306,
        "percent": 100,
        "checked": "2026-01-13",
        "always_tx": True,
        "comments": None,
        "svc_2024": "New battery",
    },
    {
        "serial": "1360672",
        "tag_id": "1826",
        "location": "On Loan",
        "days": 73,
        "percent": 24,
        "checked": "2026-06-19",
        "always_tx": True,
        "comments": (
            "DFO WASP loaner. This was not officially on loan to DFO "
            "(should've been 1540749) but OTN making a note on the loan extension. "
            "Offloaded, erased data and started new study Jan 2026. "
            "Set to not log every Tx."
        ),
        "svc_2023": "Rebattery",
    },
    {
        "serial": "1360674",
        "tag_id": "1828",
        "location": "Innovasea",
        "days": 41,
        "percent": 13,
        "checked": "2026-01-13",
        "always_tx": True,
        "comments": "Needs rebattery 2026",
    },
    {
        "serial": "1540744",
        "tag_id": "54899",
        "location": "Sambro",
        "days": 254,
        "percent": 83,
        "checked": "2026-01-13",
        "always_tx": True,
        "comments": "On Sambro for Iceland mission 2026",
        "svc_2023": "Reprogrammed",
    },
    {
        "serial": "1540745",
        "tag_id": "54900",
        "location": "Innovasea",
        "days": 0,
        "percent": 0,
        "checked": "2026-01-13",
        "always_tx": True,
        "comments": "Needs rebattery 2026",
        "svc_2023": "Reprogrammed",
    },
    {
        "serial": "1540746",
        "tag_id": "54901",
        "location": "On Loan",
        "days": 240,
        "percent": 78,
        "checked": "2026-01-13",
        "always_tx": False,
        "comments": (
            "Alseamar - Set to Never Tx, offloaded, erased data and started "
            "new study Jan 2026."
        ),
    },
    {
        "serial": "1540747",
        "tag_id": "54902",
        "location": "Unknown",
        "days": 14,
        "percent": 4,
        "checked": "2025-04-14",
        "always_tx": True,
        "comments": "Needs rebattery - not sure where this is as of Jan 2026",
        "svc_2023": "Reprogrammed",
    },
    {
        "serial": "1540748",
        "tag_id": "54903",
        "location": "Innovasea",
        "days": 54,
        "percent": 18,
        "checked": "2026-01-13",
        "always_tx": True,
        "comments": "Needs rebattery",
        "svc_2023": "Reprogrammed",
    },
    {
        "serial": "1540749",
        "tag_id": "54904",
        "location": "Innovasea",
        "days": 93,
        "percent": 30,
        "checked": "2026-01-13",
        "always_tx": False,
        "comments": (
            "This is a DFO WASP loaner! Will send back for rebattery and then return to DFO."
        ),
        "svc_2023": "Reprogrammed",
    },
    {
        "serial": "1540750",
        "tag_id": "54905",
        "location": "Unknown",
        "days": 176,
        "percent": 57,
        "checked": "2024-08-20",
        "always_tx": False,
        "comments": "Not sure where this is as of Jan 2026.",
        "svc_2023": "Reprogrammed",
    },
    {
        "serial": "1540753",
        "tag_id": "54908",
        "location": "SV3-1070",
        "days": 255,
        "percent": 73,
        "checked": "2026-01-13",
        "always_tx": False,
        "comments": (
            "Deployed with 1121 on m219 and m223, deployed with 1070 on m230"
        ),
        "svc_2023": "Reprogrammed",
        "svc_2024": "Hydrophone check - passed",
    },
    {
        "serial": "1574803",
        "tag_id": "49692",
        "location": "On Loan",
        "days": 199,
        "percent": 65,
        "checked": "2026-01-13",
        "always_tx": True,
        "comments": "On loan to BOOBBBP - Bedford Basin Benthic Pod",
    },
]


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    return date.fromisoformat(value)


def map_location_to_custody(
    location: str,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (custody_status, custody_other, location_note).

    Platform/site locations leave custody null (ST attachment covers hulls).
    """
    loc = (location or "").strip()
    lower = loc.lower()
    if lower in ("on loan",):
        return VmtCustodyStatus.ON_LOAN.value, None, None
    if lower in ("cove", "at cove"):
        return VmtCustodyStatus.COVE.value, None, None
    if lower in ("innovasea", "being serviced", "servicing"):
        return VmtCustodyStatus.SERVICING.value, None, None
    if lower in ("unknown", "missing"):
        return VmtCustodyStatus.MISSING.value, None, None
    if lower in ("lost",):
        return VmtCustodyStatus.LOST.value, None, None
    # Platform / site / vessel — leave custody null; note for migration
    return None, None, f"Spreadsheet location: {loc}"


def _infer_event_type(text: str) -> str:
    lower = text.lower()
    if "code space" in lower:
        return VmtServiceEventType.CODE_SPACE_UPDATE.value
    if "reprogram" in lower:
        return VmtServiceEventType.REPROGRAMMED.value
    if "mainboard" in lower or " mb " in f" {lower} " or lower.startswith("mb "):
        return VmtServiceEventType.MAINBOARD_REPLACEMENT.value
    if "hydrophone" in lower:
        return VmtServiceEventType.HYDROPHONE_REPLACEMENT.value
    if "head" in lower:
        return VmtServiceEventType.HEAD_REPLACEMENT.value
    if "rebattery" in lower or "new battery" in lower or "batt" in lower:
        return VmtServiceEventType.REBATTERY.value
    if "manufacturer" in lower:
        return VmtServiceEventType.MANUFACTURER_REPAIR.value
    return VmtServiceEventType.OTHER.value


def _service_events_from_row(row: Dict[str, Any]) -> List[Tuple[Optional[date], str, str]]:
    events: List[Tuple[Optional[date], str, str]] = []
    mapping = (
        ("svc_2021", date(2021, 2, 1), "InnovaSea Feb-2021"),
        ("svc_2023", date(2023, 1, 1), "InnovaSea work 2023"),
        ("svc_2024", date(2024, 1, 1), "InnovaSea work 2024"),
        ("svc_2026", date(2026, 1, 1), "InnovaSea work 2026"),
    )
    for key, approx_date, label in mapping:
        text = (row.get(key) or "").strip()
        if not text:
            continue
        events.append((approx_date, _infer_event_type(text), f"{label}: {text}"))
    return events


def seed_vmt_logbook(
    session: SQLModelSession,
    *,
    dry_run: bool = True,
    username: str = "seed",
) -> Dict[str, int]:
    created = updated = batteries = services = skipped = 0
    now = datetime.now(timezone.utc)

    for row in _SEED_ROWS:
        serial = str(row["serial"]).strip()
        custody, custody_other, loc_note = map_location_to_custody(row["location"])
        comments = row.get("comments") or ""
        if loc_note:
            comments = f"{comments}\n{loc_note}".strip() if comments else loc_note

        existing = session.exec(
            select(VmtUnit).where(VmtUnit.serial_number == serial)
        ).first()

        if existing is None:
            created += 1
            logger.info("CREATE %s (tag=%s, custody=%s)", serial, row["tag_id"], custody)
            if not dry_run:
                unit = VmtUnit(
                    serial_number=serial,
                    tag_id=str(row["tag_id"]),
                    code_map=DEFAULT_CODE_MAP,
                    always_tx=bool(row["always_tx"]),
                    comments=comments or None,
                    custody_status=custody,
                    custody_status_other=custody_other,
                    sensor_tracker_link_status=VmtSensorTrackerLinkStatus.NEVER_LINKED.value,
                    created_via=VmtCreatedVia.SEED.value,
                    is_active=True,
                    created_at_utc=now,
                    updated_at_utc=now,
                    updated_by_username=username,
                )
                session.add(unit)
                session.flush()
            else:
                unit = None
        else:
            updated += 1
            logger.info("UPSERT fields for existing %s (id=%s)", serial, existing.id)
            unit = existing
            if not dry_run:
                unit.tag_id = str(row["tag_id"])
                unit.always_tx = bool(row["always_tx"])
                if comments and (not unit.comments or loc_note):
                    # Preserve user edits; only fill empty comments
                    if not unit.comments:
                        unit.comments = comments
                if unit.custody_status is None and custody is not None:
                    unit.custody_status = custody
                    unit.custody_status_other = custody_other
                unit.updated_at_utc = now
                unit.updated_by_username = username
                session.add(unit)

        checked = _parse_date(row.get("checked"))
        if unit is not None and checked is not None:
            existing_batt = None
            if unit.id is not None:
                existing_batt = session.exec(
                    select(VmtBatteryCheck).where(
                        VmtBatteryCheck.vmt_unit_id == unit.id,
                        VmtBatteryCheck.checked_at == checked,
                        VmtBatteryCheck.days_remaining == row.get("days"),
                        VmtBatteryCheck.percent_remaining == row.get("percent"),
                    )
                ).first()
            if existing_batt is None:
                batteries += 1
                if not dry_run and unit.id is not None:
                    session.add(
                        VmtBatteryCheck(
                            vmt_unit_id=unit.id,
                            checked_at=checked,
                            days_remaining=row.get("days"),
                            percent_remaining=row.get("percent"),
                            notes="Seeded from spreadsheet",
                            recorded_by_username=username,
                            recorded_at_utc=now,
                        )
                    )
            else:
                skipped += 1

        for event_date, event_type, description in _service_events_from_row(row):
            if unit is None or unit.id is None:
                if dry_run:
                    services += 1
                continue
            existing_svc = session.exec(
                select(VmtServiceEvent).where(
                    VmtServiceEvent.vmt_unit_id == unit.id,
                    VmtServiceEvent.description == description,
                )
            ).first()
            if existing_svc is not None:
                skipped += 1
                continue
            services += 1
            if not dry_run:
                session.add(
                    VmtServiceEvent(
                        vmt_unit_id=unit.id,
                        event_date=event_date,
                        event_type=event_type,
                        description=description,
                        recorded_by_username=username,
                        recorded_at_utc=now,
                    )
                )

    if not dry_run:
        session.commit()

    return {
        "created": created,
        "updated": updated,
        "batteries": batteries,
        "services": services,
        "skipped": skipped,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    dry_run = bool(args.dry_run)
    with SQLModelSession(sqlite_engine) as session:
        counts = seed_vmt_logbook(session, dry_run=dry_run)
    label = "Dry-run" if dry_run else "Applied"
    print(
        f"{label}: units_new={counts['created']}, units_existing={counts['updated']}, "
        f"battery_checks={counts['batteries']}, service_events={counts['services']}, "
        f"skipped_dupes={counts['skipped']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
