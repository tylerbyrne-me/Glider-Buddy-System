# Mission catalog cutover

Live-key-safe catalog (ADR [0005](../../decisions/0005-mission-catalog-live-keys.md)) stays an **index**. Catalog UUIDs never replace `mission_id`, Slocum `mission_key`, routes, or disk folders.

**Status (2026-08-26):** WG sync / AUTO_APPLY / Slocum warm / public-map consumers soaked. ST lifecycle authority + CONTINUOUS enrollment + enablement v2 shipped (code). **Env lists stay restored until the local empty-env re-soak below passes.** Unmatched ERDDAP review: Team `/team/mission-catalog`.

## Enablement membership

`list_catalog_sync_targets(platform, session)`:

| Env list | Result |
|----------|--------|
| Non-empty `ACTIVE_*` / historical | Exact env strings (override / fail-safe) |
| Empty + catalog on | Catalog `ACTIVE` ∧ `CONTINUOUS` (WG also needs an enabled realtime WGMS source + linked overview; Slocum needs linked `is_active` deployment). Unenrolled in-water missions (e.g. `m230`) stay out |
| Catalog off / empty / no session | Env list (possibly empty) |

Startup cache, WG refresh jobs, and weekly reports in `app.py` also resolve WG keys through this API (env fallback on error).

Does **not** sync ST catalog extras without enrollment. Does **not** auto-CONTINUOUS for every ST-open glider.

## Post-fix apply + enrollment seed (required before empty env)

With **env lists still restored** (so `legacy_env` can seed CONTINUOUS):

```powershell
conda activate WorkPython
python -m app.cli.mission_catalog_sync --dry-run
python -m app.cli.mission_catalog_sync --apply
```

Then verify lifecycle (read-only):

- Catalog `ACTIVE` count should collapse from ~25 wiped historicals toward the real in-water set (enrolled WG + Slocums + any ST-open extras that remain ACTIVE but **unenrolled**).
- Env-listed missions should show `sync_policy=CONTINUOUS`.
- Past missions that share WGMS folders should keep ST `end_time` and `COMPLETED`.

## Slocum active-flag tidy (done locally 2026-08-26)

There is **no UI** for deactivating a `SlocumDeployment` (the model is not in
SQLAdmin and nothing calls `DELETE /api/slocum/deployments/{id}`). Archive via
the API or a one-off DB update with the same semantics
(`is_active=False`, `status="archived"`; do **not** delete rows):

| id | dataset / key | reason | local |
|----|---------------|--------|-------|
| 3 | `fundy_20260621_225` | superseded by `fundy_20260724_229` | archived |
| 4 | `polly_20260519_222` | delayed/recovered; not in water | archived |

Prod needs the same archive when replaying (ids may differ — match on `mission_key`).

## Overview PK hygiene (optional, independent)

```powershell
python -m app.cli.merge_overview_pk_duplicates --dry-run
# review outbox statuses; only then:
python -m app.cli.merge_overview_pk_duplicates --apply
# pending outbox on legacy PKs: investigate, or --force-outbox after review
```

Merges `1070-m211`→`m211`, `1070-m216`→`m216`; deletes empty `1071-m169`, `1071-m209`, stray `1071`. Leaves single legacy `####-m###` rows, `_test`/`_offloads`, `m204_realtime` alone.

## Consumer flag order (local + prod)

Flip one at a time. Restart after each change.

1. `MISSION_CATALOG_WG_SYNC_FROM_CATALOG=true` — **done**
2. `MISSION_CATALOG_AUTO_APPLY=true` — **done**
3. `MISSION_CATALOG_SLOCUM_WARM_FROM_CATALOG=true` — **done**
4. `MISSION_CATALOG_PUBLIC_MAP_FROM_CATALOG=true` — **soaked** (still env ∩ `public_map_enabled` while lists non-empty)

## Emptying `ACTIVE_*` (ops — after apply + enrollment verify)

Attempted 2026-08-26 and rolled back (19 historical WG keys leaked). Retry only after post-fix apply + CONTINUOUS seed:

1. Confirm dry-run gates CLEAN and enablement keys **exactly** match current env lists (parity logs); `m230` stays out.
2. Empty `ACTIVE_REALTIME_MISSIONS` / `ACTIVE_SLOCUM_DATASETS` (and historical when ready) on one host; restart.
3. Watch: sync/warm/public map/startup cache use the enrolled set; no new `data/` trees for ST-only catalog missions.
4. Restore-test: put env lists back; confirm override returns.
5. Restore env lists immediately if anything drifts; then prod.

Keep `REMOTE_MISSION_FOLDER_MAP_JSON` / alias maps as needed until folder resolution is fully catalog-backed.

## Leave off

- Syncing catalog extras (ST missions not enrolled)
- Auto-CONTINUOUS for every ST-open glider
- Renaming single leftover historical overview PKs (`1070-m170`, …)

## Production replay (done 2026-08-24 / 2026-08-25)

Each host applies its own `catalog_mission_id` links (do **not** copy laptop SQLite).

1. Deploy with consumer flags **false**; ensure `config/mission_data_providers.json` is on the host.
2. `python -m app.cli.mission_catalog_sync --dry-run` — first apply on empty catalog shows `created>0`; expect CLEAN and env WG/Slocum 1:1.
3. Inspect Fundy (`m229-Fundy` / `fundy_20260724_229`) for an archived inactive duplicate of the **same** `mission_key`. Prod had two active rows with different keys (m225-era id=3 and current id=6) — no delete. Hard-delete only an empty archived twin of the live key.
4. `--apply` — confirm live-link; dashboards unchanged. Prod: `created=227`, `live_link … slocum=4 ambiguous=0`, Fundy id=6 got `catalog_mission_id`.
5. Post-apply dry-run: `created=0`, CLEAN.
6. Flag order: WG sync → AUTO_APPLY → Slocum warm (restart after each). Completed with no issues 2026-08-25.

## Admin review

- Team `/team/mission-catalog` — read-only unmatched ERDDAP sources (does not create missions)
- Team ops script `mission_catalog_sync` — dry-run only

## Next (backlog)

- Empty `ACTIVE_*` on local then prod after set-equality confirmation (restoreable fail-safe)
- Broader admin runtime mission/config control (Team enroll/unenroll UI)

## Related

- Env reference: [ENV_VARIABLES.md](../ENV_VARIABLES.md)
- Architecture: [architecture.md](../architecture.md)
- Public map: [public_login_map.md](./public_login_map.md)
- Tracking: [in-progress](../../tasks/in-progress.md) / [backlog](../../tasks/backlog.md) / [done](../../tasks/done.md)
- CLI: `python -m app.cli.mission_catalog_sync --dry-run|--apply`
- PK merge: `python -m app.cli.merge_overview_pk_duplicates --dry-run|--apply`
