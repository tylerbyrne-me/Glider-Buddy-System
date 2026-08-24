"""Team Visualizations gallery: static fleet charts from Sensor Tracker.

Charts are generated on demand (UI or CLI), written under
``data_store/team_viz_outputs/{slug}/``, and served as static PNGs until rebuilt.
GET paths never contact Tracker.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import httpx
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from app.core.mission_catalog.naming import classify_platform_family
from app.core.mission_catalog.providers_config import (
    ProvidersManifest,
    load_providers_manifest,
)
from app.services.sensor_tracker_analytics import (
    intersect_intervals,
    parse_window_time,
    total_days,
    windows_to_intervals,
)
from app.services.sensor_tracker_query import (
    SensorTrackerQueryError,
    _as_int,
    _identifier,
    _platform_name,
    _record_id,
    _serial_of,
    _walk_tracker_pages,
    pin_relationship_rows,
    relationship_window,
    tracker_base_url,
)

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = _PROJECT_ROOT / "data_store" / "team_viz_cache"
OUTPUT_DIR = _PROJECT_ROOT / "data_store" / "team_viz_outputs"
SNAPSHOT_PATH = CACHE_DIR / "fleet_snapshot.json"

# Higher than the Team browser RELATIONSHIP_FETCH_CAP (500) for fleet walks.
FLEET_FETCH_CAP = 5000
TOP_SENSOR_SERIES = 12
SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
ALLOWED_PLATFORM_FAMILIES = frozenset({"wave_glider", "slocum"})

Interval = Tuple[datetime, datetime]


@dataclass(frozen=True)
class ChartSpec:
    slug: str
    title: str
    caption: str
    renderer: str  # key into RENDERERS


CHART_SPECS: Dict[str, ChartSpec] = {
    "platform_share": ChartSpec(
        slug="platform_share",
        title="Platform share of deployments and days at sea",
        caption=(
            "Deployment count and at-sea days per Wave Glider / Slocum hull from "
            "Sensor Tracker deployment windows (open-ended through as-of). "
            "Non-glider Tracker platforms are excluded. At-sea days only — not "
            "shelf time. Totals may be low if Tracker lists were truncated."
        ),
        renderer="platform_share",
    ),
    "sensor_days_by_platform": ChartSpec(
        slug="sensor_days_by_platform",
        title="Sensor at-sea days by platform",
        caption=(
            "Stacked at-sea days by sensor identifier (e.g. SBE43F), not serial, "
            "on Wave Glider / Slocum hulls only. Days = sensor-on-instrument ∩ "
            "instrument attachment ∩ that hull’s deployments. Top series shown; "
            "remainder as Other. At-sea only — not shelf time. Totals may be low "
            "if joins were truncated."
        ),
        renderer="sensor_days_by_platform",
    ),
    "use_over_time": ChartSpec(
        slug="use_over_time",
        title="Fleet use over time",
        caption=(
            "Glider-days from Sensor Tracker deployment windows on Wave Glider / "
            "Slocum platforms only (year × month). Does not include track distance "
            "(Tracker has no fleet km). Open-ended windows run through as-of. "
            "Totals may be low if deployment lists were truncated."
        ),
        renderer="use_over_time",
    ),
}


def list_chart_specs() -> List[ChartSpec]:
    return list(CHART_SPECS.values())


def get_chart_spec(slug: str) -> ChartSpec:
    try:
        return CHART_SPECS[slug]
    except KeyError as exc:
        raise KeyError(f"Unknown chart slug: {slug!r}") from exc


def safe_chart_slug(slug: str) -> Optional[str]:
    if not slug or not SLUG_RE.fullmatch(slug):
        return None
    if slug not in CHART_SPECS:
        return None
    return slug


def chart_output_dir(slug: str) -> Path:
    return OUTPUT_DIR / slug


def chart_png_path(slug: str) -> Path:
    return chart_output_dir(slug) / "latest.png"


def chart_meta_path(slug: str) -> Path:
    return chart_output_dir(slug) / "meta.json"


def ensure_dirs() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    try:
        tmp.replace(path)
    except OSError:
        path.write_text(tmp.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    try:
        tmp.replace(path)
    except OSError:
        path.write_bytes(data)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def load_chart_meta(slug: str) -> Optional[Dict[str, Any]]:
    path = chart_meta_path(slug)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_fleet_snapshot() -> Optional[Dict[str, Any]]:
    if not SNAPSHOT_PATH.is_file():
        return None
    try:
        data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_fleet_snapshot(snapshot: Dict[str, Any]) -> None:
    ensure_dirs()
    _atomic_write_json(SNAPSHOT_PATH, snapshot)


def gallery_catalog() -> Dict[str, Any]:
    """Registry + on-disk meta for the Team gallery API (no PNG bytes)."""
    charts: List[Dict[str, Any]] = []
    for spec in list_chart_specs():
        meta = load_chart_meta(spec.slug) or {}
        has_image = chart_png_path(spec.slug).is_file()
        charts.append(
            {
                "slug": spec.slug,
                "title": spec.title,
                "caption": spec.caption,
                "generated_at": meta.get("generated_at"),
                "as_of": meta.get("as_of"),
                "has_image": has_image,
                "image_url": (
                    f"/api/team/visualizations/{spec.slug}/image"
                    if has_image
                    else None
                ),
                "notes": meta.get("notes") or [],
                "row_counts": meta.get("row_counts") or {},
                "truncated": bool(meta.get("truncated")),
                "error": meta.get("error"),
            }
        )
    snap = load_fleet_snapshot()
    return {
        "charts": charts,
        "snapshot_as_of": (snap or {}).get("as_of"),
        "snapshot_fetched_at": (snap or {}).get("fetched_at"),
        "tracker_host": tracker_base_url(),
    }


# ---------------------------------------------------------------------------
# Snapshot fetch
# ---------------------------------------------------------------------------


async def _walk_capped(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    client: Optional[httpx.AsyncClient] = None,
    cap: int = FLEET_FETCH_CAP,
) -> Tuple[List[Dict[str, Any]], bool]:
    rows, _count, more = await _walk_tracker_pages(
        path,
        params,
        min_rows=cap,
        max_rows=cap,
        client=client,
    )
    return rows, more


async def _try_walk(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[List[Dict[str, Any]], bool, Optional[str]]:
    try:
        rows, more = await _walk_capped(path, params, client=client)
        return rows, more, None
    except SensorTrackerQueryError as exc:
        if exc.status_code in (403, 400, 404):
            return [], False, f"{path}: HTTP {exc.status_code} ({exc.message})"
        raise


def _compact_platform(
    row: Dict[str, Any],
    *,
    type_by_id: Optional[Dict[int, str]] = None,
    manifest: Optional[ProvidersManifest] = None,
) -> Optional[Dict[str, Any]]:
    plat_id = _record_id(row)
    name = _platform_name(row)
    if plat_id is None and not name:
        return None
    type_id = _as_int(row.get("platform_type"))
    model = None
    if type_id is not None and type_by_id:
        model = type_by_id.get(type_id)
    if not model:
        maybe = row.get("model") or row.get("platform_type_name")
        if maybe and not isinstance(maybe, (int, float)):
            model = str(maybe).strip()
    family = None
    if manifest is not None:
        family = classify_glider_platform_family(
            platform_name=name,
            model_name=model,
            manifest=manifest,
        )
    return {
        "id": plat_id,
        "name": name,
        "serial": _serial_of(row),
        "platform_type_id": type_id,
        "model": model,
        "platform_family": family,
    }


def classify_glider_platform_family(
    *,
    platform_name: Optional[str],
    model_name: Optional[str],
    manifest: ProvidersManifest,
) -> Optional[str]:
    """Return ``wave_glider`` / ``slocum`` or None for non-glider / unknown.

    Same rules as the mission-catalog Sensor Tracker adapter: allowlisted ST
    model first; if model is present but not allowlisted, exclude; if model is
    missing, fall back to name heuristics (SV3/DL/SV2, known Slocum names).
    """
    family = manifest.family_for_model(model_name)
    if family in ALLOWED_PLATFORM_FAMILIES:
        return family
    if model_name:
        return None
    family = classify_platform_family(
        platform_name,
        wave_glider_prefixes=manifest.wave_glider_prefixes,
        slocum_known_names=manifest.slocum_known_names,
    )
    if family in ALLOWED_PLATFORM_FAMILIES:
        return family
    return None


def build_platform_type_model_map(
    type_rows: Sequence[Dict[str, Any]],
) -> Dict[int, str]:
    type_by_id: Dict[int, str] = {}
    for row in type_rows:
        if not isinstance(row, dict):
            continue
        type_id = _as_int(row.get("id") or row.get("pk"))
        model_name = row.get("model") or row.get("name") or row.get("platform_type")
        if type_id is not None and model_name:
            type_by_id[type_id] = str(model_name).strip()
    return type_by_id


def allowed_platform_index(
    platforms: Sequence[Dict[str, Any]],
) -> Tuple[set, set]:
    """Return (platform_ids, casefolded platform names) for glider hulls only."""
    ids: set = set()
    names: set = set()
    for plat in platforms:
        if not isinstance(plat, dict):
            continue
        if plat.get("platform_family") not in ALLOWED_PLATFORM_FAMILIES:
            continue
        pid = plat.get("id")
        if pid is not None:
            try:
                ids.add(int(pid))
            except (TypeError, ValueError):
                pass
        name = plat.get("name")
        if name:
            names.add(str(name).casefold())
    return ids, names


def row_on_allowed_platform(
    row: Dict[str, Any],
    allowed_ids: set,
    allowed_names: set,
) -> bool:
    pid = row.get("platform_id")
    if pid is not None:
        try:
            if int(pid) in allowed_ids:
                return True
        except (TypeError, ValueError):
            pass
    name = row.get("platform_name")
    if name and str(name).casefold() in allowed_names:
        return True
    return False


def filter_snapshot_to_glider_platforms(
    snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """Keep only wave_glider / slocum platforms and related deployment/attach rows.

    Safe to call on an already-filtered snapshot (idempotent). Platforms without
    ``platform_family`` are dropped unless they already carry an allowed family.
    """
    platforms = [
        p
        for p in (snapshot.get("platforms") or [])
        if isinstance(p, dict) and p.get("platform_family") in ALLOWED_PLATFORM_FAMILIES
    ]
    allowed_ids, allowed_names = allowed_platform_index(platforms)
    deployments = [
        d
        for d in (snapshot.get("deployments") or [])
        if isinstance(d, dict)
        and row_on_allowed_platform(d, allowed_ids, allowed_names)
    ]
    attachments = [
        a
        for a in (snapshot.get("instrument_attachments") or [])
        if isinstance(a, dict)
        and row_on_allowed_platform(a, allowed_ids, allowed_names)
    ]
    allowed_inst = {
        int(a["instrument_id"])
        for a in attachments
        if a.get("instrument_id") is not None
    }
    sensors = []
    for s in snapshot.get("sensor_on_instrument") or []:
        if not isinstance(s, dict):
            continue
        inst_id = s.get("instrument_id")
        if inst_id is None:
            continue
        try:
            if int(inst_id) in allowed_inst:
                sensors.append(s)
        except (TypeError, ValueError):
            continue
    out = dict(snapshot)
    out["platforms"] = platforms
    out["deployments"] = deployments
    out["instrument_attachments"] = attachments
    out["sensor_on_instrument"] = sensors
    counts = dict(snapshot.get("counts") or {})
    counts["platforms"] = len(platforms)
    counts["deployments"] = len(deployments)
    counts["instrument_attachments"] = len(attachments)
    counts["sensor_on_instrument"] = len(sensors)
    out["counts"] = counts
    return out


def _compact_deployment(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    dep_id = _record_id(row)
    start, end = relationship_window(row)
    plat = row.get("platform") if isinstance(row.get("platform"), dict) else None
    plat_id = _record_id(plat) if isinstance(plat, dict) else None
    if plat_id is None:
        plat_id = _as_int(row.get("platform"))
    plat_name = _platform_name(row)
    if dep_id is None and start in (None, ""):
        return None
    return {
        "id": dep_id,
        "platform_id": plat_id,
        "platform_name": plat_name,
        "start_time": start,
        "end_time": end,
        "deployment_number": row.get("deployment_number"),
        "title": row.get("title"),
    }


def _nested_entity(row: Dict[str, Any], *keys: str) -> Optional[Dict[str, Any]]:
    for key in keys:
        value = row.get(key)
        if isinstance(value, dict):
            return value
    return None


def _compact_instrument_on_platform(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    inst = _nested_entity(row, "instrument")
    plat = _nested_entity(row, "platform")
    start, end = relationship_window(row)
    inst_id = _record_id(inst) if inst else None
    if inst_id is None and not inst:
        return None
    return {
        "instrument_id": inst_id,
        "instrument_identifier": _identifier(inst, "identifier") if inst else None,
        "platform_id": _record_id(plat) if plat else None,
        "platform_name": _platform_name(plat) if plat else _platform_name(row),
        "start_time": start,
        "end_time": end,
        "via_logger": False,
    }


def _compact_instrument_on_logger(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    inst = _nested_entity(row, "instrument")
    logger_rec = _nested_entity(row, "data_logger", "logger")
    start, end = relationship_window(row)
    inst_id = _record_id(inst) if inst else None
    if inst_id is None and not inst:
        return None
    return {
        "instrument_id": inst_id,
        "instrument_identifier": _identifier(inst, "identifier") if inst else None,
        "logger_id": _record_id(logger_rec) if logger_rec else None,
        "logger_identifier": (
            _identifier(logger_rec, "identifier") if logger_rec else None
        ),
        "start_time": start,
        "end_time": end,
    }


def _compact_logger_on_platform(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    logger_rec = _nested_entity(row, "data_logger", "logger")
    plat = _nested_entity(row, "platform")
    start, end = relationship_window(row)
    return {
        "logger_id": _record_id(logger_rec) if logger_rec else None,
        "logger_identifier": (
            _identifier(logger_rec, "identifier") if logger_rec else None
        ),
        "platform_id": _record_id(plat) if plat else None,
        "platform_name": _platform_name(plat) if plat else _platform_name(row),
        "start_time": start,
        "end_time": end,
    }


def _compact_sensor_on_instrument(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sensor = _nested_entity(row, "sensor")
    inst = _nested_entity(row, "instrument")
    start, end = relationship_window(row)
    if not sensor and not inst:
        return None
    return {
        "sensor_id": _record_id(sensor) if sensor else None,
        "sensor_identifier": (
            _identifier(sensor, "identifier", "short_name") if sensor else None
        ),
        "instrument_id": _record_id(inst) if inst else None,
        "instrument_identifier": _identifier(inst, "identifier") if inst else None,
        "start_time": start,
        "end_time": end,
    }


def resolve_instrument_attachments(
    on_platform: Sequence[Dict[str, Any]],
    on_logger: Sequence[Dict[str, Any]],
    logger_on_platform: Sequence[Dict[str, Any]],
    as_of: datetime,
) -> List[Dict[str, Any]]:
    """Flatten instrument attachments onto platforms (incl. logger-mounted)."""
    out: List[Dict[str, Any]] = []
    for row in on_platform:
        if not isinstance(row, dict):
            continue
        compact = _compact_instrument_on_platform(row)
        if compact and (compact.get("platform_id") or compact.get("platform_name")):
            out.append(compact)

    logger_rows = [
        c
        for c in (_compact_logger_on_platform(r) for r in logger_on_platform if isinstance(r, dict))
        if c and (c.get("logger_id") is not None or c.get("logger_identifier"))
    ]
    for row in on_logger:
        if not isinstance(row, dict):
            continue
        iol = _compact_instrument_on_logger(row)
        if not iol:
            continue
        inst_iv = windows_to_intervals(
            [(iol.get("start_time"), iol.get("end_time"))], as_of
        )
        if not inst_iv:
            continue
        for lop in logger_rows:
            same_logger = False
            if (
                iol.get("logger_id") is not None
                and lop.get("logger_id") is not None
                and iol["logger_id"] == lop["logger_id"]
            ):
                same_logger = True
            elif (
                iol.get("logger_identifier")
                and lop.get("logger_identifier")
                and str(iol["logger_identifier"]).casefold()
                == str(lop["logger_identifier"]).casefold()
            ):
                same_logger = True
            if not same_logger:
                continue
            logger_iv = windows_to_intervals(
                [(lop.get("start_time"), lop.get("end_time"))], as_of
            )
            overlap = intersect_intervals(inst_iv, logger_iv)
            if not overlap:
                continue
            for start, end in overlap:
                out.append(
                    {
                        "instrument_id": iol.get("instrument_id"),
                        "instrument_identifier": iol.get("instrument_identifier"),
                        "platform_id": lop.get("platform_id"),
                        "platform_name": lop.get("platform_name"),
                        "start_time": start.isoformat(),
                        "end_time": end.isoformat(),
                        "via_logger": True,
                    }
                )
    return out


async def _fetch_per_platform_fallback(
    platforms: Sequence[Dict[str, Any]],
    *,
    client: Optional[httpx.AsyncClient],
    notes: List[str],
) -> Tuple[
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
    bool,
]:
    """When unfiltered joins fail, walk per platform (slower, still capped)."""
    deployments: List[Dict[str, Any]] = []
    iop: List[Dict[str, Any]] = []
    iol: List[Dict[str, Any]] = []
    lop: List[Dict[str, Any]] = []
    soi: List[Dict[str, Any]] = []
    truncated = False
    seen_dep: set[int] = set()
    seen_soi: set[Tuple[Any, Any, Any]] = set()

    for plat in platforms:
        name = plat.get("name")
        plat_id = plat.get("id")
        serial = plat.get("serial")
        if not name:
            continue
        dep_rows, more = await _walk_capped(
            "deployment", {"platform_name": name}, client=client
        )
        truncated = truncated or more
        if plat_id is not None:
            dep_rows = pin_relationship_rows(
                dep_rows,
                parent_id=int(plat_id),
                parent_entity="platform",
                parent_serial=serial,
                require_match=False,
            )
        for row in dep_rows:
            compact = _compact_deployment(row)
            if not compact:
                continue
            did = compact.get("id")
            if did is not None:
                if did in seen_dep:
                    continue
                seen_dep.add(did)
            if not compact.get("platform_name"):
                compact["platform_name"] = name
            if compact.get("platform_id") is None:
                compact["platform_id"] = plat_id
            deployments.append(compact)

        for path, bucket in (
            ("instrument_on_platform", iop),
            ("data_logger_on_platform", lop),
        ):
            rows, more, err = await _try_walk(
                path, {"depth": 1, "platform_name": name}, client=client
            )
            if err:
                notes.append(err)
                continue
            truncated = truncated or more
            if plat_id is not None:
                rows = pin_relationship_rows(
                    rows,
                    parent_id=int(plat_id),
                    parent_entity="platform",
                    parent_serial=serial,
                    require_match=False,
                )
            bucket.extend(rows)

        # Instruments currently on this platform → sensors via instrument_identifier
        for row in iop[-200:]:  # bound work from this platform's last batch
            inst = _nested_entity(row, "instrument")
            if not isinstance(inst, dict):
                continue
            ident = _identifier(inst, "identifier")
            if not ident:
                continue
            rows, more, err = await _try_walk(
                "sensor_on_instrument",
                {"depth": 1, "instrument_identifier": ident},
                client=client,
            )
            if err:
                notes.append(err)
                continue
            truncated = truncated or more
            inst_id = _record_id(inst)
            pinned = (
                pin_relationship_rows(
                    rows,
                    parent_id=inst_id,
                    parent_entity="instrument",
                    parent_serial=_serial_of(inst),
                )
                if inst_id is not None
                else rows
            )
            for srow in pinned:
                compact = _compact_sensor_on_instrument(srow)
                if not compact:
                    continue
                key = (
                    compact.get("sensor_id"),
                    compact.get("instrument_id"),
                    compact.get("start_time"),
                )
                if key in seen_soi:
                    continue
                seen_soi.add(key)
                soi.append(srow)

        # Logger-mounted instruments for loggers on this platform
        for row in lop[-100:]:
            logger_rec = _nested_entity(row, "data_logger", "logger")
            if not isinstance(logger_rec, dict):
                continue
            lid = _identifier(logger_rec, "identifier")
            if not lid:
                continue
            rows, more, err = await _try_walk(
                "instrument_on_data_logger",
                {"depth": 1, "data_logger_identifier": lid},
                client=client,
            )
            if err:
                notes.append(err)
                continue
            truncated = truncated or more
            iol.extend(rows)

    notes.append(
        "Used per-platform Tracker walks (unfiltered fleet join unavailable or empty)."
    )
    return deployments, iop, iol, lop, soi, truncated


async def build_fleet_snapshot(
    *,
    as_of: Optional[datetime] = None,
    client: Optional[httpx.AsyncClient] = None,
    reuse: bool = False,
) -> Dict[str, Any]:
    """Fetch (or reload) a fleet snapshot suitable for all gallery charts."""
    if reuse:
        existing = load_fleet_snapshot()
        if existing:
            return existing
        logger.info("No cached fleet snapshot; fetching from Tracker")

    as_of = as_of or _utc_now()
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    else:
        as_of = as_of.astimezone(timezone.utc)

    notes: List[str] = []
    truncated = False
    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)

    try:
        manifest = load_providers_manifest()
        type_rows, type_more, type_err = await _try_walk(
            "platform_type", client=client
        )
        if type_err:
            # Alternate Tracker path used by SensorTrackerService
            type_rows2, type_more2, type_err2 = await _try_walk(
                "platformtype", client=client
            )
            if type_err2:
                notes.append(type_err)
                notes.append(type_err2)
                type_rows = []
            else:
                type_rows = type_rows2
                truncated = truncated or type_more2
        else:
            truncated = truncated or type_more
        type_by_id = build_platform_type_model_map(type_rows)

        plat_rows, plat_more, plat_err = await _try_walk("platform", client=client)
        if plat_err:
            notes.append(plat_err)
            raise SensorTrackerQueryError(
                f"Cannot list platforms: {plat_err}", status_code=502
            )
        truncated = truncated or plat_more
        all_platforms = [
            p
            for p in (
                _compact_platform(r, type_by_id=type_by_id, manifest=manifest)
                for r in plat_rows
            )
            if p is not None
        ]
        platforms = [
            p
            for p in all_platforms
            if p.get("platform_family") in ALLOWED_PLATFORM_FAMILIES
        ]
        skipped = len(all_platforms) - len(platforms)
        if skipped:
            notes.append(
                f"Excluded {skipped} non–Wave Glider / non–Slocum Tracker "
                "platform(s) (model allowlist + name heuristics)."
            )
        notes.append(
            "Fleet charts include only Wave Glider and Slocum platforms "
            "(config/mission_data_providers.json allowed_platform_models)."
        )

        dep_rows, dep_more, dep_err = await _try_walk("deployment", client=client)
        deployments: List[Dict[str, Any]] = []
        if dep_err:
            notes.append(dep_err)
        else:
            truncated = truncated or dep_more
            deployments = [
                d for d in (_compact_deployment(r) for r in dep_rows) if d is not None
            ]

        iop_rows, iop_more, iop_err = await _try_walk(
            "instrument_on_platform", {"depth": 1}, client=client
        )
        iol_rows, iol_more, iol_err = await _try_walk(
            "instrument_on_data_logger", {"depth": 1}, client=client
        )
        lop_rows, lop_more, lop_err = await _try_walk(
            "data_logger_on_platform", {"depth": 1}, client=client
        )
        soi_rows, soi_more, soi_err = await _try_walk(
            "sensor_on_instrument", {"depth": 1}, client=client
        )

        for err in (iop_err, iol_err, lop_err, soi_err):
            if err:
                notes.append(err)

        need_fallback = bool(dep_err or iop_err or soi_err) or (
            not deployments and bool(platforms)
        )
        if need_fallback:
            (
                fb_deps,
                fb_iop,
                fb_iol,
                fb_lop,
                fb_soi,
                fb_trunc,
            ) = await _fetch_per_platform_fallback(
                platforms, client=client, notes=notes
            )
            truncated = truncated or fb_trunc
            if not deployments:
                deployments = fb_deps
            if iop_err or not iop_rows:
                iop_rows = fb_iop
                iop_more = fb_trunc
            if iol_err or not iol_rows:
                iol_rows = fb_iol
            if lop_err or not lop_rows:
                lop_rows = fb_lop
            if soi_err or not soi_rows:
                soi_rows = fb_soi
                soi_more = fb_trunc
        else:
            truncated = truncated or iop_more or iol_more or lop_more or soi_more

        instrument_attachments = resolve_instrument_attachments(
            iop_rows, iol_rows, lop_rows, as_of
        )
        sensors = [
            s
            for s in (_compact_sensor_on_instrument(r) for r in soi_rows)
            if s is not None
        ]

        if truncated:
            notes.append(
                f"One or more Tracker lists hit the fleet fetch cap ({FLEET_FETCH_CAP}); "
                "totals may be low."
            )

        snapshot: Dict[str, Any] = {
            "as_of": _fmt_iso(as_of),
            "fetched_at": _fmt_iso(_utc_now()),
            "tracker_host": tracker_base_url(),
            "truncated": truncated,
            "notes": notes,
            "counts": {
                "platforms_listed": len(all_platforms),
                "platforms_excluded": skipped,
                "platforms": len(platforms),
                "deployments": len(deployments),
                "instrument_attachments": len(instrument_attachments),
                "sensor_on_instrument": len(sensors),
                "instrument_on_platform_raw": len(iop_rows),
                "instrument_on_data_logger_raw": len(iol_rows),
                "data_logger_on_platform_raw": len(lop_rows),
                "platform_types": len(type_by_id),
            },
            "platforms": platforms,
            "deployments": deployments,
            "instrument_attachments": instrument_attachments,
            "sensor_on_instrument": sensors,
        }
        snapshot = filter_snapshot_to_glider_platforms(snapshot)
        save_fleet_snapshot(snapshot)
        logger.info(
            "Fleet snapshot saved: %s glider platforms (%s excluded), %s deployments, "
            "%s instrument attachments, %s sensor joins",
            snapshot["counts"].get("platforms"),
            skipped,
            snapshot["counts"].get("deployments"),
            snapshot["counts"].get("instrument_attachments"),
            snapshot["counts"].get("sensor_on_instrument"),
        )
        return snapshot
    finally:
        if owns_client and client is not None:
            await client.aclose()


def parse_snapshot_as_of(snapshot: Dict[str, Any]) -> datetime:
    raw = snapshot.get("as_of")
    dt = parse_window_time(raw) if raw else None
    return dt or _utc_now()


# ---------------------------------------------------------------------------
# Aggregations (pure; unit-tested with fake snapshots)
# ---------------------------------------------------------------------------


def _platform_key(platform_id: Any, platform_name: Any) -> str:
    if platform_name:
        return str(platform_name)
    if platform_id is not None:
        return f"platform#{platform_id}"
    return "unknown"


def aggregate_platform_share(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    as_of = parse_snapshot_as_of(snapshot)
    by_plat: Dict[str, Dict[str, Any]] = {}
    for dep in snapshot.get("deployments") or []:
        if not isinstance(dep, dict):
            continue
        key = _platform_key(dep.get("platform_id"), dep.get("platform_name"))
        bucket = by_plat.setdefault(
            key,
            {
                "platform": key,
                "deployment_count": 0,
                "days_at_sea": 0.0,
                "windows": [],
            },
        )
        bucket["deployment_count"] += 1
        bucket["windows"].append((dep.get("start_time"), dep.get("end_time")))

    rows: List[Dict[str, Any]] = []
    for key, bucket in by_plat.items():
        days = total_days(windows_to_intervals(bucket["windows"], as_of))
        rows.append(
            {
                "platform": key,
                "deployment_count": bucket["deployment_count"],
                "days_at_sea": days,
            }
        )
    rows.sort(key=lambda r: (-r["days_at_sea"], -r["deployment_count"], r["platform"]))
    return {
        "as_of": _fmt_iso(as_of),
        "rows": rows,
        "truncated": bool(snapshot.get("truncated")),
        "notes": list(snapshot.get("notes") or []),
    }


def _deployments_by_platform(
    snapshot: Dict[str, Any], as_of: datetime
) -> Dict[str, List[Interval]]:
    out: Dict[str, List[Interval]] = defaultdict(list)
    for dep in snapshot.get("deployments") or []:
        if not isinstance(dep, dict):
            continue
        key = _platform_key(dep.get("platform_id"), dep.get("platform_name"))
        iv = windows_to_intervals(
            [(dep.get("start_time"), dep.get("end_time"))], as_of
        )
        out[key].extend(iv)
    return out


def _attachments_by_instrument(
    snapshot: Dict[str, Any], as_of: datetime
) -> Dict[int, List[Tuple[str, Interval]]]:
    """instrument_id -> [(platform_key, interval), ...]."""
    out: Dict[int, List[Tuple[str, Interval]]] = defaultdict(list)
    for row in snapshot.get("instrument_attachments") or []:
        if not isinstance(row, dict):
            continue
        inst_id = row.get("instrument_id")
        if inst_id is None:
            continue
        try:
            inst_id = int(inst_id)
        except (TypeError, ValueError):
            continue
        plat = _platform_key(row.get("platform_id"), row.get("platform_name"))
        for iv in windows_to_intervals(
            [(row.get("start_time"), row.get("end_time"))], as_of
        ):
            out[inst_id].append((plat, iv))
    return out


def aggregate_sensor_days_by_platform(
    snapshot: Dict[str, Any],
    *,
    top_n: int = TOP_SENSOR_SERIES,
) -> Dict[str, Any]:
    as_of = parse_snapshot_as_of(snapshot)
    dep_by_plat = _deployments_by_platform(snapshot, as_of)
    att_by_inst = _attachments_by_instrument(snapshot, as_of)

    # (platform, sensor_identifier) -> days
    cells: Dict[Tuple[str, str], float] = defaultdict(float)
    for soi in snapshot.get("sensor_on_instrument") or []:
        if not isinstance(soi, dict):
            continue
        sensor_id_label = soi.get("sensor_identifier") or (
            f"sensor#{soi.get('sensor_id')}" if soi.get("sensor_id") is not None else None
        )
        if not sensor_id_label:
            continue
        inst_id = soi.get("instrument_id")
        if inst_id is None:
            continue
        try:
            inst_id = int(inst_id)
        except (TypeError, ValueError):
            continue
        sensor_ivs = windows_to_intervals(
            [(soi.get("start_time"), soi.get("end_time"))], as_of
        )
        if not sensor_ivs:
            continue
        for plat, attach_iv in att_by_inst.get(inst_id, []):
            overlap_attach = intersect_intervals(sensor_ivs, [attach_iv])
            if not overlap_attach:
                continue
            sea = intersect_intervals(overlap_attach, dep_by_plat.get(plat, []))
            if not sea:
                continue
            cells[(plat, str(sensor_id_label))] += total_days(sea)

    # Round and drop zeros
    cells = {k: round(v, 1) for k, v in cells.items() if v > 0}

    # Top sensor identifiers by total days
    by_sensor: Dict[str, float] = defaultdict(float)
    for (_plat, sensor), days in cells.items():
        by_sensor[sensor] += days
    ranked = sorted(by_sensor.items(), key=lambda kv: (-kv[1], kv[0]))
    top = [name for name, _ in ranked[:top_n]]
    top_set = set(top)

    platforms = sorted({plat for plat, _ in cells.keys()})
    series: Dict[str, List[float]] = {name: [] for name in top}
    series["Other"] = []
    for plat in platforms:
        other = 0.0
        for name in top:
            series[name].append(cells.get((plat, name), 0.0))
        for (p, sensor), days in cells.items():
            if p == plat and sensor not in top_set:
                other += days
        series["Other"].append(round(other, 1))

    # Drop Other if empty
    if all(v == 0 for v in series["Other"]):
        del series["Other"]

    return {
        "as_of": _fmt_iso(as_of),
        "platforms": platforms,
        "series": series,
        "truncated": bool(snapshot.get("truncated")),
        "notes": list(snapshot.get("notes") or []),
    }


def _iter_month_slices(start: datetime, end: datetime) -> List[Tuple[str, Interval]]:
    """Split [start, end) into calendar-month pieces labeled YYYY-MM."""
    if end <= start:
        return []
    slices: List[Tuple[str, Interval]] = []
    cursor = start
    while cursor < end:
        year, month = cursor.year, cursor.month
        if month == 12:
            next_month = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            next_month = datetime(year, month + 1, 1, tzinfo=timezone.utc)
        piece_end = min(end, next_month)
        label = f"{year:04d}-{month:02d}"
        slices.append((label, (cursor, piece_end)))
        cursor = piece_end
    return slices


def aggregate_use_over_time(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    as_of = parse_snapshot_as_of(snapshot)
    month_days: Dict[str, float] = defaultdict(float)
    for dep in snapshot.get("deployments") or []:
        if not isinstance(dep, dict):
            continue
        for iv in windows_to_intervals(
            [(dep.get("start_time"), dep.get("end_time"))], as_of
        ):
            for label, piece in _iter_month_slices(iv[0], iv[1]):
                month_days[label] += (piece[1] - piece[0]).total_seconds() / 86400.0

    months = sorted(month_days.keys())
    values = [round(month_days[m], 1) for m in months]
    years = sorted({m[:4] for m in months})
    # Heatmap grid: rows = years, cols = months 01-12
    grid: List[List[float]] = []
    for year in years:
        row = []
        for month in range(1, 13):
            key = f"{year}-{month:02d}"
            row.append(round(month_days.get(key, 0.0), 1))
        grid.append(row)

    return {
        "as_of": _fmt_iso(as_of),
        "months": months,
        "values": values,
        "years": years,
        "grid": grid,
        "truncated": bool(snapshot.get("truncated")),
        "notes": list(snapshot.get("notes") or []),
        "use_heatmap": len(months) >= 6,
    }


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _apply_infographic_style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": "#ffffff",
            "axes.facecolor": "#f8f9fa",
            "axes.edgecolor": "#343a40",
            "axes.labelcolor": "#212529",
            "text.color": "#212529",
            "xtick.color": "#212529",
            "ytick.color": "#212529",
            "grid.color": "#ced4da",
            "font.size": 10,
        }
    )


def _save_figure(fig: plt.Figure, slug: str) -> Path:
    ensure_dirs()
    out_dir = chart_output_dir(slug)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = chart_png_path(slug)
    # Suffix must stay .png so matplotlib picks the PNG writer (.png.tmp fails).
    tmp = path.with_name(path.stem + ".tmp.png")
    fig.savefig(tmp, dpi=140, bbox_inches="tight", facecolor=fig.get_facecolor())
    try:
        tmp.replace(path)
    except OSError:
        path.write_bytes(tmp.read_bytes())
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    plt.close(fig)
    return path


def render_platform_share(snapshot: Dict[str, Any], slug: str = "platform_share") -> Path:
    data = aggregate_platform_share(snapshot)
    rows = data["rows"]
    _apply_infographic_style()
    if not rows:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, "No deployment data in snapshot", ha="center", va="center")
        ax.set_axis_off()
        return _save_figure(fig, slug)

    platforms = [r["platform"] for r in rows]
    deps = [r["deployment_count"] for r in rows]
    days = [r["days_at_sea"] for r in rows]
    x = range(len(platforms))
    width = 0.38
    fig, ax = plt.subplots(figsize=(max(8, len(platforms) * 0.55), 5))
    ax.bar([i - width / 2 for i in x], deps, width, label="Deployments", color="#0d6efd")
    ax.bar([i + width / 2 for i in x], days, width, label="Days at sea", color="#198754")
    ax.set_xticks(list(x))
    ax.set_xticklabels(platforms, rotation=45, ha="right")
    ax.set_ylabel("Count / days")
    ax.set_title("Platform share of deployments and days at sea")
    ax.legend()
    ax.grid(axis="y", alpha=0.4)
    fig.tight_layout()
    return _save_figure(fig, slug)


def render_sensor_days_by_platform(
    snapshot: Dict[str, Any], slug: str = "sensor_days_by_platform"
) -> Path:
    data = aggregate_sensor_days_by_platform(snapshot)
    platforms = data["platforms"]
    series = data["series"]
    _apply_infographic_style()
    if not platforms or not series:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.text(0.5, 0.5, "No sensor at-sea data in snapshot", ha="center", va="center")
        ax.set_axis_off()
        return _save_figure(fig, slug)

    fig, ax = plt.subplots(figsize=(max(9, len(platforms) * 0.7), 6))
    x = range(len(platforms))
    bottoms = [0.0] * len(platforms)
    # Stable color cycle
    cmap = plt.get_cmap("tab20")
    for idx, (name, values) in enumerate(series.items()):
        color = cmap(idx % 20)
        ax.bar(list(x), values, bottom=bottoms, label=name, color=color, width=0.75)
        bottoms = [b + v for b, v in zip(bottoms, values)]
    ax.set_xticks(list(x))
    ax.set_xticklabels(platforms, rotation=45, ha="right")
    ax.set_ylabel("At-sea days")
    ax.set_title("Sensor at-sea days by platform")
    ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1), fontsize=8)
    ax.grid(axis="y", alpha=0.4)
    fig.tight_layout()
    return _save_figure(fig, slug)


def render_use_over_time(snapshot: Dict[str, Any], slug: str = "use_over_time") -> Path:
    data = aggregate_use_over_time(snapshot)
    _apply_infographic_style()
    years = data["years"]
    grid = data["grid"]
    if data.get("use_heatmap") and years and grid:
        fig, ax = plt.subplots(figsize=(10, max(3, len(years) * 0.55 + 1.5)))
        cmap = LinearSegmentedColormap.from_list(
            "glider_days", ["#f8f9fa", "#0d6efd", "#012a5a"]
        )
        im = ax.imshow(grid, aspect="auto", cmap=cmap)
        ax.set_xticks(range(12))
        ax.set_xticklabels(
            ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        )
        ax.set_yticks(range(len(years)))
        ax.set_yticklabels(years)
        ax.set_title("Fleet glider-days over time")
        fig.colorbar(im, ax=ax, label="Glider-days")
        fig.tight_layout()
        return _save_figure(fig, slug)

    months = data["months"]
    values = data["values"]
    fig, ax = plt.subplots(figsize=(max(8, len(months) * 0.35 + 2), 4.5))
    if not months:
        ax.text(0.5, 0.5, "No deployment windows in snapshot", ha="center", va="center")
        ax.set_axis_off()
    else:
        # Collapse to yearly bars when sparse
        if len(months) < 6:
            by_year: Dict[str, float] = defaultdict(float)
            for m, v in zip(months, values):
                by_year[m[:4]] += v
            labels = sorted(by_year.keys())
            ax.bar(labels, [by_year[y] for y in labels], color="#0d6efd")
            ax.set_xlabel("Year")
        else:
            ax.bar(months, values, color="#0d6efd")
            ax.set_xticklabels(months, rotation=45, ha="right")
            ax.set_xlabel("Month")
        ax.set_ylabel("Glider-days")
        ax.set_title("Fleet glider-days over time")
        ax.grid(axis="y", alpha=0.4)
    fig.tight_layout()
    return _save_figure(fig, slug)


RENDERERS: Dict[str, Callable[[Dict[str, Any], str], Path]] = {
    "platform_share": render_platform_share,
    "sensor_days_by_platform": render_sensor_days_by_platform,
    "use_over_time": render_use_over_time,
}


def write_chart_meta(
    slug: str,
    *,
    snapshot: Dict[str, Any],
    success: bool,
    duration_ms: int,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    spec = get_chart_spec(slug)
    meta = {
        "slug": slug,
        "title": spec.title,
        "caption": spec.caption,
        "generated_at": _fmt_iso(_utc_now()),
        "as_of": snapshot.get("as_of"),
        "success": success,
        "duration_ms": duration_ms,
        "truncated": bool(snapshot.get("truncated")),
        "notes": list(snapshot.get("notes") or []),
        "row_counts": dict(snapshot.get("counts") or {}),
        "error": error,
        "image_url": f"/api/team/visualizations/{slug}/image" if success else None,
    }
    ensure_dirs()
    _atomic_write_json(chart_meta_path(slug), meta)
    return meta


def render_chart_from_snapshot(slug: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Render one chart PNG + meta from an existing snapshot (sync)."""
    spec = get_chart_spec(slug)
    renderer = RENDERERS.get(spec.renderer)
    if renderer is None:
        raise KeyError(f"No renderer for {spec.renderer!r}")
    started = time.perf_counter()
    error: Optional[str] = None
    success = True
    try:
        renderer(snapshot, slug)
    except Exception as exc:
        success = False
        error = f"{type(exc).__name__}: {exc}"
        logger.exception("Chart render failed for %s", slug)
    duration_ms = int((time.perf_counter() - started) * 1000)
    return write_chart_meta(
        slug,
        snapshot=snapshot,
        success=success,
        duration_ms=duration_ms,
        error=error,
    )


async def generate_chart(
    slug: str,
    *,
    reuse_snapshot: bool = False,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    if safe_chart_slug(slug) is None:
        raise KeyError(f"Unknown chart slug: {slug!r}")
    snapshot = await build_fleet_snapshot(reuse=reuse_snapshot, client=client)
    return render_chart_from_snapshot(slug, snapshot)


async def generate_all_charts(
    *,
    reuse_snapshot: bool = False,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    snapshot = await build_fleet_snapshot(reuse=reuse_snapshot, client=client)
    results = []
    for spec in list_chart_specs():
        results.append(render_chart_from_snapshot(spec.slug, snapshot))
    return {
        "success": all(r.get("success") for r in results),
        "snapshot_as_of": snapshot.get("as_of"),
        "snapshot_fetched_at": snapshot.get("fetched_at"),
        "charts": results,
    }
