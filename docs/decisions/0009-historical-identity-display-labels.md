---
status: accepted
date: 2026-09-15
supersedes: null
---

# Title: Display labels vs stable mission identity; one Slocum briefing per mission_key

## Context

Historical WG/Slocum navigation mixed storage keys (legacy `1070-m170`, bare `m###`, full ERDDAP ids) with human-facing names. Completed Slocum briefings were invisible to active-only resolvers, so historical GETs could auto-create empty active orphan rows beside the real metadata owner. Realtime and delayed ERDDAP datasets must share one briefing row while both remain as catalog sources.

## Decision

Treat canonical names as **display labels only**. Stable route/storage keys (`MissionOverview.mission_id`, Slocum `mission_key` / ERDDAP dataset ids, disk folders, catalog UUIDs) do not change. Navigation detail APIs return `{key, label, catalog_mission_id}`; List[str] endpoints remain for other consumers.

One `SlocumDeployment` owns briefing metadata per suffix-neutral `mission_key`. Historical/read paths resolve inactive completed rows and never auto-create; only catalog reopen/provision reactivates. Alembic enforces unique non-null `mission_key` after a safe orphan-repair CLI.

## Alternatives considered

- **Rename primary keys / folders to canonical labels** — rejected; breaks bookmarks, reports, media, and forms.
- **Collapse realtime/delayed into one CatalogMissionSource** — rejected; both ERDDAP datasets must stay attachable.
- **Always get-or-create on GET info** — rejected; created empty orphans and lost historical metadata.

## Consequences

- UI shows `m###-SV3-<hull>` / `m###-<GliderName>` while navigating with unchanged keys.
- Repair CLI removes only empty active orphans when a single inactive catalog-linked owner exists; ambiguous metadata groups stay manual.
- Rollout order: resolver first → repair report/apply → unique index → label-aware UI.
