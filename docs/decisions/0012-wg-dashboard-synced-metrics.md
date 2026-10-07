---
status: accepted
date: 2026-10-07
supersedes: null
---

# Title: Wave Glider dashboard uses synced-first reads and sync-maintained lifetime metrics

## Context

Wave Glider mission dashboards were slow for the same reasons as early PIC forms: default remote WGMS loads, full-history telemetry/power scans just to compute mission distance and observed max battery Wh, fragmented time-window cache keys (SSR 24h vs charts 72h vs background `full_dataset`), eager nine-chart fan-out, and process-local LRU caches that could not see leader sync replacements. Soft refresh was also inactive because `index.html` never set `data-is-realtime`.

## Decision

1. **Default dashboard reads** use an auto path: trusted synced disk under `local_data_base_path` first, remote WGMS only when the synced file is missing/empty. Explicit `source=remote` / `refresh=true` stays upstream-only; admin `source=local` is unchanged.
2. **Lifetime distance and observed max Wh** are persisted in `wave_glider_mission_metrics`, refreshed by the leader after sync (full CSV recompute when file mtime or `calculation_version` changes). Dashboard SSR and summary cards load a **72h** window for telemetry/power and inject the persisted lifetime totals.
3. **Synced cache hits** revalidate against on-disk mtime (no remote incremental probes). Cache-status prefers a synced-file change token so soft refresh follows leader replacements.
4. **Client** loads only the active time-series category on first paint; other categories load on first selection. `data-is-realtime` enables polling.

## Alternatives considered

- **Incremental CSV tail arithmetic for distance** — fragile under WGMS corrections/backfills; rejected in favor of sync-time full recompute into a shared SQLite snapshot.
- **Bulk chart API** — deferred until after synced reads + lazy loading; may revisit if HTTP overhead remains material.
- **Shared Redis/process cache** — larger ops change; synced disk + mtime revalidation is enough for cross-worker freshness of CSV-backed data.

## Consequences

- Fast paint depends on leader sync having populated `data/{mission}/` and metrics rows; missing metrics bootstrap once from synced files.
- PIC observed max remains a **48h** window (ADR 0011); dashboard / metrics table use **mission** peak.
- Operators grep `DASHBOARD_SSR`, `DASHBOARD_SUMMARIES`, `DATA_LOAD`, `WG_MISSION_METRICS` alongside `SLOWREQ`.
