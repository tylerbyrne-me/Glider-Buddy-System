# Architecture

_Last updated: 2026-08-31_

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
- **Sensor Tracker instruments** — sync stores `MissionInstrument` + nested `MissionSensor` in SQLite. Mission/deployment info APIs and home briefing load them via `app/core/mission_instruments.py` (`selectinload`). UI lists (dashboards, admin overviews, home) show nested sensors under each instrument when present; weekly reports use the same DB rows.
- **UI preferences** — `users.ui_preferences` JSON (`theme_mode`, `accent`, `platform_accents`, `density`, `map_style`) on `GET`/`PUT /api/users/me`. Client: `web/static/js/ui_preferences.js` + User Settings Appearance (General vs Platform accents). Platform pages set `data-platform` on `<html>`; accent resolves override → general. Theme CSS/JS load with `?v={{ app_version }}` (mtime token includes `themes.css` / `ui_preferences.js`). Org-wide defaults not implemented yet.
- **Mission reports** — PDF builders in `app/core/reporting/` (Wave Glider) and `app/platforms/slocum/reports.py` (Slocum). Automated weekly jobs use default options (goals + `include_in_report` comments only). User-generated reports may pass ephemeral `expanded_notes` that render as **Additional notes** after the Mission details “Publication, attribution, and data” table (not stored in-app). Dashboard Mission Overview shows only the latest PDF per type via persisted URLs (`MissionOverview.weekly_report_url` / `end_of_mission_report_url` for WG; `SlocumDeployment` equivalents for Slocum) — not a full on-disk listing. Slocum EOM generation is still open (column ready; weekly generation already writes `weekly_report_url`).
- **Outlier suppress (|z| > 2.5)** — display/report only; never mutates mirror/ERDDAP. Shared helpers: `suppress_zscore_outliers` / `prepare_report_numeric_frame` in `app/core/data/processors.py`, and `maskOutlierPointsByZScore` / `maskScatterByValueZScore` in `chart_time_series_utils.js`. Dashboard: optional “Hide outliers” toggle beside Resample (off by default; re-renders from cache). WG time-series cards and Slocum `TIME_SERIES_CARD_CONFIGS` series inherit via render helpers; Slocum CTD depth-vs-time profile scatters mask on measurement value (`v`), not depth axis. Reports: automated on applicable KPI means and time-series plot frames; Slocum weekly CTD summary KPIs (Temperature / Salinity / Density) and CTD profile pages use the same z-score helper; flagged KPI values get a subtle `*` plus Caption footnote `* Outliers suppressed (|z| > 2.5)`. Skips circular/geo fields. New sensors: add series to declarative configs — outlier hook is automatic unless the field is in the skip list (see [conventions — Outlier suppress](./conventions.md#outlier-suppress)).
- **Web assets** — Jinja templates in `web/templates/` and static files in `web/static/` (wired in `app/core/templates.py` / `app/app.py`); Python form helpers in `app/forms/`. Prefer `?v={{ app_version }}` on mutable CSS/JS (see [conventions — Theme tokens](./conventions.md#theme-tokens)).
- **Submitted forms** — All platforms write to shared SQLite `submitted_forms` (`SubmittedForm`: PIC handoff, pre-deployment, Slocum daily checklist). List APIs return summary rows only (no `sections_data`) with interactive windows (mission PIC / Slocum checklist default **7 days**); detail/edit fetch full JSON by id. Helpers: `app/core/forms/submission_queries.py`. Policy: [FORM_SUBMISSION_POLICIES.md](./standards/FORM_SUBMISSION_POLICIES.md); ADR [0006](../decisions/0006-form-submission-retention-windows.md).
- **CLI** — admin/ops scripts such as station CSV import (`app/cli/`)
- **Team** — platform-agnostic admin sandbox at `/team` (feature toggle `team_hub`; `can_access_*` platform ACLs do not apply). Parallel to WG/Slocum, not a `PlatformSpec`. In-area title is *Team Glider Buddy System* (same modifier rule as Slocum). Entry is a second-row card on `/platform`; Team pages use the product banner (Team + Platform links). Admins still see the chooser even if they have only one vehicle platform. Ops catalog (`app/services/team_ops_catalog.py`, `app/routers/team.py`) mixes zero-arg `kind=run` scripts (`check_mission_files`, mission catalog dry-run) and `kind=page` form tools: SFMC log-note import (in-process note create; no CLI HTTP loopback), Wave Glider telemetry hexbin (sync generate; WGMS and/or ERDDAP via `source_filter`; cache `data_store/team_hexbin_cache/`, PNG `data_store/team_hexbin_outputs/`; mission/time caps — large runs can still hit gunicorn `--timeout 200`), a live read-only **Sensor Tracker browser** (`/team/sensor-tracker`, `app/services/sensor_tracker_query.py`) that queries Tracker REST directly (paginated search/detail/relations; list search is substring via Tracker `search=` plus a local scan; `/api/sensor/` ignores `search=` so Buddy uses exact `identifier=` then a `sensor_on_instrument` scan, never the 235k catalog; `/api/deployment/` ignores `search=`/`title=` (~1k rows) so Buddy tries `platform_name=` then a full list scan so unnumbered/dateless titles remain findable; list pages follow Tracker `next` then slice in Buddy; optional logger/component tabs hide on 404; related lists default to currently attached / no end date, open rows first; sensors expose related Instruments via `sensor_on_instrument`; loggers/instruments/sensors also climb to Platforms/Deployments, instruments to parent Loggers). Detail loads live **service time** (`sensor_tracker_analytics.py`: days at sea / current deployment / attached / shelf from Tracker windows, including logger-mounted instruments, sensors via `current_instrument`, and components via `component_on_platform`; calibration/lifetime not yet). Deployment detail may overlay local `SensorTrackerDeployment` sync status; it does not write to Tracker or replace mission-sync cache (`sensor_tracker_service` / admin overviews). **Visualizations gallery** (`/team/visualizations`, `app/services/team_visualizations.py`): named static matplotlib PNGs from a Sensor Tracker fleet snapshot (`data_store/team_viz_cache/`, `data_store/team_viz_outputs/{slug}/`); explicit Rebuild (UI or `python -m app.cli.team_visualizations`); GET never contacts Tracker. **Mission catalog** unmatched ERDDAP review (`/team/mission-catalog`, read-only). **VMT log book** (`/team/vmt-logbook`, `app/services/team_vmt_logbook.py`): SQLite inventory for Vemco Mobile Transceivers (battery/service history, manual add, ST sync for `identifier=vmt` instruments; local rows retained if ST linkage is lost; detail ST accounting reuses sensor-tracker analytics/attachment helpers). Ops: [Sensor Tracker Team browser](./how-tos/sensor_tracker_team_browser.md), [Team Visualizations](./how-tos/team_visualizations.md), [VMT log book](./how-tos/vmt_logbook.md). Not a home for per-platform Admin Management.
- **Mission catalog** — source-neutral **index** in SQLite (`catalog_platforms`, `catalog_missions`, `catalog_external_identities`, `catalog_mission_sources`) under feature toggle `mission_catalog`. Catalog UUIDs never replace live `mission_id` / Slocum `mission_key` / disk paths; nullable `catalog_mission_id` links existing rows only. Sensor Tracker (allowlisted Platforms models) is the sole lifecycle authority for start/end dates and `operational_state`; ERDDAP / WGMS / legacy `.env` attach sources and may seed enrollment (`config/mission_data_providers.json`, `lifecycle_authority` on ST). Preemptive ST deployments without `deployment_number` stay `PLANNED` / `CATALOG_ONLY`. Enrollment is `sync_policy=CONTINUOUS` (preserved while ACTIVE; `ON_DEMAND` on completion). Reconciliation: `app/core/mission_catalog/` + `app/services/mission_catalog_sync.py`. Leader job `system_mission_catalog_sync_job` and startup sync default to **dry-run** until `MISSION_CATALOG_AUTO_APPLY=true` (after identity gate report is clean). CLI: `python -m app.cli.mission_catalog_sync --dry-run|--apply` (apply refused if gates unclean). Live-link prefers Wave Glider `m###-SV3-####` overviews over bare `m###` / legacy `####-m###`, and only active Slocum briefing rows. Enablement uses exact `.env` key strings when `ACTIVE_*` lists are non-empty (override); when empty, derives keys from catalog `ACTIVE` ∧ `CONTINUOUS` (WG needs realtime WGMS source + linked overview; Slocum needs linked `is_active` deployment) — never the full ST inventory. Optional `MISSION_CATALOG_WG_SYNC_FROM_CATALOG` / `MISSION_CATALOG_SLOCUM_WARM_FROM_CATALOG` / `MISSION_CATALOG_PUBLIC_MAP_FROM_CATALOG` plus `app.py` startup cache / refresh / weekly reports route through that API. Team `/team/mission-catalog` is a read-only unmatched ERDDAP review page. Overview PK merge CLI: `python -m app.cli.merge_overview_pk_duplicates`. Ops: [mission catalog cutover](./how-tos/mission_catalog_cutover.md). ADR: [0005](../decisions/0005-mission-catalog-live-keys.md). Generic tabledap helper: `app/core/data/erddap_tabledap.py`.

- **Data on disk** — mission CSVs under `data/`; weather/bathy/iridium/slocum/public-map caches under `data_store/`; static vector map GeoJSON under `config/map_layers/`
- **Scheduler** — APScheduler jobs for cache refresh, weekly reports, weather/bathy/iridium/slocum/public-map warm + cleanup, Slocum ERDDAP poke, and mission catalog reconciliation (leader only; see [ADR 0001](../decisions/0001-gunicorn-leader-lock.md))
- **Public login map** — optional unauthenticated Leaflet map on `/login.html` (feature toggle `public_login_map`). Only missions with admin `public_map_enabled` **and** in the enablement membership set appear (`ACTIVE_*` when non-empty, else enrolled ACTIVE∧CONTINUOUS keys when `MISSION_CATALOG_PUBLIC_MAP_FROM_CATALOG` is on). Slocum entries may use short aliases via `SLOCUM_DATASET_ALIAS_MAP_JSON` (same idea as Wave Glider `REMOTE_MISSION_FOLDER_MAP_JSON` mission keys). APIs under `/api/public/*` return lat/lon/timestamp (plus Slocum waypoint); optional gated weekly PDF via `/api/public/reports/.../latest`. Popup labels use shared `resolve_public_mission_labels()` (Sensor Tracker → deployment → telemetry/folder hints) so Wave Glider and Slocum share the same **Platform Name** / **Mission Title** rules. Login UI centers the map in the non-banner viewport (~75% size) with Refresh / Download KML under the map. Disk cache: `data_store/public_map_cache/`; leader job `system_public_map_warm_job`. Distinct from auth token Live KML (`/api/kml/live/{token}`). Ops: [Public login map how-to](./how-tos/public_login_map.md).

## Data flow

```
Remote/local sources → sync (leader) → data/ + data_store caches
                                      ↓
Client → FastAPI routers → core/services → cached telemetry / SQLite → HTML/JSON
```

Typical dashboard path: select mission → load/summarize telemetry from cache (warm on demand if needed) → charts and status widgets. Map overlays (weather, Iridium, NAVWARN, AIS vessel density, CIOPS-East ice, static vector zones) use feature toggles; weather/Iridium/NAVWARN/vessel-density/CIOPS ice use `data_store/` caches with TTL, while reference GeoJSON lives under git-tracked `config/map_layers/`.

### Static vector map layers

Toggleable Leaflet polygons (GOSL zones, DFO LFAs/FMAs, NOAA shipping lanes) for home maps on all platforms (`map_vector_layers` feature toggle; catalog-driven toggles). Ops how-to: [map_vector_layers.md](./how-tos/map_vector_layers.md).

- **On disk** — [`config/map_layers/`](../../config/map_layers/): `manifest.json`, `published/*.geojson`, optional `sources/` (KML + ArcGIS fetch metadata; git-tracked; convert/fetch locally, deploy via git — prod does not re-ingest at runtime)
- **Ingest** — [`scripts/convert_map_layer_kml.py`](../../scripts/convert_map_layer_kml.py) (KML) and [`scripts/fetch_map_layer_arcgis.py`](../../scripts/fetch_map_layer_arcgis.py) (ArcGIS REST Feature Layer → GeoJSON snapshot); publish under `config/map_layers/`
- **API** — `GET /api/map/layers` (catalog), `GET /api/map/layers/{id}` (GeoJSON + ETag); gated by `map_vector_layers`
- **Client** — [`web/static/js/vector_map_layer.js`](../../web/static/js/vector_map_layer.js) on WG/Slocum home maps via `map_generator.js` (catalog-driven toggles; pane under tracks)
- **Shipped overlays** — GOSL DSZ/safe zones; DFO lobster LFAs; DFO Atlantic FMAs (crab, snow crab, scallop, capelin, mackerel, herring, squid, salmon, northern shrimp); NOAA NW Atlantic shipping lanes
- **Not yet** — public login map overlays; PDF report maps (`plot_telemetry_page_with_notes`); per-mission `default_on` / “always show”; fishery notices/openings linked to FMA polygons (see [backlog](../tasks/backlog.md))

### AIS vessel density map layer

Toggleable DFO NW Atlantic AIS vessel-density rasters (2025 monthly, all vessel types) for home maps (`vessel_density_map_layer` feature toggle). Ops how-to: [vessel_density_map_layer.md](./how-tos/vessel_density_map_layer.md).

- **Upstream** — egisp MapServer raster layers 7–18 (live `export`, not GeoJSON snapshots)
- **Cache** — short-TTL PNG tile cache under `data_store/vessel_density_cache/`
- **API** — `GET /api/map/vessel-density/meta|export`; gated by `vessel_density_map_layer`
- **Client** — [`web/static/js/vessel_density_map_layer.js`](../../web/static/js/vessel_density_map_layer.js) (parent toggle + exclusive month radios; pane z-index 340)
- **Not yet** — yearly vessel-class rasters (layers 1–6); opacity slider; public login map

### CIOPS-East ice forecast map layer

Toggleable MSC GeoMet CIOPS-East sea ice area fraction (48 h hourly forecast) for home maps (`ciops_ice_map_layer` feature toggle). Ops how-to: [ciops_ice_map_layer.md](./how-tos/ciops_ice_map_layer.md).

- **Upstream** — GeoMet WMS `CIOPS-East_2km_SeaIceAreaFraction` (live GetMap, not GeoJSON snapshots)
- **Cache** — short-TTL PNG tile cache under `data_store/ciops_ice_cache/`; GetCapabilities in-memory (~10 min)
- **API** — `GET /api/map/ciops-ice/meta|export|legend`; gated by `ciops_ice_map_layer`
- **Client** — [`web/static/js/ciops_ice_map_layer.js`](../../web/static/js/ciops_ice_map_layer.js) (parent toggle + hourly time slider; pane z-index 345)
- **Not yet** — winter visual soak / empty-vs-broken UX; CIOPS-West; GetFeatureInfo; style picker; public login map; cache cleanup job

### NAVWARN map layer

Toggleable CCG navigational-warning overlays for home maps (`navwarn_map_layer` feature toggle). Ops how-to: [navwarn_map_layer.md](./how-tos/navwarn_map_layer.md).

- **Upstream** — HTML scrape of `nis.ccg-gcc.gc.ca` (no public JSON search API); active message geometries + area reference polygons
- **Cache** — `data_store/navwarn_cache/` (`active_warnings.geojson`, `areas.geojson`, rate-limit gate); 30 min incremental (page 1) prefetch + daily catalog reconcile
- **API** — `GET /api/map/navwarn/active|areas` (GeoJSON + ETag), cache status/purge; gated by `navwarn_map_layer`
- **Client** — [`web/static/js/navwarn_map_layer.js`](../../web/static/js/navwarn_map_layer.js) on WG/Slocum home maps (pane z-index 360). Per-message hide/restore (localStorage) for overlapping active geometries; `POLYLINE` / `LineString` features share polygon popups plus a wide hit target
- **Not yet** — public login map; radius circles (units unconfirmed); catalog-driven toggles
### Dashboard summary soft refresh

Left-nav summary cards, mini-trends, and detail “Last data” footers must stay on the same freshness path as main charts. Both platforms soft-refresh on cache advance (no full page reload as the primary path):

| Platform | Cache status | Summaries API | Builder | Client |
|----------|--------------|---------------|---------|--------|
| Wave Glider | `/api/cache-status/{mission}` | `/api/wave_glider/sensor-summaries/{mission}` → `/api/sensor-summaries/{mission}` | `app/platforms/wave_glider/summaries.py` | `web/static/js/dashboard.js` |
| Slocum | `/api/slocum/cache-status/{dataset}` | `/api/slocum/sensor-summaries/{dataset}` | `app/platforms/slocum/summaries.py` | `web/static/js/slocum_dashboard.js` |

Shared card JSON shape: `{values, latest_timestamp_str, time_ago_str, mini_trend}` (WG waves may add `ess_state`). SSR and the JSON API use the same builder. Chart fetches may also update detail footers from `cache_metadata.last_data_timestamp`.

**New platform checklist:** package builder → `/api/{id}/sensor-summaries/...` → poll cache → refresh charts + cards (reuse `mini_charts.js`). Card HTML formatting stays platform-specific until a shared formatter exists. Convention: [conventions](./conventions.md#patterns-to-follow).

Slocum weekly PDFs (`app/platforms/slocum/reports.py`): Mission Summary includes Distance (period) + Distance (total), Average water depth (prefer filtered `m_water_depth`, else ETOPO 2022 along track), Battery power (pack type + V stats), CTD oceanographic KPIs, and (when DMON review is available) confirmed detection-day tallies per whale species. Telemetry track is colored by SFMC-style surfacing speed (distance ÷ time between depth-detected surfacings; 0–1.1 kt cmocean speed) — the public SFMC Bearer API does not expose Surfacings `speedMap`, so the report reproduces that panel’s formula from the ERDDAP track. A dedicated Battery page follows telemetry: UTC daily Δ of `m_coulomb_amphr_total` (complete-day solid bars + cumulative twin axis; partial days hatched after ΔAh÷hours×24; projection Ah/day prefers complete days) and linear projections to 50/75/90/100% of checklist pack endurance Ah. CTD pages use depth-vs-time cmocean profile scatters with an optional filtered `m_water_depth` bathymetry overlay (rejects ≤0 / `-1` sentinels and local spikes); Dashboard sensors charts are omitted. The DMON Whale detections page adds SFMC `*.asc` offload/gap accounting (dashboard-style, gaps >16h highlighted; listings paginate past SFMC’s 20-file page size and clip to the report window) plus thruster Yes/No per interval from full-window dashboard telemetry (≤3 m surface bursts excluded; Yes shows estimated on-time and depth range).

### Slocum resolution

Slocum mirror and overage fetches store **full ERDDAP resolution** by default (active and historical). After startup warm, the leader job `slocum_erddap_poke_job` (default every 90 min) queries Ocean Track `allDatasets` `maxTime` and runs an incremental mirror sync only when a dataset tail advanced — glider→SFMC is ~every 4–8h and ERDDAP processes new files ~every 3h, so Buddy no longer full-pulls on the Wave Glider 60-minute cache cadence. Admin **Check ERDDAP now** on Manage Slocum Mission Overviews is the same poke. Wave Glider realtime stays on WGMS folders; when it lands on ERDDAP, share the probe and keep a WG-owned refresh — [erddap_poke.md](./how-tos/erddap_poke.md). Interactive reads prefer the rolling 72h disk mirror (partial overlap with `stale` metadata — last sample behind wall-clock now, **not** an outage) over a live ERDDAP round-trip when the mirror already covers part of the window; ERDDAP outages therefore keep charts/maps populated from `data_store/slocum_cache/` instead of blanking (`fallback_error` is set only when a live fetch failed). Report jobs (`context="report"`) skip that shortcut and fetch the full requested window via overage/ERDDAP so weekly PDFs (including DMON thruster columns) are not clipped to the 72h mirror. Time thinning for charts/CSV is pilot-controlled via the dashboard **Resample** control (`granularity_minutes`). `slocum_erddap_decimation_minutes` defaults to `0` (ops escape hatch only). CTD/checklist bundles never use ERDDAP time decimation. Dashboard/checklist preprocess use exact+stem column rename so ERDDAP unit suffixes (e.g. `c_heading (rad)`, `m_coulomb_amphr_total (amp hrs)`, digifin/thruster/DMON unit variants) map to chart columns; bump `BUNDLE_SCHEMA_VERSION` when rename/preprocess semantics change so mirrors rebuild (currently **14** for digifin + thruster + DMON + `m_gps_status` invalid-fix masking + implausible track-speed filtering). Shared chart toolkit (style, depth overlay, zoom/pan/reset) lives in `web/static/js/chart_*_utils.js` and `_chart_plot_controls.html`. Daily checklist Plot-it and side-by-side compare are documented in [Slocum how-to](./how-tos/slocum.md#daily-pilot-checklist). DMON sensor card (admin-toggled) adds `sci_dmon_msg_byte_count` charts plus SFMC `from-glider` `*.asc` gap checks (left-nav green/red status dot via the same `.ess-indicator` CSS as Wave Glider Waves ESS); Science checklist ASC/gap items appear only when `dmon` is enabled. When `SlocumDeployment.robots4whales_url` is set, a leader job every 12h caches Robots4Whales daily analyst-review HTML under `data_store/dmon_review_cache/` for the DMON dashboard and weekly PDF section ([ADR 0004](../decisions/0004-dmon-robots4whales-review-cache.md)). Optional CLS Argos/Kinéis api-telemetry credentials (`ARGOS_USERNAME` / `ARGOS_PASSWORD`) plus per-deployment `argos_id` (CLS `deviceRef`) drive an on-demand Argos Doppler vs glider GPS separation check on the daily checklist (20 km default; cache under `data_store/argos_cache/`).

## Key files / entry points

| File | Purpose |
|------|---------|
| `app/app.py` | App factory, lifespan, router includes, startup sync/cache |
| `app/config.py` | Settings / env-backed configuration |
| `app/core/platforms/` | Product brand + platform registry |
| `app/platforms/slocum/` | Slocum ERDDAP, mirrors, checklists, deployments |
| `app/platforms/wave_glider/summaries.py` | WG left-nav sensor summaries (SSR + soft-refresh API) |
| `app/routers/wave_glider.py` | WG APIs under `/api/...` (also via `/api/wave_glider/...` alias) |
| `app/core/infra/logging_config.py` | Root logging, request IDs |
| `app/core/data/` | Data service / telemetry loading |
| `app/core/public_map_service.py` | Public login-map allowlist, shared popup labels, bundle cache, static KML |
| `app/core/geo/map_layers.py` | Static vector layer catalog + GeoJSON reads (`config/map_layers/`) |
| `app/core/geo/vessel_density.py` | DFO AIS vessel-density MapServer export proxy + tile cache |
| `app/core/geo/ciops_ice.py` | MSC GeoMet CIOPS-East sea-ice WMS proxy + tile cache |
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
