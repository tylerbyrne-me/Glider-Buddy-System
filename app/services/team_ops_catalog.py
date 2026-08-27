"""Team hub ops-tool catalog and capture-based runner.

Registry of admin Team tools. ``kind="run"`` entries execute in-process via
importlib (stdout/stderr/logging capture). ``kind="page"`` entries link to
dedicated Team tool pages with their own forms/APIs.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional

from app.core.models.schemas import OpsScriptRunResult

logger = logging.getLogger(__name__)

ToolKind = Literal["run", "page"]


@dataclass(frozen=True)
class OpsScriptSpec:
    id: str
    label: str
    description: str
    kind: ToolKind = "run"
    module_path: Optional[str] = None
    func_name: Optional[str] = None
    href: Optional[str] = None


OPS_SCRIPTS: Dict[str, OpsScriptSpec] = {
    "check_mission_files": OpsScriptSpec(
        id="check_mission_files",
        label="Check mission file references",
        description=(
            "Read-only integrity check: verify MissionOverview and MissionMedia "
            "file-path references exist on disk."
        ),
        kind="run",
        module_path="app.cli.check_mission_files",
        func_name="run_checks",
    ),
    "sfmc_lognotes": OpsScriptSpec(
        id="sfmc_lognotes",
        label="SFMC log-note import",
        description=(
            "Paste SFMC user-log-note JSON and preview or post backdated "
            "Slocum deployment notes."
        ),
        kind="page",
        href="/team/sfmc-lognotes",
    ),
    "telemetry_hexbin": OpsScriptSpec(
        id="telemetry_hexbin",
        label="Wave Glider telemetry hexbin",
        description=(
            "Build a Cartopy hexbin coverage map from past Wave Glider "
            "telemetry around a center/size or bbox."
        ),
        kind="page",
        href="/team/telemetry-hexbin",
    ),
    "mission_catalog_sync": OpsScriptSpec(
        id="mission_catalog_sync",
        label="Mission catalog sync (dry-run)",
        description=(
            "Reconcile Sensor Tracker, ERDDAP, WGMS, and legacy .env mission "
            "lists into the source-neutral catalog (dry-run only from Team UI)."
        ),
        kind="run",
        module_path="app.cli.mission_catalog_sync",
        func_name="run_dry_run_checks",
    ),
    "mission_catalog": OpsScriptSpec(
        id="mission_catalog",
        label="Mission catalog (unmatched ERDDAP)",
        description=(
            "Read-only review of unmatched ERDDAP datasets in the mission "
            "catalog (does not create missions)."
        ),
        kind="page",
        href="/team/mission-catalog",
    ),
    "sensor_tracker": OpsScriptSpec(
        id="sensor_tracker",
        label="Sensor Tracker browser",
        description=(
            "Live read-only search of Sensor Tracker platforms, deployments, "
            "loggers, instruments, sensors, and components."
        ),
        kind="page",
        href="/team/sensor-tracker",
    ),
    "visualizations": OpsScriptSpec(
        id="visualizations",
        label="Visualizations gallery",
        description=(
            "Named static fleet charts from Sensor Tracker (platform share, "
            "sensor days, use over time). Rebuild on demand; served from disk."
        ),
        kind="page",
        href="/team/visualizations",
    ),
    "vmt_logbook": OpsScriptSpec(
        id="vmt_logbook",
        label="VMT log book",
        description=(
            "Track Vemco Mobile Transceiver inventory, battery checks, service "
            "history, Sensor Tracker sync, and deployment accounting."
        ),
        kind="page",
        href="/team/vmt-logbook",
    ),
}


def list_ops_scripts() -> List[OpsScriptSpec]:
    return list(OPS_SCRIPTS.values())


def get_ops_script(script_id: str) -> OpsScriptSpec:
    try:
        return OPS_SCRIPTS[script_id]
    except KeyError as exc:
        raise KeyError(f"Unknown ops script id: {script_id!r}") from exc


def run_ops_script(script_id: str) -> OpsScriptRunResult:
    spec = get_ops_script(script_id)
    if spec.kind != "run":
        raise ValueError(f"Ops script {script_id!r} is kind={spec.kind!r}, not runnable")
    if not spec.module_path or not spec.func_name:
        raise ValueError(f"Ops script {script_id!r} is missing module_path/func_name")

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    log_buf = io.StringIO()
    handler = logging.StreamHandler(log_buf)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)

    started = time.perf_counter()
    ran_at = datetime.now(timezone.utc)
    error_text: str | None = None
    success = True
    try:
        module = importlib.import_module(spec.module_path)
        func = getattr(module, spec.func_name)
        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            func()
    except Exception as exc:
        success = False
        error_text = f"{type(exc).__name__}: {exc}"
        logger.exception("Ops script %s failed", script_id)
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)

    duration_ms = int((time.perf_counter() - started) * 1000)
    output = "\n".join(
        part
        for part in (
            stdout_buf.getvalue().rstrip(),
            stderr_buf.getvalue().rstrip(),
            log_buf.getvalue().rstrip(),
        )
        if part
    )
    return OpsScriptRunResult(
        script_id=script_id,
        success=success,
        output=output,
        error=error_text,
        duration_ms=duration_ms,
        ran_at=ran_at,
    )
