---
status: accepted
date: 2026-08-02
supersedes: null
---

# Title: Product brand and multi-platform naming contract

## Context

The application grew from a Wave Glider–only product into a multi-platform system (Wave Glider + Slocum, with more expected). Display strings, CSS prefixes (`wgbs-*`), URL layouts (WG HTML at site root vs Slocum under `/slocum/`), and scattered `"wave_glider"` / `"slocum"` literals made expansion error-prone and branding inconsistent (Slocum pages titled under “Wave Glider Buddy”).

## Decision

1. **Product brand:** *Glider Buddy System* (full) and *GBS* (short). In-platform UI titles use *{DisplayName} Glider Buddy System*.
2. **Central registry** in `app/core/platforms/` owns platform IDs, URL/home/API prefixes, buddy titles, feature/KB toggle names, and ACL attribute names. Callers import helpers/constants instead of hardcoding strings.
3. **URL contract:** HTML under `/{kebab(platform_id)}/...`; legacy Wave Glider root HTML redirects to `/wave-glider/...`. New APIs prefer `/api/{platform_id}/...`; existing WG `/api/...` paths stay for compatibility.
4. **CSS product prefix:** `gbs-*` (not `wgbs-*`). Logo asset filenames remain a follow-up.
5. **New platform modules:** document target layout `app/platforms/{id}/`; do not require moving existing `slocum_*.py` in the same change.

## Alternatives considered

- **Display-only rename** — rejected; does not harden expansion or URL consistency.
- **Rename DB `platform` values / ACL columns** — rejected for this phase; IDs already snake_case and stable.
- **Full WG API move under `/api/wave_glider/` in one shot** — deferred to avoid breaking clients; aliases optional later.

## Consequences

- Adding a platform means: register a `PlatformSpec`, add routes under its URL prefix, optional `{id}_platform` toggle, and (eventually) code under `app/platforms/{id}/`.
- High-traffic wiki (`architecture`, `conventions`, `WEB_FOLDER_STANDARDS`) must stay aligned with the registry.
- Follow-ups: logo/favicon rename, GitHub repo rename, production path rename, archive-doc sweep, optional full WG API prefix migration.
