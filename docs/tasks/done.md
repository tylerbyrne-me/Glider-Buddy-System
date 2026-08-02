# Done

Archive of completed items, most recent first. Useful for "wait, did we already
fix this" checks and for the AI assistant to see what's already been tried.

- [x] 2026-08-02 — Glider Buddy System rebrand: platform registry, GBS brand titles, `gbs-*` CSS, WG HTML under `/wave-glider/` with redirects, high-traffic wiki + ADR 0003
- [x] 2026-07-31 — Slocum DMON sensor card + checklist: admin `dmon` toggle; ERDDAP `sci_dmon_msg_byte_count` dashboard/checklist; SFMC `from-glider` `*.asc` last-48h listing with >16h gap highlight; left-nav green/red ASC gap status dot (Waves ESS style); Science checklist items gated on DMON; `BUNDLE_SCHEMA_VERSION` **12**
- [x] 2026-07-31 — Slocum checklist Plot-it expansions: water depth, BMS currents, leak channels (+ digifin on y3), thruster_val autofill + plot; multi-series series API; checklist ERDDAP vars; schema bumped through digifin/thruster work (now **11**)
- [x] 2026-07-31 — Slocum dashboard digifin + thruster: digifin leak detect on Vehicle Health secondary Y; Flight thruster power/% dual-axis chart; dashboard ERDDAP wishlist + preprocess + chart allowlists; `BUNDLE_SCHEMA_VERSION` 11
- [x] 2026-07-29 — Slocum daily checklist side-by-side compare: lock reference (right), navigate prior submissions (left), value diffs + changed-only / include-notes; `GET /api/slocum/checklists/compare`
- [x] 2026-07-31 — Slocum chart toolkit defaults: shared zoom/pan/reset + depth overlay on CTD/DO placeholders and time-series cards; CTD profiles use vehicle-depth background overlay from dashboard `m_depth`
- [x] 2026-07-30 — Fix Slocum dashboard heading/coulomb charts: map ERDDAP `(rad)` / `(amp hrs)` column suffixes via stem-aware rename; bundle schema v9 rebuilds empty mirrors ([BUG-001](../bugs/BUG-001-slocum-heading-coulomb-rename.md))
- [x] 2026-07-30 — Slocum full-res by default: no ERDDAP orderByClosest on overage or historical/active mirror sync; pilots thin only via UI Resample; `slocum_erddap_decimation_minutes` default 0; bundle schema v8 rebuilds prior decimated mirrors

