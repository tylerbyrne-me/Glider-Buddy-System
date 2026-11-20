---
status: accepted
date: 2026-11-17
supersedes: null
---

# Title: Slocum final sync waits for delayed ERDDAP and reopens cutover when delayed links late

## Context

Completed Slocum missions share one `SlocumDeployment` per `mission_key` (ADR 0009) with separate realtime/delayed catalog sources. Final sync (ADR 0008) could succeed on `*_realtime` before Ocean Track published `*_delayed`, mark the work item DONE, and never revisit. Historical enablement then exposed the stale realtime id. Wave Glider already waits for a past WGMS source; Slocum did not.

## Decision

1. Slocum final sync requires a fresh linked delayed ERDDAP source (`waiting_for_delayed_source`); it never completes cutover on realtime alone.
2. Waiting for delayed/past sources does not burn attempt quotas or age-exhaust; manual retry refreshes the age clock.
3. Post-reconcile (and completion) reopen DONE/FAILED/EXHAUSTED final-sync items when delayed is linked but the deployment pointer is still realtime.
4. Historical enablement prefers the linked delayed ref over a stored realtime `erddap_dataset_id`.
5. Completion handlers rewrite `erddap_dataset_id` when delayed is already present.

## Alternatives considered

- **Read-time preference only** — rejected; live pointer and mirrors would stay wrong for jobs that trust `erddap_dataset_id`.
- **Always full-history delayed mirror on cutover** — rejected; unbounded pulls remain backlog (historical mirror v2); pointer + bounded warm sync is enough for cutover.

## Consequences

Ops see expected Health for wait states and a fault when delayed is linked but the pointer lags. Late-linking delayed datasets drain via the existing batch limit. Unrelated ST completed missions that exhaust for other reasons are unchanged.
