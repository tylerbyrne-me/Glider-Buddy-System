"""Robots4Whales DMON daily analyst-review fetch, parse, and disk cache.

Derived from WHOI deployment pages (e.g. dcs.whoi.edu/.../*.shtml). Dashboard and
reports read cache only; the leader job refreshes on an interval.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from sqlmodel import Session as SQLModelSession, select

from app.config import settings
from app.core import models
from app.core.utils import (
    replace_path_with_retries,
    slocum_mission_key,
    unique_sibling_tmp_path,
)
from app.platforms.slocum.checklist_autofill import parse_enabled_sensor_cards

logger = logging.getLogger(__name__)

PROGRAM_NAME = "Robots4Whales"
PROGRAM_URL = "https://robots4whales.whoi.edu/"
INSTITUTION = "Woods Hole Oceanographic Institution"

USER_AGENT = (
    "GliderBuddySystem-DMON-review/1.0 "
    "(research dashboard; contact via Glider Buddy System ops)"
)

COLOR_MAP = {
    "lightgray": "Not detected",
    "lightgrey": "Not detected",
    "red": "Detected",
    "yellow": "Possibly detected",
}

SPECIES_ORDER = [
    "Sei whale",
    "Fin whale",
    "Right whale",
    "Humpback whale",
    "Blue whale",
]

ALLOWED_HOSTS = {"dcs.whoi.edu", "www.dcs.whoi.edu"}

OCCURRENCE_DISCLAIMER = (
    "Occurrence from analyst-reviewed call detections is not an indication of whale abundance."
)


def order_species_columns(columns: Sequence[str]) -> list[str]:
    """Return columns in SPECIES_ORDER, appending unrecognized species alphabetically."""
    known = [s for s in SPECIES_ORDER if s in columns]
    extra = sorted(c for c in columns if c not in SPECIES_ORDER)
    return known + extra


def validate_robots4whales_url(url: Optional[str]) -> Optional[str]:
    """Normalize and validate a Robots4Whales deployment page URL.

    Returns the stripped URL, or None when clearing. Raises ValueError when invalid.
    """
    if url is None:
        return None
    text = str(url).strip()
    if not text:
        return None
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("robots4whales_url must be an http(s) URL")
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        raise ValueError(
            "robots4whales_url host must be dcs.whoi.edu "
            f"(got {host or 'missing'})"
        )
    path = parsed.path or ""
    if not path.lower().endswith(".shtml"):
        raise ValueError("robots4whales_url path must end with .shtml")
    return text


def default_attribution(*, source_url: Optional[str] = None) -> dict[str, Any]:
    return {
        "program_name": PROGRAM_NAME,
        "program_url": PROGRAM_URL,
        "institution": INSTITUTION,
        "analysts": None,
        "operators": None,
        "source_url": source_url,
    }


def _cache_dir() -> Path:
    path = Path(getattr(settings, "dmon_review_cache_dir", Path("data_store/dmon_review_cache")))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_path(mission_key: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", mission_key.strip()) or "unknown"
    return _cache_dir() / f"{safe}.json"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = unique_sibling_tmp_path(path)
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        replace_path_with_retries(tmp_path, path)
    except Exception:
        try:
            if tmp_path.is_file():
                tmp_path.unlink()
        except OSError:
            pass
        raise


def _read_json_file(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read DMON review cache %s: %s", path, exc)
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def color_to_status(style: str) -> str:
    match = re.search(r"background(?:-color)?\s*:\s*([^;]+)", style, re.IGNORECASE)
    if not match:
        return "UNKNOWN(no-style)"
    color = match.group(1).strip().lower()
    return COLOR_MAP.get(color, f"UNKNOWN({color})")


def find_review_table(soup: BeautifulSoup):
    marker = soup.find(string=re.compile(r"Daily analyst review", re.IGNORECASE))
    if marker is not None:
        table = marker.find_next("table")
        if table is not None:
            return table
    for table in soup.find_all("table"):
        header_text = table.get_text(" ", strip=True).lower()
        if "date" in header_text and "whale" in header_text:
            return table
    return None


def parse_attribution(soup: BeautifulSoup) -> dict[str, Any]:
    """Extract Analysts (and optional operators) from page text. Skips PIs."""
    text = soup.get_text("\n", strip=True)
    analysts = None
    operators = None
    analysts_match = re.search(
        r"Analysts?\s*:\s*(.+?)(?:\n|$)",
        text,
        re.IGNORECASE,
    )
    if analysts_match:
        analysts = analysts_match.group(1).strip() or None
    # Org line often appears near the top before "Study objectives"
    operators_match = re.search(
        r"(?m)^([A-Z][^\n]{10,120}?University[^\n]{0,80})$",
        text,
    )
    if operators_match:
        candidate = operators_match.group(1).strip()
        if "investigator" not in candidate.lower() and "analyst" not in candidate.lower():
            operators = candidate
    return {
        "analysts": analysts,
        "operators": operators,
    }


def parse_review_table(table) -> list[dict[str, Any]]:
    rows = table.find_all("tr")
    if not rows:
        return []
    header_cells = rows[0].find_all(["td", "th"])
    species_names = [c.get_text(strip=True) for c in header_cells[1:]]
    records: list[dict[str, Any]] = []
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        date_text = cells[0].get_text(strip=True)
        parsed_date = None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
            try:
                parsed_date = datetime.strptime(date_text, fmt).date()
                break
            except ValueError:
                continue
        if parsed_date is None:
            logger.warning("DMON REVIEW: unparseable date %r", date_text)
            continue
        for species, cell in zip(species_names, cells[1:]):
            if not species:
                continue
            status = color_to_status(cell.get("style", ""))
            records.append(
                {
                    "date": parsed_date.isoformat(),
                    "species": species,
                    "status": status,
                }
            )
    return records


def parse_deployment_html(html: str, *, source_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    table = find_review_table(soup)
    if table is None:
        raise ValueError("Could not locate Daily analyst review table on page")
    rows = parse_review_table(table)
    species = order_species_columns(sorted({r["species"] for r in rows}))
    scraped = parse_attribution(soup)
    attribution = default_attribution(source_url=source_url)
    attribution["analysts"] = scraped.get("analysts")
    attribution["operators"] = scraped.get("operators")
    return {
        "source_url": source_url,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "attribution": attribution,
        "rows": rows,
        "species": species,
    }


async def fetch_deployment_html(url: str) -> str:
    timeout = float(getattr(settings, "dmon_review_http_timeout_seconds", 30.0) or 30.0)
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


def get_cached_dmon_review(mission_key: str) -> Optional[dict[str, Any]]:
    if not mission_key:
        return None
    return _read_json_file(_cache_path(mission_key))


def write_dmon_review_cache(mission_key: str, payload: dict[str, Any]) -> Path:
    path = _cache_path(mission_key)
    _atomic_write_json(path, payload)
    return path


def _parse_iso_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def pivot_rows_to_day_records(
    rows: Sequence[dict[str, Any]],
    species: Sequence[str],
) -> list[dict[str, Any]]:
    by_date: dict[str, dict[str, str]] = {}
    for row in rows:
        d = row.get("date")
        sp = row.get("species")
        st = row.get("status")
        if not d or not sp:
            continue
        by_date.setdefault(str(d), {})[str(sp)] = str(st)
    ordered_species = order_species_columns(list(species) if species else [])
    if not ordered_species:
        ordered_species = order_species_columns(
            sorted({sp for statuses in by_date.values() for sp in statuses})
        )
    days = sorted(by_date.keys(), reverse=True)
    return [
        {"date": day, "statuses": {sp: by_date[day].get(sp) for sp in ordered_species}}
        for day in days
    ]


def filter_dmon_review(
    payload: Optional[dict[str, Any]],
    *,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    recent_hours: Optional[float] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Filter cached review into recent + all (optionally date-windowed) day records."""
    payload = payload if isinstance(payload, dict) else {}
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    species = payload.get("species") if isinstance(payload.get("species"), list) else []
    attribution = payload.get("attribution") if isinstance(payload.get("attribution"), dict) else {}
    source_url = payload.get("source_url") or attribution.get("source_url")

    merged_attr = default_attribution(source_url=source_url)
    merged_attr.update({k: v for k, v in attribution.items() if v is not None or k in attribution})
    merged_attr["source_url"] = source_url

    window_rows = list(rows)
    if start_date is not None or end_date is not None:
        filtered = []
        for row in window_rows:
            d = _parse_iso_date(row.get("date"))
            if d is None:
                continue
            if start_date is not None and d < start_date:
                continue
            if end_date is not None and d > end_date:
                continue
            filtered.append(row)
        window_rows = filtered

    all_days = pivot_rows_to_day_records(window_rows, species)

    recent_days = all_days
    if recent_hours is not None and recent_hours > 0:
        ref = now or datetime.now(timezone.utc)
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        cutoff = (ref - timedelta(hours=float(recent_hours))).date()
        recent_rows = []
        for row in window_rows:
            d = _parse_iso_date(row.get("date"))
            if d is not None and d >= cutoff:
                recent_rows.append(row)
        recent_days = pivot_rows_to_day_records(recent_rows, species)

    detected_recent: list[str] = []
    for day in recent_days:
        statuses = day.get("statuses") or {}
        for sp, st in statuses.items():
            if st == "Detected" and sp not in detected_recent:
                detected_recent.append(sp)

    return {
        "source_url": source_url,
        "fetched_at_utc": payload.get("fetched_at_utc"),
        "attribution": merged_attr,
        "species": order_species_columns(list(species)) if species else order_species_columns(
            sorted(
                {
                    sp
                    for day in all_days
                    for sp in (day.get("statuses") or {})
                }
            )
        ),
        "recent": recent_days,
        "all": all_days,
        "summary": {"detected_species_recent": detected_recent},
        "meta": {
            "row_count": len(window_rows),
            "recent_hours": recent_hours,
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
        },
    }


def count_dmon_confirmed_detections(review_payload: Optional[dict[str, Any]]) -> dict[str, int]:
    """Count report-window days with status ``Detected`` per species (confirmed only)."""
    if not isinstance(review_payload, dict):
        return {}
    days = review_payload.get("all") or review_payload.get("recent") or []
    if not isinstance(days, list) or not days:
        return {}
    species = list(review_payload.get("species") or [])
    if not species:
        species = order_species_columns(
            sorted(
                {
                    sp
                    for day in days
                    if isinstance(day, dict)
                    for sp in (day.get("statuses") or {})
                }
            )
        )
    counts: dict[str, int] = {str(sp): 0 for sp in species}
    for day in days:
        if not isinstance(day, dict):
            continue
        statuses = day.get("statuses") or {}
        if not isinstance(statuses, dict):
            continue
        for sp, st in statuses.items():
            if st == "Detected":
                key = str(sp)
                counts[key] = int(counts.get(key, 0)) + 1
    return counts


def deployment_is_dmon_review_eligible(deployment: models.SlocumDeployment) -> bool:
    if not deployment or not deployment.is_active:
        return False
    cards = {c.lower() for c in parse_enabled_sensor_cards(deployment.enabled_sensor_cards)}
    if "dmon" not in cards:
        return False
    url = (deployment.robots4whales_url or "").strip()
    return bool(url)


async def refresh_dmon_review_for_deployment(
    deployment: models.SlocumDeployment,
) -> dict[str, Any]:
    """Fetch, parse, and cache review data for one deployment."""
    url = validate_robots4whales_url(deployment.robots4whales_url)
    if not url:
        raise ValueError("Deployment has no robots4whales_url")
    mission_key = (
        deployment.mission_key
        or slocum_mission_key(deployment.erddap_dataset_id or "")
        or f"deployment_{deployment.id}"
    )
    html = await fetch_deployment_html(url)
    payload = parse_deployment_html(html, source_url=url)
    write_dmon_review_cache(mission_key, payload)
    logger.info(
        "DMON REVIEW: cached %s rows for mission_key=%s from %s",
        len(payload.get("rows") or []),
        mission_key,
        url,
    )
    return payload


def list_eligible_dmon_review_deployments(
    session: SQLModelSession,
) -> list[models.SlocumDeployment]:
    rows = session.exec(
        select(models.SlocumDeployment).where(models.SlocumDeployment.is_active == True)  # noqa: E712
    ).all()
    return [d for d in rows if deployment_is_dmon_review_eligible(d)]


async def prefetch_all_dmon_reviews(session: SQLModelSession) -> dict[str, Any]:
    """Refresh all eligible deployments. Returns a summary dict."""
    if not bool(getattr(settings, "dmon_review_prefetch_enabled", True)):
        logger.info("DMON REVIEW: prefetch skipped (dmon_review_prefetch_enabled=false)")
        return {"skipped": True, "reason": "disabled", "refreshed": 0, "failed": 0}

    deployments = list_eligible_dmon_review_deployments(session)
    refreshed = 0
    failed = 0
    errors: list[str] = []
    for deployment in deployments:
        try:
            await refresh_dmon_review_for_deployment(deployment)
            refreshed += 1
        except Exception as exc:
            failed += 1
            msg = f"{deployment.mission_key or deployment.id}: {exc}"
            errors.append(msg)
            logger.warning("DMON REVIEW: refresh failed for %s: %s", deployment.id, exc)
    return {
        "skipped": False,
        "eligible": len(deployments),
        "refreshed": refreshed,
        "failed": failed,
        "errors": errors[:10],
    }


def format_report_attribution_lines(attribution: dict[str, Any], *, fetched_at_utc: Optional[str] = None) -> list[str]:
    """Lines for PDF footnote (site + analysts)."""
    lines: list[str] = []
    program = attribution.get("program_name") or PROGRAM_NAME
    institution = attribution.get("institution") or INSTITUTION
    program_url = attribution.get("program_url") or PROGRAM_URL
    source_url = attribution.get("source_url")
    lines.append(f"Derived from {program} ({institution}). Program: {program_url}")
    if source_url:
        lines.append(f"Deployment page: {source_url}")
    analysts = attribution.get("analysts")
    if analysts:
        lines.append(f"Analysts: {analysts}")
    else:
        lines.append("Analysts: not listed on source page.")
    if fetched_at_utc:
        lines.append(f"Cached at: {fetched_at_utc}")
    lines.append(OCCURRENCE_DISCLAIMER)
    return lines
