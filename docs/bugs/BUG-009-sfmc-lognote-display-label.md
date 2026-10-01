---
id: BUG-009
type: bug
status: fixed
priority: high
created: 2026-10-01
tags: [slocum, sfmc, lognotes, mission-catalog, display-labels]
---

# SFMC log-note import cannot resolve catalog display labels (m226-Peggy)

## Repro

1. After mission-catalog cutover, note active Slocum nav labels such as `m226-Peggy`.
2. Open Team → SFMC log-note import (or CLI `--alias m226-Peggy`).
3. Dry-run with valid SFMC JSON.

## Expected

Resolve the existing `SlocumDeployment` briefing row (same as selecting the
mission in Slocum nav) and preview/post notes.

## Notes

ADR 0009 made `m###-<GliderName>` **display-only**. Storage keys remain ERDDAP
`mission_key` / dataset ids (and optional env aliases). The importer only
resolved env aliases + parseable ERDDAP ids, so paste-of-UI-label failed with
“cannot resolve deployment”.

## Resolution

Fixed 2026-10-01.

- `resolve_deployment_for_dataset` / `get_or_create_deployment_for_dataset`
  accept nav display labels; labels never create rows or overwrite
  `erddap_dataset_id` / `mission_key`.
- Team SFMC form loads `/api/slocum/available_datasets/detail` (label shown,
  storage key submitted) and still accepts typed labels/aliases.
- Coverage: `test_resolve_nav_display_label_m226_peggy` in
  `app/core/mission_catalog/test_historical_identity.py`.
