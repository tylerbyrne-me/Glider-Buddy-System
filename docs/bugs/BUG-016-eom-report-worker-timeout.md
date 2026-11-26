---
id: BUG-016
type: bug
status: fixed
priority: high
created: 2026-11-26
tags: [reporting, eom, gunicorn, timeout, ctd]
---

# End-of-mission PDF generation times out for long / dense Wave Glider missions

## Repro

1. Admin → generate End of Mission report with Sensor Tracker sync for a long mission with dense CTD (e.g. `m227-SV3-1071`, ~294k CTD rows, ~20 ISO weeks).
2. Observe Resty gateway timeout and/or gunicorn `WORKER TIMEOUT` while journal shows week loop still progressing.

## Expected

EOM PDF completes and is saved to `end_of_mission_report_url` within gunicorn/proxy budgets (comparable missions with fewer CTD rows succeed, e.g. `m230-SV3-1070` ~77s).

## Notes

- Runtime evidence (2026-11-26): 1070 finished (`SLOWREQ 76.70s` → 200). 1071 killed at week_idx 3 with PDF `elapsed_s≈94` after weeks taking 14–23s each (`ctd_rows` 13k–21k/week).
- Cause: synchronous matplotlib/ReportLab on full-resolution CTD across many ISO weeks; each week also re-copied/re-preprocessed full CTD (~294k) and often refetched ETOPO bathymetry per week map; uvicorn worker silence triggered `WORKER TIMEOUT`.

## Resolution

- Stride-downsample chart frames with ceil (`REPORT_CHART_MAX_POINTS=5000`) before z-score/plot.
- EOM preprocesses CTD/weather/waves/AIS once, then cheap time-slices per ISO week.
- Skip ETOPO bathymetry on EOM per-week track maps (full-mission overview keeps it).
- Run `write_mission_pdf` via `asyncio.to_thread` so gunicorn heartbeats continue.
- Confirmed 2026-11-26: all EOM reports generating on glider-dev after deploy.
