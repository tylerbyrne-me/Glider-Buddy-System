# Slocum ERDDAP exploration

**Exploratory only** — not integrated into the main app. Use the **WorkPython** conda environment for all commands.

- **ERDDAP server:** https://erddap.oceantrack.org/erddap (Ocean Track Slocum glider repository)
- **Dataset:** Set `DATASET_ID` in `fetch_sample.py` to a valid tabledap dataset from the Ocean Track server. Browse datasets at https://erddap.oceantrack.org/erddap/index.html or query the "all datasets" table.
- **Run sample:** `conda activate WorkPython` then `python exploration/slocum_erddap/fetch_sample.py`

---

## Testing (before presentation UI)

You can validate Slocum data and the backend without building the dashboard yet.

### 1. CLI (exploration script)

From the project root with **WorkPython** active:

```bash
conda activate WorkPython
# Default dataset and time range
python exploration/slocum_erddap/fetch_sample.py

# Custom dataset and time range
python exploration/slocum_erddap/fetch_sample.py --dataset peggy_20250522_206_delayed --start 2025-08-01 --end 2025-08-31

# Write to a specific file
python exploration/slocum_erddap/fetch_sample.py -d peggy_20250522_206_delayed -s 2025-08-01 -e 2025-08-31 -o my_test.csv

# Summary only (shape, columns, time range; no CSV)
python exploration/slocum_erddap/fetch_sample.py --dataset peggy_20250522_206_delayed --summary-only
```

Use this to try different missions and time windows, inspect columns, and confirm ERDDAP responses.

### 2. Authenticated API (full-stack test)

With the app running, call the exploration Slocum endpoint to test auth + backend + ERDDAP together (e.g. from Postman, curl, or a script). No Slocum UI required.

- **Endpoint:** `GET /api/exploration/slocum/data`
- **Query params:** `dataset_id`, `time_start`, `time_end` (ISO 8601)
- **Auth:** Required (same login as Wave Glider). Send the usual auth cookie or Bearer token.
- **Response:** JSON with `dataset_id`, `time_start`, `time_end`, `row_count`, `columns`, and `data` (capped at 10,000 rows).

Example (after logging in and using your session cookie):

```bash
curl -b "access_token=YOUR_COOKIE" "http://localhost:8000/api/exploration/slocum/data?dataset_id=peggy_20250522_206_delayed&time_start=2025-08-18T00:00:00Z&time_end=2025-08-25T23:59:59Z"
```

Or in the browser: open the app, log in, then visit the same URL (with query params). This confirms the pipeline from login through to ERDDAP data.

---

## Platform data source abstraction (design)

Future integration could use a single abstraction for "platform data source":

- **Wave:** Existing `load_report(report_type, mission_id, base_path, base_url)` in `app/core/loaders.py` → CSV by filename (e.g. power, ctd, weather). Used by `app/core/data_service.py`.
- **Slocum:** ERDDAP server + `dataset_id` (+ mission/deployment mapping) + variables/constraints → DataFrame via erddapy `to_pandas()`.

No code changes yet in `app/core/loaders.py`, `app/core/data_service.py`, or any router. This folder is exploration + design only.

---

## Variable mapping (for later)

| Wave Glider (current)     | ERDDAP Slocum (typical)     |
|---------------------------|-----------------------------|
| `gliderTimeStamp`         | `time` (UTC)                |
| `VehicleName`             | (dataset_id / platform id)   |
| Report-specific (power, CTD, etc.) | Variables per dataset (e.g. `depth`, `latitude`, `longitude`, `sea_water_temperature`, `salinity`) |

Future integration will need a **normalization layer**: map ERDDAP variables to a common schema (or existing processor expectations) so the rest of the app can stay report-type oriented (e.g. "ctd" vs "trajectory") without caring whether the source was Wave CSV or Slocum ERDDAP.

---

## Slocum dataset types: real-time vs delayed

Ocean Track ERDDAP exposes two kinds of Slocum datasets, analogous to Wave Glider data:

| Slocum ERDDAP   | Wave Glider equivalent        | Behaviour |
|-----------------|--------------------------------|----------|
| **Real-time**   | `output_realtime_missions`     | Updated as data arrives and is processed. Requires similar **cache refresh strategies** as Wave Glider active missions: incremental loading, overlap for gaps, and proactive background refresh (e.g. `background_cache_refresh_interval_minutes`, active-missions list). |
| **Delayed**     | `output_past_missions`         | Full dataset processed post-deployment (historical). Like Wave Glider past missions: can be cached longer or loaded on demand; no need for frequent proactive refresh. |

Integration should treat **real-time** Slocum datasets like Wave incremental report types (`CACHE_STRATEGIES` with `incremental=True`, `overlap_hours`) and only run background refresh for Slocum missions that are "active" (real-time). **Delayed** Slocum datasets can use on-demand or long-lived cache, similar to historical Wave missions.

---

## Dataset ID format and Sensor Tracker

Slocum gliders use Sensor Tracker (like Wave Gliders). The ERDDAP **dataset ID** encodes the mission and type:

**Format:** `{glider}_{YYYYMMDD}_{mission_id}_{realtime|delayed}`

**Example:** `peggy_20250522_206_delayed`

| Part        | Example   | Meaning |
|-------------|-----------|--------|
| Glider name | `peggy`   | Platform/glider name. |
| Deploy date | `20250522`| Deployment date (YYYYMMDD). |
| Mission ID  | `206`     | **Sensor Tracker mission ID** — use this for Sensor Tracker API tie-ins (deployments, instruments, etc.). |
| Designator  | `delayed` or `realtime` | Whether the dataset is real-time (live) or delayed (post-deployment). |

Parsing the dataset ID yields: Sensor Tracker mission ID for linking deployments/instruments, glider name, deployment date, and whether to apply real-time cache refresh or historical caching.

---

## UI separation: platform choice after login (design)

Slocum data and dashboard must stay **separate** from Wave Glider data and dashboard. For the moment, the intended behaviour is:

- **Single login** — use the existing auth; no separate Slocum login.
- **After authentication** — present a **platform choice**: "Wave Glider" or "Slocum".
- **Based on choice:**
  - **Wave Glider** → current Wave Glider home/dashboard and all Wave Glider missions, data, and features (unchanged).
  - **Slocum** → a Slocum-specific home/dashboard; only Slocum missions and ERDDAP-backed data. No Wave Glider data or mission list here.
- **Separation** — Wave Glider and Slocum datasets and UIs do not mix: no Slocum missions on the Wave dashboard, no Wave missions on the Slocum dashboard.

**Implementation outline (when integrating):**

1. **Post-login redirect:** After successful login, redirect to a **platform-select** page (e.g. `/platform-select.html`) instead of directly to `/home.html`.
2. **Platform-select page:** Two clear options (e.g. cards or buttons): "Wave Glider" and "Slocum". On choose, store the selected platform (e.g. in `sessionStorage` or a cookie) and redirect:
   - Wave Glider → `/home.html` (current Wave Glider home).
   - Slocum → Slocum home/dashboard (e.g. `/slocum.html` or `/home-slocum.html`).
3. **Session/state:** All subsequent requests and front-end behaviour use the stored platform so that data loading, nav, and dashboards only show the chosen platform’s data.
4. **Switching platform:** Provide a way (e.g. in nav or user menu) to "Switch to Wave Glider" / "Switch to Slocum" that returns to the platform-select page or directly switches context and reloads the appropriate dashboard, without logging out.

This keeps a single sign-on while ensuring Wave Glider and Slocum experiences and datasets remain separate.
