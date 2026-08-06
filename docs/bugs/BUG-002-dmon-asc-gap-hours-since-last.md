---
id: BUG-002
type: bug
status: fixed
priority: high
created: 2026-08-05
tags: [slocum, dmon, sfmc, asc, gap, reporting]
---

# DMON ASC gap warning overstates hours since last file

## Repro

1. Generate (or view) a Slocum weekly report whose period `end_date` is the same UTC calendar day as recent `*.asc` offloads — or inspect the DMON ASC offloads section when the summary window is report-sized (e.g. “20 *.asc in last 216h”).
2. Note newest table row, e.g. `zh042158.asc` at `2026-08-05T00:20:56Z`.
3. Wall clock ~`2026-08-05T03:27Z` → real age ≈ 3.1h.
4. Gap banner / caption still shows ~`23.6h since last *.asc` and `GAP >16h`.

## Expected

“Hours since last *.asc” should be age relative to report generation time (or live wall clock on the dashboard), not relative to end-of-day of the report window. With a file at 00:20Z and generation at 03:27Z, age ≈ 3h and no current-staleness gap warning unless an inter-file gap >16h exists.

## Notes

### Investigation (2026-08-05) — confirmed

Root cause: report path passed `now=window_end` (`23:59:59` UTC) into `normalize_dmon_asc_files`, inflating `hours_since_last` (e.g. 23.65h) and falsely tripping `has_gap_over_16h`. Banner copy always framed any gap as “Xh since last *.asc”.

## Resolution

2026-08-05 — Weekly report ASC section no longer shows a live staleness / “hours since last” warning or the normalize summary that embeds age and `GAP >16h`. The section lists files for the report window and highlights inter-file gaps >16h in the table only, which is appropriate when readers open the PDF days or weeks later. Dashboard live ASC age/gap UX is unchanged (separate concern).

Follow-up (same day): ASC fetch now paginates SFMC’s 20-file pages and clips to `[window_start, window_end]`, so early-window `*.asc` files are not dropped when there are >20 files in range.
