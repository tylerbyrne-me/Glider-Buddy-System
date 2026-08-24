# ERDDAP poke (new-data probe)

Cheap Ocean Track `allDatasets` `maxTime` check so Buddy only does a heavy cache refresh when ERDDAP’s tail advanced. **Shipped for Slocum realtime.** Wave Glider realtime is **not** on ERDDAP yet — do not wire a WG refresh adapter until that changes.

## Today (Slocum)

| Piece | Where |
|-------|--------|
| Probe + Slocum refresh | [`app/platforms/slocum/erddap_poke.py`](../../../app/platforms/slocum/erddap_poke.py) |
| Leader job | `slocum_erddap_poke_job` (default every **90** min, `SLOCUM_ERDDAP_POKE_INTERVAL_MINUTES`) |
| Admin | Manage Slocum Mission Overviews → **Check ERDDAP now** → `POST /api/slocum/erddap-poke` |
| Membership | Same warm keys as startup (`ACTIVE_SLOCUM_DATASETS` / aliases; optional catalog enablement) |
| Known tail | Parquet `meta.json` `last_data_timestamp`, else last poked `erddap_max_time` |
| On new data | Incremental `sync_dataset_mirror` (dashboard / CTD / checklist bundles) |
| Startup | Still a **full** warm — poke is the scheduled path only |

Ops cadence this was sized for: glider→SFMC ~every 4–8h; Ocean Track processes new files ~every 3h. The poke is cheap (one `allDatasets` query for the active set, `orderByMax` only if a row has no `maxTime`). A failed poke does **not** fall back to a full pull.

Slocum dashboard/mirror details: [slocum.md](./slocum.md). Env: [ENV_VARIABLES.md](../ENV_VARIABLES.md) (`SLOCUM_ERDDAP_POKE_INTERVAL_MINUTES`).

Logs: `SLOCUM POKE:` / `AUTOMATED: Slocum ERDDAP poke finished`.

## Later: Wave Glider when realtime lands on ERDDAP

Treat ERDDAP as a **source**, not a Slocum feature. The probe (server + dataset IDs → `maxTime` vs known tail) is already platform-neutral. Only “what do we refresh?” is platform-owned.

**Do not** wait for this to invent a shared ERDDAP parquet format, or route WG dashboards through `data_store/slocum_cache/`.

### What is already shared

- Ocean Track provider `oceantrack_erddap` in [`config/mission_data_providers.json`](../../../config/mission_data_providers.json) — same server, `dataset_id_filter` `.*(_realtime|_delayed)$`, notes already say WG and Slocum share it.
- Catalog naming: [`build_erddap_dataset_candidates`](../../../app/core/mission_catalog/naming.py) / `parse_erddap_dataset_id` already emit/parse WG `prefix_YYYYMMDD_n_{realtime|delayed}`.
- Generic tabledap: [`app/core/data/erddap_tabledap.py`](../../../app/core/data/erddap_tabledap.py) (`list_tabledap_datasets`, `fetch_tabledap_track`). Still defaults `server` to `slocum_erddap_server` and reuses the Slocum client for that URL — pass `server=` from the provider manifest when a second host appears.
- Team hexbin already pulls **historical / catalog** WG tracks from ERDDAP (`source_filter=erddap|all` via `catalog_mission_sources`). That is **not** a live dashboard refresh and must not become the poke’s refresh adapter.

### What WG live data does today

Realtime WG still comes from **WGMS remote folders** (`REMOTE_DATA_URL` / `output_realtime_missions`) into `data/{mission_id}/`, warmed by `sync_all_realtime_missions` on the Wave Glider cache interval (`BACKGROUND_CACHE_REFRESH_INTERVAL_MINUTES`, default 60). Dashboards read that CSV cache via `data_service`, not ERDDAP.

Until Ocean Track publishes **realtime** WG tabledap for missions Buddy operates, leave that path alone. Catalog ERDDAP rows for WG (delayed / extras) are inventory + hexbin, not poke membership.

### Recommended split (when a live WG ERDDAP mission exists)

```text
membership (env keys, then catalog enablement)
        ↓  ERDDAP dataset IDs, grouped by server / provider_key
core probe  — allDatasets maxTime (lift from slocum/erddap_poke.py)
        ↓  has_new?
platform refresh adapter
   slocum      → incremental parquet mirror (already shipped)
   wave_glider → write whatever the WG dashboard already reads
```

| Layer | Owns | Must not own |
|-------|------|----------------|
| Core probe | Server URL, dataset IDs, one `allDatasets` query, `maxTime` vs known tail, epsilon | Parquet layout, WGMS CSVs, chart columns |
| Slocum adapter | `meta.json` / parquet existence, `sync_dataset_mirror`, historical skip | ERDDAP HTTP |
| WG adapter (future) | Known tail + refresh into `data/` (or a WG-owned cache) | Slocum mirror helpers |

**Known tail for WG (pick when implementing, do not invent early):**

1. Last timestamp already in the mission CSV cache (`data_service` / last_data_timestamp), or
2. A small sidecar next to `data/{mission_id}/` (same fields as Slocum poke: `erddap_max_time`, `last_poke_timestamp`), or
3. Catalog source metadata if you start persisting last-seen `maxTime` on `catalog_mission_sources`.

Compare with the same ~1s epsilon as Slocum (`has_new_erddap_data`).

**Refresh for WG (pick when you know the live path):**

- If dashboards still consume WGMS CSVs: poke may only *notice* ERDDAP; a WGMS sync is a different source and a different tail. Do not assume ERDDAP `maxTime` means the CSV folder moved.
- If that mission’s live path **is** ERDDAP: write into the existing `data/{mission_id}/` incremental sync (or a dedicated WG ERDDAP cache under `data_store/`). Reuse `erddap_tabledap.fetch_tabledap_data` + WG processors — not `sync_dataset_mirror`.
- Mixed era (some missions WGMS, some ERDDAP): membership is per `catalog_mission_sources` row (`source_kind=erddap` vs `wgms_remote`), not “all active WG missions.”

### Membership and job

Follow [ADR 0005](../../decisions/0005-mission-catalog-live-keys.md): keep env key strings until catalog enablement soaks.

1. First WG ERDDAP consumer: explicit dataset IDs or catalog `source_kind=erddap` ∩ `platform_family=wave_glider` ∩ live enablement (same idea as hexbin, but **active realtime only**).
2. After Slocum + WG both poke: lift probe into `app/core/data/` next to `erddap_tabledap.py`; rename job/setting to `system_erddap_poke_job` / `ERDDAP_POKE_INTERVAL_MINUTES`; keep Slocum admin button as a thin call. One job, one `allDatasets` query per server, then dispatch to adapters.
3. Do **not** add a second 90-minute WG job that re-queries the same Ocean Track `allDatasets`.

Admin “check now” for WG can wait until there is a cache to refresh; Team is a reasonable home if it stays source-level.

### Checklist when the first realtime WG dataset appears

1. Confirm Ocean Track `allDatasets` `maxTime` moves when new files are processed (same ~3h cadence or document the new one).
2. Confirm the Buddy live key (`m###` / `m###-SV3-####`) ↔ ERDDAP dataset id (catalog identity + alias if needed).
3. Decide the refresh target (`data/` vs new cache). Do not reuse `slocum_cache`.
4. Extract core probe; add `app/platforms/wave_glider/` adapter (or a focused module next to `summaries.py`).
5. Gate WG poke on that mission having an ERDDAP source — leave WGMS-only missions on the existing 60-minute folder sync.
6. Update this page, [architecture](../architecture.md), and [ENV_VARIABLES](../ENV_VARIABLES.md). Move the backlog line to done.

### Explicit non-goals (until then)

- Do not poke every catalog ERDDAP extra (~225 inventory-only ST leftovers).
- Do not call Slocum `warm_active_slocum_datasets` / parquet sync for WG IDs.
- Do not rename `slocum_erddap_server` until a second server exists; the setting is the Ocean Track base URL, poorly named.
- Do not change Wave Glider `BACKGROUND_CACHE_REFRESH_INTERVAL_MINUTES` because of the Slocum poke.
