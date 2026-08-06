# Architecture

_Last updated: 2026-08-05_

## One-paragraph summary

**Glider Buddy System (GBS)** is a FastAPI web app for multi-platform glider operations. Today it supports **Wave Glider** and **Slocum** (with room for more): home hubs, real-time dashboards, station/offload and PIC workflows (WG), knowledge base / LLM features, and admin tools. Platforms are registered in `app/core/platforms/` (IDs, URL prefixes, brand titles, access attrs). Telemetry is synced into on-disk caches under `data_store/` and `data/`; a background scheduler refreshes active caches. Production typically runs under gunicorn with two Uvicorn workers; only the leader worker runs sync and APScheduler (fcntl lock).

## Platforms

- **Registry** — [`app/core/platforms/registry.py`](../../app/core/platforms/registry.py): canonical `platform_id` (`wave_glider`, `slocum`), kebab URL prefixes (`/wave-glider`, `/slocum`), home/API prefixes, KB toggles, ACL attribute names.
- **Brand** — Product: *Glider Buddy System* / *GBS*. In-platform chrome: *{Display} Glider Buddy System* (e.g. *Wave Glider Buddy System*).
- **HTML** — Platform pages live under `/{url_prefix}/...`; legacy Wave Glider root HTML paths redirect to `/wave-glider/...`.
- **APIs** — Prefer `/api/{platform_id}/...` for new work; existing Wave Glider `/api/...` paths remain supported (grandfathered).
- **Platform packages** — Slocum business logic lives under `app/platforms/slocum/`; routers stay in `app/routers/`. Register new platforms in the registry first; put platform-only code under `app/platforms/{id}/`.

See [conventions](./conventions.md#product--platform-naming) and [ADR 0003](../decisions/0003-platform-brand-naming.md).

## Components

- **App entry / lifespan** — FastAPI app, middleware, startup leader lock, router mounts (`app/app.py`)
- **Core** — shared business logic, data loading, auth, models, platforms registry, infra (logging, feature toggles, caching helpers) (`app/core/`)
- **Platforms** — vehicle-specific packages (e.g. Slocum ERDDAP/mirrors/checklists) (`app/platforms/`)
- **Routers** — HTTP endpoints only; depend on core/platforms/services, never the reverse (`app/routers/`)
- **Services** — higher-level orchestration (knowledge base, reporting, sensor tracker, etc.) (`app/services/`)
- **Web assets** — Jinja templates in `web/templates/` and static files in `web/static/` (wired in `app/core/templates.py` / `app/app.py`); Python form helpers in `app/forms/`
- **CLI** — admin/ops scripts such as station CSV import (`app/cli/`)
- **Data on disk** — mission CSVs under `data/`; weather/bathy/iridium/slocum/public-map caches under `data_store/`
- **Scheduler** — APScheduler jobs for cache refresh, weekly reports, weather/bathy/iridium/slocum/public-map warm + cleanup (leader only; see [ADR 0001](../decisions/0001-gunicorn-leader-lock.md))
- **Public login map** — optional unauthenticated Leaflet map on `/login.html` (feature toggle `public_login_map`). Only missions with admin `public_map_enabled` **and** listed in `ACTIVE_REALTIME_MISSIONS` / `ACTIVE_SLOCUM_DATASETS` appear. Slocum entries may use short aliases via `SLOCUM_DATASET_ALIAS_MAP_JSON` (same idea as Wave Glider `REMOTE_MISSION_FOLDER_MAP_JSON` mission keys). APIs under `/api/public/*` return lat/lon/timestamp (plus Slocum waypoint); optional gated weekly PDF via `/api/public/reports/.../latest`. Popup labels use shared `resolve_public_mission_labels()` (Sensor Tracker → deployment → telemetry/folder hints) so Wave Glider and Slocum share the same **Platform Name** / **Mission Title** rules. Login UI centers the map in the non-banner viewport (~75% size) with Refresh / Download KML under the map. Disk cache: `data_store/public_map_cache/`; leader job `system_public_map_warm_job`. Distinct from auth token Live KML (`/api/kml/live/{token}`). Ops: [Public login map how-to](./how-tos/public_login_map.md).

## Data flow

```
Remote/local sources → sync (leader) → data/ + data_store caches
                                      ↓
Client → FastAPI routers → core/services → cached telemetry / SQLite → HTML/JSON
```

Typical dashboard path: select mission → load/summarize telemetry from cache (warm on demand if needed) → charts and status widgets. Map overlays (weather, Iridium) use feature toggles and disk caches with TTL/cleanup jobs.

Slocum weekly PDFs (`app/platforms/slocum/reports.py`): Mission Summary includes Distance (period) + Distance (total), Average water depth (prefer filtered `m_water_depth`, else ETOPO 2022 along track), Battery power (pack type + V stats), CTD oceanographic KPIs, and (when DMON review is available) confirmed detection-day tallies per whale species. Telemetry track is colored by SFMC-style surfacing speed (distance ÷ time between depth-detected surfacings; 0–1.1 kt cmocean speed) — the public SFMC Bearer API does not expose Surfacings `speedMap`, so the report reproduces that panel’s formula from the ERDDAP track. A dedicated Battery page follows telemetry: UTC daily Δ of `m_coulomb_amphr_total` (complete-day solid bars + cumulative twin axis; partial days hatched after ΔAh÷hours×24; projection Ah/day prefers complete days) and linear projections to 50/75/90/100% of checklist pack endurance Ah. CTD pages use depth-vs-time cmocean profile scatters with an optional filtered `m_water_depth` bathymetry overlay (rejects ≤0 / `-1` sentinels and local spikes); Dashboard sensors charts are omitted. The DMON Whale detections page adds SFMC `*.asc` offload/gap accounting (dashboard-style, gaps >16h highlighted; listings paginate past SFMC’s 20-file page size and clip to the report window).

### Slocum resolution

Slocum mirror and overage fetches store **full ERDDAP resolution** by default (active and historical). Time thinning for charts/CSV is pilot-controlled via the dashboard **Resample** control (`granularity_minutes`). `slocum_erddap_decimation_minutes` defaults to `0` (ops escape hatch only). CTD/checklist bundles never use ERDDAP time decimation. Dashboard/checklist preprocess use exact+stem column rename so ERDDAP unit suffixes (e.g. `c_heading (rad)`, `m_coulomb_amphr_total (amp hrs)`, digifin/thruster/DMON unit variants) map to chart columns; bump `BUNDLE_SCHEMA_VERSION` when rename/preprocess semantics change so mirrors rebuild (currently **12** for digifin + thruster + DMON byte count). Shared chart toolkit (style, depth overlay, zoom/pan/reset) lives in `web/static/js/chart_*_utils.js` and `_chart_plot_controls.html`. Daily checklist Plot-it and side-by-side compare are documented in [Slocum how-to](./how-tos/slocum.md#daily-pilot-checklist). DMON sensor card (admin-toggled) adds `sci_dmon_msg_byte_count` charts plus SFMC `from-glider` `*.asc` gap checks (left-nav green/red status dot via the same `.ess-indicator` CSS as Wave Glider Waves ESS); Science checklist ASC/gap items appear only when `dmon` is enabled. When `SlocumDeployment.robots4whales_url` is set, a leader job every 12h caches Robots4Whales daily analyst-review HTML under `data_store/dmon_review_cache/` for the DMON dashboard and weekly PDF section ([ADR 0004](../decisions/0004-dmon-robots4whales-review-cache.md)). Optional CLS Argos/Kinéis api-telemetry credentials (`ARGOS_USERNAME` / `ARGOS_PASSWORD`) plus per-deployment `argos_id` (CLS `deviceRef`) drive an on-demand Argos Doppler vs glider GPS separation check on the daily checklist (20 km default; cache under `data_store/argos_cache/`).

## Key files / entry points

| File | Purpose |
|------|---------|
| `app/app.py` | App factory, lifespan, router includes, startup sync/cache |
| `app/config.py` | Settings / env-backed configuration |
| `app/core/platforms/` | Product brand + platform registry |
| `app/platforms/slocum/` | Slocum ERDDAP, mirrors, checklists, deployments |
| `app/core/infra/logging_config.py` | Root logging, request IDs |
| `app/core/data/` | Data service / telemetry loading |
| `app/core/public_map_service.py` | Public login-map allowlist, shared popup labels, bundle cache, static KML |
| `app/core/mission_aliases.py` | Env-backed mission/dataset alias resolution (Slocum + future platforms) |
| `app/routers/public_map.py` | Unauthenticated `/api/public/map/*` + report gate |
| `web/templates/login.html` / `web/static/js/public_map.js` | Public login map UI (centered map, bottom toolbar) |
| `AGENTS.md` | Ops runbook (gunicorn, logging, cache inventory) |

## Things that look wrong but aren't

- **No gunicorn `--preload`** — torch, ChromaDB, SQLite, and APScheduler do not play well with preload; see [ADR 0002](../decisions/0002-no-gunicorn-preload.md) and `AGENTS.md`.
- **Only one worker runs sync/scheduler** — leader lock on `data_store/.app_leader.lock`; the other worker serves HTTP only; see [ADR 0001](../decisions/0001-gunicorn-leader-lock.md).
- **`os.replace` failures on NFS/SELinux** — copy fallback is intentional; stranded `*.tmp` are cleaned by scheduled jobs.
- **Admin scheduler status empty on non-leader** — scheduler lives on the leader worker only.
- **Slocum long windows look dense** — overage/mirror are full-res; sparse charts mean the sensor or UI Resample, not automatic >48h ERDDAP decimation.
- **Wave Glider has no `{id}_platform` feature toggle** — WG remains always-on; Slocum (and future platforms) use `{id}_platform`.
