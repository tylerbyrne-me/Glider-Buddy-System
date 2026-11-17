---
id: BUG-012
type: bug
status: fixed
priority: medium
created: 2026-11-10
tags: [team-ora, sensor-tracker, wave-glider]
---

# ORA Sensor Tracker loadout pulled fleet-wide instruments

## Repro

1. Open Team → Wave Glider ORA request for a hull such as SV3-1121.
2. Click **Load from Sensor Tracker**.
3. Observe many instruments that are not on that Wave Glider, including
   Slocum `sci_*` instruments and other fleet gear.

## Expected

Only instruments currently on that hull (`instrument_on_platform`) and
instruments currently mounted on that hull's own flight/science data loggers
appear in the device table.

## Notes

- `load_tracker_devices` called `fetch_instruments_on_data_logger(identifier)`.
- Logger identifiers such as `science computer` / `flight computer` are
  type-level labels shared across the fleet, so the API returns every matching
  logger's instruments.
- Mission metadata sync already filters by nested `data_logger.id` (and the
  shared helper `pin_relationship_rows` documents the same rule).
- No current-attachment filter was applied, so ended relationships could also
  appear.

## Resolution

2026-11-10: `app/services/team_ora.py` now keeps only currently attached
platform/logger relationships, pins logger instruments with
`pin_relationship_rows` by logger id/serial, and caches one fetch per
identifier. Covered by `test_tracker_loadout_merges_platform_and_logger_instruments`.
