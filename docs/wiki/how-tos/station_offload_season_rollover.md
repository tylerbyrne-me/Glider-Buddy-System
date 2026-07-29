# Station offload and field season (operator runbook)

## Mental model: registry + tagged events

- **`station_metadata` is the single source of truth** for each `station_id`: current serial, modem, settings, coordinates, notes (admin-curated). A row stays for the life of that ID.
- **`is_retired`** means the ID is no longer deployed. The row is kept so offload history and foreign keys remain valid. Do not hard-delete stations that have offload logs.
- **`field_season_year` on `station_metadata`** is **deprecated**. Season belongs on **`offload_logs.field_season_year`** and on **`field_seasons`**, not on the registry row.
- **`is_archived` on `station_metadata`** is a **legacy** flag from the old “close season = archive the fleet” workflow. Season close no longer sets it. A DB migration clears it for normal operation; it is still honored as “read-only” if ever set.

## Season selector in the UI

- Choosing a **season** filters which **offload logs** drive per-station summaries (success, latest VRL, etc.).
- The **grid always shows the live registry** (non-retired rows): hardware and settings columns reflect the current row, not a historical roster.

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
