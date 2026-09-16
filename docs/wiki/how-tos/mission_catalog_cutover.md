# Mission catalog cutover

Live-key-safe catalog (ADR [0005](../../decisions/0005-mission-catalog-live-keys.md),
[0008](../../decisions/0008-catalog-durable-ops-state.md)) stays an **index**. Catalog
UUIDs never replace `mission_id`, Slocum `mission_key`, routes, or disk folders.

**Status (2026-09-16): CLOSED — production rollover complete.** Historical identity
(ADR 0009) + Slocum `mission_key` uniqueness deployed on prod: repair CLI / manual
orphan cleanup (no duplicates), `alembic` head including `20260915_slocum_mk`,
metadata still linked, active Slocum set verified (m224 / m226 / m228 / m231),
label-aware nav + historical notes/reports/briefings smoke OK. Remaining ops
follow-up (not blocking): many COMPLETED missions show expected
`completed_final_sync_pending` while the batch final-sync queue drains — high-priority
backlog check-in. Env `ACTIVE_*` remain break-glass for one compatibility release.

**Status (2026-09-15):** Historical identity repair landed in repo (ADR 0009) —
display-only labels, Slocum inactive resolve + no historical GET create, safe
mission_key orphan repair, unique non-null `mission_key` migration
`20260915_slocum_mk`. Local verification: `pytest app/` 124 passed; migration
preflight/upgrade/downgrade smoke OK.

**Status (2026-09-11):** Complete crossover ops state landed — durable audit/runs,
write lock, truthful success markers, bounded final-sync work items, catalog-backed
historical Slocum when env is empty, TTL deep ST refresh, public-map invalidate on
membership changes. Empty `ACTIVE_*` / historical env lists are the normal production
state; env lists remain break-glass for one compatibility release.

## Lifecycle and enrollment

| ST condition | State | Policy (default) |
|--------------|-------|------------------|
| No deployment number | PLANNED | CATALOG_ONLY (workspace only) |
| Numbered, no / future start | PLANNED | CATALOG_ONLY |
| Start reached, no end | ACTIVE | CONTINUOUS (ST `enrollment_authority`) |
| End time set | COMPLETED | ON_DEMAND (+ durable `final_sync` work item) |

Overrides: `enrollment_override` = `automatic` | `forced_on` | `forced_off` (completion still wins over `forced_on`). WGMS/ERDDAP cannot enroll. Team enrollment/provision actions are attributed to the authenticated admin in `catalog_mission_events`.

Shadow mode: `MISSION_CATALOG_ENROLLMENT_SHADOW=true` logs would-enroll without writing CONTINUOUS.

## Enablement membership

`list_catalog_sync_targets(platform, session)`:

| Env list | Result |
|----------|--------|
| Non-empty `ACTIVE_*` / historical | Exact env strings (override / fail-safe) |
| Empty + catalog on | Catalog authority (see below) |
| Catalog off / empty / no session | Env list (possibly empty) |

Empty-env catalog authority:

- **Active WG:** `ACTIVE` ∧ `CONTINUOUS` + realtime WGMS + linked overview
- **Active Slocum:** `ACTIVE` ∧ `CONTINUOUS` + ERDDAP + linked *active* deployment
- **Historical Slocum:** `COMPLETED` ∩ inactive linked `SlocumDeployment` (not unrelated orphans). Dropdown uses canonical ERDDAP dataset ids (aliases are active-only).
- **Historical WG:** catalog `COMPLETED` linked overviews only (one preferred key per `m###`); WGMS scrape is fallback when catalog has no completed WG rows — never unioned (avoids `1070-m170` + `m170-SV3-1070` duplicates).

STALE/CONFLICT sources are excluded from readiness. Prefer realtime while ACTIVE; delayed/past while COMPLETED.

## Ops flags

1. `MISSION_CATALOG_WG_SYNC_FROM_CATALOG=true`
2. `MISSION_CATALOG_AUTO_APPLY=true`
3. `MISSION_CATALOG_SLOCUM_WARM_FROM_CATALOG=true`
4. `MISSION_CATALOG_PUBLIC_MAP_FROM_CATALOG=true`
5. Optional: `MISSION_CATALOG_ENROLLMENT_SHADOW=true` before first ST auto-enroll write soak
6. `MISSION_CATALOG_SYNC_INTERVAL_MINUTES=30` (default; `0` = daily cron only)
7. `MISSION_CATALOG_ST_DEEP_SYNC_TTL_HOURS=24` (deep ST refresh cadence)
8. `MISSION_CATALOG_FINAL_SYNC_MAX_ATTEMPTS` / `_MAX_AGE_DAYS` / `_BATCH_LIMIT`

## Admin / Team UI

Open `/team/mission-catalog` (admin + `team_hub`):

| Tab | Purpose |
|-----|---------|
| Active / Planned / Completed / Archived | Mission table with platform, policy, **readiness badge**, dates |
| Detail panel | Sources (incl. stale badges), live rows, ST sync, instruments, **final-sync state**, **recent events**, **Retry provision**, **Retry final sync**, enrollment override |
| Health | Counts + issues with **expected vs fault** severity; final-sync pending/failed/exhausted |
| Unmatched | Unmatched ERDDAP inventory |

Status banner: cadence, last **success** age, last **partial**, write-lock/in-progress, this-worker-is-leader, shared scheduler job outcome, auto-apply / consumer flags.

### API

- `GET /api/team/mission-catalog/status`
- `GET /api/team/mission-catalog/missions?operational_state=…`
- `GET /api/team/mission-catalog/missions/{uuid}`
- `GET /api/team/mission-catalog/missions/{uuid}/events`
- `GET /api/team/mission-catalog/runs`
- `POST …/enrollment?override=automatic|forced_off|forced_on`
- `POST …/provision` (HTTP 409 if catalog write lock busy)
- `POST …/final-sync/retry`
- `GET /api/team/mission-catalog/health`
- `GET /api/team/mission-catalog/unmatched-sources`

Catalog **apply** remains CLI/scheduler (gate-aware, locked). Success marker advances only on clean gates + zero reconcile/provision/final-sync failures.

## CLI

```powershell
conda activate WorkPython
python -m app.cli.mission_catalog_sync --dry-run
python -m app.cli.mission_catalog_sync --apply
python -m app.cli.mission_catalog_repair_duplicates
python -m app.cli.mission_catalog_repair_duplicates --apply
python -m app.cli.mission_catalog_repair_duplicates --wg-inventory
python -m app.cli.mission_catalog_export_keys --json > catalog_keys.json
```

Before Alembic `20260911_catalog_ops`: run duplicate catalog-link preflight / repair so unique indexes do not fail.

Before Alembic `20260915_slocum_mk`: run mission_key orphan report / safe apply so unique non-null `mission_key` does not fail.

## Historical identity and display labels (ADR 0009)

Canonical names are **display-only**. Storage keys, routes, disk folders, and catalog UUIDs stay unchanged.

| Platform | Label | Navigation `key` |
|----------|-------|------------------|
| Wave Glider | `m###-SV3-<hull>` (legacy `1070-m170` → `m170-SV3-1070`) | `MissionOverview.mission_id` |
| Slocum | `m###-<GliderName>` | ERDDAP dataset id / configured key |

Detail endpoints (keep List[str] APIs):

- `GET /api/available_missions/detail`, `/api/available_historical_missions/detail`, `/api/available_all_missions/detail`
- `GET /api/slocum/available_datasets/detail`, `/api/slocum/available_historical_datasets/detail`

Slocum briefing identity: one `SlocumDeployment` per suffix-neutral `mission_key`; `_realtime` / `_delayed` stay separate `CatalogMissionSource` rows. Historical GET `/api/slocum/datasets/{id}/info` and SSR resolve inactive completed owners with **no auto-create**. Only catalog reopen/provision reactivates.

### Identity repair rollout

**Prod (2026-09-16): complete** (resolver deployed; orphans repaired; migration applied;
label UI + historical metadata verified).

1. Deploy resolver / read-path fix (stops new empty orphans).
2. `python -m app.cli.mission_catalog_repair_duplicates` (report) — archive output.
3. `--apply` only for `safe_auto` empty active orphans; resolve `ambiguous_metadata` / empty inactive twins manually (delete `slocum_sfmc_snapshots` for the orphan first if `--apply` hits IntegrityError).
4. `alembic upgrade head` (includes `20260915_slocum_mk` unique non-null `mission_key`).
5. Enable label-aware UI (auth.js / admin selectors already prefer `/detail`).
6. Smoke: active + historical WG/Slocum dropdowns (label ≠ key OK), historical notes/reports/media, final sync, reopen, rollback.

Rollback for labels: clients fall back to List[str] endpoints; no PK renames to undo. Rollback for uniqueness: `alembic downgrade 20260911_catalog_ops` drops the mission_key index only.

## Rollback (exercised procedure)

1. Export current keys: `python -m app.cli.mission_catalog_export_keys --json > catalog_keys_before_rollback.json`
2. Disable consumer flags + auto-apply:
   - `MISSION_CATALOG_WG_SYNC_FROM_CATALOG=false`
   - `MISSION_CATALOG_SLOCUM_WARM_FROM_CATALOG=false`
   - `MISSION_CATALOG_PUBLIC_MAP_FROM_CATALOG=false`
   - `MISSION_CATALOG_AUTO_APPLY=false`
3. Restore exact `ACTIVE_REALTIME_MISSIONS`, `ACTIVE_SLOCUM_DATASETS`, `HISTORICAL_SLOCUM_DATASETS` from the export (or prior known-good `.env`).
4. Reactivate any catalog-completed Slocum live rows required by the restored active list (set `is_active=true` / status active on those deployments).
5. Invalidate public-map cache (Team/admin purge or delete `data_store` public-map bundle) and restart `gliderbuddy`.
6. Verify UI/maps/sync against restored env lists.
7. Return to catalog mode by re-enabling the three consumer flags + auto-apply after parity looks good.

## Acceptance checklist (crossover soak)

**Prod close-out (2026-09-16):** items 9–10 + identity smoke signed off (no mission_key
duplicates; metadata retained; active/historical membership + labels OK). Item 4
final-sync **drain** still in progress as expected pending backlog — treat
`completed_final_sync_pending` as healthy until failed/exhausted appear.

1. **Status** — Banner: auto-apply + three `*_FROM_CATALOG` true; cadence ~30m; last success advances only on clean runs; partial runs visible separately; write lock idle between jobs.
2. **m231 source-late** — `waiting_for_source` (expected severity) until ERDDAP → `ready`, one live row.
3. **Forced_off** — Audit event with admin actor; public map drops within one job cycle after invalidate.
4. **Completion + final sync** — One WG and one Slocum: COMPLETED, work item → done (or retryable failed without reactivation); history catalog-backed; reopen restores same live row. **Post-rollover:** bulk COMPLETED queue may show many `completed_final_sync_pending` (expected) until batched drain finishes.
5. **Unnumbered planned→active** — ST id only → numbered → start → enroll → source → one live row; forms/instruments stay attached.
6. **Concurrency** — Two applies / provision retries / restart: stable UUIDs; lock prevents double live rows; Team provision returns 409 when busy.
7. **Outage recovery** — Simulated provider failure recovers; failed work item manual retry works.
8. **Rollback** — Export → disable flags → restore env → verify → return to catalog.
9. **Migrations** — Alembic head includes `20260911_catalog_ops` and `20260915_slocum_mk` after duplicate + mission_key orphan repair. ✅ prod 2026-09-16
10. **Historical identity** — Completed Slocum info returns original deployment id; repeated historical loads do not grow row count; labels show in dropdowns while hrefs use storage keys. ✅ prod 2026-09-16

## Leave deferred (compatibility release)

- Keep env overrides as break-glass while comparing env/catalog parity
- Retire WG historical scrape only after COMPLETED backfill parity is clean
- ERDDAP-metadata-only promote — [ADR 0007](../../decisions/0007-erddap-metadata-only-deferred.md)

## Related

- Env: [ENV_VARIABLES.md](../ENV_VARIABLES.md)
- Architecture: [architecture.md](../architecture.md)
- ADR: [0005](../../decisions/0005-mission-catalog-live-keys.md), [0008](../../decisions/0008-catalog-durable-ops-state.md), [0009](../../decisions/0009-historical-identity-display-labels.md)
