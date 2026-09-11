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
2. **Sensor Tracker** is membership and lifecycle authority for allowlisted glider Platforms models. Start/end dates drive `operational_state`; no `deployment_number` (preemptive staging) stays `PLANNED` / `CATALOG_ONLY` and never invents `m{n}`. Numbered deployments without a start time (or with a future start) stay `PLANNED`.
3. **`deployment_code` / Slocum `mission_key`** are org-scoped global identities across providers. ERDDAP/WGMS/legacy attach; they do not create a second CEOTR mission for the same code.
4. **Platforms** match by ST platform id or canonical name — never by ERDDAP `data_prefix`.
5. **Lifecycle vs enrollment.** Sensor Tracker alone may set/clear catalog `start_time` / `end_time` and drive `operational_state` re-derive. WGMS / ERDDAP update sources and identities only. **Enrollment** is `sync_policy=CONTINUOUS` (GBS operates/pilots the mission). Providers with `enrollment_authority` (Sensor Tracker + legacy_env) may seed CONTINUOUS when a mission is `ACTIVE` (`start_time` reached, no `end_time`). CONTINUOUS is preserved while ACTIVE and dropped to `ON_DEMAND` on completion. Per-mission `enrollment_override` (`automatic` | `forced_on` | `forced_off`) survives reconcile; completion still wins over `forced_on`.
6. **Enablement** when env membership lists are empty: catalog `ACTIVE` ∧ `CONTINUOUS` (WG also requires an enabled realtime WGMS source + linked overview; Slocum requires a linked `is_active` deployment). Non-empty `ACTIVE_*` / historical lists remain an emergency exact-string override. Optional consumers (`MISSION_CATALOG_WG_SYNC_FROM_CATALOG`, `MISSION_CATALOG_SLOCUM_WARM_FROM_CATALOG`, `MISSION_CATALOG_PUBLIC_MAP_FROM_CATALOG`) plus `app.py` startup cache / refresh / weekly reports read through this API. `MISSION_CATALOG_ENROLLMENT_SHADOW` reports would-enroll rows without writing CONTINUOUS. Ops: [mission catalog cutover](../wiki/how-tos/mission_catalog_cutover.md).

## Alternatives considered

- **Auto-CONTINUOUS for every ST-open glider without start-time gating** — rejected; numbered missions without start stay PLANNED for pre-deployment staging.
- **Promote SensorTrackerDeployment as the only canonical mission table** — rejected; partners and ERDDAP-only missions must remain representable.
- **Merge platforms by SV3/DL prefix** — rejected; collapses distinct vehicles.
- **WGMS/ERDDAP enrollment** — rejected; folder/dataset existence is data location, not GBS operating the mission.

## Consequences

- Safer cutover: dry-run gates and live-link before consumer swaps.
- Local consumer soak completed 2026-08-15; production apply + consumer soak completed 2026-08-24/25; public-map enablement soaked 2026-08-26. Empty-env live-row membership failed soak 2026-08-26 (WGMS wiped ST end dates); ST lifecycle authority + CONTINUOUS enrollment + enablement v2 shipped 2026-08-26. Empty-env authenticated UI fix + recovery soak confirmed 2026-09. Do not copy laptop SQLite between hosts.
- Ops must allowlist ST model names in `config/mission_data_providers.json` when new glider types appear.
- Emptying `ACTIVE_*` is an ops step after enrollment seed + set-equality confirmation; restoring env lists re-engages the override.
- ST auto-enrollment requires `enrollment_authority` and ACTIVE state; use `forced_off` for ST-tracked missions GBS should not operate.
