# Slocum Glider integration

Slocum glider data is served via ERDDAP (Ocean Track). This document describes how Slocum is integrated into the project and how to use it.

## Configuration

- **`slocum_erddap_server`** (config / `.env`): ERDDAP base URL. Default: `https://erddap.oceantrack.org/erddap`. Override with `slocum_erddap_server` in `.env` if needed.
- **Feature toggle** `slocum_platform`: In `feature_toggles_json` (or `.env`), set `"slocum_platform": true` to enable Slocum API and map endpoints. When `false`, Slocum endpoints return 403.

## Public login map

Shared for Wave Glider and Slocum — see **[Public login map](./public_login_map.md)**.

Quick Slocum path:

1. Ensure the dataset is in `ACTIVE_SLOCUM_DATASETS` (alias keys OK).
2. On **Manage Slocum Mission Overviews**, enable **Show on public map** (optional: **Show latest weekly report**).
3. Set `"public_login_map": true` in feature toggles.

Public labels prefer Sensor Tracker platform name / mission title (not dataset aliases). Static KML is on the login map; live/network KML remains authenticated.

## Mission dashboard

Active/historical mission dashboards (`/slocum/...`) show overview plus optional sensor cards (admin-configured per deployment). Chart cards share a time toolbar (hours / UTC range / resample / download) and per-chart toolkit: plot style, **Show depth** background overlay (`m_depth`), Ctrl+scroll zoom, pan, and Reset zoom.

Left-nav summary cards soft-refresh via `GET /api/slocum/sensor-summaries/{dataset_id}` when mirror cache `last_data_timestamp` advances (same pattern as Wave Glider — see [architecture](../architecture.md#dashboard-summary-soft-refresh)).

| Card | Notable series |
|------|----------------|
| CTD | Depth-vs-time profiles (temp / conductivity / density) with optional vehicle-depth overlay |
| Power | Battery, coulomb AmpHr (daily + total), BMS currents |
| Flight | Pitch / fin (measured vs commanded); **roll measured only** (no commanded roll); **thruster** power (W) + commanded on (%) on dual axes |
| Navigation | Heading, depth rate, depth/altimeter, speed, depth-averaged currents |
| Vehicle Health | Vacuum; leak detect channels (main / forward / science) with **digifin** on a secondary Y axis; SFMC call length |
| Dissolved Oxygen | Placeholder charts (data wiring TBD) |
| DMON | `sci_dmon_msg_byte_count` over time; SFMC `from-glider` `*.asc` files (last 48h) with >16h gap highlight and **Thruster since prev** Yes/No from dashboard `m_thruster_power` / `c_thruster_on` over each `[prev_mtime, this_mtime)` interval; left-nav green/red status dot (same style as Wave Glider Waves ESS); **Robots4Whales daily analyst review** (last 48h table + full-history collapse) when `robots4whales_url` is set on the deployment |

### Data path

Dashboard charts load from the rolling **dashboard** mirror under `data_store/slocum_cache/` (with overage cache for windows the mirror does not fully cover). After startup warm, a leader **ERDDAP poke** (`slocum_erddap_poke_job`, default every 90 min via `SLOCUM_ERDDAP_POKE_INTERVAL_MINUTES`) reads `allDatasets` `maxTime` and only then incremental-syncs when Ocean Track’s tail advanced. Admin **Check ERDDAP now** on Manage Slocum Mission Overviews runs the same poke for the selected dataset. Wave Glider realtime is not on ERDDAP yet — future split is in [erddap_poke.md](./erddap_poke.md). Variables must be present in:

1. `SLOCUM_DASHBOARD_VARIABLES` ([`app/platforms/slocum/erddap_client.py`](../../app/platforms/slocum/erddap_client.py))
2. Dashboard rename/stems + `preprocess_slocum_dashboard_df` std columns ([`app/core/data/processors.py`](../../app/core/data/processors.py))
3. Chart allowlists in [`app/routers/slocum.py`](../../app/routers/slocum.py) (`_SLOCUM_VARIABLE_TO_COLUMN`, `_SLOCUM_CHART_VARIABLES`, CSV header)

When preprocess/schema columns change, bump `BUNDLE_SCHEMA_VERSION` in [`app/platforms/slocum/bundle_registry.py`](../../app/platforms/slocum/bundle_registry.py) so mirrors rebuild. Current schema is **14** (includes digifin/thruster/DMON, `m_gps_status` invalid-fix masking, and implausible track-speed filtering from trusted GPS anchors). After deploy, wait for leader sync or force an admin mirror rebuild if new series stay empty.

Shared chart UI helpers: `web/static/js/chart_*_utils.js`, `_chart_plot_controls.html`, `_chart_zoom_scripts.html`.

## Daily Pilot Checklist

Per-mission daily checklist (`/slocum/dataset/{dataset_id}/checklist.html`, also the dashboard **Checklist** tab).

### Autofill and Plot-it

- Schema: [`app/platforms/slocum/checklist_definitions.py`](../../app/platforms/slocum/checklist_definitions.py)
- Autofill / Plot-it registry: [`app/platforms/slocum/checklist_autofill.py`](../../app/platforms/slocum/checklist_autofill.py) (`CHECKLIST_PLOTTABLE_ITEMS`, `build_checklist_series_payload`)
- Checklist ERDDAP wishlist includes digifin leak detect, thruster, and `sci_dmon_msg_byte_count`; preprocess via checklist rename/std columns
- Plot modal (`web/static/js/slocum_checklist_form.js`): depth on left (`y`); value series on `y2`; digifin / thruster % on `y3` when needed
- Plottable autofill rows include vacuum/attitude/buoyancy (legacy), plus **water depth**, **BMS currents**, **leak channels** (main/forward/science/digifin), combined **thruster** (`m_thruster_power` / `c_thruster_on`), and **DMON** `sci_dmon_msg_byte_count` when the DMON sensor card is enabled
- **DMON gating:** Science items `dmon_msg_byte_count_val`, `dmon_asc_files_val`, and `asc_gap_check_val` appear only when `dmon` is in `SlocumDeployment.enabled_sensor_cards` (Manage Slocum Mission Overviews). The ASC list comes from the SFMC snapshot (`from-glider` `*.asc`, last 48h) and highlights gaps >16h since the newest file (and inter-file gaps >16h). Runtime injection: `apply_dmon_science_checklist_items` in [`checklist_autofill.py`](../../app/platforms/slocum/checklist_autofill.py)
- **Argos vs GPS:** Set admin checklist reference `argos_id` to the CLS api-telemetry `deviceRef`. With `ARGOS_USERNAME` / `ARGOS_PASSWORD` in `.env`, autofill loads the latest Doppler fix (cached under `data_store/argos_cache/`, 30 min TTL) and compares it to the latest glider GPS (`m_gps_*` preferred). Item `argos_gps_check_val` shows distance · OK/REVIEW (20 km default); `argos_monitor_val` is pre-suggested Yes / No / N/A. Access test: `python scripts/test_argos_access.py --device-ref <id>` (optional `--gps-lat` / `--gps-lon`). **Live on prod 2026-09-03** (M2M credentials confirmed). Optional later: leader prefetch job (medium backlog).
- **Robots4Whales detections:** Set `robots4whales_url` on the same admin page (must be a `dcs.whoi.edu` `*.shtml` deployment page). Leader job `system_dmon_review_prefetch_job` refreshes every 12h into `data_store/dmon_review_cache/`. Dashboard shows last-48h review + full history collapse with site attribution; weekly PDFs include a date-filtered analyst-review table (`styled_data_table`, Detected/Possibly color fills) and Analysts in the footnote ([ADR 0004](../../decisions/0004-dmon-robots4whales-review-cache.md)).
- Series API: `GET /api/slocum/checklists/{dataset_id}/series?item_id=...`

### Side-by-side compare

- Dashboard Checklist tab → **Compare** (needs ≥2 submissions)
- Locked **reference** on the right; navigable prior submission on the left (past → present)
- Value diffs via `GET /api/slocum/checklists/compare`; toggles for changed-only (default on) and include notes
- Core: [`app/platforms/slocum/checklist_compare.py`](../../app/platforms/slocum/checklist_compare.py); UI: `web/static/js/slocum_checklist_compare.js`

## Weekly PDF reports

Generated via [`app/platforms/slocum/reports.py`](../../app/platforms/slocum/reports.py) (default last-7-day window). Notable content polish:

| Section | Behavior |
|---------|----------|
| Mission summary | Period + total distance; average water depth (`m_water_depth` / ETOPO); battery pack + V stats; CTD KPIs; DMON confirmed detection-day tallies |
| Telemetry | Continuous track colored by SFMC-style surfacing SOG (0–1.1 kt); dynamic vmax still backlog |
| Mission notes | Letter-keyed notes matched to the telemetry track (immediately after Telemetry) |
| Battery | Daily Ah bars from `m_coulomb_amphr_total` (partial days rate-normalized / hatched); projections to 50/75/90/100% of checklist pack endurance |
| CTD | Depth-vs-time cmocean profiles; optional filtered water-depth overlay |
| DMON | Analyst-review table + ASC offloads for the **full report window** (SFMC listings paginated; inter-file gaps >16h highlighted; thruster Yes/No per interval since previous `*.asc`; no live “hours since last” banner — [BUG-002](../../bugs/BUG-002-dmon-asc-gap-hours-since-last.md)) |

Helpers: [`battery_report.py`](../../app/platforms/slocum/battery_report.py), [`sfmc_client.fetch_dmon_asc_files`](../../app/core/sfmc_client.py).

## API

All Slocum endpoints require authentication (same as Wave Glider). When `slocum_platform` is disabled, Slocum routes return 403.

| Endpoint | Purpose |
|----------|--------|
| `GET /api/exploration/slocum/data?dataset_id=...&time_start=...&time_end=...` | Fetch raw ERDDAP data as JSON (testing; capped at 10k rows). |
| `GET /api/map/slocum/telemetry/{dataset_id}?hours_back=72` or `?time_start=...&time_end=...` | Track points for map display. Same response shape as Wave Glider `GET /api/map/telemetry/{mission_id}`: `track_points`, `point_count`, `bounds`, `source`. |
| `GET /api/slocum/chart-data-bulk/{dataset_id}?variables=...` | Multi-variable dashboard chart series (mirror / overage). |
| `GET /api/slocum/profile-data/{dataset_id}` | CTD depth-vs-time profile points (+ optional `depth_overlay` from dashboard `m_depth`). |
| `GET /api/slocum/sfmc/connection-durations/{dataset_id}` | Cached SFMC surface-call durations (Vehicle Health). |
| `GET /api/slocum/sfmc/dmon-asc-files/{dataset_id}` | Cached SFMC `from-glider` `*.asc` listing + gap flags; enriches each file with `thruster_since_prev` from the 48h dashboard mirror (DMON card). |
| `GET /api/slocum/dmon/review/{dataset_id}?recent_hours=48` | Cached Robots4Whales daily analyst-review detections (`recent` / `all`, site attribution; optional `start_date`/`end_date` ISO for reports). |
| `PUT /api/slocum/deployments/{id}/robots4whales-url` | Admin: set/clear deployment page URL (`dcs.whoi.edu` `*.shtml`). |
| `GET /api/slocum/checklists/{dataset_id}/series?item_id=...` | Checklist Plot-it time series (depth + value / multi-series). |
| `GET /api/slocum/checklists/compare?reference_id=&other_id=` | Form-to-form checklist diff (`changed_item_ids`). |
| `POST /api/slocum/erddap-poke` | Admin: cheap `allDatasets` maxTime poke (`dataset_id` optional; `sync_if_new` default true). |

Dataset ID format: `{glider}_{YYYYMMDD}_{mission_id}_{realtime|delayed}` (e.g. `peggy_20250522_206_delayed`). The map endpoint returns points with `lat`, `lon`, `timestamp` for use with existing map/KML tools.

### Map / track GPS quality

Slocum map tracks are derived from the **dashboard** mirror (`latitude` / `longitude`), not a dedicated ERDDAP track pull. Before points reach the map (also KML, public map, weekly report track), preprocess / `dashboard_df_to_track_df` apply:

1. Null-island `(0,0)` mask
2. `m_gps_status` suppress for `{2, 3, -2}` (invalid fix / wrong sentence / best-guess invalid); keep `0`, `1`, `-1`
3. Implausible-speed filter: only `m_gps_status == 0` advances the trusted anchor; intermediate (usually NaN-status) points implying **>3 kt** over **≥1 nm** are dropped; a later status-0 snap-back is kept

`m_gps_status` is sparse in OceanTrack (often only on GPS sentence events), so step 3 is required for dead-reckoned outliers (see [BUG-005](../../bugs/BUG-005-slocum-invalid-gps-status-track-points.md)). Schema **14** includes these preprocess semantics.

## CLI

From project root with WorkPython:

```bash
conda activate WorkPython
python -m app.platforms.slocum.cli --dataset peggy_20250522_206_delayed --start 2025-08-01 --end 2025-08-31 --output my_slocum.csv
python -m app.platforms.slocum.cli --summary-only
```

The exploration script `exploration/slocum_erddap/fetch_sample.py` also uses the same app client; run it from project root so `app` is importable.

## Code layout

- **`app/platforms/slocum/erddap_client.py`**: ERDDAP fetch (sync). Used by routers and CLI. Reads server URL from config. Bundle variable wishlists (`SLOCUM_DASHBOARD_VARIABLES`, CTD, checklist).
- **`app/core/data/processors.py`**: `preprocess_slocum_dashboard_df` / CTD / track / checklist normalize ERDDAP columns for parquet and charts.
- **`app/platforms/slocum/bundle_registry.py`**: Bundle specs + `BUNDLE_SCHEMA_VERSION`.
- **`app/platforms/slocum/mirror_service.py`** / **`overage_cache.py`**: Rolling mirror and temporary overage windows.
- **`app/platforms/slocum/erddap_poke.py`**: Cheap allDatasets maxTime poke; scheduled job + admin Check ERDDAP now.
- **`app/routers/slocum.py`**: Mission dashboard chart/CSV/profile APIs; SFMC connection-durations + DMON ASC listing endpoints.
- **`app/routers/slocum_checklists.py`**: Daily checklist template/submit/series/compare APIs and form page.
- **`app/platforms/slocum/checklist_autofill.py`** / **`checklist_compare.py`** / **`checklist_definitions.py`**: Autofill, Plot-it payloads, DMON Science-item gating, form-to-form diff, static checklist schema.
- **`app/platforms/slocum/summaries.py`** / **`reports.py`** / **`battery_report.py`** / **`masterdata_service.py`**: Sensor-card summaries, weekly PDF reports (incl. Battery Ah page + SFMC-style SOG track), KB masterdata vectorization.
- **`app/core/sfmc_client.py`** / **`sfmc_transforms.py`** / **`sfmc_cache_service.py`**: SFMC HTTP, paginated `*.asc` listing + gap helpers, snapshot cache (includes `dmon_asc_files`).
- **`app/core/argos_client.py`** / **`argos_cache_service.py`**: CLS Argos/Kinéis api-telemetry OAuth + bulk Doppler fetch; on-demand cache for checklist Argos–GPS check.
- **`scripts/test_argos_access.py`**: CLI auth / deviceRef / optional GPS distance check against CLS.
- **`app/routers/exploration_slocum.py`**: Exploration data endpoint (testing).
- **`app/routers/map_router.py`**: Slocum map telemetry endpoint; uses same `prepare_track_points` / `get_track_bounds` as Wave Glider.
- **`app/platforms/slocum/cli.py`**: Official CLI for fetching Slocum data (`python -m app.platforms.slocum.cli`).
- **`web/static/js/slocum_dashboard.js`**: Declarative sensor-card chart configs (incl. DMON ASC panel + left-nav ASC gap status indicator), checklist tab, compare entry.
- **`web/static/js/slocum_checklist_form.js`** / **`slocum_checklist_compare.js`**: Checklist fill/Plot-it and side-by-side compare UI.

Slocum data and UI stay separate from Wave Glider; login routes to the platform-specific dashboard.
