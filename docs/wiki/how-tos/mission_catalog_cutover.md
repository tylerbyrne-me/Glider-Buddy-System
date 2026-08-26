# Mission catalog cutover

Live-key-safe catalog (ADR [0005](../../decisions/0005-mission-catalog-live-keys.md)) stays an **index**. Catalog UUIDs never replace `mission_id`, Slocum `mission_key`, routes, or disk folders. Enablement still returns exact `.env` strings.

**Status (2026-08-25):** local and production consumer soaks are done. Prod: `--apply` (Fundy id=6 linked; no archived duplicate of `fundy_20260724_229`), post-apply dry-run `created=0` / CLEAN, then WG sync → AUTO_APPLY → Slocum warm with no issues. Public map and `ACTIVE_*` retirement remain later.

## Consumer flag order (local + prod — done)

Flip one at a time. Restart after each change. Do not empty `ACTIVE_*` lists or sync the extra ST `m{n}` inventory.

1. `MISSION_CATALOG_WG_SYNC_FROM_CATALOG=true`  
   WG `sync_all_realtime_missions` reads keys via `list_catalog_sync_targets("wave_glider")`. Same `ACTIVE_REALTIME_MISSIONS` strings. Watch: only env WG missions, no new `data/` trees.

2. `MISSION_CATALOG_AUTO_APPLY=true` (after step 1 is uneventful)  
   Leader/startup catalog job writes when gates are clean. CLI `--apply` is unchanged. Watch one run: `created=0`, gates CLEAN, no new `MissionOverview` / `SlocumDeployment` rows. If gates go unclean, set the flag back to `false` and run `python -m app.cli.mission_catalog_sync --dry-run`.

3. `MISSION_CATALOG_SLOCUM_WARM_FROM_CATALOG=true` (after step 2 is uneventful)  
   `warm_active_slocum_datasets` reads keys via `list_catalog_sync_targets("slocum")`. Same `ACTIVE_SLOCUM_DATASETS` / alias strings.

Public map stays env-gated (`ACTIVE_*` ∩ `public_map_enabled`). Leave it last.

## Leave off until set-equality soak after public-map consumer

- Emptying `ACTIVE_REALTIME_MISSIONS` / `ACTIVE_SLOCUM_DATASETS` / folder-map lists
- Syncing catalog extras (ST missions not in `.env`)
- Auto-CONTINUOUS for every ST-open glider
- Merging leftover historical overview PKs (`m211` vs `1070-m211`)

## Production replay (done 2026-08-24 / 2026-08-25)

Each host applies its own `catalog_mission_id` links (do **not** copy laptop SQLite).

1. Deploy with consumer flags **false**; ensure `config/mission_data_providers.json` is on the host.
2. `python -m app.cli.mission_catalog_sync --dry-run` — first apply on empty catalog shows `created>0`; expect CLEAN and env WG/Slocum 1:1.
3. Inspect Fundy (`m229-Fundy` / `fundy_20260724_229`) for an archived inactive duplicate of the **same** `mission_key`. Prod had two active rows with different keys (m225-era id=3 and current id=6) — no delete. Hard-delete only an empty archived twin of the live key.
4. `--apply` — confirm live-link; dashboards unchanged. Prod: `created=227`, `live_link … slocum=4 ambiguous=0`, Fundy id=6 got `catalog_mission_id`.
5. Post-apply dry-run: `created=0`, CLEAN.
6. Flag order: WG sync → AUTO_APPLY → Slocum warm (restart after each). Completed with no issues 2026-08-25.

## Next (backlog)

- Catalog unmatched ERDDAP admin UI
- Public login map via enablement (last consumer)
- Retire `ACTIVE_*` membership authority after set-equality
- Optional historical overview PK merges

## Related

- Env reference: [ENV_VARIABLES.md](../ENV_VARIABLES.md)
- Architecture: [architecture.md](../architecture.md)
- Tracking: [in-progress](../../tasks/in-progress.md) / [backlog](../../tasks/backlog.md) / [done](../../tasks/done.md)
- CLI: `python -m app.cli.mission_catalog_sync --dry-run|--apply`
