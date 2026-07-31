# Slocum Glider integration

Slocum glider data is served via ERDDAP (Ocean Track). This document describes how Slocum is integrated into the project and how to use it.

## Configuration

- **`slocum_erddap_server`** (config / `.env`): ERDDAP base URL. Default: `https://erddap.oceantrack.org/erddap`. Override with `slocum_erddap_server` in `.env` if needed.
- **Feature toggle** `slocum_platform`: In `feature_toggles_json` (or `.env`), set `"slocum_platform": true` to enable Slocum API and map endpoints. When `false`, Slocum endpoints return 403.

## Mission dashboard

Active/historical mission dashboards (`/slocum/...`) show overview plus optional sensor cards (admin-configured per deployment). Chart cards share a time toolbar (hours / UTC range / resample / download) and per-chart toolkit: plot style, **Show depth** background overlay (`m_depth`), Ctrl+scroll zoom, pan, and Reset zoom.

| Card | Notable series |
|------|----------------|
| CTD | Depth-vs-time profiles (temp / conductivity / density) with optional vehicle-depth overlay |
| Power | Battery, coulomb AmpHr (daily + total), BMS currents |
| Flight | Pitch / roll / fin; **thruster** power (W) + commanded on (%) on dual axes |
| Navigation | Heading, depth rate, depth/altimeter, speed, depth-averaged currents |
| Vehicle Health | Vacuum; leak detect channels (main / forward / science) with **digifin** on a secondary Y axis; SFMC call length |
| Dissolved Oxygen | Placeholder charts (data wiring TBD) |
| DMON | `sci_dmon_msg_byte_count` over time; SFMC `from-glider` `*.asc` files (last 48h) with >16h gap highlight; left-nav green/red status dot (same style as Wave Glider Waves ESS) |

### Data path

Dashboard charts load from the rolling **dashboard** mirror under `data_store/slocum_cache/` (with overage cache for windows the mirror does not fully cover). Variables must be present in:

1. `SLOCUM_DASHBOARD_VARIABLES` ([`app/core/slocum_erddap_client.py`](../../app/core/slocum_erddap_client.py))
2. Dashboard rename/stems + `preprocess_slocum_dashboard_df` std columns ([`app/core/data/processors.py`](../../app/core/data/processors.py))
3. Chart allowlists in [`app/routers/slocum.py`](../../app/routers/slocum.py) (`_SLOCUM_VARIABLE_TO_COLUMN`, `_SLOCUM_CHART_VARIABLES`, CSV header)

When preprocess/schema columns change, bump `BUNDLE_SCHEMA_VERSION` in [`app/core/slocum_bundle_registry.py`](../../app/core/slocum_bundle_registry.py) so mirrors rebuild. Current schema is **12** (includes digifin leak detect + thruster + DMON byte count). After deploy, wait for leader sync or force an admin mirror rebuild if new series stay empty.

Shared chart UI helpers: `web/static/js/chart_*_utils.js`, `_chart_plot_controls.html`, `_chart_zoom_scripts.html`.

## Daily Pilot Checklist

Per-mission daily checklist (`/slocum/dataset/{dataset_id}/checklist.html`, also the dashboard **Checklist** tab).

### Autofill and Plot-it

- Schema: [`app/forms/slocum_checklist_definitions.py`](../../app/forms/slocum_checklist_definitions.py)
- Autofill / Plot-it registry: [`app/core/slocum_checklist_autofill.py`](../../app/core/slocum_checklist_autofill.py) (`CHECKLIST_PLOTTABLE_ITEMS`, `build_checklist_series_payload`)
- Checklist ERDDAP wishlist includes digifin leak detect, thruster, and `sci_dmon_msg_byte_count`; preprocess via checklist rename/std columns
- Plot modal (`web/static/js/slocum_checklist_form.js`): depth on left (`y`); value series on `y2`; digifin / thruster % on `y3` when needed
- Plottable autofill rows include vacuum/attitude/buoyancy (legacy), plus **water depth**, **BMS currents**, **leak channels** (main/forward/science/digifin), combined **thruster** (`m_thruster_power` / `c_thruster_on`), and **DMON** `sci_dmon_msg_byte_count` when the DMON sensor card is enabled
- **DMON gating:** Science items `dmon_msg_byte_count_val`, `dmon_asc_files_val`, and `asc_gap_check_val` appear only when `dmon` is in `SlocumDeployment.enabled_sensor_cards` (Manage Slocum Mission Overviews). The ASC list comes from the SFMC snapshot (`from-glider` `*.asc`, last 48h) and highlights gaps >16h since the newest file (and inter-file gaps >16h). Runtime injection: `apply_dmon_science_checklist_items` in [`slocum_checklist_autofill.py`](../../app/core/slocum_checklist_autofill.py)
- Series API: `GET /api/slocum/checklists/{dataset_id}/series?item_id=...`

### Side-by-side compare

- Dashboard Checklist tab → **Compare** (needs ≥2 submissions)
- Locked **reference** on the right; navigable prior submission on the left (past → present)
- Value diffs via `GET /api/slocum/checklists/compare`; toggles for changed-only (default on) and include notes
- Core: [`app/core/slocum_checklist_compare.py`](../../app/core/slocum_checklist_compare.py); UI: `web/static/js/slocum_checklist_compare.js`

## API

All Slocum endpoints require authentication (same as Wave Glider). When `slocum_platform` is disabled, Slocum routes return 403.

| Endpoint | Purpose |
|----------|--------|
| `GET /api/exploration/slocum/data?dataset_id=...&time_start=...&time_end=...` | Fetch raw ERDDAP data as JSON (testing; capped at 10k rows). |
| `GET /api/map/slocum/telemetry/{dataset_id}?hours_back=72` or `?time_start=...&time_end=...` | Track points for map display. Same response shape as Wave Glider `GET /api/map/telemetry/{mission_id}`: `track_points`, `point_count`, `bounds`, `source`. |
| `GET /api/slocum/chart-data-bulk/{dataset_id}?variables=...` | Multi-variable dashboard chart series (mirror / overage). |
| `GET /api/slocum/profile-data/{dataset_id}` | CTD depth-vs-time profile points (+ optional `depth_overlay` from dashboard `m_depth`). |
| `GET /api/slocum/sfmc/connection-durations/{dataset_id}` | Cached SFMC surface-call durations (Vehicle Health). |
| `GET /api/slocum/sfmc/dmon-asc-files/{dataset_id}` | Cached SFMC `from-glider` `*.asc` listing + gap flags (DMON card). |
| `GET /api/slocum/checklists/{dataset_id}/series?item_id=...` | Checklist Plot-it time series (depth + value / multi-series). |
| `GET /api/slocum/checklists/compare?reference_id=&other_id=` | Form-to-form checklist diff (`changed_item_ids`). |

Dataset ID format: `{glider}_{YYYYMMDD}_{mission_id}_{realtime|delayed}` (e.g. `peggy_20250522_206_delayed`). The map endpoint returns points with `lat`, `lon`, `timestamp` for use with existing map/KML tools.

## CLI

From project root with WorkPython:

```bash
conda activate WorkPython
python -m app.cli.slocum_cli --dataset peggy_20250522_206_delayed --start 2025-08-01 --end 2025-08-31 --output my_slocum.csv
python -m app.cli.slocum_cli --summary-only
```

The exploration script `exploration/slocum_erddap/fetch_sample.py` also uses the same app client; run it from project root so `app` is importable.

## Code layout

- **`app/core/slocum_erddap_client.py`**: ERDDAP fetch (sync). Used by routers and CLI. Reads server URL from config. Bundle variable wishlists (`SLOCUM_DASHBOARD_VARIABLES`, CTD, checklist).
- **`app/core/data/processors.py`**: `preprocess_slocum_dashboard_df` / CTD / track / checklist normalize ERDDAP columns for parquet and charts.
- **`app/core/slocum_bundle_registry.py`**: Bundle specs + `BUNDLE_SCHEMA_VERSION`.
- **`app/core/slocum_mirror_service.py`** / **`slocum_overage_cache.py`**: Rolling mirror and temporary overage windows.
- **`app/routers/slocum.py`**: Mission dashboard chart/CSV/profile APIs; SFMC connection-durations + DMON ASC listing endpoints.
- **`app/routers/slocum_checklists.py`**: Daily checklist template/submit/series/compare APIs and form page.
- **`app/core/slocum_checklist_autofill.py`** / **`slocum_checklist_compare.py`**: Autofill, Plot-it payloads, DMON Science-item gating, form-to-form diff.
- **`app/core/sfmc_client.py`** / **`sfmc_transforms.py`** / **`sfmc_cache_service.py`**: SFMC HTTP, `*.asc` listing + gap helpers, snapshot cache (includes `dmon_asc_files`).
- **`app/routers/exploration_slocum.py`**: Exploration data endpoint (testing).
- **`app/routers/map_router.py`**: Slocum map telemetry endpoint; uses same `prepare_track_points` / `get_track_bounds` as Wave Glider.
- **`app/cli/slocum_cli.py`**: Official CLI for fetching Slocum data.
- **`web/static/js/slocum_dashboard.js`**: Declarative sensor-card chart configs (incl. DMON ASC panel + left-nav ASC gap status indicator), checklist tab, compare entry.
- **`web/static/js/slocum_checklist_form.js`** / **`slocum_checklist_compare.js`**: Checklist fill/Plot-it and side-by-side compare UI.

Slocum data and UI stay separate from Wave Glider; login routes to the platform-specific dashboard.
