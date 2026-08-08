# Glider Buddy System — application settings (app/config.py)
import json
import logging
from typing import Any, Optional  # Import Any and Optional
from pathlib import Path

from pydantic_settings import BaseSettings

from app.feature_toggle_config import default_feature_toggles_json, load_feature_toggles

_settings_log = logging.getLogger(__name__)


class Settings(BaseSettings):
    local_data_base_path: Path = Path(
        "/home/cove/Glider-Buddy-System/data"
    )
    remote_data_url: str = (
        "http://129.173.20.180:8086/"  # Base URL before specific output folders
    )
    # Store as JSON string in .env, parse here
    remote_mission_folder_map_json: str = "{}"
    # Store as JSON string in .env, parse here
    active_realtime_missions: list[str] = []
    # Example: List of mission IDs considered active
    # In a real scenario, this list might be managed dynamically or via
    # another config source.
    # These are the missions whose data in 'output_realtime_missions' will be
    # proactively cached.
    background_cache_refresh_interval_minutes: int = 60
    # Default if not in .env
    # Root log verbosity (DEBUG restores per-file sync / ERDDAP / date-filter detail).
    log_level: str = "INFO"
    # When set, also write rotating app logs here; primary stream remains stderr (journalctl).
    log_file_path: Optional[Path] = None

    week_starts_sunday: bool = True 

    # Default relative to project root if not overridden by .env

    # --- App URL / HTTP(S) (for production) ---
    # Public URL of the app. Used for links, redirects, KML network links, etc.
    # Must match the origin users open (scheme + host + port). See .env.example.
    # Local: http://localhost:8000  |  Production: https://your-host (prefer hostname over raw IP)
    app_base_url: str = "http://localhost:8000"
    # True when the browser URL is https:// — sets Secure on cookies and https_only on session middleware.
    # Not inferred from reverse-proxy headers; set APP_USE_HTTPS explicitly. See .env.example.
    app_use_https: bool = False
    # Comma-separated hosts trusted to set X-Forwarded-Proto / Host (or "*" behind a locked-down reverse proxy).
    # Enables correct https URLs from url_for() when TLS terminates before uvicorn.
    proxy_trusted_hosts: str = "*"
    # Path where SQLAdmin is mounted (default /admin). Use e.g. /app/admin if app is under a prefix.
    app_admin_base_url: str = "/admin"

    # JWT Settings
    # IMPORTANT: The default JWT_SECRET_KEY is INSECURE and for DEVELOPMENT ONLY.
    # ALWAYS override this in your .env file with a strong, randomly generated key for production.
    jwt_secret_key: str = "CHANGE_THIS_IN_DOT_ENV_FOR_PRODUCTION_NEVER_USE_THIS_DEFAULT"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60 * 24
    # 24 hours, adjust as needed
    forms_storage_mode: str = "local_json"  # Options: "local_json", "sqlite"
    sqlite_database_url: str = (
        "sqlite:///./data_store/app_data.sqlite" # Reverted to original default
    )
    sqlite_echo_log: bool = False  # Add this line, set to True for SQL logging

    # --- Email Settings (optional; retained for future notification features) ---
    # SECURITY: All email settings MUST be configured in .env file
    # These defaults are placeholders and will cause email functionality to fail if not overridden
    MAIL_USERNAME: Optional[str] = None
    MAIL_PASSWORD: Optional[str] = None
    MAIL_FROM: Optional[str] = None
    MAIL_PORT: int = 587
    MAIL_SERVER: Optional[str] = None
    MAIL_STARTTLS: bool = True
    MAIL_SSL_TLS: bool = False

    # Feature Toggles — prefer FEATURE_TOGGLES_FILE (pretty JSON) over FEATURE_TOGGLES_JSON (inline).
    # See config/feature_toggles.example.json. wave_glider_specific_nav: WG-only nav items.
    # iridium_map_layer: home Leaflet Iridium overlay. public_login_map: unauthenticated /login map.
    feature_toggles_file: Optional[Path] = None
    feature_toggles_json: str = default_feature_toggles_json()

    # --- Slocum ERDDAP Settings ---
    # Ocean Track Slocum glider ERDDAP server; override in .env if needed
    slocum_erddap_server: str = "https://erddap.oceantrack.org/erddap"
    # Active (realtime/current) dataset IDs. Same format as ACTIVE_REALTIME_MISSIONS: JSON array in .env,
    # e.g. ACTIVE_SLOCUM_DATASETS=["cabot_20240901_198_realtime"] or aliases via SLOCUM_DATASET_ALIAS_MAP_JSON
    active_slocum_datasets: list[str] = []
    # Historical (delayed/past) dataset IDs. JSON array in .env, e.g. HISTORICAL_SLOCUM_DATASETS=["peggy_20250522_206_delayed"]
    historical_slocum_datasets: list[str] = []
    # Alias → ERDDAP dataset id (like REMOTE_MISSION_FOLDER_MAP_JSON for Wave Glider mission keys).
    # e.g. SLOCUM_DATASET_ALIAS_MAP_JSON={"fundy": "fundy_20260724_229_realtime", "peggy": "peggy_20260621_226_realtime"}
    slocum_dataset_alias_map_json: str = "{}"
    # Optional per-platform alias maps for future platforms: {"some_platform": {"alias": "canonical_id"}}
    mission_alias_maps_json: str = "{}"
    # Round time window to this many minutes for hours_back mode so cache key is stable (fewer ERDDAP refetches).
    slocum_cache_window_minutes: int = 15
    # Persistent parquet mirror for Slocum ERDDAP data (shared across gunicorn workers).
    slocum_mirror_dir: Path = Path("data_store/slocum_cache")
    # Hours of data retained in the mirror for active (realtime) datasets.
    slocum_mirror_retention_hours: int = 72
    # Default warm/sync window aligned with dashboard UI (DEFAULT_HOURS = 24).
    slocum_warm_hours: int = 24
    # Overlap when merging incremental ERDDAP pulls into the mirror.
    slocum_sync_overlap_hours: int = 2
    # Ops escape hatch only: ERDDAP orderByClosest minutes for dashboard mirror pulls.
    # Default 0 = full resolution (active and historical). Pilots thin via UI Resample.
    # CTD/checklist never use this (allow_decimation=False).
    slocum_erddap_decimation_minutes: int = 0
    # Regex filter for allDatasets metadata queries (Ocean Track Slocum IDs).
    slocum_erddap_dataset_id_filter: str = r".*(_realtime|_delayed)$"
    # Temporary on-demand overage cache for windows outside the rolling mirror.
    slocum_overage_cache_dir: Path = Path("data_store/slocum_overage_cache")
    slocum_overage_ttl_hours: int = 24
    slocum_overage_cleanup_interval_hours: int = 6
    slocum_overage_interactive_max_days: int = 31
    slocum_overage_max_bytes: int = 10 * 1024 * 1024 * 1024  # 10 GB

    # --- ETOPO 2022 Bathymetry (ERDDAP griddap for PDF report map contours) ---
    etopo_erddap_server: str = "https://oceanwatch.pifsc.noaa.gov/erddap"
    etopo_dataset_id: str = "ETOPO_2022_v1_15s"
    etopo_request_timeout: int = 30  # seconds; fetch failures skip contours silently
    bathy_cache_dir: Path = Path("data_store/bathy_cache")
    # Longer than weather: grids are stable topography reused across report generation.
    bathy_cache_max_age_days: int = 90
    bathy_cache_max_bytes: int = 512 * 1024 * 1024  # 512 MB

    # --- Open-Meteo weather map layer cache (home-page wind overlay) ---
    weather_map_cache_dir: Path = Path("data_store/weather_cache")
    weather_map_prefetch_enabled: bool = True
    weather_map_bbox_pad_deg: float = 1.0
    weather_map_bbox_snap_deg: float = 1.0
    weather_map_prefetch_horizon_days: int = 7
    weather_map_prefetch_step_hours: int = 3
    weather_map_prefetch_cron_hour: int = 7  # UTC
    # Buddy manifest TTL: API rebuilds latest.json when older than this (ICON runs update often).
    weather_map_manifest_ttl_seconds: int = 6 * 3600
    # Daily disk cleanup runs even when weather_map_layers is disabled (stranded cache).
    weather_map_cleanup_cron_hour: int = 7  # UTC
    weather_map_cache_max_bytes: int = 5 * 1024 * 1024 * 1024  # 5 GB

    # --- Iridium constellation TLE cache (home-page satellite overlay) ---
    # CelesTrak updates ~every 2 hours; disk gate enforces ≤1 upstream contact per TTL.
    iridium_tle_cache_dir: Path = Path("data_store/iridium_cache")
    iridium_tle_cache_ttl_seconds: int = 7200
    iridium_tle_prefetch_enabled: bool = True
    # Leader interval job; should be >= ttl (CelesTrak policy).
    iridium_tle_prefetch_interval_hours: int = 2
    # Daily cleanup reclaim when feature off or files older than this.
    iridium_tle_cleanup_max_age_days: int = 7
    iridium_tle_cleanup_cron_hour: int = 7  # UTC

    # --- DMON Robots4Whales analyst-review cache ---
    # Scraped HTML from dcs.whoi.edu; leader job only (no live scrape on dashboard).
    dmon_review_cache_dir: Path = Path("data_store/dmon_review_cache")
    dmon_review_prefetch_interval_hours: int = 12
    dmon_review_prefetch_enabled: bool = True
    dmon_review_http_timeout_seconds: float = 30.0

    # --- Static vector map layers (GeoJSON overlays; git-tracked under config/) ---
    map_layers_dir: Path = Path("config/map_layers")

    # --- Public login-page map (unauthenticated) ---
    public_map_cache_dir: Path = Path("data_store/public_map_cache")
    public_map_cache_ttl_seconds: int = 600  # 10 minutes
    public_map_window_hours: int = 168  # fixed 7-day window
    public_map_max_points_per_mission: int = 500
    public_map_max_missions: int = 20
    public_map_warm_interval_minutes: int = 10
    # Client IP for rate limits: 0 = request.client.host; >0 = trust that many rightmost X-Forwarded-For hops.
    trusted_proxy_count: int = 0

    # --- Sensor Tracker Settings ---
    # SECURITY: Credentials MUST be configured in .env file
    sensor_tracker_host: str = "https://prod.ceotr.ca/sensor_tracker"
    sensor_tracker_token: Optional[str] = None  # Must be set in .env
    sensor_tracker_username: Optional[str] = None  # Must be set in .env
    sensor_tracker_password: Optional[str] = None  # Must be set in .env
    sensor_tracker_debug: bool = False
    sensor_tracker_debug_host: str = "http://127.0.0.1:8000/"

    # --- Teledyne SFMC (Slocum Fleet Mission Control) ---
    # Optional; checklist SFMC autofill is skipped when unset. Client ID/Secret from SFMC API Access page.
    sfmc_base_url: Optional[str] = None
    sfmc_client_id: Optional[str] = None
    sfmc_client_secret: Optional[str] = None
    sfmc_verify_tls: bool = True  # Set false for self-signed SFMC certs (SFMC_VERIFY_TLS=false)
    # Leader-only job: refresh slocum_sfmc_snapshots for active deployments.
    sfmc_cache_refresh_interval_minutes: int = 60
    # SFMC hosts typically allow ~25 requests/minute; stay under that.
    sfmc_max_requests_per_minute: int = 20

    # --- CLS Argos / Kinéis api-telemetry (optional) ---
    # Password-grant Keycloak auth; checklist Argos-vs-GPS check skipped when unset.
    # Per-glider deviceRef is SlocumDeployment.checklist_reference_values.argos_id.
    argos_username: Optional[str] = None
    argos_password: Optional[str] = None
    argos_auth_url: str = (
        "https://account.groupcls.com/auth/realms/cls/protocol/openid-connect/token"
    )
    argos_api_base_url: str = "https://api.groupcls.com/telemetry/api/v1"
    argos_client_id: str = "api-telemetry"
    argos_gps_max_separation_km: float = 20.0
    argos_fix_max_age_hours: float = 48.0
    argos_cache_dir: Path = Path("data_store/argos_cache")
    argos_cache_ttl_minutes: int = 30
    argos_http_timeout_seconds: float = 45.0

    # --- Automated Slocum daily checklist (leader cron; UTC only) ---
    # Fires at deadline; submits missing checklists as System using cached SFMC.
    slocum_auto_checklist_cron_hour: int = 23
    slocum_auto_checklist_cron_minute: int = 30
    slocum_auto_checklist_stagger_seconds: int = 150  # pause between missions
    
    # --- Knowledge Base Settings ---
    knowledge_base_max_upload_size_mb: int = 50  # Maximum file upload size in MB
    
    # --- OpenWeatherMap API Settings ---
    # SECURITY: API key MUST be configured in .env file
    openweathermap_api_key: Optional[str] = None  # Must be set in .env
    
    # --- Default User Accounts (Seed Users) ---
    # SECURITY: Passwords MUST be set in .env file - no defaults for security
    # Usernames can have defaults for convenience, but passwords must be configured
    default_admin_username: str = "adminuser"
    default_admin_password: Optional[str] = None  # MUST be set in .env
    default_admin_email: str = "admin@example.com"
    default_pilot_username: str = "pilotuser"
    default_pilot_password: Optional[str] = None  # MUST be set in .env
    default_pilot_email: str = "pilot@example.com"
    default_pilot_rt_username: str = "pilot_rt_only"
    default_pilot_rt_password: Optional[str] = None  # MUST be set in .env
    default_pilot_rt_email: str = "pilot_rt@example.com"

    # --- Mission Media Settings ---
    mission_media_root_path: str = "web/static/mission_media"
    mission_media_max_image_size_mb: int = 10
    mission_media_max_video_size_mb: int = 50
    mission_media_max_files_per_upload: int = 10
    
    # --- Chatbot Vector Search Settings ---
    vector_search_enabled: bool = False  # Enable vector search (requires chromadb and sentence-transformers)
    vector_similarity_threshold: float = 0.35  # Minimum similarity for matches (0.0-1.0, 0.35 works well)
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"  # Embedding model name
    vector_chunking_enabled: bool = False  # Enable chunking for document vectorization
    vector_chunking_min_chars: int = 2000  # Chunk documents longer than this
    
    # --- LLM Settings (Ollama) ---
    llm_enabled: bool = False  # Enable LLM for response synthesis
    llm_host: str = "http://localhost:11434"  # Ollama server URL
    llm_model: str = "mistral:7b"  # Model to use (mistral:7b recommended for quality + context)
    llm_temperature: float = 0.3  # Lower temperature for more factual/consistent answers
    llm_max_tokens: int = 512  # Max response length (increased for detailed answers)
    llm_timeout: int = 180  # Timeout in seconds (increased for larger context)
    llm_fallback_to_search: bool = False  # Fall back to search results if LLM unavailable
    llm_max_context_chars: int = 6000  # Max context to send to LLM (Mistral supports ~8k tokens)
    
    # Parsed values (not loaded directly from env)
    remote_mission_folder_map: dict[str, str] = {}
    slocum_dataset_alias_map: dict[str, str] = {}
    mission_alias_maps: dict[str, dict[str, str]] = {}
    feature_toggles: dict[str, bool] = {}

    def model_post_init(self, __context: Any) -> None:
        """Post-initialization hook to parse JSON strings."""
        self.remote_mission_folder_map = json.loads(self.remote_mission_folder_map_json)
        self.slocum_dataset_alias_map = json.loads(self.slocum_dataset_alias_map_json)
        raw_alias_maps = json.loads(self.mission_alias_maps_json)
        self.mission_alias_maps = raw_alias_maps if isinstance(raw_alias_maps, dict) else {}
        self.feature_toggles = load_feature_toggles(
            json_str=self.feature_toggles_json,
            file_path=self.feature_toggles_file,
        )
        base = self.app_base_url.strip()
        base_l = base.lower()
        if self.app_use_https and not base_l.startswith("https://"):
            _settings_log.warning(
                "APP_USE_HTTPS=true but APP_BASE_URL=%r does not start with https:// — "
                "set APP_BASE_URL to the public HTTPS origin (e.g. https://glider-buddy.ceotr.ca) "
                "so KML network links and other absolute URLs are correct.",
                self.app_base_url,
            )
        if not self.app_use_https and base_l.startswith("https://"):
            _settings_log.warning(
                "APP_BASE_URL uses HTTPS but APP_USE_HTTPS=false — session and auth cookies "
                "will not be marked Secure; use APP_USE_HTTPS=true when users load the site over HTTPS.",
            )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        env_prefix = "" # Ensure no prefix is added to env var names
        extra = "ignore"  # Ignore extra environment variables (like CLI_ADMIN_* for CLI tools)


settings = Settings()
