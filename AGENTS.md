# Agent and automation notes



## Project tracking & docs

This project uses `docs/` for persistent tracking. For **non-trivial** work (multi-file, behavior, or architecture), read the relevant files before changing code, and update them when you finish. Tiny one-line fixes need not re-read the whole wiki.

### Before making changes

1. Read `docs/wiki/index.md`, then `architecture.md` and `conventions.md`.
2. Check `docs/tasks/in-progress.md` — is this already being worked?
3. Check `docs/bugs/` if this relates to a reported bug.
4. Skim `docs/decisions/` filenames for anything touching the area you're changing.

### When you finish a change

- Closed a backlog item → move the line from `docs/tasks/backlog.md` (or `in-progress.md`) to `docs/tasks/done.md` with today's date.
- Fixed a bug → update the bug file's `status` to `fixed` and fill in `## Resolution`.
- Made a non-obvious architectural choice → add a new file in `docs/decisions/` using `0000-template.md` as the format.
- Changed how the system works → update `docs/wiki/architecture.md`.

### Conventions

Don't guess at style — [`docs/wiki/conventions.md`](docs/wiki/conventions.md) is the short source of truth (it links to `docs/wiki/standards/` for depth). Always-apply Cursor rules live under [`.cursor/rules/`](.cursor/rules/) as `.mdc` files (including [no Grok models](.cursor/rules/no-grok-model.mdc) and [no inferred git commits](.cursor/rules/no-inferred-git-commits.mdc)).

## Python environment

Use the **conda** environment **`WorkPython`** for any commands that need this project’s dependencies (imports, tests, scripts, PDF/report generation). **git** and **gh** are also installed in WorkPython (like `pip` / `python`), not on the default system PATH — activate the env before git operations or agents will not find them.

```powershell
conda activate WorkPython
python -m pytest ...
python path\to\script.py
git status
```

To run a single command without activating the shell (Windows):

```powershell
& "$env:USERPROFILE\.conda\envs\WorkPython\python.exe" path\to\script.py
conda run -n WorkPython git status
```

**Windows:** `conda run -n WorkPython python -c "..."` does not support multiline `-c` strings; use a small `.py` file or the interpreter path above.

## Application logging

Root logging is configured in `app/core/infra/logging_config.py` (called from `app/app.py` at import).

| Env / setting | Default | Purpose |
|---------------|---------|---------|
| `LOG_LEVEL` | `INFO` | Root verbosity. Use `DEBUG` for per-file sync, date-filter, ERDDAP row counts, and missing-variable detail. |
| `LOG_FILE_PATH` | unset | Optional rotating file (10MB × 5). Primary stream is always stderr (`journalctl -u gliderbuddy`). |

At `INFO`, third-party `httpx` / `httpcore` / `apscheduler` are quieted to WARNING. Each HTTP request gets an `X-Request-ID` (propagated from the client when valid, otherwise generated); it appears in log lines as `[request_id]` and is echoed on the response. Background/startup lines use `[-]`. Grep operational milestones with:

```bash
sudo journalctl -u gliderbuddy --since "5 min ago" | grep -E 'STARTUP:|AUTOMATED:|BACKGROUND TASK:|SYNC:|SLOCUM WARM:|SLOCUM POKE:|SLOWREQ|APP5XX|WORKER TIMEOUT|startup leader'
```

Expect clear lifecycle summaries without per-request HTTP URLs. Re-enable detail with `LOG_LEVEL=DEBUG` and restart. To follow one request: `grep '<id>'` using the `X-Request-ID` response header.

## Production (Linux / gunicorn)

The app is typically run under systemd as `gliderbuddy.service` with gunicorn and `uvicorn.workers.UvicornWorker`. On hosts with no local nginx, gunicorn listens directly on port **8080**; tune `--timeout` and worker count here (not `proxy_read_timeout`).

### Canonical `gliderbuddy.service`

Install at `/etc/systemd/system/gliderbuddy.service` (adjust paths if needed):

```ini
[Unit]
Description=Glider Buddy System FastAPI Application
After=network.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=cove
Group=cove
WorkingDirectory=/home/cove/Glider-Buddy-System

Environment="PYTHONUNBUFFERED=1"
Environment="TORCH_DISABLE_MKLDNN=1"
Environment="OMP_NUM_THREADS=1"
Environment="MKL_NUM_THREADS=1"

ExecStart=/home/cove/miniconda3/envs/buddyenv/bin/gunicorn \
  -w 2 \
  -k uvicorn.workers.UvicornWorker \
  app.app:app \
  -b 0.0.0.0:8080 \
  --timeout 200 \
  --graceful-timeout 60 \
  --keep-alive 5 \
  --max-requests 300 \
  --max-requests-jitter 30 \
  --log-level info \
  --access-logfile - \
  --error-logfile -

Restart=always
RestartSec=15

[Install]
WantedBy=multi-user.target
```

| Flag | Purpose |
|------|---------|
| `-w 2` | Two workers (~2.4GB RAM vs four at ~1.1GB each); leader lock runs sync/scheduler once |
| `--timeout 200` | Above `llm_timeout` (180s) and slow dashboard/ERDDAP paths; default 30s causes worker kills |
| `--max-requests` | Recycle workers to limit pandas/torch memory creep |

Do **not** use `--preload` (torch, ChromaDB, SQLite, APScheduler).

### Fix duplicate `ExecStart` (drop-in override)

If `systemctl cat gliderbuddy.service` shows **two** fragments—the main file **and** `gliderbuddy.service.d/override.conf`—the drop-in **wins**. A typical override clears `ExecStart` and replaces it with an old one-liner (`-w 1`, `debug`, no `--timeout`), which undoes the main unit.

**Remove the override** (recommended when the main unit is already correct):

```bash
sudo rm /etc/systemd/system/gliderbuddy.service.d/override.conf
# If the directory is empty afterward:
sudo rmdir /etc/systemd/system/gliderbuddy.service.d 2>/dev/null || true
sudo systemctl daemon-reload
sudo systemctl cat gliderbuddy.service   # should show only ONE ExecStart block
sudo systemctl restart gliderbuddy.service
ps aux | grep '[g]unicorn'               # expect -w 2 and --timeout 200
```

Inspect before removing:

```bash
systemctl cat gliderbuddy.service
ls -la /etc/systemd/system/gliderbuddy.service.d/
```

### Deploy and verify (on server)

```bash
sudo systemctl daemon-reload
sudo systemctl restart gliderbuddy.service
sudo systemctl status gliderbuddy.service

# Two workers, new flags
ps aux | grep '[g]unicorn'
ss -tlnp | grep 8080

# One leader: single sync + single scheduler start per restart
sudo journalctl -u gliderbuddy --since "5 min ago" | grep -E 'STARTUP:|AUTOMATED:|BACKGROUND TASK:|APScheduler started|startup leader|WORKER TIMEOUT'
```

Expect **one** `STARTUP: Syncing remote data`, **one** `APScheduler started`, and **one** `Acquired startup leader lock` per restart. Non-leader logs: `Could not acquire startup leader lock`.

Watch for problems: `WORKER TIMEOUT`, `SIGKILL`, repeated `BACKGROUND TASK` storms.

### Multi-worker behavior (application)

With gunicorn `-w 2`, only the **leader** worker (fcntl lock on `data_store/.app_leader.lock`) runs:

- `sync_all_realtime_missions`
- `initialize_startup_cache`
- APScheduler (cache refresh + weekly reports), including:
  - `system_weather_map_prefetch_job` / `system_weather_map_cleanup_job`
  - `system_bathy_cache_cleanup_job`
  - `system_iridium_tle_prefetch_job` (every 2h when `iridium_map_layer` is on)
  - `system_iridium_tle_cleanup_job` (daily :25 UTC; runs even if the feature is off)
 - `system_navwarn_prefetch_job` (every 30m when `navwarn_map_layer` is on; incremental page-1)
 - `system_navwarn_cleanup_job` (daily :30 UTC; stranded temps + catalog reconcile when feature on)
  - `system_dmon_review_prefetch_job` (every 12h; Robots4Whales DMON analyst-review cache for deployments with `dmon` card + `robots4whales_url`)
  - `slocum_erddap_poke_job` (every 90m default; allDatasets maxTime poke, incremental mirror sync only when the tail advanced)

The other worker serves HTTP; cache warms on demand. Admin **scheduler status** API returns an empty job list on non-leader workers (scheduler lives on the leader only).

If the public URL is not `:8080` on this host, an external load balancer may impose its own idle/read timeout—align that with `--timeout 200`.

### `data_store` cache inventory (disk pressure)

Leader jobs that reclaim disk: `system_weather_map_cleanup_job` (daily :15 UTC), `system_bathy_cache_cleanup_job` (daily :20 UTC), `system_iridium_tle_cleanup_job` (daily :25 UTC), `system_navwarn_cleanup_job` (daily :30 UTC), `slocum_overage_cleanup_job` (every 6h; TTL + quota + orphan mirror dirs + stranded mirror `*.tmp`). Prefetch (`system_weather_map_prefetch_job`, `system_iridium_tle_prefetch_job`, `system_navwarn_prefetch_job`) stays gated by the matching feature toggles.

```bash
# Size by top-level cache
du -h --max-depth=1 /home/cove/Glider-Buddy-System/data_store | sort -h

# Weather map Open-Meteo responses (common multi-GB culprit)
du -h --max-depth=1 /home/cove/Glider-Buddy-System/data_store/weather_cache 2>/dev/null | sort -h | tail
find /home/cove/Glider-Buddy-System/data_store/weather_cache -name '*.body' 2>/dev/null | wc -l

# Bathymetry grids (usually small; 90d TTL / 512MB cap)
du -sh /home/cove/Glider-Buddy-System/data_store/bathy_cache 2>/dev/null
ls /home/cove/Glider-Buddy-System/data_store/bathy_cache 2>/dev/null | wc -l

# Iridium TLE cache (small: tles.json + upstream_rate_limit.json; CelesTrak ≤1 contact / 2h)
du -sh /home/cove/Glider-Buddy-System/data_store/iridium_cache 2>/dev/null
ls -la /home/cove/Glider-Buddy-System/data_store/iridium_cache 2>/dev/null

# NAVWARN cache (active_warnings.geojson + areas.geojson; HTML scrape of nis.ccg-gcc.gc.ca)
du -sh /home/cove/Glider-Buddy-System/data_store/navwarn_cache 2>/dev/null
ls -la /home/cove/Glider-Buddy-System/data_store/navwarn_cache 2>/dev/null

# DMON Robots4Whales review cache (one JSON per mission_key)
du -sh /home/cove/Glider-Buddy-System/data_store/dmon_review_cache 2>/dev/null
ls /home/cove/Glider-Buddy-System/data_store/dmon_review_cache 2>/dev/null | wc -l

# Slocum mirror parquets (dashboard/ctd/checklist per dataset)
du -sh /home/cove/Glider-Buddy-System/data_store/slocum_cache 2>/dev/null
find /home/cove/Glider-Buddy-System/data_store/slocum_cache -name '*.tmp' 2>/dev/null | wc -l

# Team Visualizations (static fleet charts; rebuild via UI/CLI, no scheduled job)
du -sh /home/cove/Glider-Buddy-System/data_store/team_viz_cache /home/cove/Glider-Buddy-System/data_store/team_viz_outputs 2>/dev/null
ls /home/cove/Glider-Buddy-System/data_store/team_viz_outputs 2>/dev/null

# CIOPS-East ice WMS tiles (on-demand; no scheduled job)
du -sh /home/cove/Glider-Buddy-System/data_store/ciops_ice_cache 2>/dev/null
ls /home/cove/Glider-Buddy-System/data_store/ciops_ice_cache 2>/dev/null | wc -l

# Confirm feature toggle / cleanup jobs on leader
# FEATURE_TOGGLES_JSON weather_map_layers / iridium_map_layer / navwarn_map_layer; admin scheduler UI or:
sudo journalctl -u gliderbuddy --since "1 day ago" | grep -E 'Weather map cleanup|Bathymetry cache cleanup|Iridium TLE prefetch|Iridium TLE cleanup|NAVWARN prefetch|NAVWARN cleanup|Slocum overage cleanup|orphan mirror|CelesTrak|upstream_ttl_gate'
```

One-time reclaim (safe; rebuilds on next use):
- Weather: `rm -rf data_store/weather_cache/responses` — admin `GET/POST /api/map/weather/cache/status|purge`
- Bathy: `rm -rf data_store/bathy_cache/*.npz` — admin `GET/POST /api/reporting/bathy-cache/status|purge`
- Iridium: `rm -rf data_store/iridium_cache` — admin `GET/POST /api/map/iridium/cache/status|purge` (`force_all=true` wipes TLEs + rate-limit gate). Ensure the directory is owned by the service user (`cove`) and writable; atomic renames use a copy fallback on NFS/SELinux, but leftover `*.tmp` files usually mean a prior permission failure — remove them after fixing ownership (`chown -R cove:cove data_store/iridium_cache`).
- NAVWARN: `rm -rf data_store/navwarn_cache` — admin `GET/POST /api/map/navwarn/cache/status|purge` (`force_all=true` wipes GeoJSON + rate-limit gate). Keep owned by `cove:cove`.
- Team viz: `rm -rf data_store/team_viz_cache data_store/team_viz_outputs` — rebuild via `/team/visualizations` or `python -m app.cli.team_visualizations --chart all`. Keep owned by `cove:cove`.
- CIOPS ice: `rm -rf data_store/ciops_ice_cache` — rebuilds on next home-map tile request when `ciops_ice_map_layer` is on. Keep owned by `cove:cove`.
- Slocum mirror: ensure `data_store/slocum_cache` is owned by `cove:cove` (`chown -R cove:cove data_store/slocum_cache`). `os.replace` warnings with `errno=13` on `*.parquet.*.tmp` → `*.parquet` are expected on NFS/SELinux; the copy fallback still updates data. Stranded temps are reclaimed by `slocum_overage_cleanup_job` (or `find data_store/slocum_cache -name '*.tmp' -delete` after fixing ownership).
- Mission CSV sync (`data/<mission_id>/`): same rename quirk — keep owned by `cove:cove` (`chown -R cove:cove data`). Sync uses copy fallback after `os.replace` refusal; clean stranded `*.tmp` with `find data -name '*.tmp' -delete`.

### Iridium map overlay (home Leaflet)

Feature toggle: set `"iridium_map_layer": true` in `FEATURE_TOGGLES_JSON`. Defaults stay off in config.

- Data: CelesTrak SupGP `Iridium-E`, disk-cached under `data_store/iridium_cache/` with a persistent upstream TTL gate (do not contact CelesTrak more than once per ~2 hours).
- Leader: `system_iridium_tle_prefetch_job` refreshes when stale; `system_iridium_tle_cleanup_job` reclaims stranded/old files.
- Browser: pinned `satellite.js` SGP4 on the home maps; positions use the **last track sample** per loaded glider (not live modem GPS).

**Deploy verify**

1. Enable `iridium_map_layer` on staging/prod `.env`, restart `gliderbuddy.service`.
2. On the leader: confirm prefetch/cleanup lines and no CelesTrak 403 loops (`journalctl` grep above).
3. Open home with a loaded track, toggle **Iridium (in view)** — expect in-view markers, footprints, and next-pass panel.
4. `GET /api/map/iridium/cache/status` — check `is_fresh`, `upstream_allowed`, `satellite_count`.
