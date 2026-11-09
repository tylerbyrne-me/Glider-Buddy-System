---
status: accepted
date: 2026-10-20
supersedes: null
---

# Title: Slocum dashboard uses persisted mission distance (daily full-history refresh)

## Context

Slocum weekly reports already compute Distance (period) and Distance (total) from
full-history ERDDAP/overage tracks. The interactive dashboard only kept a 72h
mirror for left-nav cards and never showed mission distance. Deriving mission
totals from the mirror would recreate the Wave Glider PIC windowing bug.

## Decision

1. Persist mission track distance in `slocum_mission_metrics`, keyed by stable
   `mission_key` (shared across realtime/delayed), with
   `source_erddap_dataset_id` and mirror-tail tokens for invalidation.
2. Recompute from the authoritative full-history track pipeline used by weekly
   PDFs (`dashboard_df_to_track_df` → `normalize_slocum_track_for_report` →
   `calculate_telemetry_summary`). Snapshots are recomputable (corrections and
   backfills replace prior values); they are not irreversible accumulators.
3. Refresh on a leader-only **daily** job (`slocum_mission_metrics_job`, 06:40 UTC)
   and upsert from weekly-report builds that already load full mission history.
4. Dashboard SSR / soft refresh read the snapshot only (no full-history fetch on
   request). Navigation shows Distance (24h) from the mirror slice and Distance
   (mission) from the snapshot; missing snapshots render as `N/A`.

## Alternatives considered

- **Recompute after every ERDDAP poke (~90m)** — too expensive for long missions;
  rejected in favor of daily refresh plus report-time upsert.
- **Incremental tail arithmetic** — fragile under GPS corrections; deferred.
- **Reuse Wave Glider observed-max battery logic** — Slocum power semantics differ
  (voltage / coulomb Ah); battery extrema stay out of this ADR.

## Consequences

- Dashboard mission distance can lag up to ~1 day unless a weekly report ran.
- Realtime → delayed handoff forces full recompute when
  `source_erddap_dataset_id` changes.
- Operators grep `SLOCUM_MISSION_METRICS` alongside `SLOCUM_DASHBOARD_*`.
