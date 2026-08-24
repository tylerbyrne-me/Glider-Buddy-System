---
status: accepted
date: 2026-08-12
supersedes: null
---

# Title: Mission catalog indexes live keys; ST is membership/lifecycle authority

## Context

Hardcoded `.env` mission lists do not scale. A source-neutral catalog was introduced with Sensor Tracker, ERDDAP, and WGMS as discovery providers. Live metadata (MissionOverview, SensorTrackerDeployment, SlocumDeployment, disk paths) is keyed by legacy strings (`m203`, `m227-SV3-1071`, Slocum `mission_key`), not catalog UUIDs. An unfiltered ST pull and provider-scoped identities risk duplicate catalog rows and crossed references.

## Decision

1. **Catalog is an index**, not a remapper. Catalog UUIDs never become `mission_id`, `mission_key`, route params, or disk folders. Sync may set nullable `catalog_mission_id` on existing live rows only when the join is unique. Wave Glider overview linking prefers `m###-SV3-####` over bare `m###`; legacy `####-m###` is last-resort only. Slocum linking uses the active briefing row and ignores archived duplicates.
2. **Sensor Tracker** is membership and lifecycle authority for allowlisted glider Platforms models. Start/end dates drive `operational_state`; no `deployment_number` (preemptive staging) stays `PLANNED` / `CATALOG_ONLY` and never invents `m{n}`.
3. **`deployment_code` / Slocum `mission_key`** are org-scoped global identities across providers. ERDDAP/WGMS/legacy attach; they do not create a second CEOTR mission for the same code.
4. **Platforms** match by ST platform id or canonical name — never by ERDDAP `data_prefix`.
5. **Enablement** stays `.env` key strings until crossover proof. Leader/startup catalog apply defaults off (`MISSION_CATALOG_AUTO_APPLY=false`); CLI `--apply` is refused when identity gates are unclean. Optional consumers (`MISSION_CATALOG_WG_SYNC_FROM_CATALOG`, `MISSION_CATALOG_SLOCUM_WARM_FROM_CATALOG`) still return those env strings. Public map stays env-gated last. Ops: [mission catalog cutover](../wiki/how-tos/mission_catalog_cutover.md).

## Alternatives considered

- **Auto-CONTINUOUS for every ST-open glider immediately** — rejected; would create new `data/` trees and live rows for vehicles GBS is not operating.
- **Promote SensorTrackerDeployment as the only canonical mission table** — rejected; partners and ERDDAP-only missions must remain representable.
- **Merge platforms by SV3/DL prefix** — rejected; collapses distinct vehicles.

## Consequences

- Safer cutover: dry-run gates and live-link before consumer swaps.
- Local consumer soak completed 2026-08-15 (env-equivalent WG sync / AUTO_APPLY / Slocum warm). Production must replay apply on its own SQLite; do not copy the laptop DB.
- Ops must allowlist ST model names in `config/mission_data_providers.json` when new glider types appear.
- Full retirement of `ACTIVE_*` env lists waits for set-equality soak **after production** enablement wiring.
