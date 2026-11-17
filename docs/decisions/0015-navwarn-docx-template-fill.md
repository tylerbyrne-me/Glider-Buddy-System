---
status: accepted
date: 2026-11-16
supersedes: null
---

# Fill the official NAVWARN .docx and keep a ReportLab PDF copy

## Context

Wave Glider ops email a Canadian Coast Guard NAVWARN request form to desks such as Sydney and Port aux Basques. The form is an official Word document with fixed wording, logos, and Word checkbox controls. Operators already draft Liquid Robotics ORA requests in Team (`/team/ora`) and download a ReportLab PDF; they want a similar Team flow for NAVWARN without rewriting Coast Guard text.

Email automation exists only as unused `MAIL_*` settings. Previous NAVWARN numbers are known only after CCG publishes a warning, so they cannot be filled at first-request time.

## Decision

Store Team drafts in `navwarn_requests`. The primary download fills the official `.docx` template with `python-docx` (desk title, return email, value cells, and `w14:checkbox` states). A ReportLab PDF that mirrors the form wording is also offered so operators can compare outputs and choose which to keep later. Prescott and outbound email are deferred. Previous NAVWARN numbers are a plain optional field (plus duplicate-as-update); cache-based issued-number tracking is backlog.

## Alternatives considered

- **ReportLab-only PDF** — rejected as the sole artifact because Coast Guard desks expect the Word form layout.
- **LibreOffice .docx→PDF conversion only** — deferred; useful later if Word output stays primary and a PDF attachment is required without maintaining a second layout.
- **Reuse `submitted_forms`** — rejected for the same reasons as ORA (ADR 0010): not a mission checklist cadence.

## Consequences

Template checkbox labels must stay aligned with `TEMPLATE_CHECKBOX_LABELS` (tests fail on Coast Guard form updates). Duplicate labels such as `No` are matched by absolute checkbox index, not label text alone. Operators still send mail manually until a real SMTP path is built.
