# Done

Archive of completed items, most recent first. Useful for "wait, did we already
fix this" checks and for the AI assistant to see what's already been tried.

- [x] 2026-08-07 — Mission wrap-up expanded notes (ephemeral v1): optional toggle on user-generated WG weekly/EOM + Slocum weekly report UIs; free text embedded after "Publication, attribution, and data" in Mission details; automated scheduler reports unchanged; persistent in-app briefing storage deferred
- [x] 2026-08-07 — BUG-003: checklist Plot-it shares inverted Depth axis for `m_water_depth` (`invert_value_axis`; axis min 0; filter invalid water-depth samples) — [BUG-003](../bugs/BUG-003-flip-water-depth-axis.md)
- [x] 2026-08-06 — Nested Sensor Tracker sensors in UI: APIs return `MissionInstrumentRead.sensors`; shared `sensor_tracker_instruments.js` + home Jinja list nested sensors under instruments (same DB data reports already use)
- [x] 2026-08-06 — Phase A UI tokens + comfort (no DB): Bootstrap bridges in `themes.css`; `.gbs-card` / `.gbs-hint` / `.gbs-empty-state`; login + admin page CSS extraction; theme-aware Leaflet tiles (`map_tiles.js`); admin overview empty states; equal platform-choice cards

## Rebrand round summary (2026-08-02 → 2026-08-03)

Closed in-repo for **Glider Buddy System (GBS)** multi-platform rebrand:

| Area | Outcome |
|------|---------|
| Brand / registry | Product GBS; platform buddy titles; `gbs-*` CSS; favicon wiring + interim SVG |
| URLs | WG HTML under `/wave-glider/` with redirects; `/api/wave_glider` alias |
| Packages | `app/platforms/slocum/` (full Slocum package); `app/platforms/wave_glider/` scaffold |
| CLI | `python -m app.platforms.slocum.cli` only (`app.cli.slocum_cli` shim removed) |
| GitHub | Repo renamed to `Glider-Buddy-System`; tag `pre-gbs-rename-20260803`; mirror under `%USERPROFILE%\backups\` |
| Local folder | Clone dir renamed to `Glider Buddy System` (safe; independent of remotes) |

Still open (not this round): **manual** prod path cutover ([PROD_PATH_RENAME.md](../wiki/how-tos/PROD_PATH_RENAME.md)); optional later WG peel ([backlog](backlog.md) Later note); product backlog (theme UI, prod verify, reports polish).

- [x] 2026-08-05 — Public login map polish: platform-agnostic popup labels (`platform_name` / `mission_title` via shared resolver); login map centered below measured banner (~75%) with Refresh / Download KML under the map ([how-to](../wiki/how-tos/public_login_map.md))
- [x] 2026-08-05 — Public login-screen map + static KML + gated weekly reports: `/login.html` Leaflet map for allowlisted WG/Slocum missions (`public_login_map` toggle; admin `public_map_enabled` / `public_weekly_report_enabled`); `/api/public/map/bundle|kml`, report gate, rate limits, leader warm job; Slocum `weekly_report_url` persistence
- [x] 2026-08-05 — CLS Argos M2M + daily checklist Argos–GPS check (code): `argos_client` / `argos_cache_service`, `scripts/test_argos_access.py`, autofill `argos_gps_check_val` (20 km) + pre-suggest `argos_monitor_val` from admin `argos_id` (CLS deviceRef). Live credential / deviceRef verify still open on backlog (awaiting admin M2M login confirmation)
- [x] 2026-08-05 — Slocum weekly DMON ASC listings: paginate SFMC folder API (20/page) and clip files to the report window so early-window `*.asc` files are not dropped
- [x] 2026-08-05 — Slocum weekly Battery page: daily Ah bars (partial days rate-normalized / hatched; projection mean prefers complete days) + 50/75/90/100% pack-endurance projections (`battery_report.py`)
- [x] 2026-08-05 — Slocum weekly telemetry track: SFMC-style surfacing SOG (depth sessions + distance/time; 0–1.1 kt scale); dynamic vmax parked on backlog
- [x] 2026-08-05 — BUG-002: weekly report DMON ASC section drops staleness/“hours since last” warning; table gap highlighting only ([BUG-002](../bugs/BUG-002-dmon-asc-gap-hours-since-last.md))
- [x] 2026-08-05 — Slocum weekly DMON: summary uses confirmed detection-day tallies per species; whale page adds ASC offload/gap table (dashboard-style >16h highlight)
- [x] 2026-08-04 — Slocum weekly report content polish: period+total distance, avg water depth (m_water_depth / ETOPO 2022), Battery power row + pack type, DMON ASC gap-days KPI; GPS-derived continuous SOG telemetry track; drop Dashboard sensors; CTD depth-vs-time cmocean profiles; “DMON Whale detections” title
- [x] 2026-08-04 — Slocum DMON Robots4Whales analyst-review detections: `robots4whales_url` on deployment + admin UI; 12h leader cache under `data_store/dmon_review_cache/`; `GET /api/slocum/dmon/review/{dataset_id}`; DMON dashboard 48h table + full-history collapse (site attribution); weekly PDF section with Analysts footnote + `styled_data_table` status colors (Detected / Possibly detected) ([ADR 0004](../decisions/0004-dmon-robots4whales-review-cache.md))
- [x] 2026-08-03 — Rebrand closeout: removed deprecated `app.cli.slocum_cli` shim; canonical CLI is `python -m app.platforms.slocum.cli`
- [x] 2026-08-03 — Ops GitHub rename to `Glider-Buddy-System` (tag `pre-gbs-rename-20260803`, mirror under `%USERPROFILE%\backups\`, local origin updated; old URL 301s). Prod path cutover still open — use `docs/wiki/how-tos/gbs_prod_path_cutover.sh` on host
- [x] 2026-08-03 — Platform packages Now/Soon: scaffold `app/platforms/wave_glider/`; move Slocum summaries/reports/masterdata/checklist_definitions/cli into `app/platforms/slocum/`
- [x] 2026-08-03 — Favicon wiring (`PRODUCT_FAVICON_*`, interim `gbs_favicon.svg`); remove transitional `wgbs_logo`; move `app/core/slocum_*.py` → `app/platforms/slocum/` (routers stay put)
- [x] 2026-08-02 — Rebrand follow-ups Phases 1–6 in-repo: `gbs_logo.svg` + placeholder; GitHub/prod how-tos; archive note; `/api/wave_glider` alias + JS prefix; `app/platforms/` scaffold (live GitHub rename + prod `mv` remain ops)
- [x] 2026-08-02 — Glider Buddy System rebrand: platform registry, GBS brand titles, `gbs-*` CSS, WG HTML under `/wave-glider/` with redirects, high-traffic wiki + ADR 0003
- [x] 2026-07-31 — Slocum DMON sensor card + checklist: admin `dmon` toggle; ERDDAP `sci_dmon_msg_byte_count` dashboard/checklist; SFMC `from-glider` `*.asc` last-48h listing with >16h gap highlight; left-nav green/red ASC gap status dot (Waves ESS style); Science checklist items gated on DMON; `BUNDLE_SCHEMA_VERSION` **12**
- [x] 2026-07-31 — Slocum checklist Plot-it expansions: water depth, BMS currents, leak channels (+ digifin on y3), thruster_val autofill + plot; multi-series series API; checklist ERDDAP vars; schema bumped through digifin/thruster work (now **11**)
- [x] 2026-07-31 — Slocum dashboard digifin + thruster: digifin leak detect on Vehicle Health secondary Y; Flight thruster power/% dual-axis chart; dashboard ERDDAP wishlist + preprocess + chart allowlists; `BUNDLE_SCHEMA_VERSION` 11
- [x] 2026-07-29 — Slocum daily checklist side-by-side compare: lock reference (right), navigate prior submissions (left), value diffs + changed-only / include-notes; `GET /api/slocum/checklists/compare`
- [x] 2026-07-31 — Slocum chart toolkit defaults: shared zoom/pan/reset + depth overlay on CTD/DO placeholders and time-series cards; CTD profiles use vehicle-depth background overlay from dashboard `m_depth`
- [x] 2026-07-30 — Fix Slocum dashboard heading/coulomb charts: map ERDDAP `(rad)` / `(amp hrs)` column suffixes via stem-aware rename; bundle schema v9 rebuilds empty mirrors ([BUG-001](../bugs/BUG-001-slocum-heading-coulomb-rename.md))
- [x] 2026-07-30 — Slocum full-res by default: no ERDDAP orderByClosest on overage or historical/active mirror sync; pilots thin only via UI Resample; `slocum_erddap_decimation_minutes` default 0; bundle schema v8 rebuilds prior decimated mirrors

