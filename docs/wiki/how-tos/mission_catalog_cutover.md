# Mission catalog cutover

Live-key-safe catalog (ADR [0005](../../decisions/0005-mission-catalog-live-keys.md)) stays an **index**. Catalog UUIDs never replace `mission_id`, Slocum `mission_key`, routes, or disk folders.

**Status (2026-09-10):** Empty-env + ST auto-enrollment soaked. Consumer flags on. Team catalog **ops UI** shows readiness/health/enrollment/provision. Slocum source-late (e.g. m231) waits on ERDDAP before active lists. Public map remains opt-in.

## Lifecycle and enrollment

| ST condition | State | Policy (default) |
|--------------|-------|------------------|
| No deployment number | PLANNED | CATALOG_ONLY (workspace only) |
| Numbered, no / future start | PLANNED | CATALOG_ONLY |
| Start reached, no end | ACTIVE | CONTINUOUS (ST `enrollment_authority`) |
| End time set | COMPLETED | ON_DEMAND |

Overrides: `enrollment_override` = `automatic` | `forced_on` | `forced_off` (completion still wins over `forced_on`). WGMS/ERDDAP cannot enroll.

Shadow mode: `MISSION_CATALOG_ENROLLMENT_SHADOW=true` logs would-enroll without writing CONTINUOUS.

## Enablement membership

`list_catalog_sync_targets(platform, session)`:

| Env list | Result |
|----------|--------|
| Non-empty `ACTIVE_*` / historical | Exact env strings (override / fail-safe) |
| Empty + catalog on | Catalog `ACTIVE` ∧ `CONTINUOUS` (+ live-row gates) |
| Catalog off / empty / no session | Env list (possibly empty) |

Live-row gates:

- **Wave Glider:** realtime WGMS source + linked `MissionOverview`
- **Slocum:** ERDDAP identity/source + linked active `SlocumDeployment` (ST-only enrolled missions stay catalog-visible with readiness `waiting_for_source`)

## Ops flags

1. `MISSION_CATALOG_WG_SYNC_FROM_CATALOG=true`
2. `MISSION_CATALOG_AUTO_APPLY=true`
3. `MISSION_CATALOG_SLOCUM_WARM_FROM_CATALOG=true`
4. `MISSION_CATALOG_PUBLIC_MAP_FROM_CATALOG=true`
5. Optional: `MISSION_CATALOG_ENROLLMENT_SHADOW=true` before first ST auto-enroll write soak
6. `MISSION_CATALOG_SYNC_INTERVAL_MINUTES=30` (default; `0` = daily cron only)

## Admin / Team UI

Open `/team/mission-catalog` (admin + `team_hub`):

| Tab | Purpose |
|-----|---------|
| Active / Planned / Completed / Archived | Mission table with platform, policy, **readiness badge**, dates |
| Detail panel | Sources, live rows, ST sync, instruments, dashboard links, **Retry provision**, **enrollment override** |
| Health | Counts + issues (`enrolled_but_not_ready`, `missing_source_links`, `completed_without_archived_live_row`, …) |
| Unmatched | Unmatched ERDDAP inventory |

Status banner: cadence, last success age, auto-apply / consumer flags, leader hint.

### API fallback

- `GET /api/team/mission-catalog/status`
- `GET /api/team/mission-catalog/missions?operational_state=…`
- `GET /api/team/mission-catalog/missions/{uuid}`
- `POST …/enrollment?override=automatic|forced_off|forced_on`
- `POST …/provision`
- `GET /api/team/mission-catalog/health`
- `GET /api/team/mission-catalog/unmatched-sources`

Catalog **apply** remains CLI-only (gate-aware). Slocum soft-archive: admin overviews → Archive Deployment.

## CLI

```powershell
conda activate WorkPython
python -m app.cli.mission_catalog_sync --dry-run
python -m app.cli.mission_catalog_sync --apply
```

## Acceptance checklist (finalize soak)

1. **Status** — Team banner / `/status`: auto-apply + three `*_FROM_CATALOG` flags true; cadence ~30m; last success not stale.
2. **m231 source-late** — Active tab shows `waiting_for_source` until ERDDAP appears; after next apply/interval → `ready`, one linked Slocum deployment, appears in active Slocum UI.
3. **Forced_off** — On a low-risk ACTIVE mission: set `forced_off` → policy leaves `continuous`, drops from active consumers, stays in catalog; restore `automatic` → re-enrolls without a new live row.
4. **Completion / history** — ST-ended Slocum: `COMPLETED` / `ON_DEMAND`, inactive retained deployment (if it had ERDDAP), absent from active lists, present on `GET /api/slocum/available_historical_datasets` when a live row existed; health has no `completed_still_continuous`.
5. **Migrations / leader** — Alembic head `20260909_planned_ws`; one leader schedules catalog job; last-success marker advances after clean apply.
6. **Idempotency** — Two `--apply` runs + two provision retries: stable UUIDs, one overview/deployment per mission.

## Leave deferred (backlog)

- ERDDAP-metadata-only promote/link workflow for unknown platforms — [ADR 0007](../../decisions/0007-erddap-metadata-only-deferred.md)
- ST webhooks (interval reconcile is the current cadence)
- Full historical WG scrape retirement once catalog COMPLETED coverage is complete

## Related

- Env: [ENV_VARIABLES.md](../ENV_VARIABLES.md)
- Architecture: [architecture.md](../architecture.md)
- ADR: [0005](../../decisions/0005-mission-catalog-live-keys.md)
