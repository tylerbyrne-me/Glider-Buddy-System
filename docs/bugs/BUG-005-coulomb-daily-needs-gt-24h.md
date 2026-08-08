---
id: BUG-005
type: bug
status: fixed
priority: medium
created: 2026-08-08
tags: [slocum, dashboard, coulomb, ampahr, chart, lookback]
---

# Coulomb AmpHr daily consumption empty/wrong until window &gt; 24h

## Repro

1. Open a Slocum mission dashboard → Power → Coulomb AmpHr chart (Daily consumption bars + Total AmpHr).
2. Leave the time toolbar at the default **24 hours** (or any window ≤ ~24h).
3. Observe Daily consumption missing, flat/null, or not calculating sensibly while Total AmpHr may still plot.
4. Widen the window past 24h (e.g. 48h+) and reload — daily bars appear / look correct.

## Expected

Rolling Ah/day (`coulomb_amphr_daily`) should populate for a 24h display window whenever the mirror (or load path) has enough history before the window to compute the ~24h lookback — pilots should not need to load &gt;24h just to see daily consumption for the last day.

## Notes

Related prior issues / mitigations:

- [BUG-001](./BUG-001-slocum-heading-coulomb-rename.md) — empty coulomb **series** from ERDDAP unit-suffix rename (fixed); this report is about **derived daily rate** needing lookback, not missing total AmpHr column mapping.
- Bulk chart path already comments on a “24h vs 48h gap” and widens load when derived vars are requested (`hours_back + _DERIVED_CHART_LOOKBACK_HOURS` with `_DERIVED_CHART_LOOKBACK_HOURS = 36` in `app/routers/slocum.py`).

Derivation (`_derive_coulomb_amphr_daily`):

- At each sample `t`, finds nearest prior near `t − 24h`.
- Requires lag in **[12h, 36h]**; otherwise null. Negative deltas null.
- Intended to match checklist `compute_amphr_usage_rate`.

Likely failure modes when display `hours_back ≤ 24`:

1. **Load widen ineffective** — `_load_bundle_result(load_hours_back=…)` still returns only ~display-length data (strict mirror coverage / overage / BUG-004 outage path), so `full_df` has no prior samples for the lookback band.
2. **Date-range mode skips widen** — bulk endpoint only expands `load_hours_back` when `start_date`/`end_date` are unset.
3. **Single-variable `/chart-data`** — no derived lookback widen at all (`hours_back` passed straight through).
4. **Sparse coulomb samples** — glider may not log `m_coulomb_amphr_total` densely enough inside [12h, 36h] of each point even when the time span is long enough.

### Likely fix direction

- Ensure derived loads always pull ≥ `hours_back + 36h` (cap at mirror retention) of **actual** rows before deriving, then filter output to the display window (already done for bulk derived vars — verify the load truly returns that span).
- Apply the same widen on `/chart-data` for derived variables and when using explicit date ranges (extend `start` backward by lookback for the fetch only).
- Optional: for the first day in-window, allow a shorter lag with clear “partial” styling (as weekly battery PDF does for partial UTC days) instead of all-null bars.

## Resolution

Fixed 2026-08-08.

- Centralized `_resolve_fetch_window` / `_compute_load_hours_back` so bulk, single `/chart-data`, and date-range modes fetch `display + 36h` lookback for derived vars while filtering series to the display window.
- BUG-004 mirror overlap serve ensures widened loads actually return pre-window rows from disk during ERDDAP outages.
- Coverage: `tests/test_slocum_mirror_fallback.py` (derive + date-range lookback helpers).
