# Done

Archive of completed items, most recent first. Useful for "wait, did we already
fix this" checks and for the AI assistant to see what's already been tried.

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

