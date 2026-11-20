# Station offload and field season (operator runbook)

## Mental model: registry + tagged events

- **`station_metadata` is the single source of truth** for each `station_id`: current serial, modem, settings, coordinates, notes (admin-curated). A row stays for the life of that ID.
- **Per-attempt Mission ID** lives on each `offload_log` (`mission_id` API field → sheet-style `parser_session_ref`). Station Info **Station Offload Mission ID (Current)** is only `last_offload_by_glider` for overview/status — editing one log must not rewrite other attempts ([BUG-013](../../bugs/BUG-013-offload-log-mission-id-overwrites-all.md)).
- **VRL filenames** are per log. WG-VM4 attach fills blank `vrl_file_name` only on a **time-matched** attempt; it must not fall back to an arbitrary older blank log on the station ([BUG-014](../../bugs/BUG-014-vm4-vrl-attach-overwrote-older-logs.md)).
- **VRL mis-attach audit:** `python -m app.cli.audit_offload_vrl_attach` (dry-run; `--station HFX273`; `--csv …`; `--apply` after review) — see BUG-014. VRL attach never overwrites a non-blank `vrl_file_name`; failed attempts with a VRL are highlighted by the mission audit (`failed_with_vrl`).
- **Mission ID audit (VM4 folder as ground truth):** `python -m app.cli.audit_offload_mission_id --mission m227-SV3-1071` / `--all-local-vm4` / `--station HFX231`; `--apply` rewrites blank/sheet refs only — [BUG-015](../../bugs/BUG-015-offload-mission-id-misattribution.md).
- **Unified consistency dry-run (preferred first pass):** `python -m app.cli.audit_offload_consistency` — runs both audits, prints one summary, optional `--csv-dir` for linked CSVs. Does **not** apply; use the dedicated CLIs with `--apply` after review (see [operator handoff](#operator-handoff-offload--vm4-fixes) below).
- **Admin sheet “Process VM4”** (`run_vm4_background_pipeline`): VRL + remote health attach only. Info CSV load is **full-file** (not checkpoint-windowed) so blank VRLs after an audit clear can refill on reprocess — same sessions remote health already sees. Checkpoint rows still record last run time/row counts.

- **Rename `station_id` (admin):** use **Rename ID** on Station Offload Status (or `POST /api/station_metadata/{station_id}/rename`). Re-keys the registry row and moves offload logs, flag events, hardware history, and season snapshots in one transaction; sheet-style `parser_session_ref` suffixes are rewritten. Refuses if the target ID already exists (no merge). Prefer rename over delete/recreate for typos or naming-convention changes so history stays attached.
- **`is_retired`** means the ID is no longer deployed. The row is kept so offload history and foreign keys remain valid. Do not hard-delete stations that have offload logs.
- **`field_season_year` on `station_metadata`** is **deprecated**. Season belongs on **`offload_logs.field_season_year`** and on **`field_seasons`**, not on the registry row.
- **`is_archived` on `station_metadata`** is a **legacy** flag from the old “close season = archive the fleet” workflow. Season close no longer sets it. A DB migration clears it for normal operation; it is still honored as “read-only” if ever set.

## Season selector in the UI

- Choosing a **season** filters which **offload logs** drive per-station summaries (success, latest VRL, etc.).
- The **grid always shows the live registry** (non-retired rows): hardware and settings columns reflect the current row, not a historical roster.

## Progress map

Station offload progress is shown as tiny Leaflet `circleMarker`s (no clustering). Colors are map-only (table row colors stay as today):

| Color | Meaning |
|-------|---------|
| Green | Offloaded |
| Yellow | Skipped or flagged |
| Red | Failed offload |
| White | Awaiting offload (includes hardware-swapped awaiting first offload) |

Stations without `deployment_latitude` / `deployment_longitude` are omitted.

### Season context (map + default overview)

Both the home/dedicated map layer (`GET /api/map/stations/offload-status`) and the Station Offload Status overview when no season is selected use `StationSeasonService.resolve_operational_season_context`:

1. **Active open season** (`is_active` and not closed) — e.g. 2026 mid-season, or 2027 after it is opened.
2. Else **most recent closed season** — e.g. after closing 2026 in November while an inactive 2027 shell may already exist; keep showing 2026 until 2027 is set active.
3. Else newest season row / none.

GeoJSON `meta` includes `season_year`, `season_is_closed`, and `season_source` (shown on the map status line).

### Surfaces

1. **WG home map layer** — toggle **Offload status** under Station Offloads (gated by `station_offloads`). Data: `GET /api/map/stations/offload-status` (GeoJSON). Popup links to the offload sheet (`?station=`).
2. **Dedicated page** — `/wave-glider/station_progress_map.html` (new tab): active WG mission track toggles + All/None, hours-back select, array-prefix filters, and the same station layer. Linked from Station Offload Status and the WG-VM4 dashboard card.
3. **Public login map** — deferred (auth GeoJSON only for now).

JS: `web/static/js/station_offload_map_layer.js` (shared), `station_progress_map.js` (dedicated page).

## Closing a field year

1. Confirm the **`field_seasons`** row for that operational year.
2. **Close the season** (admin): writes an immutable **`station_metadata_season_snapshots`** row per registry station (audit), stamps open offload logs to that year where appropriate, computes **`summary_statistics`** on the season, and marks the season closed.
3. **No** mass-archive of `station_metadata`. Operators continue editing the same registry for the next year.

## CSV and master list

- **Upload CSV** / **master list import**: bulk **registry** upsert. They do not attach `field_season_year` to station rows. Optional query `season_year` only checks that the season exists.
- **Master list export**: current **non-retired** registry; the year in the URL is for naming/compatibility only.

## Historical / analytics

- Closed-season **summary statistics** prefer **snapshots** for roster shape when present; otherwise station IDs come from that season’s **logs**.
- **`station_hardware_history`** remains the time axis for serial/modem changes; the registry row is “as of now.” Serial→station search (`find_station_by_serial`, mission-ID audit) still uses **current** serial only — pre-swap serials in VM4 CSVs can show `no_station` even when logs exist under the station ID; historical resolve is backlog (2026-11-18).

## Testing / destructive endpoints

- **Delete season** (testing): removes that season’s **logs** and **snapshots**; does **not** delete `station_metadata` or hardware history.

## Operator handoff: offload / VM4 fixes

Operator-owned: **you** commit, deploy, and run any production DB `--apply`. Agents do not commit or touch prod.

### Suggested git commit paths (offload stack only)

Stage these for the offload/VM4 commit; leave unrelated `app/core/mission_catalog/*`, ADR-0016, and mission-catalog UI dirties for a separate commit.

**Code / tests**

- `app/core/offload_comments.py`
- `app/core/stations/wg_vm4_station_service.py`
- `app/core/stations/vrl_filename.py`
- `app/routers/station_metadata.py` (per-log mission / related station API only — review the diff)
- `web/static/js/view_station_status.js`
- `web/static/js/wg_vm4.js`
- `web/templates/view_station_status.html`
- `app/cli/audit_offload_vrl_attach.py`
- `app/cli/audit_offload_mission_id.py`
- `app/cli/audit_offload_consistency.py`
- `app/services/offload_vrl_audit.py`
- `app/services/offload_mission_audit.py`
- `app/services/offload_consistency_audit.py`
- `app/services/test_offload_log_mission_id.py`
- `app/services/test_offload_vrl_audit.py`
- `app/services/test_offload_mission_audit.py`
- `app/services/test_offload_consistency_audit.py`
- `app/services/test_wg_vm4_vrl_attach.py`

**Docs**

- `docs/bugs/BUG-013-offload-log-mission-id-overwrites-all.md`
- `docs/bugs/BUG-014-vm4-vrl-attach-overwrote-older-logs.md`
- `docs/bugs/BUG-015-offload-mission-id-misattribution.md`
- `docs/bugs/README.md`
- `docs/tasks/backlog.md` / `docs/tasks/done.md` (offload-related lines only)
- `docs/wiki/how-tos/station_offload_season_rollover.md`

Do **not** commit local audit CSV dumps under `data_store/tmp_*` or a copied prod `app_data.sqlite`.

### Deploy reminder

After your deploy: `sudo systemctl restart gliderbuddy.service` so VRL attach guards and per-log Mission ID UI are live **before** re-running WG-VM4 processing or DB cleanup.

### Production DB remediation (2025–26 missions)

Requires mission VM4 CSVs on disk for `m219-SV3-1121`, `m223-SV3-1121`, `m227-SV3-1071`, `m230-SV3-1070`. Use the host conda env (`buddyenv` / WorkPython as appropriate).

1. **Backup** `app_data.sqlite` (+ `-wal` / `-shm` if present) to a dated path.
2. **Unified dry-run** (preferred):

```bash
python -m app.cli.audit_offload_consistency \
  --mission m219-SV3-1121 --mission m223-SV3-1121 \
  --mission m227-SV3-1071 --mission m230-SV3-1070 \
  --csv-dir data_store/tmp_offload_consistency_prod
```

3. **VRL apply** (stamp mismatches only; leave near-duplicate-only unless reviewed):

```bash
python -m app.cli.audit_offload_vrl_attach --csv data_store/tmp_vrl_audit_prod.csv
python -m app.cli.audit_offload_vrl_attach --apply --reasons vrl_stamp_far_from_log_time
```

4. **Mission apply** (blank/sheet missing + mismatch only):

```bash
python -m app.cli.audit_offload_mission_id \
  --mission m219-SV3-1121 --mission m223-SV3-1121 \
  --mission m227-SV3-1071 --mission m230-SV3-1070 \
  --csv data_store/tmp_mission_audit_prod.csv
python -m app.cli.audit_offload_mission_id \
  --mission m219-SV3-1121 --mission m223-SV3-1121 \
  --mission m227-SV3-1071 --mission m230-SV3-1070 \
  --apply --reasons mission_mismatch,mission_missing
```

5. **Retest** with the same `audit_offload_consistency` command — expect **0** `mission_applyable` and **0** (or unchanged intentional) VRL stamp mismatches. Remaining `no_station` / `no_matching_log` are accepted for now (historical serial backlog).
6. Do **not** run `--all-local-vm4 --apply` in this pass (legacy folder noise).
7. Spot-check UI: HFX273 Nov success keeps its VRL; a few stations show per-log Mission IDs; station **Current** mission stays independent.
8. Keep parser notes (`[VRL_AUDIT_CLEARED …]`, `[MISSION_AUDIT_SET …]`) as the audit trail.

Local laptop copy already exercised this path (14 VRL clears; 464 mission stamps on those four missions). Treat prod as a fresh dry-run → apply → retest — counts may differ if the DB moved on.

## What changed from the old workflow

- Season close **no longer** archives every station or forces a CSV-driven “new roster table” for the next year.
- Snapshots are **audit / statistics**, not the primary driver of the status grid.
- Retire IDs with **`is_retired`** (e.g. via admin / SQLAdmin) instead of treating “closed year” as archived fleet.
