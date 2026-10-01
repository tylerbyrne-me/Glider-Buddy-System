---
status: accepted
date: 2026-09-28
supersedes: null
---

# Team ORA drafts stay out of submitted_forms

## Context

The Liquid Robotics Operational Risk Assessment is a Wave Glider request: header, coordinates, vehicle config, and a device power table. It is filled before or beside a catalog mission, not on the daily pilot cadence of `pic_handoff_checklist` / `pre_deployment_checklist` / `slocum_daily_checklist`. The file emailed to the contractor is a PDF.

`submitted_forms` is mission-scoped, list-summarized, and windowed for interactive history (ADR 0006). An ORA draft is a reusable Team document with a nullable catalog link and a per-hull vehicle overlay Sensor Tracker does not store.

## Decision

Store ORA drafts in `ora_requests` and last-used vehicle config in `ora_hull_profiles`. The Team page at `/team/ora` edits the draft and downloads a ReportLab PDF of the same fields (header, coordinates, vehicle config, device power, notes). Device watts come from a local library, optionally merged with Sensor Tracker instrument names. The app does not email the contractor.

## Alternatives considered

- **New `form_type` on `submitted_forms`** — rejected. That table assumes a mission key and checklist retention windows.
- **A generic form engine first** — rejected for this request. One purpose-built page is enough until a second request form needs the same shape.

## Consequences

Later Team request forms can follow the same draft-table plus external-template pattern. Mission dashboards and weekly reports do not show ORA status. Hull memory only updates non-empty vehicle fields, so a partial save does not clear a previous umbilical or software version.
