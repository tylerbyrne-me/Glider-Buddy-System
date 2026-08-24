---
id: BUG-006
type: bug
status: fixed
priority: medium
created: 2026-08-14
tags: [slocum, erddap, mirror, ui]
---

# Slocum badge says “ERDDAP unreachable” after a successful realtime pull

## Repro

1. Reboot / restart the app so startup syncs Slocum mirrors from ERDDAP.
2. Confirm realtime parquet under `data_store/slocum_cache/` has recent rows (sync succeeded).
3. Open a Slocum mission dashboard (default last-24h window ending at now).
4. Source badge shows **Cached data — ERDDAP unreachable**.

## Expected

After a successful ERDDAP pull, the badge should read **Source: 72h mirror**. “ERDDAP unreachable” is only for a live fetch that actually failed (`fallback_error`).

## Notes

Interactive `get_bundle_dataframe` prefers the rolling 72h mirror over another ERDDAP round-trip when parquet already overlaps the window. Display windows end at wall-clock now, so `mirror_max` is almost always a few minutes (or a surfacing interval) behind → metadata `stale: true` with **no** `fallback_error`.

`setSlocumDataSourceBadge` treated `stale || fallback_error` as an outage (BUG-004 UI). That conflates “last sample ≠ now” with “ERDDAP is down.”

## Resolution

Fixed 2026-08-14. Badge keys the outage label on `fallback_error` only. `stale` without that field keeps the normal source label and a tooltip that the mirror tail is behind the requested window.
