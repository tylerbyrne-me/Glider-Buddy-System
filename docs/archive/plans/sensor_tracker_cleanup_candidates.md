# Sensor Tracker code — cleanup review candidates

Generated after fixing `attached_time` date-only truncation (SM4BAT / m223). Use as a checklist for a focused ST refactor pass.

## Confirmed fix (done)

| Item | Detail |
|------|--------|
| `format_attached_time_for_api()` | Replaces date-only `.split()[0]` in `enrich_deployment_with_data_loggers` |
| Tests | `tests/test_sensor_tracker_attached_time.py` |
| Diagnostic | `scripts/check_platform_instruments_query.py --mission m223` |

## Likely dead / unused (verify before delete)

| Symbol | Location | Notes |
|--------|----------|--------|
| `HistoryOption` enum | `sensor_tracker_service.py` | Defined, never referenced |
| `enrich_deployment_with_platform()` | `sensor_tracker_service.py` | Not called; platform fetched inside `enrich_deployment_with_data_loggers` |
| `fetch_deployment(deployment_id)` | `sensor_tracker_service.py` | Superseded by `fetch_deployment_by_number` / `fetch_deployment_by_mission_id` |
| `test_connection()` | `sensor_tracker_service.py` | No callers in `app/` |
| `fetch_deployments_by_platform()` | `sensor_tracker_service.py` | Only used by diagnostic script |

## Parsed but unused in sync path

| Field / path | Notes |
|--------------|--------|
| `instrument_on_platform_history` | Stored in `parse_platform()`; sync uses `/api/instrument_on_platform/` only |
| `sensor_on_instrument_history` | Same pattern (comment at ~1106) |
| Removed parsers | Comment references `parse_instrument_on_platform_history` — already deleted |

## Duplicate fetch patterns (consolidation opportunity)

Each endpoint implements **client library try → httpx fallback**:

- `fetch_data_loggers_on_platform`
- `fetch_instruments_on_data_logger`
- `fetch_sensors_on_instrument`
- `fetch_instruments_on_platform`
- `fetch_parameters_by_identifier`

Consider one `_st_get(resource, params)` helper to reduce ~200 lines of repetition.

## Behavioral edges to document or retest

| Topic | Risk |
|-------|------|
| Early return when no data loggers | Skips platform-direct fetch entirely (`~1168–1171`) |
| `attached_time` on all ST relationship calls | Now full timestamp; confirm older deployments still behave |
| Cached sync without `force_refresh` | Stale instruments until admin forces refresh |
| Flight computer instruments | Synced to DB but hidden on mission overview UI |
| `skip_auth` / dual auth paths | Complexity for library compatibility |

## Files in ST surface area

| File | Role |
|------|------|
| `app/services/sensor_tracker_service.py` | API + parse + enrich |
| `app/services/sensor_tracker_sync_service.py` | DB sync orchestration |
| `app/routers/missions.py` | Admin sync route |
| `app/routers/reporting.py` | Report-time sync |
| `app/core/fluorometer_channels.py` | Only typed instrument special-case |
| `web/static/js/admin_mission_overviews.js` | Overview UI filters |
| `web/templates/home.html` | Public overview filters |

## Suggested review order

1. Remove or wire up dead methods (`enrich_deployment_with_platform`, `fetch_deployment`, `HistoryOption`).
2. Fix early-return when no data loggers (platform instruments should still load).
3. Consolidate httpx/client GET helpers.
4. Decide whether `instrument_on_platform_history` should be removed from `parse_platform` or used as fallback.
5. UI: show flight-computer instruments or document omission.
