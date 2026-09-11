---
id: BUG-008
type: bug
status: fixed
priority: high
created: 2026-09-05
tags: [slocum, dashboard, erddap, mirror, overage, cache]
---

# Slocum interactive ranges clipped to the 72-hour mirror

## Repro

1. Open an active Slocum dashboard with a populated rolling mirror.
2. Select a range longer than the 72-hour mirror retention.
3. Observe that charts contain only the mirror overlap and the overage cache is not populated.

## Expected

When the requested start predates the mirror, fetch the missing historical window through
the shared overage cache while retaining mirror fallback during an ERDDAP outage.

## Resolution

Fixed 2026-09-06.

- The interactive partial-mirror shortcut now applies only when the mirror covers the
  requested start and only the recent tail is stale.
- Requests with a missing older head populate and merge the overage cache; failed live
  fetches still degrade to the available mirror overlap.
- Runtime verification fetched Peggy's seven-day dashboard window from ERDDAP (15,955 rows,
  beginning 2026-08-30), and the dashboard displayed data older than 72 hours.
- Coverage: `app/platforms/slocum/test_overage_cache.py`.
