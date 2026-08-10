# Environment Variables Guide

This document lists all settings from `app/config.py` that should be moved to your `.env` file for better configuration management, security, and deployment flexibility.

---

## 🔒 Security-Critical Settings (MUST be in .env)

These contain sensitive information and should **never** be committed to version control.

```bash
# JWT Authentication
JWT_SECRET_KEY=your-strong-random-secret-key-here-min-32-chars
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=1440

# Email/SMTP Settings
MAIL_USERNAME=your-email@example.com
MAIL_PASSWORD=your-email-password
MAIL_FROM=no-reply@wgbuddy.com
MAIL_SERVER=smtp.example.com
MAIL_PORT=587
MAIL_STARTTLS=True
MAIL_SSL_TLS=False

# Sensor Tracker API Credentials
SENSOR_TRACKER_TOKEN=your-api-token-here
SENSOR_TRACKER_USERNAME=your-username
SENSOR_TRACKER_PASSWORD=your-password

# CLS Argos / Kinéis api-telemetry (optional; checklist Argos-vs-GPS)
ARGOS_USERNAME=your-cls-username
ARGOS_PASSWORD=your-cls-password
# Optional overrides (defaults are production Group CLS URLs):
# ARGOS_AUTH_URL=https://account.groupcls.com/auth/realms/cls/protocol/openid-connect/token
# ARGOS_API_BASE_URL=https://api.groupcls.com/telemetry/api/v1
# ARGOS_CLIENT_ID=api-telemetry
# ARGOS_GPS_MAX_SEPARATION_KM=20
# ARGOS_FIX_MAX_AGE_HOURS=48
# ARGOS_CACHE_DIR=data_store/argos_cache
# ARGOS_CACHE_TTL_MINUTES=30
```

---

## 🌍 Deployment-Specific Settings (SHOULD be in .env)

These vary by environment (dev, staging, production) and should be configured per deployment.

```bash
# Data Paths (vary by server/environment)
LOCAL_DATA_BASE_PATH=/home/cove/Glider-Buddy-System/data
LOG_FILE_PATH=/var/log/wave-glider-buddy/app.log

# Remote Data Configuration
REMOTE_DATA_URL=http://129.173.20.180:8086/
REMOTE_MISSION_FOLDER_MAP_JSON={"m209": "output_realtime_missions/m209", "m211": "output_realtime_missions/m211"}

# Active Missions (changes over time)
ACTIVE_REALTIME_MISSIONS=["m209", "m211"]

# Slocum ERDDAP datasets (aliases optional — see SLOCUM_DATASET_ALIAS_MAP_JSON)
ACTIVE_SLOCUM_DATASETS=["fundy", "peggy"]
HISTORICAL_SLOCUM_DATASETS=["sable_20260621_224_delayed"]
SLOCUM_DATASET_ALIAS_MAP_JSON={"fundy": "fundy_20260724_229_realtime", "peggy": "peggy_20260621_226_realtime"}
# Optional per-platform alias maps for future platforms:
# MISSION_ALIAS_MAPS_JSON={"some_platform": {"alias": "canonical_mission_id"}}

# Database Configuration
SQLITE_DATABASE_URL=sqlite:///./data_store/app_data.sqlite
SQLITE_ECHO_LOG=False
FORMS_STORAGE_MODE=local_json

# Sensor Tracker Hosts
SENSOR_TRACKER_HOST=https://prod.ceotr.ca/sensor_tracker
SENSOR_TRACKER_DEBUG=False
SENSOR_TRACKER_DEBUG_HOST=http://127.0.0.1:8000/
```

---

## ⚙️ Feature Configuration (SHOULD be in .env)

These control application behavior and may need adjustment per environment.

```bash
# Feature toggles — prefer a pretty JSON file (one flag per line):
FEATURE_TOGGLES_FILE=config/feature_toggles.json
# Copy config/feature_toggles.example.json to config/feature_toggles.json and edit.
# Or use inline JSON (still valid if formatted with newlines inside quotes):
# FEATURE_TOGGLES_JSON={"pic_management": true, "admin_management": true}

# Background Tasks
BACKGROUND_CACHE_REFRESH_INTERVAL_MINUTES=60

# UI Preferences
WEEK_STARTS_SUNDAY=True

# Knowledge Base
KNOWLEDGE_BASE_MAX_UPLOAD_SIZE_MB=50
```

---

## 🤖 LLM & Vector Search Settings (SHOULD be in .env)

These control AI/ML features and may vary by deployment or need tuning.

```bash
# Vector Search Configuration
VECTOR_SEARCH_ENABLED=True
VECTOR_SIMILARITY_THRESHOLD=0.35
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

# LLM Configuration (Ollama)
LLM_ENABLED=True
LLM_HOST=http://localhost:11434
LLM_MODEL=mistral:7b
LLM_TEMPERATURE=0.3
LLM_MAX_TOKENS=512
LLM_TIMEOUT=180
LLM_FALLBACK_TO_SEARCH=True
LLM_MAX_CONTEXT_CHARS=6000
```

---

## 📋 Complete .env Template

Here's a complete template you can copy to your `.env` file:

```bash
# ============================================================================
# WAVE GLIDER BUDDY SYSTEM - ENVIRONMENT CONFIGURATION
# ============================================================================
# Copy this file to .env and fill in your values
# NEVER commit .env to version control!

# ============================================================================
# SECURITY SETTINGS (REQUIRED)
# ============================================================================

# JWT Authentication - Generate a strong random key for production!
# Use: python -c "import secrets; print(secrets.token_urlsafe(32))"
JWT_SECRET_KEY=CHANGE_THIS_IN_DOT_ENV_FOR_PRODUCTION_NEVER_USE_THIS_DEFAULT
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=1440

# ============================================================================
# EMAIL/SMTP SETTINGS
# ============================================================================
MAIL_USERNAME=your-email@example.com
MAIL_PASSWORD=your-email-password
MAIL_FROM=no-reply@wgbuddy.com
MAIL_SERVER=smtp.example.com
MAIL_PORT=587
MAIL_STARTTLS=True
MAIL_SSL_TLS=False

# ============================================================================
# DATA PATHS (Deployment-Specific)
# ============================================================================
LOCAL_DATA_BASE_PATH=/home/cove/Glider-Buddy-System/data
LOG_FILE_PATH=/var/log/wave-glider-buddy/app.log

# ============================================================================
# REMOTE DATA CONFIGURATION
# ============================================================================
REMOTE_DATA_URL=http://129.173.20.180:8086/
REMOTE_MISSION_FOLDER_MAP_JSON={"m209": "output_realtime_missions/m209", "m211": "output_realtime_missions/m211"}

# ============================================================================
# ACTIVE MISSIONS
# ============================================================================
# JSON array of mission IDs (update as missions change)
ACTIVE_REALTIME_MISSIONS=["m209", "m211"]

# ============================================================================
# SLOCUM DATASETS
# ============================================================================
# Use short aliases in ACTIVE/HISTORICAL lists when mapped via SLOCUM_DATASET_ALIAS_MAP_JSON
ACTIVE_SLOCUM_DATASETS=["fundy", "peggy"]
HISTORICAL_SLOCUM_DATASETS=[]
SLOCUM_DATASET_ALIAS_MAP_JSON={"fundy": "fundy_20260724_229_realtime", "peggy": "peggy_20260621_226_realtime"}

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================
SQLITE_DATABASE_URL=sqlite:///./data_store/app_data.sqlite
SQLITE_ECHO_LOG=False
FORMS_STORAGE_MODE=local_json

# ============================================================================
# SENSOR TRACKER API
# ============================================================================
SENSOR_TRACKER_HOST=https://prod.ceotr.ca/sensor_tracker
SENSOR_TRACKER_TOKEN=your-api-token-here
SENSOR_TRACKER_USERNAME=your-username
SENSOR_TRACKER_PASSWORD=your-password
SENSOR_TRACKER_DEBUG=False
SENSOR_TRACKER_DEBUG_HOST=http://127.0.0.1:8000/

# ============================================================================
# CLS ARGOS / KINÉIS API-TELEMETRY (optional)
# ============================================================================
ARGOS_USERNAME=your-cls-username
ARGOS_PASSWORD=your-cls-password
# ARGOS_GPS_MAX_SEPARATION_KM=20
# ARGOS_FIX_MAX_AGE_HOURS=48
# ARGOS_CACHE_TTL_MINUTES=30

# ============================================================================
# FEATURE TOGGLES
# ============================================================================
# Recommended: pretty-printed JSON file (see config/feature_toggles.example.json)
FEATURE_TOGGLES_FILE=config/feature_toggles.json
# Alternative: single env var (must be valid JSON — newlines OK inside quoted value)
# FEATURE_TOGGLES_JSON={"pic_management": true, "admin_management": true}

# ============================================================================
# BACKGROUND TASKS
# ============================================================================
BACKGROUND_CACHE_REFRESH_INTERVAL_MINUTES=60

# ============================================================================
# UI PREFERENCES
# ============================================================================
WEEK_STARTS_SUNDAY=True

# ============================================================================
# KNOWLEDGE BASE
# ============================================================================
KNOWLEDGE_BASE_MAX_UPLOAD_SIZE_MB=50

# ============================================================================
# VECTOR SEARCH (RAG System)
# ============================================================================
VECTOR_SEARCH_ENABLED=True
VECTOR_SIMILARITY_THRESHOLD=0.35
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

# ============================================================================
# LLM CONFIGURATION (Ollama)
# ============================================================================
LLM_ENABLED=True
LLM_HOST=http://localhost:11434
LLM_MODEL=mistral:7b
LLM_TEMPERATURE=0.3
LLM_MAX_TOKENS=512
LLM_TIMEOUT=180
LLM_FALLBACK_TO_SEARCH=True
LLM_MAX_CONTEXT_CHARS=6000
```

---

## 📊 Settings Summary

| Category | Count | Priority | Notes |
|---------|-------|----------|-------|
| **Security-Critical** | 9 | 🔴 HIGH | Must be in .env, never commit |
| **Deployment-Specific** | 10 | 🟡 MEDIUM | Varies by environment |
| **Feature Config** | 4 | 🟡 MEDIUM | May need per-environment tuning |
| **LLM/Vector Search** | 9 | 🟢 LOW | Can stay in code for defaults |
| **Total** | **32** | - | - |

---

## 🔄 Migration Steps

1. **Create `.env` file** (if it doesn't exist):
   ```bash
   cp .env.example .env  # If you have an example file
   # OR
   touch .env
   ```

2. **Add settings to `.env`**:
   - Copy the template above
   - Replace placeholder values with your actual values
   - Pay special attention to security-critical settings

3. **Update `.gitignore`** (if not already):
   ```gitignore
   .env
   .env.local
   .env.*.local
   ```

4. **Test configuration**:
   ```bash
   python -c "from app.config import settings; print('Config loaded successfully!')"
   ```

5. **Remove hardcoded defaults** (optional):
   - After confirming .env works, you can remove hardcoded defaults from `config.py`
   - Keep sensible defaults for development

---

## ⚠️ Important Notes

### Security
- **Never commit `.env` to version control**
- Generate strong `JWT_SECRET_KEY` for production:
  ```python
  import secrets
  print(secrets.token_urlsafe(32))
  ```
- Rotate credentials regularly

### JSON Values
Some settings use JSON strings:
- `REMOTE_MISSION_FOLDER_MAP_JSON` - Must be valid JSON
- `ACTIVE_REALTIME_MISSIONS` - Must be valid JSON array
- `FEATURE_TOGGLES_FILE` - Path to a JSON file (recommended; one toggle per line). Example: `config/feature_toggles.example.json`
- `FEATURE_TOGGLES_JSON` - Inline JSON object (used when no file, or as fallback if the file path is missing). Include `"public_login_map": true` to enable the unauthenticated login-page map; default off. Include `"map_vector_layers": true` to enable static GeoJSON reference-zone toggles (GOSL, DFO fishery areas, NOAA shipping lanes) on home maps. Include `"vessel_density_map_layer": true` to enable DFO AIS vessel-density monthly rasters on home maps. Include `"navwarn_map_layer": true` to enable CCG NAVWARN overlays on home maps.

### Public login map
- Kill switch: `public_login_map` in `FEATURE_TOGGLES_FILE` / `FEATURE_TOGGLES_JSON`
- Allowlist intersection: active env lists (`ACTIVE_REALTIME_MISSIONS`, `ACTIVE_SLOCUM_DATASETS`) ∩ admin `public_map_enabled`
- Optional: `TRUSTED_PROXY_COUNT` (int; default `0`) — how many rightmost `X-Forwarded-For` hops to trust for rate-limit client IP
- Cache dir / TTL defaults live in `app/config.py` (`public_map_cache_dir`, `public_map_cache_ttl_seconds`, `public_map_warm_interval_minutes`, `public_map_max_missions`)
- Ops detail: [Public login map how-to](./how-tos/public_login_map.md)

### Static vector map layers (home overlays)
- Kill switch: `map_vector_layers` in `FEATURE_TOGGLES_FILE` / `FEATURE_TOGGLES_JSON` (default **off**)
- Layer files: git-tracked under `config/map_layers/` (`map_layers_dir` in `app/config.py`) — GOSL zones, DFO LFAs/FMAs, NOAA shipping lanes
- Convert/fetch locally: `scripts/convert_map_layer_kml.py` (KML), `scripts/fetch_map_layer_arcgis.py` (ArcGIS REST); commit `published/` + `manifest.json` (+ optional `sources/`) — do not require prod to re-ingest
- Ops detail: [Static vector map layers how-to](./how-tos/map_vector_layers.md)

### AIS vessel density map layer (home overlays)
- Kill switch: `vessel_density_map_layer` in `FEATURE_TOGGLES_FILE` / `FEATURE_TOGGLES_JSON` (default **off**)
- Upstream: DFO egisp MapServer (monthly All-types layers 7–18); live `export` proxy — not git GeoJSON
- Cache: `vessel_density_cache_dir` (default `data_store/vessel_density_cache`), TTL `vessel_density_cache_ttl_seconds` (default 3600), timeout `vessel_density_http_timeout_seconds`
- Optional override: `VESSEL_DENSITY_MAPSERVER_URL`
- Ops detail: [AIS vessel density how-to](./how-tos/vessel_density_map_layer.md)

### NAVWARN map layer (home overlays)
- Kill switch: `navwarn_map_layer` in `FEATURE_TOGGLES_FILE` / `FEATURE_TOGGLES_JSON` (default **off**)
- Cache: `navwarn_cache_dir` (default `data_store/navwarn_cache`), TTLs `navwarn_cache_ttl_seconds` / `navwarn_areas_ttl_seconds`, rate gate `navwarn_upstream_min_interval_seconds`
- Search paging: reconcile walks `page=1..N` until empty (upstream ~50/page); incremental prefetch uses page 1 only; safety ceilings `navwarn_search_max_hits` (default 5000) and `navwarn_search_max_pages` (default 100)
- Prefetch interval: `navwarn_prefetch_interval_minutes` (default 30); cleanup cron hour `navwarn_cleanup_cron_hour` (daily reconcile)
- Ops detail: [NAVWARN map layer how-to](./how-tos/navwarn_map_layer.md)

### Path Values
- Use forward slashes `/` even on Windows for `LOCAL_DATA_BASE_PATH`
- Use absolute paths for production deployments
- Relative paths work for development

### Boolean Values
- Use `True`/`False` (Python boolean strings)
- Or `1`/`0` (will be converted)

### List Values
- `ACTIVE_REALTIME_MISSIONS` must be a JSON array: `["m209", "m211"]`
- Not a comma-separated string

---

## 🧪 Testing Your Configuration

After setting up `.env`, test that everything loads correctly:

```python
from app.config import settings

# Check critical settings
assert settings.jwt_secret_key != "CHANGE_THIS_IN_DOT_ENV_FOR_PRODUCTION_NEVER_USE_THIS_DEFAULT"
assert settings.llm_model == "mistral:7b"
assert len(settings.active_realtime_missions) > 0

print("✅ Configuration loaded successfully!")
```

---

## 📝 Example .env for Different Environments

### Development
```bash
LLM_HOST=http://localhost:11434
SENSOR_TRACKER_DEBUG=True
SENSOR_TRACKER_DEBUG_HOST=http://127.0.0.1:8000/
SQLITE_ECHO_LOG=True
```

### Production
```bash
LLM_HOST=http://ollama-service:11434
SENSOR_TRACKER_DEBUG=False
SENSOR_TRACKER_DEBUG_HOST=
SQLITE_ECHO_LOG=False
LOG_FILE_PATH=/var/log/wave-glider-buddy/app.log
```

---

## 🔍 Current Hardcoded Values to Review

These are currently hardcoded in `config.py` and should be reviewed:

1. **`local_data_base_path`**: `/home/cove/Glider-Buddy-System/data` - Linux path, may need Windows equivalent
2. **`log_file_path`**: Windows path hardcoded - should be environment-specific
3. **`remote_data_url`**: Production URL hardcoded
4. **`sensor_tracker_host`**: Production URL hardcoded
5. **`active_realtime_missions`**: Hardcoded list - should be configurable

---

## ✅ Checklist

- [ ] Create `.env` file
- [ ] Add all security-critical settings
- [ ] Add deployment-specific paths
- [ ] Configure LLM settings
- [ ] Set up feature toggles
- [ ] Test configuration loading
- [ ] Verify `.env` is in `.gitignore`
- [ ] Document any environment-specific requirements
- [ ] Update deployment documentation
