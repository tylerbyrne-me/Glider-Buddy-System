# Sensor Tracker Team browser

Live, **read-only** inventory search in the admin Team hub. Use this to inspect Sensor Tracker as the source of truth (platforms, deployments, loggers, instruments, sensors, and components when Tracker exposes them). Detail pages show live **service time** (days at sea, days on the current deployment, days attached / on the shelf) from Tracker start/end windows. Calibration age and lifetime expectations are not computed yet.

## Access

- Feature toggle: `team_hub` (same as the rest of Team)
- Role: admin
- URL: `/team/sensor-tracker` (also listed on `/team` as **Sensor Tracker browser**)

## What it queries

Requests go **live** to `sensor_tracker_host` via authenticated `httpx` (`app/services/sensor_tracker_query.py`). They do **not** read the mission-sync SQLite cache except for a deployment **Buddy overlay** (`SensorTrackerDeployment.sensor_tracker_deployment_id` → `mission_id` / `last_synced_at` / `sync_status`).

GET does not require a token on many Tracker installs. Buddy sends `sensor_tracker_token` when set, then **retries the GET anonymously** on HTTP 401/403 (a stale token 403s lists that work without Authorization) and remembers that list path so later GETs skip the token. Pagination (`page` / `page_size` / `limit`) is applied in Buddy, not forwarded on the first request — Tracker often 403s unknown query keys. Later list pages follow Tracker's own `next` URL (typically `?page=2`) and then slice to Buddy's page size. Sensor lists omit the old `output=all` query (prod 403s it). If Tracker still 403s with “doesn't accept following parameter: …”, Buddy retries once without those keys and **remembers** them for that path. Those 403 retries are filter/auth negotiation, not an upstream rate limit (rate limits would be HTTP 429). Deployment → related sensors uses `/api/instrument_on_platform/` then `/api/sensor_on_instrument/` (prod `/api/sensor/` 403s `output` and `start_time`). Platform is resolved by **name**, not the numeric FK.

## Usage

1. Open Team → Sensor Tracker browser.
2. Pick an entity tab. Optional types (loggers, components) hide if Tracker returns 404 for that list endpoint.
3. Search by partial name, identifier, serial, title, numeric id, or `m###` (deployments). Spaces are AND (e.g. `sv3 1070`). Exact id still opens that record when it exists. **Sensors:** Tracker does not substring-filter `/api/sensor/` (~235k rows). Paste the related-list title, the exact identifier, a numeric id, or a token from an **attached** sensor (Buddy scans `sensor_on_instrument`, not the whole catalog). **Deployments:** Tracker ignores `search=` and `title=` on `/api/deployment/` (~1k rows). Title search (including unnumbered / dateless / PLANNED-style entries such as `TEST HOLD`) walks that catalog locally. Hull name uses honored `platform_name=` (list rows often store `platform` as an int FK, so a local match on `SV3-1121` would miss). Exact numeric id still works; you do not need it to find a new ST entry by title.
4. Open a row for curated fields, **service time** (days at sea / deployed / attached), related records, raw JSON, and an “Open in Sensor Tracker” / API JSON link.
5. Related lists default to **currently attached** (no end date), open-ended rows first. Uncheck that box for full history (Tracker time order). **As of** (on any entity with relations) keeps rows that had already started by that time and still have no end date, or whose end is after that time. Click a related button again, or **Hide**, to collapse the list. Components use `/api/component_on_platform/` (Tracker has no identifier field on components; pin by instance id / serial). A component’s **Deployments** list is those missions whose start/end overlap an attachment stint on that hull. Loggers, instruments, and sensors also climb **up** to **Platforms** and **Deployments** (same attach∩mission overlap rule as components); instruments additionally list parent **Loggers** when logger-mounted. A sensor’s **Instruments** list is `sensor_on_instrument` (e.g. an SBE43F on a GPCTD / Seabird CTD), falling back to `current_instrument` when that join is empty; sensor platforms/deployments follow that parent instrument’s attachments.
6. Nested related records are pinned to the **parent instance** (id, or serial if id is missing). Tracker type identifiers (`flight computer`, `CTD`, `ballast_pump`) are only used as fetch hints — they are never treated as “this is the same logger/instrument”. Related labels append serial or `#id` when the title is that shared identifier. Relationship `next` URLs are followed as-is (passing `params={}` would strip `depth` / identifier / offset and later pages un-nest).

Deep links: `/team/sensor-tracker?type=instrument&id=123`.

## What it does not do

- No writes, outbox, or PATCH/POST to Tracker
- No “sync this deployment into Buddy” (that remains on admin mission / Slocum overviews)
- No calibration-age or lifetime-expectation math, and no new inventory tables (days at sea are computed live from Tracker windows)

## Ops notes

- List calls are paginated in Buddy (default 25, cap 100). Tracker is not sent `page` / `limit` / `page_size` on the first request; Buddy follows `next` for later pages. Sensor lists are not sent `output=all`. Text search sends Tracker `search=` (not exact `name=` / `identifier=`). If that returns nothing, Buddy scans up to 500 list rows and keeps case-insensitive substring matches (every space-separated token must appear; punctuation-only tokens like `-` are ignored). Exact numeric id still wins when that record exists. Deployment list/detail **platform** shows the hull name (`SV3-1071`) when Tracker only stored a numeric FK; falls back to that id when the name is missing (`app.core.sensor_tracker.platform_display` — display cells only, not search matching).
- **Sensors tab:** prod `/api/sensor/` ignores `search=` and `serial=` (same ~235k `count` as an unfiltered list). Buddy then tries exact `identifier=` (related titles that append a duplicate serial, e.g. `SBE43F Dissolved Oxygen - 4051 - 4051`, are stripped to the real identifier) and, if still empty, walks `sensor_on_instrument` (hundreds of attached sensors) for a local token match. Never page through the full sensor catalog. Unattached sensors are only found by exact identifier or numeric id.
- **Deployments tab:** prod `/api/deployment/` ignores `search=` and `title=` (same ~923 `count` as an unfiltered list). The first 500 rows are recent numbered missions; unnumbered / dateless titles sit later, so a 500-row local scan misses them (they still appear on a platform’s related Deployments list, which queries `platform_name=`). Buddy then tries `platform_name=` with the query as-is and, if that is empty or ignored, walks the full deployment list (cap 2500, catalog is ~1k — not 235k sensors) for a local token match.
- Tracker HTTP 403 after the anonymous retry (and optional rejected-param strip) is returned as **400** (not 502) with a prompt to search by name/id.
- Tracker timeouts surface as HTTP 504 from `/api/team/sensor-tracker/*`; gunicorn `--timeout 200` is not the usual limiter here (query timeout is 30s).
- Connection strip on the page is a cheap `GET /api/platform/` (no `limit` query).
- Detail **Service time** is `GET /api/team/sensor-tracker/{entity}/{id}/analytics` (math in `app/services/sensor_tracker_analytics.py`). Open-ended windows run through now (UTC). History is capped at 500 Tracker rows.
  - **Days at sea** = attachment windows ∩ that platform’s deployment windows (all missions, merged so overlaps are not double-counted).
  - **Days on current deployment** = same intersection, but only deployments that are still open.
  - **Days attached** = time on a platform (loggers, components) or on a platform/logger (instruments). **Days on shelf** = attached − at sea.
  - Deployments use their own start/end. Platforms sum their deployment windows. Loggers use `data_logger_on_platform`. Components use `component_on_platform` (no type identifier; history is pinned by instance id). Instruments use **both** `instrument_on_platform` and `instrument_on_data_logger` (Slocum science CTDs are logger-mounted; querying platform-only history left those at 0 days). Logger-mounted sea time is attachment ∩ logger-on-platform ∩ that vehicle’s deployments.
  - Sensors: `sensor_on_instrument` when Tracker returns rows; otherwise the sensor’s `current_instrument` and that instrument’s windows (prod `sensor_identifier` / `instrument_identifier` filters on that join are empty). Sensor detail **Instruments** is the same join (history + currently attached).

Related how-tos: [SENSOR_TRACKER_QUICK_START.md](./SENSOR_TRACKER_QUICK_START.md), [SENSOR_TRACKER_TROUBLESHOOTING.md](./SENSOR_TRACKER_TROUBLESHOOTING.md).
