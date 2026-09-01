# Form Submission Policies

Canonical policy for how GBS stores, lists, and retains mission form submissions across platforms.

Schema definitions live in [`FORMS_FOLDER_STANDARDS.md`](./FORMS_FOLDER_STANDARDS.md). This document covers **submission storage, list vs detail APIs, interactive retention windows, and operational baselines**. ADR: [0006](../../decisions/0006-form-submission-retention-windows.md).

## Shared storage

All platform form submissions use one SQLite table: `submitted_forms` ([`SubmittedForm`](../../../app/core/models/database.py)).

| Column | Role |
|--------|------|
| `id` | Primary key |
| `mission_id` | Mission / Slocum mission key |
| `form_type` | Discriminator (see inventory) |
| `form_title` | Display title at submit time |
| `sections_data` | Full JSON snapshot of sections/items (heavy) |
| `submitted_by_username` | Submitter (`System` for automated Slocum checklists) |
| `submission_timestamp` | UTC submit time |
| `edited_by_username` / `last_edited_timestamp` | Optional edit audit |

Composite index `(mission_id, form_type, submission_timestamp)` supports mission-scoped list queries. Full history remains in the DB for audit; **interactive UIs do not load it by default**.

## Form inventory

| `form_type` | Platform | Typical cadence | Notes |
|-------------|----------|-----------------|-------|
| `pic_handoff_checklist` | Wave Glider | Multiple / day on active missions | Primary volume driver (e.g. m227) |
| `pre_deployment_checklist` | Wave Glider | Rare | Low volume |
| `slocum_daily_checklist` | Slocum | ~1 / UTC day (+ automated `System` fill) | Same table; list via `/api/slocum/checklists/...` |

Related but **out of scope** for this policy: WG-VM4 `offload_logs` (separate table), weekly/EOM PDF URLs on mission/deployment rows.

## Interactive retention windows

**UI/API list defaults** control what is fetched for typical pilot/admin interaction. They do **not** delete rows.

| Surface | Default window | Payload | Expand older history |
|---------|----------------|---------|----------------------|
| WG mission PIC tab | 7 days | Summary only | `days=0` + pagination |
| WG view all forms | Pilot: 72 hours; Admin/MOS: 7 days | Summary only | Widen `days` / paginate |
| WG recent PIC page | 24 hours | Summary only | N/A |
| WG my PIC handoffs | 90 days | Summary only | Paginate / widen `days` |
| Slocum checklist tab | 7 days | Summary only | `days=0` + pagination |

### Full-record access (never windowed by list defaults)

- **View Details / Edit** — fetch one row by id (`GET /api/forms/id/{id}` or `GET /api/slocum/checklists/id/{id}`).
- **PIC “changes since last”** — `GET /api/forms/id/{id}/with-changes` uses bounded mission data loads (8–48h windows, parallel) for the **latest** PIC of a mission only; do not call for every list row. The UI loads the stored snapshot first, then fetches change badges in the background.
- **Slocum compare** — picker uses summary metadata (id, timestamp, submitter); compare payload loads two full forms by id.

## API contract

### Summary vs detail

- **List endpoints** return [`SubmittedFormSummary`](../../../app/core/models/schemas.py) items **without** `sections_data`.
- **Detail endpoints** return the full `SubmittedForm` including `sections_data`.

List responses use a wrapper:

```json
{
  "items": [ /* SubmittedFormSummary */ ],
  "total": 42,
  "days": 30,
  "limit": 100,
  "offset": 0,
  "has_more": false
}
```

Query params (mission / Slocum / my / admin list endpoints):

| Param | Meaning |
|-------|---------|
| `days` | Window in days; omit for surface default; `0` = no time filter |
| `limit` | Page size (default 100, capped) |
| `offset` | Pagination offset |

Fixed windows:

- Pilot `GET /api/forms/all` — 72 hours (not overridable via `days` for pilots).
- `GET /api/forms/pic_handoffs/recent` — last 24 hours.

Shared helpers: [`app/core/forms/submission_queries.py`](../../../app/core/forms/submission_queries.py).

Routers: [`app/routers/forms.py`](../../../app/routers/forms.py), [`app/routers/slocum_checklists.py`](../../../app/routers/slocum_checklists.py).

## Performance rules

1. **List endpoints must not return `sections_data`.** Table UIs only need id, titles, submitter, timestamps.
2. **Detail on demand.** Open View Details → fetch by id; do not embed full blobs in the list payload.
3. Prefer opening the modal with the stored snapshot; call `/with-changes` only when change highlighting is needed (typically the latest PIC). Background refresh must not re-open a dismissed modal.
4. Prefer column projection / summary selects over loading full ORM rows for lists.
5. New form types that share `submitted_forms` must use the same list/detail split and a documented default window.

## Operational baseline

Track growth during host baseline weeks ([`ops/monitoring/BASELINE.md`](../../../ops/monitoring/BASELINE.md)):

```sql
SELECT form_type, COUNT(*) FROM submitted_forms GROUP BY form_type;

SELECT mission_id, form_type, COUNT(*) AS n
  FROM submitted_forms
 GROUP BY mission_id, form_type
 ORDER BY n DESC
 LIMIT 10;
```

SQLite approximate JSON payload size:

```sql
SELECT form_type,
       COUNT(*) AS n,
       SUM(LENGTH(sections_data)) AS sections_bytes
  FROM submitted_forms
 GROUP BY form_type;
```

(Postgres equivalent: `pg_column_size(sections_data)`.)

Expect KB-scale mission list responses after the summary + 7-day default; multi-MB responses indicate a client still requesting `days=0` without pagination or a regression to full blobs.

## Future policy (not implemented)

- Archival tier after 12–24 months (archive table or export).
- Slimmer snapshots on write (drop redundant labels from persisted JSON).
- Extracted summary columns (PIC, mission status, battery %) for list/filter without parsing JSON.
- Edit-form autofill caching / parallel sensor loads for template generation latency.

## Related documentation

- [FORMS_FOLDER_STANDARDS.md](./FORMS_FOLDER_STANDARDS.md) — schema definitions only
- [ADR 0006](../../decisions/0006-form-submission-retention-windows.md)
- [Architecture — Submitted forms](../architecture.md#submitted-forms)
- Slocum checklist how-to: [slocum.md](../how-tos/slocum.md#daily-pilot-checklist)
