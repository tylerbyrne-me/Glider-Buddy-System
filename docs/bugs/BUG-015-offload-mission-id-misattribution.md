---
id: BUG-015
type: bug
status: investigating
priority: medium
created: 2026-11-18
tags: [station-offloads, mission-id, wg-vm4]
---

# Offload logs misattributed to wrong / missing mission ID

## Repro

1. Station HFX231: confirmed Nov offload by `m227-SV3-1071` and May offload by `m219-SV3-1121`.
2. DB / UI may show Nov attempt as `…1070` (or other wrong hull) and May with no per-log mission.

## Expected

Each attempt’s computed `mission_id` (from `parser_session_ref`) matches the glider mission that produced the VM4 completed session for that time.

## Notes

- Related UI overwrite: [BUG-013](./BUG-013-offload-log-mission-id-overwrites-all.md). VRL mis-attach: [BUG-014](./BUG-014-vm4-vrl-attach-overwrote-older-logs.md).
- Current VM4 background pipeline only attaches VRL/health — it does **not** stamp mission on logs.
- VRL attach does not overwrite a non-blank `vrl_file_name`. Failed attempts (`was_offloaded=False`) can still carry a VRL if time-matched; audit flags `failed_with_vrl`.

## Resolution

Preferred first pass (dry-run only): `python -m app.cli.audit_offload_consistency` (VRL + mission summary; optional `--csv-dir`). Apply stays on the dedicated CLIs after review — see [station_offload_season_rollover.md](../wiki/how-tos/station_offload_season_rollover.md#operator-handoff-offload--vm4-fixes).

```powershell
python -m app.cli.audit_offload_consistency --mission m227-SV3-1071 --mission m219-SV3-1121 --csv-dir data_store/tmp_offload_consistency
python -m app.cli.audit_offload_mission_id --mission m227-SV3-1071 --mission m219-SV3-1121 --station HFX231 --csv data_store/tmp_mission_HFX231.csv
python -m app.cli.audit_offload_mission_id --all-local-vm4 --csv data_store/tmp_mission_audit_all.csv
python -m app.cli.audit_offload_mission_id --mission m227-SV3-1071 --apply --reasons mission_mismatch,mission_missing
```

`--apply` rewrites blank/sheet refs only; locked non-sheet parser refs are reported as `locked_parser_ref`.

**Local prod-copy (2026-11-18):**

- HFX231 (`m227-SV3-1071` + `m219-SV3-1121`): **#852** `mission_mismatch` (actual `m230-SV3-1070` → expect 1071); **#506** `mission_missing` (May → expect 1121). No `failed_with_vrl` on those successes.
- `--all-local-vm4` (18 mission folders): large `mission_missing` / `no_matching_log` / `locked_parser_ref` counts expected for historical CSV vs sparse sheet attribution — review CSV before fleet `--apply`. Applyable subset is `mission_mismatch` + `mission_missing` with `can_apply=true` only.
- **Applied `mission_mismatch` only** on local copy: **10** logs / 10 stations (FUN_02, HFX003/004/151/227/231/233/234/256/284). Left `mission_missing` untouched.
- **Caveat:** `--all-local-vm4` discovers disk folders including legacy names (`1070-m170`, `m211_offloads_west`, …) even when the UI lists modern `m###-SV3-####` ids. Treat `locked_parser_ref` / some `mission_missing` against those folders as naming/alias noise until folder↔catalog identity is cleaned up — not as automatic apply candidates.
- **2025–26 missions** (`m219` / `m223` / `m227` / `m230`): applied **464** blank `mission_missing` refs; re-audit left **0** applyable. Remaining **46** `no_station` (all m219) are pre-swap serials not on current `station_metadata` (e.g. 250483 was HFX042 before swap to 250214) — accepted for now; historical serial resolve is on the [backlog](../tasks/backlog.md). **4** `no_matching_log` also remain.
