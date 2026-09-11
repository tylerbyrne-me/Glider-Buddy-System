---
status: accepted
date: 2026-09-09
supersedes: null
---

# Title: Defer ERDDAP-metadata-only mission promotion and generic platform onboarding

## Context

Automatic mission lifecycle (ADR 0005 + ST enrollment authority) couples allowlisted Sensor Tracker deployments to live WG/Slocum rows when sources appear. Unknown ERDDAP datasets still appear as unmatched / catalog inventory. Promoting those into operable missions without ST lifecycle authority would invent live keys, enroll consumers from data-location alone, and blur the ST vs source-authority split.

New vehicle families will arrive; core lifecycle must not grow per-family enrollment branches.

## Decision

Do **not** auto-create or auto-enroll catalog missions from ERDDAP (or other metadata-only discovery) alone. Keep unmatched ERDDAP rows as inventory until an audited promote/link workflow exists.

When a new actively operated platform is added, require only: platform registry entry, ST model mapping, one provisioning handler, source capability preferences, and that platform’s UI/consumer package — not changes to core lifecycle/enrollment policy.

A future ADR will cover the promote/link UX, audit trail, and generic track-only consumers via capability-based `resolve_mission_sources`.

## Alternatives considered

- **Auto-enroll any ERDDAP dataset with a parseable mission key** — rejected; data location ≠ GBS operating the mission; risks ghost live rows and public-map surprises.
- **Hard-code each future family into reconcile enrollment** — rejected; contradicts the handler-registry design and ADR 0005 enrollment_authority split.

## Consequences

- Unmatched ERDDAP review on Team catalog remains the operator surface until promote/link ships.
- ST-tracked allowlisted models stay the enrollment path for automatic ACTIVE/CONTINUOUS.
- Backlog: audited promote/link + metadata-only onboarding ADR (see `docs/tasks/backlog.md`).
