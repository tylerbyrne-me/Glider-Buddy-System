---
id: BUG-010
type: bug
status: fixed
priority: high
created: 2026-10-20
tags: [wave-glider, pic, power, mission-metrics]
---

# PIC handoff observed max Wh used 48h peak instead of mission lifetime

## Repro

1. Open a Wave Glider mission dashboard whose capacity has peaked earlier in the
   mission (observed max much higher than the last 48h).
2. Open the PIC handoff form for the same mission.
3. Compare **Observed max** and **% Battery Remaining**.

## Expected

PIC observed max and % remaining match the dashboard (mission-lifetime peak from
`wave_glider_mission_metrics`).

## Notes

ADR 0011 intentionally bounded PIC power loads to 48h for speed; `RealisticMaxBatteryWh`
was taken from that window only. Dashboard (ADR 0012) injects persisted
`observed_max_battery_wh`. Pilots saw inflated % remaining (e.g. ~90% vs ~60%).

## Resolution

Fixed 2026-10-20 (hardened same day).

- PIC autofill/compare resolve lifetime observed max via
  `resolve_wave_glider_lifetime_metrics` (field-aware bootstrap) and pass it into
  `get_power_status` with `allow_frame_lifetime_fallback=False`.
- 48h power CSV still supplies current Wh only; missing snapshots do not fall
  back to the 48h peak.
- ADR 0011 / 0012 consequences and architecture PIC bullet amended.
- Coverage: `test_power_helpers_prefer_lifetime_observed_max`,
  `test_power_helpers_do_not_use_48h_peak_without_lifetime`,
  `test_build_autofilled_schema_uses_lifetime_observed_max`,
  `test_build_compare_total_battery_uses_lifetime_observed_max`.
