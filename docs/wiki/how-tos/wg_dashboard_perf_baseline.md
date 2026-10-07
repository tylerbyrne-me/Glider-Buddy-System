# Wave Glider dashboard performance baseline

Repeatable cold/warm checks after dashboard load-path changes. Use WorkPython / production journal as available.

## What to record

| Scenario | Measure |
|----------|---------|
| Cold worker (new gunicorn worker, empty LRU) | Time to first HTML (`DASHBOARD_SSR … duration=`), follow-on chart request count, `DATA_LOAD` count / upstream vs `Synced:` |
| Warm worker (repeat same mission) | SSR duration, chart requests (should be 1 active category), cache hits |
| Explicit refresh (`?refresh=true`) | Confirm `mode=remote` / `DATA_LOAD` remote sources |

## Journal greps

```bash
sudo journalctl -u gliderbuddy --since "10 min ago" | grep -E 'DASHBOARD_SSR|DASHBOARD_SUMMARIES|DATA_LOAD|WG_MISSION_METRICS|SLOWREQ|APP5XX'
```

## Browser checks

1. Open `/wave-glider?mission=<active>` — Network: **one** time-series category load (active card), not nine.
2. Click another left-nav sensor — that category fetches once; soft refresh only reloads opened categories.
3. Confirm `data-is-realtime="true"` on active missions and that cache poll runs (~30s) when auto-refresh is on.
4. Historical `/wave-glider/historical?mission=…` — no cache polling.

## Expected after 2026-10-07 changes

- Default loads prefer `Synced:` when files exist under `data/{mission}/`.
- SSR telemetry/power use `hours=72` (not full mission); lifetime distance / max Wh come from `wave_glider_mission_metrics`.
- Mission distance tooltip mentions odometer vs great-circle when `data-distance-method` is set.
