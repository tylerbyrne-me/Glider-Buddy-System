---
status: accepted
date: 2026-10-06
supersedes: null
---

# Title: PIC template loads synced disk by default; submit uses client idempotency + SQLite WAL

## Context

Wave Glider PIC handoff form loads were timing out sporadically under gunicorn `-w 2`. `GET /api/forms/{mission}/template/pic_handoff_checklist` loaded full mission CSVs sequentially (local-then-remote), but pilots cannot use admin local loading, so almost every request hit remote WGMS. Process-local caches differ between leader and worker. Separately, `POST /api/forms/{mission}` had no payload validation, no double-submit protection, and exposed SQLite lock failures as 500s.

## Decision

1. **Initial PIC autofill** reads only the leader-synced tree under `local_data_base_path` (`source_preference="synced"`) with bounded `hours_back` windows and `asyncio.gather`. Explicit **Refresh Data** passes `?refresh=true` to force remote WGMS.
2. **Creates** accept a client-generated `client_submission_id` (unique per submitter) so retries after proxy timeouts do not duplicate rows. Multiple intentional PIC handoffs per day remain allowed.
3. **SQLite** connections enable WAL, `busy_timeout=15000`, and `foreign_keys=ON`. Form persist maps lock exhaustion to HTTP 503 with `Retry-After`.

## Alternatives considered

- **Always check upstream with an overall deadline** — still pins workers when WGMS is slow; rejected for the default path.
- **One PIC per mission per day** — conflicts with operational handoff cadence; rejected.
- **Global commit retry after rollback** — unsafe without idempotency; client UUID + 503 is preferred.

## Consequences

- Fast form open depends on leader sync having populated `data/{mission}/`; missing files show `N/A` until Refresh Data.
- Observed max battery Wh is computed over the 48h power window (not full mission history).
- Operators correlate browser toast `request <id>` with journal `[request_id]` / `PIC_AUTOFILL_*` / `FORM_SUBMIT_*` lines.
