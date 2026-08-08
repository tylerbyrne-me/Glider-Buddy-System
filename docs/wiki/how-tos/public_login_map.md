# Public login map

Unauthenticated Leaflet map on `/login.html` for allowlisted Wave Glider and Slocum missions (and future platforms that wire into the same service).

## Enable

1. Set feature toggle `public_login_map` to `true` in `FEATURE_TOGGLES_FILE` / `FEATURE_TOGGLES_JSON` (default **off**).
2. List the mission in the active env config:
   - Wave Glider: `ACTIVE_REALTIME_MISSIONS`
   - Slocum: `ACTIVE_SLOCUM_DATASETS` (aliases via `SLOCUM_DATASET_ALIAS_MAP_JSON` are fine)
3. In admin Mission Overview (WG) or Slocum Mission Overviews, enable **Show on public map**. Optionally enable **Show latest weekly report**.

Both the env active list **and** the DB flag are required. Cap: `public_map_max_missions` in config.

## APIs

| Endpoint | Purpose |
|----------|---------|
| `GET /api/public/map/bundle` | Cached track bundle (`?refresh=1` forces rebuild; stricter rate limit) |
| `GET /api/public/map/kml` | Static snapshot KML (same 7-day window; not live/network KML) |
| `GET /api/public/reports/{platform}/{id}/latest` | Gated weekly PDF when `public_weekly_report_enabled` |

Rate limits and client IP handling: `app/core/infra/rate_limit.py` (`TRUSTED_PROXY_COUNT`). Live KML (`/api/kml/live/{token}`) remains authenticated and separate.

## Popup labels (platform-agnostic)

Bundle entries expose `platform_name` and `mission_title` (plus `display_name` = platform name for KML folders). Resolution is shared in `resolve_public_mission_labels()` (`app/core/public_map_service.py`):

1. **Sensor Tracker** — `platform_name` / `title` (match full mission id **or** deployment code, same as weekly reports)
2. **Platform deployment row** — Slocum `glider_name` / `name` when present
3. **Telemetry vehicle name** — Wave Glider `vehicleName` / `VehicleName` when ST is missing
4. **Folder-style mission id hint** — e.g. `m227-SV3-1071` → platform `SV3-1071`
5. Else fall back to the configured mission/dataset id

Popups show **Platform Name**, platform type, **Mission Title**, lat/lon, and optional weekly report link — not env aliases as the headline.

Without a Sensor Tracker row for a WG mission, Mission Title may still be the folder id until ST is synced for that deployment code.

## Login UI

- Map is centered in the viewport **below** the fixed banner (~75% of that area).
- Banner height is measured at runtime into `--public-login-banner-height` so the map is not clipped by the navbar.
- **Refresh map** and **Download KML** sit in a toolbar **under** the map (not overlaid on tiles / not under the banner).
- Login is a navbar button → Bootstrap modal (`#loginForm` still used by `auth.js`).

## Cache / leader

- Disk: `data_store/public_map_cache/`
- Leader job: `system_public_map_warm_job` (TTL from `public_map_cache_ttl_seconds` / warm interval in config)
- After label or allowlist changes, use **Refresh map** (`?refresh=1`) or wait for TTL / warm job

## Key files

| File | Role |
|------|------|
| `app/core/public_map_service.py` | Allowlist, labels, tracks, bundle, KML |
| `app/routers/public_map.py` | Public HTTP routes |
| `web/templates/login.html` | Layout + banner offset |
| `web/static/js/public_map.js` | Leaflet client |

See also [architecture](../architecture.md) and [ENV_VARIABLES](../ENV_VARIABLES.md#public-login-map).

## Out of scope (for now)

Static vector reference zones (GOSL DSZ / safe zones under `config/map_layers/`) are **home-map only**. Wiring selected layers onto this public map is a near-term backlog item — see [map_vector_layers.md](./map_vector_layers.md) and [backlog](../../tasks/backlog.md).
