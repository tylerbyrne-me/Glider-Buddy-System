---
id: BUG-013
type: bug
status: fixed
priority: medium
created: 2026-11-17
tags: [station-offloads, mission-id]
---

# Offload log Mission ID overwrite affected every attempt for the station

## Repro

1. Open Station Offload Status for a station with multiple attempts (e.g. HFX273).
2. On one recent log card, set **Station Offload Mission ID** to a glider/mission (e.g. `m227-SV3-1071`) and save.
3. Observe other log cards (including older/failed attempts) show the same mission ID.

## Expected

Each offload attempt keeps its own mission attribution (e.g. failed attempt on 1070, successful attempt on 1071). Station Info **Current** mission remains a separate station-level field.

## Notes

Recent cards were binding and saving against `StationMetadata.last_offload_by_glider` (one value per station), not the log row. Helper text even said the field was station-level.

## Resolution

2026-11-17:

- Per-log `mission_id` on create/update maps to sheet-style `parser_session_ref` (`{mission}:station_offload_sheet:{station}`) via `app/core/offload_comments.py`.
- Recent cards show/save `log.mission_id` only; station `last_offload_by_glider` is updated only when editing the latest attempt (or on create with a mission).
- Non-sheet parser session refs are not clobbered.
