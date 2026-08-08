---
id: BUG-003
type: bug
status: fixed
priority: medium
created: 2026-08-07
tags: [slocum, checklist, chart, depth, m_water_depth, plot-it]
---

# Flip / invert `m_water_depth` axis on checklist Plot-it (and depth dual-axis charts)

## Repro

1. Open a Slocum daily checklist → Plot-it on `m_water_depth` (or equivalent water-depth series).
2. Observe dual y-axes: left **Depth (m)** inverted (0 at top, deep at bottom); right **m_water_depth (m)** not inverted (large depths at top, 0 near bottom).
3. Orange water-depth points sit visually near the top while the blue dive profile’s deep extrema sit at the bottom — axes disagree on “down = deeper.”

Example window ~2026-08-05 14:00 → 2026-08-07 08:00 UTC: vehicle depth yo-yos to ~340 m (left axis); `m_water_depth` ~350–400 m plotted against an upright right axis.

## Expected

When the plotted series is itself a depth / water-depth quantity, invert the value axis (`y2` / `y3`) the same way as the vehicle Depth axis so deeper values read downward and bathymetry aligns with the dive profile.

## Notes

- Checklist Plot-it: `web/static/js/slocum_checklist_form.js` → `renderPlotChart` — scale `y` has `reverse: true`; scale `y2`/`y3` do not.
- Dashboard Nav depth chart (`slocumNavDepthChart` in `slocum_dashboard.js`) already shares one inverted `y` for `m_depth` / `m_water_depth` / altimeter — likely fine; request is mainly Plot-it dual-axis (and any future depth-on-secondary-axis cases).
- Likely fix: set `reverse: true` on `y2`/`y3` when `unit` is meters depth / series id is in a depth-like set (`water_depth_val`, `m_water_depth`, altitude-derived water depth, etc.), or always invert secondary when both axes are depth-typed.
- Optional: sync axis min/max so bathymetry and vehicle depth share comparable ranges when both are depths.

## Resolution

Fixed 2026-08-07. Plottable registry flag `invert_value_axis` on `water_depth_val` makes Plot-it place `m_water_depth` on the same inverted Depth axis as vehicle depth (no separate upright `y2`), with axis `min: 0`. Series payload also filters non-positive / spike water-depth samples via `filter_valid_water_depth_m` so `-1` no-lock values do not pull the scale below zero.

Dashboard follow-up (same day): `slocumNavDepthChart` (`invertY`) also sets axis `min: 0`; bulk/single chart APIs filter `m_water_depth` with `filter_valid_water_depth_m` before resample so the Nav depth chart does not pad to ~-50.
