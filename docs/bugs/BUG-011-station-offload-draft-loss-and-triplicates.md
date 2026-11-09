---
id: BUG-011
type: bug
status: fixed
priority: high
created: 2026-11-09
tags: [station-offloads, auth, forms]
---

# Station offload drafts lost; triplicate logs; search reset after save

## Repro

1. Open Station Offloads (or the dashboard WG-VM4 card), start filling times/notes
   during a long offload, switch tabs or wait past JWT expiry, then return or submit.
2. Click **Log New Offload** repeatedly while the overview refresh is slow.
3. Filter the station list, submit a log, observe the search box still has text but
   the table shows the unfiltered list.

## Expected

- In-progress offload fields survive tab discard / session expiry (restore after
  re-login).
- One click creates one log.
- After submit, the filtered/sorted view is preserved.

## Notes

- Dashboard fallback `location.reload` wiped the non-modal WG-VM4 card.
- `logNewOffloadBtn` was not disabled; create endpoint always inserted.
- `fetchStationStatuses()` called `renderTable(allStationsData)` instead of
  `filterAndRender()`.
- JWT had no sliding refresh; mid-shift 401s matched "logged out every few hours"
  when login was earlier in the day.

## Resolution

2026-11-09 Station Offload QOL patch:

- localStorage drafts (`offload_draft.js`) + `?station=` deep link; dirty-guard
  dashboard reload.
- Sliding JWT refresh with hard cap (`POST /api/auth/refresh`, ADR 0014).
- `client_submission_id` idempotent creates + disable-while-saving.
- Reapply filter/sort/scroll after refresh; lat/lon sort; skip reason; admin archive.
