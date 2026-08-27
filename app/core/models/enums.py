"""
Enum definitions for the Wave Glider Buddy System.
"""

from enum import Enum


class ReportTypeEnum(str, Enum):
    power = "power"
    ctd = "ctd"
    weather = "weather"
    waves = "waves"
    telemetry = "telemetry"
    ais = "ais"
    errors = "errors"
    vr2c = "vr2c"
    fluorometer = "fluorometer"
    solar = "solar"
    wg_vm4 = "wg_vm4"  # New WG-VM4 sensor
    wg_vm4_info = "wg_vm4_info"  # WG-VM4 info data for automatic offload logging
    wg_vm4_remote_health = "wg_vm4_remote_health"  # VM4 remote health at connection


class SourceEnum(str, Enum):
    local = "local"
    remote = "remote"


class UserRoleEnum(str, Enum):
    admin = "admin"
    pilot = "pilot"


class FormItemTypeEnum(str, Enum):
    CHECKBOX = "checkbox"
    TEXT_INPUT = "text_input"
    TEXT_AREA = "text_area"
    AUTOFILLED_VALUE = "autofilled_value"
    # For values auto-populated from mission data
    STATIC_TEXT = "static_text"  # For instructions or non-interactive text
    DROPDOWN = "dropdown"  # New type for dropdown lists
    DATETIME_LOCAL = "datetime-local"  # For datetime-local input
    SENSOR_STATUS = "sensor_status"  # Science sensor: last data time + On/Off toggle


class JobStatusEnum(str, Enum):
    OK = "ok"
    WARNING = "warning"
    FAILED = "failed"
    OVERDUE = "overdue"
    NEVER_RUN = "never_run"


class JobRunOutcomeEnum(str, Enum):
    """Last-run outcome reported by a job or APScheduler listener."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class JobPlatformEnum(str, Enum):
    """Platform/category for scheduled background jobs shown in admin UI."""

    WAVE_GLIDER = "wave_glider"
    SLOCUM = "slocum"
    SYSTEM = "system"


class CatalogOperationalState(str, Enum):
    """Mission operational lifecycle (not ERDDAP realtime/delayed variant)."""

    PLANNED = "planned"
    ACTIVE = "active"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class CatalogSyncPolicy(str, Enum):
    """How aggressively the app fetches telemetry for a catalog mission."""

    CATALOG_ONLY = "catalog_only"
    ON_DEMAND = "on_demand"
    WARM = "warm"
    CONTINUOUS = "continuous"


class CatalogSourceKind(str, Enum):
    """Concrete telemetry/data location kinds."""

    ERDDAP = "erddap"
    WGMS_REMOTE = "wgms_remote"
    MANUAL = "manual"


class CatalogSourceVariant(str, Enum):
    """ERDDAP (or similar) dataset revision variant."""

    REALTIME = "realtime"
    DELAYED = "delayed"
    UNKNOWN = "unknown"


class CatalogMatchStatus(str, Enum):
    """How a discovered source relates to a catalog mission."""

    LINKED = "linked"
    UNMATCHED = "unmatched"
    CONFLICT = "conflict"
    STALE = "stale"


class CatalogIdentityKind(str, Enum):
    """External identity kinds stored on CatalogExternalIdentity."""

    SENSOR_TRACKER_DEPLOYMENT_ID = "sensor_tracker_deployment_id"
    SENSOR_TRACKER_DEPLOYMENT_NUMBER = "sensor_tracker_deployment_number"
    DEPLOYMENT_CODE = "deployment_code"
    ERDDAP_DATASET_ID = "erddap_dataset_id"
    ERDDAP_MISSION_KEY = "erddap_mission_key"
    WGMS_FOLDER = "wgms_folder"
    LEGACY_ENV_KEY = "legacy_env_key"
    MANUAL = "manual"


class VmtCustodyStatus(str, Enum):
    """Manual custody when a VMT is not currently attached in Sensor Tracker."""

    ON_LOAN = "on_loan"
    COVE = "cove"
    SERVICING = "servicing"
    MISSING = "missing"
    LOST = "lost"
    OTHER = "other"


class VmtSensorTrackerLinkStatus(str, Enum):
    """Local Sensor Tracker instrument linkage state for a VMT unit."""

    NEVER_LINKED = "never_linked"
    LINKED = "linked"
    NOT_FOUND = "not_found"
    STALE = "stale"


class VmtCreatedVia(str, Enum):
    """How a VMT unit row entered the log book."""

    MANUAL = "manual"
    SEED = "seed"
    ST_SYNC = "st_sync"


class VmtServiceEventType(str, Enum):
    """Service / InnovaSea work event types for VMT log book history."""

    REBATTERY = "rebattery"
    HEAD_REPLACEMENT = "head_replacement"
    MAINBOARD_REPLACEMENT = "mainboard_replacement"
    HYDROPHONE_REPLACEMENT = "hydrophone_replacement"
    REPROGRAMMED = "reprogrammed"
    CODE_SPACE_UPDATE = "code_space_update"
    MANUFACTURER_REPAIR = "manufacturer_repair"
    OTHER = "other"

