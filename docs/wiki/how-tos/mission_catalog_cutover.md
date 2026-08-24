# Mission catalog cutover

Live-key-safe catalog (ADR [0005](../../decisions/0005-mission-catalog-live-keys.md)) stays an **index**. Catalog UUIDs never replace `mission_id`, Slocum `mission_key`, routes, or disk folders. Enablement still returns exact `.env` strings.

**Status (2026-08-15):** local consumer soak is done (WG sync, AUTO_APPLY, Slocum warm). Dashboards matched unchanged production. Next is **production replay** below. Do **not** copy this laptop’s SQLite.

## Local flag order (done on laptop)

Flip one at a time. Restart after each change. Do not empty `ACTIVE_*` lists or sync the extra ST `m{n}` inventory.

1. `MISSION_CATALOG_WG_SYNC_FROM_CATALOG=true`  
   WG `sync_all_realtime_missions` reads keys via `list_catalog_sync_targets("wave_glider")`. Same `ACTIVE_REALTIME_MISSIONS` strings. Watch: one WG mission, no new `data/` trees, dashboard still matches prod.

2. `MISSION_CATALOG_AUTO_APPLY=true` (after step 1 is uneventful)  
   Leader/startup catalog job writes when gates are clean. CLI `--apply` is unchanged. Watch one run: `created=0`, gates CLEAN, no new `MissionOverview` / `SlocumDeployment` rows. If gates go unclean, set the flag back to `false` and run `python -m app.cli.mission_catalog_sync --dry-run`.

3. `MISSION_CATALOG_SLOCUM_WARM_FROM_CATALOG=true` (after step 2 is uneventful)  
   `warm_active_slocum_datasets` reads keys via `list_catalog_sync_targets("slocum")`. Same `ACTIVE_SLOCUM_DATASETS` / alias strings. Watch Fundy / Sable / Peggy / Sambro mirrors stay 1:1 with prod.

Public map stays env-gated (`ACTIVE_*` ∩ `public_map_enabled`). Leave it last.

## Leave off until after prod soak

- Emptying `ACTIVE_REALTIME_MISSIONS` / `ACTIVE_SLOCUM_DATASETS` / folder-map lists
- Syncing catalog extras (ST missions not in `.env`)
- Auto-CONTINUOUS for every ST-open glider
- Merging leftover historical overview PKs (`m211` vs `1070-m211`)

## Production replay

Commit catalog work as its **own** commit (do not mix theme/chart UI). Each host must apply its own `catalog_mission_id` links.

Deploy code with consumer flags **false**, then:

1. `python -m app.cli.mission_catalog_sync --dry-run` — first apply on an empty catalog will show `created>0`; expect CLEAN gates and env WG/Slocum 1:1. After apply, later dry-runs should show `created=0`.
2. Inspect Fundy (`m229-Fundy` / `fundy_20260724_229`) for an archived inactive `SlocumDeployment` duplicate. Local had an empty id=8; prod may not. Hard-delete only if it has **no** goals/notes/media/SFMC children. Keep the active briefing.
3. `python -m app.cli.mission_catalog_sync --apply` — confirm live-link; Fundy and `m227-SV3-1071` dashboards unchanged.
4. Same flag order as local: WG sync, then AUTO_APPLY, then Slocum warm. Restart after each flag.

Verify after apply: `python -m app.cli.mission_catalog_sync --dry-run` still CLEAN, `created=0`.

## Related

- Env reference: [ENV_VARIABLES.md](../ENV_VARIABLES.md)
- Architecture: [architecture.md](../architecture.md)
- Tracking: [in-progress](../../tasks/in-progress.md) / [backlog](../../tasks/backlog.md)
- CLI: `python -m app.cli.mission_catalog_sync --dry-run|--apply`
