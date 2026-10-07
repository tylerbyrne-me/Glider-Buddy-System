# Slocum dashboard performance baseline

Repeatable cold/warm checks after Slocum dashboard load-path changes. Use WorkPython locally or production journal as available.

## What to record

| Scenario | Measure |
|----------|---------|
| Cold SSR (`/slocum?dataset=…`) | `SLOCUM_DASHBOARD_SSR` + nested `SLOCUM_DASHBOARD_SUMMARIES` duration; enabled cards |
| First chart open (lazy) | One `SLOCUM_CHART_BULK` (or CTD profile) for the opened category only |
| Warm soft refresh | After mirror sync/touch: poll → summary + already-loaded categories only |
| Cache status poll | `SLOCUM_CACHE_STATUS` stays sub-second; no parquet parse |

## Journal greps

```bash
sudo journalctl -u gliderbuddy --since "10 min ago" | grep -E \
  'SLOCUM_DASHBOARD_SSR|SLOCUM_DASHBOARD_SUMMARIES|SLOCUM_CACHE_STATUS|SLOCUM_CHART_BULK|SLOCUM MIRROR|SLOWREQ|APP5XX'
```

## Browser checks

1. Open `/slocum?dataset=<active>` — confirm `data-is-realtime="true"` on `<body>`; Network: overview SSR only until a sensor tab is opened.
2. Open CTD (or Power) — one chart/bulk request; Source badge shows mirror vs ERDDAP/overage.
3. With auto-refresh on, wait for the 60s poll (`/api/slocum/cache-status/...`). Soft refresh should run only when `last_data_timestamp` **or** per-bundle `cache_timestamp` (file mtime) advances.
4. Touch a mirror parquet without advancing the data tail (schema rewrite) — expect refresh from mtime alone.
5. Historical `/slocum/historical?dataset=…` — `data-is-realtime="false"`; no cache polling.

## Expected after 2026-10-07 conformity

- Chart default remains **24 hours**; rolling mirror retention stays **72 hours**.
- Cache status is metadata-only (`meta.json` + `stat()`); no `load_mirror_df` on poll.
- Summaries load each unique mirror bundle once per request (dashboard cards share one frame).
- Client single-flight / generation guards coalesce identical CTD, category, and summary refreshes; only the newest generation updates UI.
- No Slocum lifetime-metrics table (distance / battery extrema stay report-time).
