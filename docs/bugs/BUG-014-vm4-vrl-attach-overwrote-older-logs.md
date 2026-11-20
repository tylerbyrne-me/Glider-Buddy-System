---
id: BUG-014
type: bug
status: fixed
priority: medium
created: 2026-11-17
tags: [station-offloads, wg-vm4, vrl]
---

# VM4 VRL attach painted November filenames onto older blank offload logs

## Repro

1. Station (e.g. HFX273) has an older attempt with blank `vrl_file_name` (e.g. April log #353) and a new successful offload.
2. Run WG-VM4 processing so `attach_vrl_file_names_to_offload_logs` runs for the new session.
3. Older blank log(s) receive the new VRL filename (e.g. `VR4-UWM_250866_20261109190155.vrl`).

## Expected

Only a time-matched attempt for that VM4 session should get the VRL; historical blank logs stay blank (or keep their own filename).

## Notes

`_find_latest_log_for_station_vrl` preferred any blank user log on the station with no time window, so a new VRL could attach to last year’s attempt. Related UI confusion with [BUG-013](./BUG-013-offload-log-mission-id-overwrites-all.md) (mission ID was station-wide); VRL was a separate parser path.

## Resolution

2026-11-17: `attach_vrl_file_names_to_offload_logs` uses `_find_matching_log_for_enrichment` (time window + same-day / 8h enrichment fallback). Closest match only; blank fields filled; no station-wide blank-log picker. Regression tests in `app/services/test_wg_vm4_vrl_attach.py`.

Parser hardening (same day): primary ±window now picks **closest** attempt (not newest `updated_at`); attach also rejects when VRL filename stamp vs log time exceeds 48h (`stamp_mismatch_rejected`). Shared stamp helpers: `app/core/stations/vrl_filename.py`.

## Verify / cleanup

Unit coverage: `test_wg_vm4_vrl_attach.py`, `test_offload_vrl_audit.py`.

Audit (dry-run) against the app SQLite DB:

```powershell
conda activate WorkPython
python -m app.cli.audit_offload_vrl_attach --station HFX273 --csv data_store/tmp_vrl_audit_HFX273.csv
python -m app.cli.audit_offload_vrl_attach --csv data_store/tmp_vrl_audit_all.csv
```

Flags rows where the VRL filename stamp is >48h from the log attempt time, or a worse duplicate of the same VRL on the station. Review the CSV, then clear with `--apply` (adds a `[VRL_AUDIT_CLEARED …]` parser note).

**Prod copy audit (2026-11-17):** after loading prod `app_data.sqlite` (+ wal/shm) locally:

- Scanned **1025** logs with VRL names → **14 unique** stamp-mismatch rows (also counted as duplicate-worse-match) plus a few near-duplicate-only rows.
- **HFX273:** #1021 correctly holds `VR4-UWM_250866_20261109190155.vrl`; **#353** (~4772h off) and **#999** (~73h off) are mis-attached (failed attempts).
- Same pattern on other stations (e.g. HFX268/271/272/284/285/287, HFX241B/244B, HFX030–032, HFX206).
- CSV: `data_store/tmp_vrl_audit_all.csv` / `tmp_vrl_audit_HFX273.csv`. Recommended cleanup: `--apply` with reason `vrl_stamp_far_from_log_time` first; review duplicate-only / small-delta rows before clearing.
- **Local prod-copy apply (2026-11-17):** cleared **14** stamp-mismatch logs across 13 stations (`--reasons vrl_stamp_far_from_log_time`). HFX273 re-audit: 1 VRL-bearing log (#1021), **0** suspects. Left 4 near-duplicate-only rows untouched. **Prod still needs the same `--apply` (or a careful DB push of this cleaned copy)** — do not treat the laptop copy as live yet.
- **Follow-up (2026-11-18):** After clears, admin VM4 reprocess attached **remote health** but not VRL on HFX031 #1085 (Nov 12 success). Cause: `run_vm4_background_pipeline` loaded `wg_vm4_info` with a **checkpoint date window** (last run − 2h → now), so the Nov 12 session was outside scope (`last_rows_processed=1` on a later run) while remote health still loaded full-year. Correct VRL `VR4-UWM_250515_20261112035532.vrl` matches the log (~0.01 h). Fix: attach-only info load is always **full-file** (checkpoint kept as run metadata only).
