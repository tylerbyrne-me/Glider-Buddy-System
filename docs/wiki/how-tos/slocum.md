# Slocum Glider integration

Slocum glider data is served via ERDDAP (Ocean Track). This document describes how Slocum is integrated into the project and how to use it.

## Configuration

- **`slocum_erddap_server`** (config / `.env`): ERDDAP base URL. Default: `https://erddap.oceantrack.org/erddap`. Override with `slocum_erddap_server` in `.env` if needed.
- **Feature toggle** `slocum_platform`: In `feature_toggles_json` (or `.env`), set `"slocum_platform": true` to enable Slocum API and map endpoints. When `false`, Slocum endpoints return 403.

## API

All Slocum endpoints require authentication (same as Wave Glider). When `slocum_platform` is disabled, Slocum routes return 403.

| Endpoint | Purpose |
|----------|--------|
| `GET /api/exploration/slocum/data?dataset_id=...&time_start=...&time_end=...` | Fetch raw ERDDAP data as JSON (testing; capped at 10k rows). |
| `GET /api/map/slocum/telemetry/{dataset_id}?hours_back=72` or `?time_start=...&time_end=...` | Track points for map display. Same response shape as Wave Glider `GET /api/map/telemetry/{mission_id}`: `track_points`, `point_count`, `bounds`, `source`. |

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

- **`app/core/slocum_erddap_client.py`**: ERDDAP fetch (sync). Used by routers and CLI. Reads server URL from config.
- **`app/core/processors.py`**: `preprocess_slocum_track_df()` normalizes ERDDAP columns to `Timestamp`, `Latitude`, `Longitude`, `Depth` for map use.
- **`app/routers/exploration_slocum.py`**: Exploration data endpoint (testing).
- **`app/routers/map_router.py`**: Slocum map telemetry endpoint; uses same `prepare_track_points` / `get_track_bounds` as Wave Glider.
- **`app/cli/slocum_cli.py`**: Official CLI for fetching Slocum data.

Slocum data and UI are kept separate from Wave Glider; the plan is to present a platform choice (Wave Glider vs Slocum) after login and route to the appropriate dashboard.
