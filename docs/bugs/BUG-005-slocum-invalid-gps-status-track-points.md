---
id: BUG-005
type: bug
status: fixed
priority: medium
created: 2026-08-07
tags: [slocum, map, track, gps, m_gps_status, erddap]
---

# Invalid / drifted Slocum GPS points appear on map tracks

## Repro

1. Open Fundy (`fundy_20260724_229_realtime`) mission map.
2. Observe track points ~20–30 nm west of the real track (e.g. around 2026-08-06 02:19–03:29 UTC near 49.23, −64.17), then a snap-back.

## Expected

Map tracks omit invalid `m_gps_status` fixes **and** dead-reckoned / carried lat-lon that imply impossible speed from the last trusted GPS (status 0) fix.

## Notes

- Tracks come from the dashboard mirror via `dashboard_df_to_track_df`.
- Fundy mirror evidence (schema 13): `MGpsStatus` present but **6182/6199 rows have NaN status**; only 8 status=0 (all on the good track); 9 status=2 already lat/lon-nulled. The west cluster is entirely NaN-status carried coordinates; a 24 nm / 45 s jump ends at status=0.
- Status filtering alone cannot remove those points.

## Resolution

- Phase 1: fetch `m_gps_status`; mask statuses `{2, 3, -2}` (`BUNDLE_SCHEMA_VERSION` **13**).
- Phase 2: `mask_implausible_slocum_track_coordinates` trusts only status==0 anchors and NaNs intermediate points above ~3 kt over ≥1 nm; status==0 snap-backs are kept (`BUNDLE_SCHEMA_VERSION` **14**). Applied in dashboard preprocess + `dashboard_df_to_track_df`.
- Verified on Fundy mission map (UI) after local restart — west ~20–30 nm cluster gone.
