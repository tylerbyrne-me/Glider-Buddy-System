---
id: BUG-001
type: bug
status: fixed
priority: high
created: 2026-07-30
tags: [slocum, erddap, dashboard, rename]
---

# Slocum dashboard missing heading and coulomb AmpHr series

## Repro

1. Open any active Slocum mission dashboard.
2. Inspect Heading (`c_heading` / `m_heading`) and Coulomb AmpHr charts.
3. Confirm ERDDAP has values; mirror/tmp show empty standardized columns.

## Expected

Heading and `m_coulomb_amphr_total` (plus derived daily consumption) plot from the dashboard mirror like pitch/roll.

## Notes

Ocean Track ERDDAP emits unit suffixes in column names via erddapy (`c_heading (rad)`, `m_coulomb_amphr_total (amp hrs)`). Dashboard preprocess used exact alias matching only; pitch had `(rad)` aliases but heading/coulomb did not. Unmapped raw columns were ignored while empty `CHeading` / `MHeading` / `MCoulombAmphrTotal` were filled with NaN.

## Resolution

- Added heading `(rad)` / `(radians)` and coulomb `(amp hrs)` aliases to `_SLOCUM_DASHBOARD_RENAME`.
- Dashboard rename now uses the same exact+stem path as checklist (`_build_dashboard_rename_map`).
- Bumped `BUNDLE_SCHEMA_VERSION` to `9` so mirrors rebuild with mapped columns.
