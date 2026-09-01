---
status: accepted
date: 2026-08-31
supersedes: null
---

# Title: Form list APIs use summary payloads and 7-day interactive windows

## Context

Long Wave Glider missions (e.g. m227 with ~5 PIC handoffs/day) caused multi-second delays when opening mission PIC history. List endpoints returned every `SubmittedForm` row including full `sections_data` JSON (labels, AIS/error strings, etc.), so payload size grew linearly with mission age. Slocum daily checklist lists had the same structural risk. Interactive windows were inconsistent: pilots saw 72h on `/api/forms/all` and 24h on recent PIC, but mission-scoped lists had no window.

## Decision

1. **Interactive UI defaults are not DB deletion.** Full history stays in `submitted_forms` for audit; list endpoints apply a time window for typical browsing.
2. **Mission-scoped PIC and Slocum checklist lists default to 7 days.** Expand via `days=0` plus pagination. Pilot global forms stay 72h; recent PIC stays 24h; my PIC defaults to 90 days.
3. **List endpoints return summary rows only** (`SubmittedFormSummary` — no `sections_data`). Detail/edit/compare fetch one (or two) full rows by id.
4. **Wave Glider and Slocum share the same list/detail and window pattern** via `app/core/forms/submission_queries.py`.
5. **Composite index** `(mission_id, form_type, submission_timestamp)` supports the hot mission list query.

Canonical policy: [FORM_SUBMISSION_POLICIES.md](../wiki/standards/FORM_SUBMISSION_POLICIES.md).

## Alternatives considered

- **Delete or hard-archive old submissions immediately** — rejected for this change; ops need audit history; UI windowing fixes the latency without data loss.
- **Keep full blobs in list responses but paginate only** — rejected; even 7 days × full JSON remains unnecessarily heavy for a metadata table.
- **Platform-specific retention tables** — rejected; one `submitted_forms` table with `form_type` is enough if list APIs stay lean.

## Consequences

- Clients that assumed list responses were full `SubmittedForm` arrays must use the list wrapper (`items` / `total` / `days` / `limit` / `offset` / `has_more`) and fetch by id for View Details.
- Mission PIC and Slocum checklist tabs show a “last 7 days” affordance and a control to load older pages.
- Follow-ups (documented, not in this ADR): archival tier, slimmer write-time snapshots, extracted summary columns, template autofill caching.
