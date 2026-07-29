---
status: accepted
date: 2026-07-29
supersedes: null
---

# Do not use gunicorn --preload

## Context

Gunicorn’s `--preload` loads the application in the master process before forking workers. This app imports or initializes heavy, process-sensitive stacks (torch, ChromaDB, SQLite usage patterns, APScheduler) that do not fork safely or predictably under preload.

## Decision

Never run production (or staging) gunicorn with `--preload`. Workers must each import/start the app normally. Prefer the canonical unit flags in `AGENTS.md` (`-w 2`, `--timeout 200`, `--max-requests`, etc.).

## Alternatives considered

- **`--preload` for faster worker spawn / shared memory** — risk of broken torch/MKLDNN, shared SQLite/Chroma handles, and duplicated or dead schedulers after fork
- **Lazy-import all heavy deps only in request paths** — large refactor for limited gain while leader-lock + no-preload already works

## Consequences

Slightly higher per-worker import cost and memory vs a successful preload setup, in exchange for stable multi-worker behavior. Documented in `AGENTS.md` and [ADR 0001](./0001-gunicorn-leader-lock.md).
