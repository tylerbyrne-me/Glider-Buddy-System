# Station offload and field season (operator runbook)

## Mental model: registry + tagged events

- **`station_metadata` is the single source of truth** for each `station_id`: current serial, modem, settings, coordinates, notes (admin-curated). A row stays for the life of that ID.
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
- **`station_hardware_history`** remains the time axis for serial/modem changes; the registry row is “as of now.”

## Testing / destructive endpoints

- **Delete season** (testing): removes that season’s **logs** and **snapshots**; does **not** delete `station_metadata` or hardware history.

## What changed from the old workflow

- Season close **no longer** archives every station or forces a CSV-driven “new roster table” for the next year.
- Snapshots are **audit / statistics**, not the primary driver of the status grid.
- Retire IDs with **`is_retired`** (e.g. via admin / SQLAdmin) instead of treating “closed year” as archived fleet.
