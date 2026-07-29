# Settings to Move to .env - Quick Reference

## 🔴 Security-Critical (MUST move)

| Setting | Current Value | Priority | Notes |
|---------|--------------|----------|-------|
| `jwt_secret_key` | `"CHANGE_THIS..."` | 🔴 CRITICAL | Generate strong random key |
| `MAIL_USERNAME` | `"your-email@example.com"` | 🔴 HIGH | Email credentials |
| `MAIL_PASSWORD` | `"your-email-password"` | 🔴 HIGH | Email credentials |
| `sensor_tracker_token` | `"3c62f39804729f9e8aff90d0220c8aa07eed9e77"` | 🔴 HIGH | API token |
| `sensor_tracker_username` | `"tylerbyrne"` | 🔴 HIGH | API username |
| `sensor_tracker_password` | `"sJdujK3P7bYMth8"` | 🔴 HIGH | API password |

## 🟡 Deployment-Specific (SHOULD move)

| Setting | Current Value | Priority | Notes |
|---------|--------------|----------|-------|
| `local_data_base_path` | `"/home/cove/..."` | 🟡 MEDIUM | Linux path, varies by server |
| `log_file_path` | `"C:/Users/ty225269/..."` | 🟡 MEDIUM | Windows path, varies by OS |
| `remote_data_url` | `"http://129.173.20.180:8086/"` | 🟡 MEDIUM | Production URL |
| `remote_mission_folder_map_json` | `"{}"` | 🟡 MEDIUM | Already supports .env |
| `active_realtime_missions` | `["m209", "m211"]` | 🟡 MEDIUM | Changes over time |
| `sqlite_database_url` | `"sqlite:///./data_store/..."` | 🟡 MEDIUM | May vary by deployment |
| `sensor_tracker_host` | `"https://prod.ceotr.ca/..."` | 🟡 MEDIUM | Production URL |
| `sensor_tracker_debug_host` | `"http://127.0.0.1:8000/"` | 🟡 LOW | Dev-specific |

## 🟢 Feature Configuration (SHOULD move)

| Setting | Current Value | Priority | Notes |
|---------|--------------|----------|-------|
| `feature_toggles_json` | `'{"pic_management": true, ...}'` | 🟡 MEDIUM | Already supports .env |
| `background_cache_refresh_interval_minutes` | `60` | 🟢 LOW | May need tuning |
| `week_starts_sunday` | `True` | 🟢 LOW | User preference |
| `knowledge_base_max_upload_size_mb` | `50` | 🟢 LOW | May vary by server |

## 🤖 LLM & Vector Search (OPTIONAL to move)

| Setting | Current Value | Priority | Notes |
|---------|--------------|----------|-------|
| `vector_search_enabled` | `True` | 🟢 LOW | Can stay as default |
| `vector_similarity_threshold` | `0.35` | 🟢 LOW | May need tuning |
| `embedding_model` | `"sentence-transformers/..."` | 🟢 LOW | Model name |
| `llm_enabled` | `True` | 🟢 LOW | Feature toggle |
| `llm_host` | `"http://localhost:11434"` | 🟡 MEDIUM | May vary by deployment |
| `llm_model` | `"mistral:7b"` | 🟢 LOW | Model selection |
| `llm_temperature` | `0.3` | 🟢 LOW | May need tuning |
| `llm_max_tokens` | `512` | 🟢 LOW | May need tuning |
| `llm_timeout` | `180` | 🟢 LOW | May need tuning |
| `llm_max_context_chars` | `6000` | 🟢 LOW | May need tuning |

## 📋 Summary by Priority

### Must Move (6 settings)
- `jwt_secret_key`
- `MAIL_USERNAME`
- `MAIL_PASSWORD`
- `sensor_tracker_token`
- `sensor_tracker_username`
- `sensor_tracker_password`

### Should Move (13 settings)
- `local_data_base_path`
- `log_file_path`
- `remote_data_url`
- `remote_mission_folder_map_json` (already supports .env)
- `active_realtime_missions`
- `sqlite_database_url`
- `sensor_tracker_host`
- `sensor_tracker_debug_host`
- `feature_toggles_json` (already supports .env)
- `background_cache_refresh_interval_minutes`
- `week_starts_sunday`
- `knowledge_base_max_upload_size_mb`
- `llm_host`

### Optional (10 settings)
- All other LLM/vector search settings
- Can keep as defaults in code for development

---

## 🚀 Quick Migration Command

To generate a `.env` file with all current values (for reference):

```python
# Run this in Python to see current values
from app.config import settings
import json

env_vars = {
    # Security
    "JWT_SECRET_KEY": settings.jwt_secret_key,
    "MAIL_USERNAME": settings.MAIL_USERNAME,
    "MAIL_PASSWORD": settings.MAIL_PASSWORD,
    "SENSOR_TRACKER_TOKEN": settings.sensor_tracker_token,
    "SENSOR_TRACKER_USERNAME": settings.sensor_tracker_username,
    "SENSOR_TRACKER_PASSWORD": settings.sensor_tracker_password,
    
    # Deployment
    "LOCAL_DATA_BASE_PATH": str(settings.local_data_base_path),
    "LOG_FILE_PATH": str(settings.log_file_path),
    "REMOTE_DATA_URL": settings.remote_data_url,
    "REMOTE_MISSION_FOLDER_MAP_JSON": settings.remote_mission_folder_map_json,
    "ACTIVE_REALTIME_MISSIONS": json.dumps(settings.active_realtime_missions),
    "SQLITE_DATABASE_URL": settings.sqlite_database_url,
    "SENSOR_TRACKER_HOST": settings.sensor_tracker_host,
    "LLM_HOST": settings.llm_host,
    
    # Features
    "FEATURE_TOGGLES_JSON": settings.feature_toggles_json,
    "LLM_MODEL": settings.llm_model,
}

for key, value in env_vars.items():
    print(f"{key}={value}")
```
