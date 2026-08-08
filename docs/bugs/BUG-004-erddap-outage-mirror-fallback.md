---
id: BUG-004
type: bug
status: fixed
priority: high
created: 2026-08-07
tags: [slocum, erddap, mirror, overage, cache, resilience]
---

# ERDDAP outage blanks dashboard despite 72h mirror cache

## Repro

1. Confirm a Slocum dataset has a populated rolling mirror under `data_store/slocum_cache/` (`slocum_mirror_retention_hours` default **72**).
2. Break or block ERDDAP (network drop, upstream timeout, 5xx).
3. Open the Slocum mission dashboard (or chart/map APIs) for a normal recent window (e.g. last 24–72h).
4. Observe empty charts / 502 “Data fetch failed” even though mirror parquet still has data.

## Expected

Serve the best available **disk mirror** (and any valid overage parquet) for the requested window when ERDDAP is unreachable. Degrade gracefully: show cached data, optionally flag `data_source: mirror` / stale tail, do not hard-fail the whole request.

## Notes

Suspected failure chain (interactive path: `_load_bundle_result` → `get_cached_or_fetch_bundle_df` → `get_bundle_dataframe`):

1. **Strict mirror coverage** — `mirror_covers_window` requires `mirror_max >= requested_end − 1m`. Display windows end at “now” (rounded), so a healthy mirror that is minutes behind always fails coverage → overage/ERDDAP path (`app/platforms/slocum/overage_cache.py`).

2. **Overage miss hits live ERDDAP** — `_populate_overage_entry` → `_fetch_overage_window` → `_fetch_raw_bundle`. On connection errors this raises (or hangs until `ERDDAP_TIMEOUT`) instead of returning partial mirror.

3. **Gap fill hits ERDDAP again** — `_finalize_bundle_merge` may call `_fetch_overage_window` when the merged slice is empty / mirror tail is short of `requested_end`, even after an overage cache hit.

4. **Fallback re-syncs before reading disk** — `cache_service.get_cached_or_fetch_bundle_df` exception handler calls `ensure_mirror_synced(...)` before `load_mirror_df`. That sync path waits on ERDDAP again (`sync_dataset_mirror` / `_fetch_raw_bundle`), so the “serve mirror” fallback can hang or fail during an outage instead of immediately slicing existing parquet.

5. **Historical windows** — `parse_slocum_time_window` / `_compute_sync_window` call `fetch_dataset_time_extent` (ERDDAP metadata) for historical datasets; outage can block window resolution before any mirror read.

### Likely fix direction

- On ERDDAP failure: **always** fall back to `load_mirror_df` + slice (and expired-but-present overage files if useful); never require a successful sync first.
- Treat near-coverage as usable: if mirror overlaps the window, return the overlap with metadata (`stale`, `mirror_max`, `requested_end`) rather than forcing overage.
- Skip `_finalize_bundle_merge` live gap fetch when ERDDAP is known down / fetch raises; merge what is on disk only.
- Surface a clear UI banner: “Showing cached data; ERDDAP unreachable.”

## Resolution

Fixed 2026-08-08.

- `get_bundle_dataframe` prefers partial mirror overlap (with `stale` / `mirror_max` metadata) over live ERDDAP when the rolling mirror already covers part of the window; interactive reads skip `ensure_mirror_synced` when parquet already has rows.
- Gap-fetch / overage populate failures fall back to mirror overlap; `cache_service` reads mirror first on exceptions and also recovers empty primary results from on-disk mirror.
- Chart/profile endpoints use anchored-end display slices; map timeout falls back to `load_mirror_df`.
- Dashboard badge shows “Cached data — ERDDAP unreachable” when `stale` or `fallback_error` is set.
- Coverage: `tests/test_slocum_mirror_fallback.py`.
