# VMT Team log book

Admin Team tool for **Vemco Mobile Transceiver (VMT)** inventory: serial/tag metadata, battery checks, InnovaSea/service history, Sensor Tracker sync, and live deployment/use accounting.

VMTs are self-powered and self-logging — they do not stream diagnostics into Buddy like other sensors. This log book replaces the year-to-year spreadsheet.

## Access

- Feature toggle: `team_hub` (same as the rest of Team)
- Role: admin
- URL: `/team/vmt-logbook` (also listed on `/team` as **VMT log book**)

## What is stored locally (SQLite)

| Table | Purpose |
|-------|---------|
| `vmt_units` | One row per physical VMT (SN unique). Soft-retire via `is_active`; never deleted when ST linkage is lost. |
| `vmt_battery_checks` | Append-only battery readings (date, days %, notes) |
| `vmt_service_events` | Append-only service / InnovaSea work |
| `vmt_unit_audit_log` | Field-level before/after when unit metadata is patched |

Custody (when **not** currently attached in Sensor Tracker): On loan, COVE, Servicing, Missing, Lost, Other (+ free text).

## Sensor Tracker linkage

- VMTs are ST **instruments** with `identifier = vmt` (case-insensitive), distinguished by **serial**.
- Example: `id=336, identifier=vmt, serial=1540753, short_name=hydrophones`.
- **Sync from Sensor Tracker** (dry-run then apply) discovers those instruments, creates missing local units, refreshes linkage, and marks `not_found` when a previously linked serial disappears — **local history is retained**.
- Detail **Sensor Tracker accounting** reuses the same helpers as the [Sensor Tracker Team browser](./sensor_tracker_team_browser.md): service time (days at sea / attached / shelf) plus attachment history.

## Typical workflow

1. Seed spreadsheet inventory (once):

```powershell
conda activate WorkPython
python -m app.cli.vmt_logbook_seed --dry-run
python -m app.cli.vmt_logbook_seed --apply
```

2. Apply Alembic migration if needed: `alembic upgrade head` (revision `20260827_vmt_logbook`).

3. Open Team → **VMT log book** → **Sync from Sensor Tracker (dry-run)** → **Apply sync**.

4. Ongoing: **Add VMT**, edit custody/comments, append battery checks and service events.

CLI sync mirror:

```powershell
python -m app.cli.vmt_logbook_sync --dry-run
python -m app.cli.vmt_logbook_sync --apply
```

## Editing notes

- Detail **Field audit** shows a readable list of what changed (label + new value), not raw JSON. Full before/after remains in SQLite.
- The edit form **Active** checkbox soft-retires a unit. Inactive units are hidden from the default inventory list — use **Show inactive** to find them again and re-check Active to restore.
- Sync dry-run matches by serial: `create` = new, `update`/`unchanged` = already present (no duplicate rows).

## Code map reference

A69-9001 = MAP-114 — Tx: H power only, random ping interval centered on 2 min (60–180 s). Shown on the page; stored per unit (default `A69-9001`).

## What it does not do (v1)

- No writes to Sensor Tracker / outbox
- No automated battery decay estimates
- No scheduled background ST sync (on-demand only)
- No public / non-admin access
