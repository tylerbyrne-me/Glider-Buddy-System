---
status: accepted
date: 2026-09-11
supersedes: null
---

# Title: Catalog durable ops state — audit, locking, success vs partial, final sync

## Context

Mission catalog crossover needs observability and safe concurrency: Team enrollment
actions must be attributable; reconcile apply must not race across gunicorn workers
or CLI; “last success” must not advance when provisioning or final-sync failed;
completion must queue a bounded durable final sync that survives restart without
unbounded historical pulls on HTTP or startup.

## Decision

1. Persist append-only `CatalogMissionEvent`, per-run `CatalogReconcileRun`, and
   unique `(catalog_mission_id, work_type)` `CatalogMissionWorkItem` rows
   (starting with `final_sync`).
2. Serialize apply / link / provision / final-sync writes with
   `cross_process_file_lock` on `data_store/mission_catalog_write.lock`. Team
   Retry Provision uses a short timeout and returns HTTP 409 when busy.
3. Advance `mission_catalog_last_success.txt` only when gates are clean, reconcile
   failures are zero, and provisioning/final-sync errors are zero. Partial runs
   append to `mission_catalog_last_partial.txt` and persist `status=partial`.
4. Final sync is bounded (max attempts, max age, batch limit, exponential
   backoff). Failure never reactivates a completed mission.
5. Partial unique indexes enforce one overview and one *active* Slocum deployment
   per `catalog_mission_id` after a duplicate preflight that fails the migration
   with a clear report (repair CLI exists).

## Alternatives considered

- **In-memory / marker-only success** — rejected; multi-worker and restart lose state.
- **Unbounded historical pull on completion HTTP** — rejected; too slow and unsafe.
- **Silent duplicate merge in migration** — rejected; prefer explicit repair.

## Consequences

Operators can audit enrollment and see reconcile/final-sync health in Team UI.
Concurrent double-provision is blocked. Rollback uses key-export CLI plus
documented flag/env restore. Env lists remain break-glass for one compatibility
release.
