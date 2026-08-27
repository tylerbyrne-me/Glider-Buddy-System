"""
Public login-page map: allowlist, track bundle builder, disk cache, static KML.

Only missions explicitly flagged in Mission Overview / SlocumDeployment and listed
in active env config appear. Payload is lat/lon/timestamp (+ Slocum waypoint) only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence

from sqlmodel import or_, select

from ..config import settings
from . import models
from .data.data_service import get_data_service
from .data.processors import preprocess_telemetry_df
from .geo.map_utils import generate_live_kml_with_track, prepare_track_points
from .infra.db import SQLModelSession
from .infra.feature_toggles import is_feature_enabled
from .reporting.constants import REPORTS_ROOT
from .utils import (
    deployment_mission_code_from_mission_id,
    replace_path_with_retries,
    resolve_data_path,
    slocum_mission_key,
    unique_sibling_tmp_path,
)
from .mission_aliases import (
    configured_slocum_dataset_keys,
    resolve_slocum_dataset_id,
)

logger = logging.getLogger(__name__)

PlatformId = Literal["wave_glider", "slocum"]

SLOCUM_TRACK_TIMEOUT = 35
_PUBLIC_REPORT_TS_RE = re.compile(
    r"weekly_report_.+_(\d{4}-\d{2}-\d{2}_\d{6})\.pdf$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PublicMissionRef:
    platform: PlatformId
    mission_id: str
    platform_name: str
    mission_title: str
    public_weekly_report_enabled: bool
    report_resource_id: str  # WG mission_id or Slocum mission_key

    @property
    def display_name(self) -> str:
        """Back-compat label used in KML folder names (prefer platform name)."""
        return self.platform_name or self.mission_title or self.mission_id


def _cache_dir() -> Path:
    path = resolve_data_path(settings.public_map_cache_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _bundle_path() -> Path:
    return _cache_dir() / "bundle.json"


def is_public_login_map_enabled() -> bool:
    return is_feature_enabled("public_login_map")


def window_hours() -> int:
    return max(1, int(getattr(settings, "public_map_window_hours", 168) or 168))


def max_points() -> int:
    return max(50, int(getattr(settings, "public_map_max_points_per_mission", 500) or 500))


def max_missions() -> int:
    return max(1, int(getattr(settings, "public_map_max_missions", 20) or 20))


def cache_ttl_seconds() -> int:
    return max(30, int(getattr(settings, "public_map_cache_ttl_seconds", 600) or 600))


def _strip_track_points(points: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for point in points:
        try:
            lat = float(point["lat"])
            lon = float(point["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (abs(lat) <= 90 and abs(lon) <= 180):
            continue
        ts = point.get("timestamp")
        out.append(
            {
                "lat": lat,
                "lon": lon,
                "timestamp": str(ts) if ts is not None else None,
            }
        )
    return out


def _clean_label(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def platform_name_hint_from_mission_id(mission_id: str) -> Optional[str]:
    """
    Derive a platform name from folder-style mission ids.

    Example: ``m227-SV3-1071`` → ``SV3-1071``. Returns None when the id is only
    a deployment code (``m227``) or legacy ``1071-m169`` form.
    """
    trimmed = _clean_label(mission_id)
    if not trimmed:
        return None
    code = deployment_mission_code_from_mission_id(trimmed)
    prefix = f"{code}-"
    if code and trimmed.lower().startswith(prefix.lower()):
        rest = trimmed[len(prefix) :].strip()
        return rest or None
    return None


def load_sensor_tracker_for_mission(
    session: SQLModelSession,
    mission_id: str,
) -> Optional[models.SensorTrackerDeployment]:
    """Match Sensor Tracker by full mission id or deployment code (same as weekly reports)."""
    mid = _clean_label(mission_id)
    if not mid:
        return None
    code = deployment_mission_code_from_mission_id(mid)
    return session.exec(
        select(models.SensorTrackerDeployment).where(
            or_(
                models.SensorTrackerDeployment.mission_id == mid,
                models.SensorTrackerDeployment.mission_id == code,
            )
        )
    ).first()


def resolve_public_mission_labels(
    session: SQLModelSession,
    *,
    platform: PlatformId,
    mission_id: str,
    deployment: Any = None,
    dataset_id: Optional[str] = None,
    vehicle_name: Optional[str] = None,
) -> tuple[str, str]:
    """
    Platform-agnostic public popup labels: (platform_name, mission_title).

    Preference order mirrors weekly reports, with shared Sensor Tracker lookup and
    safe per-platform fallbacks so new platforms can reuse the same helper.
    """
    mid = _clean_label(mission_id) or "mission"
    st: Optional[models.SensorTrackerDeployment] = None

    if platform == "slocum":
        from app.platforms.slocum.reports import load_slocum_sensor_tracker_deployment

        did = resolve_slocum_dataset_id(dataset_id or mid)
        st = load_slocum_sensor_tracker_deployment(session, did)
    if st is None:
        st = load_sensor_tracker_for_mission(session, mid)

    st_platform = _clean_label(getattr(st, "platform_name", None) if st else None)
    st_title = _clean_label(getattr(st, "title", None) if st else None)

    deployment_platform = ""
    deployment_title = ""
    if deployment is not None:
        deployment_platform = _clean_label(getattr(deployment, "glider_name", None)).title()
        deployment_title = _clean_label(getattr(deployment, "name", None))

    folder_hint = platform_name_hint_from_mission_id(mid) or ""
    vehicle = _clean_label(vehicle_name)

    platform_name = (
        st_platform
        or deployment_platform
        or vehicle
        or folder_hint
        or mid
    )
    mission_title = st_title or deployment_title or mid
    return platform_name, mission_title


def _env_keys_for_public_map(platform: PlatformId) -> List[str]:
    if platform == "wave_glider":
        return [
            str(mission_id).strip()
            for mission_id in (getattr(settings, "active_realtime_missions", None) or [])
            if mission_id and str(mission_id).strip()
        ]
    return configured_slocum_dataset_keys(
        getattr(settings, "active_slocum_datasets", None)
    )


def active_keys_for_public_map(
    platform: PlatformId,
    session: SQLModelSession,
) -> List[str]:
    """Active config keys for the public map allowlist.

    Default: exact env strings. When ``MISSION_CATALOG_PUBLIC_MAP_FROM_CATALOG``
    is true, read the same strings via catalog enablement and fall back to env
    on error.
    """
    env_keys = _env_keys_for_public_map(platform)
    if not getattr(settings, "mission_catalog_public_map_from_catalog", False):
        return env_keys
    try:
        from .mission_catalog.enablement import (
            list_catalog_sync_targets,
            log_enablement_parity,
        )

        log_enablement_parity(session)
        keys = list_catalog_sync_targets(platform, session)
        logger.info(
            "PUBLICMAP: Catalog enablement platform=%s keys=%s",
            platform,
            keys,
        )
        return list(keys)
    except Exception as exc:
        logger.warning(
            "PUBLICMAP: Catalog enablement failed for %s (%s); falling back to env",
            platform,
            exc,
        )
        return env_keys


def get_public_mission_allowlist(session: SQLModelSession) -> List[PublicMissionRef]:
    """Active config ∩ DB public_map_enabled, capped at max_missions."""
    refs: List[PublicMissionRef] = []

    for mission_id in active_keys_for_public_map("wave_glider", session):
        mid = str(mission_id).strip()
        if not mid:
            continue
        overview = session.get(models.MissionOverview, mid)
        if overview is None:
            code = deployment_mission_code_from_mission_id(mid)
            if code and code != mid:
                overview = session.get(models.MissionOverview, code)
        if not overview or not bool(getattr(overview, "public_map_enabled", False)):
            continue
        platform_name, mission_title = resolve_public_mission_labels(
            session,
            platform="wave_glider",
            mission_id=mid,
        )
        refs.append(
            PublicMissionRef(
                platform="wave_glider",
                mission_id=mid,
                platform_name=platform_name,
                mission_title=mission_title,
                public_weekly_report_enabled=bool(
                    getattr(overview, "public_weekly_report_enabled", False)
                ),
                report_resource_id=overview.mission_id,
            )
        )

    if is_feature_enabled("slocum_platform"):
        for configured_key in active_keys_for_public_map("slocum", session):
            did = resolve_slocum_dataset_id(configured_key)
            mkey = slocum_mission_key(did) or did
            deployment = session.exec(
                select(models.SlocumDeployment).where(
                    models.SlocumDeployment.mission_key == mkey,
                    models.SlocumDeployment.is_active == True,  # noqa: E712
                )
            ).first()
            if deployment is None:
                deployment = session.exec(
                    select(models.SlocumDeployment).where(
                        models.SlocumDeployment.erddap_dataset_id == did,
                        models.SlocumDeployment.is_active == True,  # noqa: E712
                    )
                ).first()
            if not deployment or not bool(getattr(deployment, "public_map_enabled", False)):
                continue
            platform_name, mission_title = resolve_public_mission_labels(
                session,
                platform="slocum",
                mission_id=configured_key,
                deployment=deployment,
                dataset_id=did,
            )
            refs.append(
                PublicMissionRef(
                    platform="slocum",
                    mission_id=configured_key,
                    platform_name=platform_name,
                    mission_title=mission_title,
                    public_weekly_report_enabled=bool(
                        getattr(deployment, "public_weekly_report_enabled", False)
                    ),
                    report_resource_id=mkey,
                )
            )

    return refs[: max_missions()]


def _pdf_exists(url: Optional[str]) -> bool:
    if not url or not str(url).startswith("/static/"):
        return False
    rel = str(url)[len("/static/") :]
    # REPORTS_ROOT is web/static/mission_reports; static root is parent of that.
    static_root = REPORTS_ROOT.parent
    path = (static_root / rel).resolve()
    try:
        path.relative_to(static_root.resolve())
    except ValueError:
        return False
    return path.is_file()


def _newest_weekly_pdf_in_dir(report_dir: Path) -> Optional[Path]:
    if not report_dir.is_dir():
        return None
    candidates = list(report_dir.glob("weekly_report_*.pdf"))
    if not candidates:
        return None

    def sort_key(p: Path) -> tuple:
        match = _PUBLIC_REPORT_TS_RE.search(p.name)
        return (match.group(1) if match else "", p.stat().st_mtime)

    candidates.sort(key=sort_key, reverse=True)
    return candidates[0]


def resolve_latest_weekly_report_disk_path(
    platform: PlatformId,
    resource_id: str,
    *,
    session: Optional[SQLModelSession] = None,
) -> Optional[Path]:
    """Resolve filesystem path for the latest weekly PDF (or None)."""
    rid = str(resource_id).strip()
    if not rid:
        return None

    if platform == "wave_glider":
        if session is not None:
            overview = session.get(models.MissionOverview, rid)
            if overview is None:
                code = deployment_mission_code_from_mission_id(rid)
                if code:
                    overview = session.get(models.MissionOverview, code)
            if overview and overview.weekly_report_url and _pdf_exists(overview.weekly_report_url):
                rel = overview.weekly_report_url[len("/static/") :]
                return (REPORTS_ROOT.parent / rel).resolve()
        safe = rid.replace("/", "_").replace("\\", "_")
        return _newest_weekly_pdf_in_dir(REPORTS_ROOT / f"{safe}_reporting")

    # slocum
    mkey = slocum_mission_key(rid) or rid
    if session is not None:
        deployment = session.exec(
            select(models.SlocumDeployment).where(
                models.SlocumDeployment.mission_key == mkey,
                models.SlocumDeployment.is_active == True,  # noqa: E712
            )
        ).first()
        url = getattr(deployment, "weekly_report_url", None) if deployment else None
        if url and _pdf_exists(url):
            rel = str(url)[len("/static/") :]
            return (REPORTS_ROOT.parent / rel).resolve()
    safe = mkey.replace("/", "_").replace("\\", "_")
    return _newest_weekly_pdf_in_dir(REPORTS_ROOT / "slocum" / safe)


def public_report_api_url(platform: PlatformId, report_resource_id: str) -> str:
    return f"/api/public/reports/{platform}/{report_resource_id}/latest"


def _vehicle_name_from_df(df: Any) -> Optional[str]:
    if df is None or getattr(df, "empty", True):
        return None
    for col in ("vehicleName", "VehicleName"):
        if col not in df.columns:
            continue
        series = df[col].dropna()
        if series.empty:
            continue
        value = _clean_label(series.iloc[0])
        if value:
            return value
    return None


async def _load_wg_track(mission_id: str) -> Dict[str, Any]:
    hours = window_hours()
    try:
        data_service = get_data_service()
        df, source_path, _ = await data_service.load(
            "telemetry",
            mission_id,
            source_preference=None,
            custom_local_path=None,
            force_refresh=False,
            current_user=None,
            hours_back=hours,
        )
        if df is None or df.empty:
            return {
                "track_points": [],
                "current_waypoint": None,
                "vehicle_name": None,
                "error": "No data available",
            }
        vehicle_name = _vehicle_name_from_df(df)
        processed = preprocess_telemetry_df(df)
        if vehicle_name is None:
            vehicle_name = _vehicle_name_from_df(processed)
        if processed.empty:
            return {
                "track_points": [],
                "current_waypoint": None,
                "vehicle_name": vehicle_name,
                "error": "No valid track points",
            }
        points = _strip_track_points(prepare_track_points(processed, max_points=max_points()))
        return {
            "track_points": points,
            "current_waypoint": None,
            "vehicle_name": vehicle_name,
            "source": str(source_path),
            "error": None,
        }
    except Exception as exc:
        logger.warning("PUBLICMAP: WG track load failed for %s: %s", mission_id, exc)
        return {
            "track_points": [],
            "current_waypoint": None,
            "vehicle_name": None,
            "error": str(exc),
        }


async def _load_slocum_track(dataset_id: str) -> Dict[str, Any]:
    dataset_id = resolve_slocum_dataset_id(dataset_id)
    hours = window_hours()
    try:
        from app.platforms.slocum.cache_service import (
            get_cached_or_fetch_bundle_df,
            get_cached_or_fetch_dashboard_df,
            parse_slocum_time_window,
            slice_processed_df,
        )
        from app.platforms.slocum.checklist_autofill import latest_valid_waypoint
        from app.platforms.slocum.mirror_service import dashboard_df_to_track_df
        from app.platforms.slocum.overage_cache import OverageRangeError

        time_start_str, time_end_str, _ = parse_slocum_time_window(
            dataset_id, hours, False, None, None
        )
        try:
            dashboard_df = await asyncio.wait_for(
                get_cached_or_fetch_dashboard_df(
                    dataset_id,
                    time_start_str,
                    time_end_str,
                    hours_back=hours,
                    is_historical=False,
                    context="interactive",
                ),
                timeout=SLOCUM_TRACK_TIMEOUT,
            )
        except OverageRangeError as err:
            return {"track_points": [], "current_waypoint": None, "error": str(err)}

        if dashboard_df is None or dashboard_df.empty:
            return {"track_points": [], "current_waypoint": None, "error": "No data available"}

        sliced = slice_processed_df(
            dashboard_df,
            hours_back=hours,
            use_date_range=False,
            time_start_str=time_start_str,
            time_end_str=time_end_str,
        )
        processed = dashboard_df_to_track_df(sliced if not sliced.empty else dashboard_df)
        if processed.empty:
            return {"track_points": [], "current_waypoint": None, "error": "No valid track points"}
        points = _strip_track_points(prepare_track_points(processed, max_points=max_points()))

        current_waypoint = None
        try:
            checklist_df = await asyncio.wait_for(
                get_cached_or_fetch_bundle_df(
                    dataset_id,
                    "checklist",
                    time_start_str,
                    time_end_str,
                    hours_back=hours,
                    is_historical=False,
                    context="interactive",
                ),
                timeout=SLOCUM_TRACK_TIMEOUT,
            )
            if checklist_df is not None and not checklist_df.empty:
                sliced_checklist = slice_processed_df(
                    checklist_df,
                    hours_back=hours,
                    use_date_range=False,
                    time_start_str=time_start_str,
                    time_end_str=time_end_str,
                )
                wpt_src = sliced_checklist if not sliced_checklist.empty else checklist_df
                wpt_lat, wpt_lon = latest_valid_waypoint(wpt_src)
                if wpt_lat is not None and wpt_lon is not None:
                    current_waypoint = {"lat": float(wpt_lat), "lon": float(wpt_lon)}
        except Exception as wpt_err:
            logger.debug("PUBLICMAP: Slocum waypoint skipped for %s: %s", dataset_id, wpt_err)

        return {
            "track_points": points,
            "current_waypoint": current_waypoint,
            "error": None,
        }
    except asyncio.TimeoutError:
        logger.warning("PUBLICMAP: Slocum track timeout for %s", dataset_id)
        return {"track_points": [], "current_waypoint": None, "error": "timeout"}
    except Exception as exc:
        logger.warning("PUBLICMAP: Slocum track load failed for %s: %s", dataset_id, exc)
        return {"track_points": [], "current_waypoint": None, "error": str(exc)}


def _mission_entry(ref: PublicMissionRef, track: Dict[str, Any]) -> Dict[str, Any]:
    points = track.get("track_points") or []
    current_position = None
    if points:
        last = points[-1]
        current_position = {"lat": last["lat"], "lon": last["lon"]}

    weekly_report_url = None
    if ref.public_weekly_report_enabled:
        # Link only when a PDF is known to exist at build time would require session;
        # callers that have session should set this. Here we expose the gated URL
        # when the flag is on; the report route 404s if no file.
        weekly_report_url = public_report_api_url(ref.platform, ref.report_resource_id)

    platform_name = ref.platform_name
    mission_title = ref.mission_title
    vehicle_name = _clean_label(track.get("vehicle_name"))
    # Prefer live vehicle name when Sensor Tracker was missing and we only had the raw id.
    if vehicle_name and platform_name in ("", ref.mission_id):
        platform_name = vehicle_name

    waypoint = track.get("current_waypoint")
    entry: Dict[str, Any] = {
        "platform": ref.platform,
        "mission_id": ref.mission_id,
        "platform_name": platform_name,
        "mission_title": mission_title,
        "display_name": platform_name,
        "track_points": points,
        "current_position": current_position,
        "current_waypoint": waypoint,
        "weekly_report_url": weekly_report_url,
    }
    return entry


async def build_public_map_bundle(session: SQLModelSession) -> Dict[str, Any]:
    """Build a fresh public map bundle (does not write cache)."""
    refs = get_public_mission_allowlist(session)
    missions: List[Dict[str, Any]] = []

    for ref in refs:
        if ref.platform == "wave_glider":
            track = await _load_wg_track(ref.mission_id)
        else:
            track = await _load_slocum_track(ref.mission_id)

        entry = _mission_entry(ref, track)
        # Only advertise report URL when PDF exists
        if entry.get("weekly_report_url"):
            disk = resolve_latest_weekly_report_disk_path(
                ref.platform, ref.report_resource_id, session=session
            )
            if disk is None:
                entry["weekly_report_url"] = None
        missions.append(entry)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    bundle = {
        "generated_at": generated_at,
        "window_hours": window_hours(),
        "missions": missions,
    }
    logger.info(
        "PUBLICMAP: built bundle missions=%s generated_at=%s",
        len(missions),
        generated_at,
    )
    return bundle


def write_public_map_cache(bundle: Dict[str, Any]) -> None:
    path = _bundle_path()
    tmp = unique_sibling_tmp_path(path)
    payload = json.dumps(bundle, separators=(",", ":"), ensure_ascii=True)
    tmp.write_text(payload, encoding="utf-8")
    replace_path_with_retries(tmp, path)


def read_public_map_cache() -> Optional[Dict[str, Any]]:
    path = _bundle_path()
    if not path.is_file():
        return None
    try:
        age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
        if age > cache_ttl_seconds():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "missions" not in data:
            return None
        return data
    except Exception as exc:
        logger.warning("PUBLICMAP: cache read failed: %s", exc)
        return None


def read_public_map_cache_any_age() -> Optional[Dict[str, Any]]:
    """Return cached bundle even if stale (fallback when rebuild fails)."""
    path = _bundle_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "missions" not in data:
            return None
        return data
    except Exception:
        return None


async def get_or_build_public_map_bundle(
    session: SQLModelSession,
    *,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    if not force_refresh:
        cached = read_public_map_cache()
        if cached is not None:
            return cached
    try:
        bundle = await build_public_map_bundle(session)
        write_public_map_cache(bundle)
        return bundle
    except Exception as exc:
        logger.error("PUBLICMAP: rebuild failed: %s", exc, exc_info=True)
        stale = read_public_map_cache_any_age()
        if stale is not None:
            return stale
        raise


def generate_public_kml_from_bundle(bundle: Dict[str, Any]) -> str:
    """Static multi-mission KML from a public bundle (not a live NetworkLink)."""
    tracks: List[tuple] = []
    for mission in bundle.get("missions") or []:
        mid = mission.get("mission_id") or "unknown"
        points = mission.get("track_points") or []
        if not points:
            continue
        waypoint = mission.get("current_waypoint")
        label = mission.get("display_name") or mid
        tracks.append((f"{label} ({mid})", points, waypoint))
    if not tracks:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<kml xmlns="http://www.opengis.net/kml/2.2"><Document/></kml>'
        )
    return generate_live_kml_with_track(
        tracks,
        description="Public glider tracks (7-day snapshot)",
        resource_label="Glider",
    )


async def warm_public_map_cache(session: SQLModelSession) -> Dict[str, Any]:
    """Leader job entrypoint: rebuild and write cache."""
    if not is_public_login_map_enabled():
        return {"skipped": True, "reason": "feature_disabled"}
    bundle = await build_public_map_bundle(session)
    write_public_map_cache(bundle)
    return {
        "skipped": False,
        "mission_count": len(bundle.get("missions") or []),
        "generated_at": bundle.get("generated_at"),
    }
