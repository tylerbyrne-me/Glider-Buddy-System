# Backlog

Roughly ordered by priority, top = next up. Move an item to `in-progress.md`
when you start it; move it to `done.md` when it ships.

Keep each line self-contained enough that the AI assistant can pick it up cold:
what, where, and any constraint that matters.

Seeded 2026-07-29 from recent unfinished-work review
([Review of unfinished tasks](81c85f36-51b6-4c5b-9258-b0923532df06)) plus a light archive skim.

## High priority

- [ ] Finish CLS Argos live verify (blocked on admin confirming new M2M login credentials): put `ARGOS_USERNAME` / `ARGOS_PASSWORD` in `.env`; run `python scripts/test_argos_access.py --device-ref <CLS_deviceRef>` per glider; confirm admin Mission Overview `argos_id` matches CLS `deviceRef`; open a realtime daily checklist and confirm `argos_gps_check_val` + pre-suggested `argos_monitor_val`. Code already in-repo (`argos_client`, `argos_cache_service`, checklist autofill) — [Slocum how-to Argos](../wiki/how-tos/slocum.md#daily-pilot-checklist)
- [ ] Confirm prod `data/` and `data_store/` ownership (`chown cove:cove` or service user) and reclaim stranded `*.tmp` if mission CSV sync still fails — see AGENTS.md NFS/`os.replace` notes; chat [Mission CSV rename fix](c7ca764b-4f6c-42b2-a304-54183c563871)
- [ ] Commit, QA, and deploy the outstanding theme + chart hover/crosshair UI batch (keep as its own commit — not mixed with docs) — [Theme consistency](80b24643-2d50-47fd-96bb-2731d082fd3b), [Chart hover fix](c7ac3551-0b33-4987-a8c6-4d2e34e41304)
- [ ] Prod verify: auto-checklist actually submitting, Iridium map toggle on prod, UTC hardening / sensor cards as applicable; DMON card on a DMON-equipped glider (byte-count chart + ASC 48h list + green/red gap status dot + gated checklist Science items after schema **12** mirror rebuild + SFMC refresh). Robots4Whales review UI/report path is implemented in-repo — confirm on prod after deploy (URL set, 12h cache job, weekly PDF section).

## Medium priority

- [ ] Admin runtime mission & config control (avoid `.env` edit + restart where possible): add/list missions without touching `ACTIVE_SLOCUM_DATASETS` / `ACTIVE_REALTIME_MISSIONS` / `HISTORICAL_*`; move active → historical (and for Slocum, flip ERDDAP pointer realtime ↔ delayed); broader admin UI to edit feature toggles (and similar non-secret ops flags — prefer `FEATURE_TOGGLES_FILE` / DB overlay + invalidate `feature_toggles` cache). Keep secrets in `.env`; document what still requires restart — idea inbox 2026-08-05
- [ ] Optional: CLS Argos leader prefetch job (warm `data_store/argos_cache/` every 6–12h for deployments with `argos_id`) — v1 uses on-demand checklist fetch + 30 min TTL
- [ ] Slocum weekly telemetry speed scale revisit: keep SFMC-style surfacing SOG coloring (`color_by=sfmc_sog`, hard cap 1.1 kt for now); consider clamped dynamic vmax (e.g. nice P95 between ~0.6–1.1) so quiet weeks use more of the palette — chat [SFMC speed track](592cc7c9-a674-4a8c-a04f-15683bac4a10)
- [ ] Slocum weekly report polish Phase 2+: landscape multi-panel sensors, checklist-bundle charts, end-of-mission mode — content polish (summary KPIs, SOG track, CTD profiles, DMON whale title) shipped 2026-08-04; `weekly_report_url` persistence shipped with public map 2026-08-05; remaining items still open — [Report polish Phase 1](b8a79301-0344-450e-99c7-0d8d67d64032)
- [ ] Modular report requests: generate PDFs (or report sections) for subsets — dataset slices, telemetry plot groups, and individual sensors — rather than only the full weekly bundle; API/UI to pick modules + date window; reuse `app/core/reporting` section builders where possible — idea inbox 2026-08-04
- [ ] Mission wrap-up / briefing narrative for weekly + end-of-mission reports: free-text thoughts, checklist-style wrap-up, overall mission briefing — distinct from existing telemetry-tied mission comments; store in-app and render as a report section. Later (blocked externally): optional Sensor Tracker push/pull for end-of-mission metadata once Tracker APIs support it — see archive [SENSOR_TRACKER_REPORTING_INTEGRATION_PLAN](../archive/plans/SENSOR_TRACKER_REPORTING_INTEGRATION_PLAN.md) — idea inbox 2026-08-04
- [ ] Mission pre-launch / pre-deployment checklist inclusion: wire existing `pre_deployment_checklist` form (`app/forms/form_definitions.py`) into mission/deployment workflow and weekly + end-of-mission reports. Later (Sensor Tracker dependency, partly external): automate assignment of data loggers, instruments, and sensors onto a platform deployment from Tracker metadata — idea inbox 2026-08-04
- [ ] Sensor Tracker–driven deployment auto-config: on mission sync, auto-toggle platform `enabled_sensor_cards` from Tracker instruments/sensors. For Slocum, also map Tracker ballast pump type → `glider_depth_class` (deep/shallow) and power id → `battery_pack` into `checklist_reference_values` presets (`checklist_autofill.py`) — idea inbox 2026-08-05
- [ ] Chart forecast overlay layers: plot Open-Meteo forecasted solar irradiance as a secondary series/layer on the solar power chart (reuse existing `/api/forecast` / Open-Meteo path + weather cache patterns). Generalize where applicable — forecast layers for weather, waves, and ocean surface currents on matching telemetry/dashboard plots; align with declarative chart “forecast” follow-up in chart platform item below — idea inbox 2026-08-05
- [ ] Slocum summary cards mini-trend values: finish/polish sparkline mini-trends on dashboard summary cards (`app/platforms/slocum/summaries.py`, `slocum_dashboard.html` / `slocum_dashboard.js`) — ensure categories that already declare `data-mini-trend` get correct series, extend to cards still missing trends (e.g. dissolved oxygen / sensor cards), and align with declarative chart mini-trend follow-up — idea inbox 2026-08-05
- [ ] Slocum DMON doughnut chart for whale detections over time (species/call-type or period breakdown on the DMON sensor card); reuse Robots4Whales / DMON review cache where useful; fits declarative chart “doughnut” follow-up — idea inbox 2026-08-05
- [ ] Chart platform follow-ups: ERDDAP/narrow bulk API (drop client `rowsToSeries`), server-owned chart config registry, optional spectrum/doughnut/mini-trends/forecast into declarative system, WG↔Slocum schema convergence, JS test harness — [WG declarative rewrite](bcc8cb49-ec97-49b6-b793-8a04926f4140)
- [x] Ops: rename GitHub repo to `Glider-Buddy-System`; remotes updated; backup tag + mirror — [GITHUB_RENAME.md](../wiki/how-tos/GITHUB_RENAME.md) — 2026-08-03
- [ ] Ops (manual on app host): prod path cutover to `/home/cove/Glider-Buddy-System` with symlink soak — no remote access from this workstation; run [`gbs_prod_path_cutover.sh`](../wiki/how-tos/gbs_prod_path_cutover.sh) during a maintenance window — [PROD_PATH_RENAME.md](../wiki/how-tos/PROD_PATH_RENAME.md)

### Platform packages (`app/platforms/`)

This rebrand round is closed for Slocum packaging: core + stragglers live under `app/platforms/slocum/`; CLI is `python -m app.platforms.slocum.cli` (deprecated `app.cli.slocum_cli` shim removed). WG scaffold is at `app/platforms/wave_glider/` for new WG-only code. See [platforms README](../../app/platforms/README.md), ADR 0003.

Notes (not scheduled work):

- **Later:** If the package boundary is paying off, peel one clear WG island (e.g. `app/core/stations/wg_vm4_*`, or WG-only PIC/offload helpers) into `app/platforms/wave_glider/` in a focused PR — not a wholesale core evacuate
- **Avoid:** Big-bang “move all Wave Glider out of `app/core`”; keep shared pipelines (`data_service`/loaders/processors/sync), map/weather/bathy/iridium, models, and auth in core. Don’t couple module moves to a full `/api/wave_glider/` URL cutover

## Low priority / someday

- [ ] Interactive `.env` generator script: prompt for required settings, auto-generate `JWT_SECRET_KEY` (and similar hash/secret keys), seed default feature-toggle options (from `config/feature_toggles.example.json`) for optional edits; expandable for more vars. **Security:** keep secrets only in private `.env` — use tempfile / no agent-chat persistence of secret values; never write secrets to docs, logs, or repo — idea inbox 2026-08-06
- [ ] Admin UI to upload/replace brand & platform icons (product SVG/logo, favicon, main-page icons, splash/login art, per-platform SVGs under `web/static/images/` / `platforms/`); today is file-drop per [BRAND_ASSETS.md](../wiki/how-tos/BRAND_ASSETS.md) + `app/core/platforms/registry.py` paths — idea inbox 2026-08-05
- [ ] Optional Robots4Whales-style detection maps in-app (may skip — maps already exist on WHOI); if pursued, present detections differently on home/mission map. Likely needs scraping per-day HTML detection tables beyond the current cached review status ([ADR 0004](../decisions/0004-dmon-robots4whales-review-cache.md)); keep leader cache / no on-request scrape — idea inbox 2026-08-05
- [ ] More UI color themes beyond light/dark (`web/static/css/themes.css` + `data-theme`); persist choice per signed-in user (not only localStorage / system preference) — idea inbox 2026-08-05
- [ ] Update permissions reference matrix (`web/templates/_permissions_modal.html` + `permissions_modal.js`) for new pages/routes and Wave Glider vs Slocum (`can_access_wave_glider` / `can_access_slocum`) divides; keep hand-authored rows aligned with actual router guards — idea inbox 2026-08-05
- [ ] Slocum checklist history follow-ups (multi-day matrix / sparklines); side-by-side compare shipped 2026-07-29 — [Checklist history ideas](378f5e79-578b-4f7a-99cd-ca202e222768)
- [ ] Dockerize app for a more stable host — [Docker migration options](3357a043-5fd2-46e6-bfb5-fd14329e8c7e)
- [ ] Optionally standardize complex error handling in `app/routers/forms.py` and `app/routers/live_kml_router.py` (acceptable as-is; see `docs/archive/reviews/HIGH_PRIORITY_COMPLETION_SUMMARY.md`)
