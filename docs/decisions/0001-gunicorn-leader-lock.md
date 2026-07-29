---
status: accepted
date: 2026-07-29
supersedes: null
---

# Use a gunicorn leader lock for sync and scheduling

## Context

Production runs the FastAPI app under gunicorn with two Uvicorn workers (`-w 2`) for capacity and memory trade-offs. If every worker ran startup sync, cache warm, and APScheduler, the host would duplicate background work, contend on disk caches, and create confusing duplicate log lines (sync storms, multiple schedulers).

## Decision

Only the **leader** worker acquires an fcntl lock on `data_store/.app_leader.lock` and runs:

- `sync_all_realtime_missions`
- `initialize_startup_cache`
- APScheduler (cache refresh, weekly reports, weather/bathy/iridium/slocum cleanup jobs, etc.)

Non-leader workers serve HTTP only; caches warm on demand. Admin scheduler status APIs return an empty job list on non-leader workers.

## Alternatives considered

- **Single worker (`-w 1`)** — simpler, but less HTTP capacity and no failover of request serving if one process is busy
- **External scheduler (systemd timer / cron only)** — splits ops away from the app process and still needs a single owner for in-process cache semantics
- **Shared Redis/queue for jobs** — heavier than needed for the current deployment footprint

## Consequences

Expect one `Acquired startup leader lock`, one sync, and one `APScheduler started` per restart; non-leaders log that they could not acquire the lock. Ops and debugging must target the leader for background-job behavior. Details remain in root `AGENTS.md`.
