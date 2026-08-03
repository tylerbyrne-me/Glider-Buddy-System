# Architecture

_Last updated: 2026-08-03_

## One-paragraph summary

**Glider Buddy System (GBS)** is a FastAPI web app for multi-platform glider operations. Today it supports **Wave Glider** and **Slocum** (with room for more): home hubs, real-time dashboards, station/offload and PIC workflows (WG), knowledge base / LLM features, and admin tools. Platforms are registered in `app/core/platforms/` (IDs, URL prefixes, brand titles, access attrs). Telemetry is synced into on-disk caches under `data_store/` and `data/`; a background scheduler refreshes active caches. Production typically runs under gunicorn with two Uvicorn workers; only the leader worker runs sync and APScheduler (fcntl lock).

## Platforms

- **Registry** — [`app/core/platforms/registry.py`](../../app/core/platforms/registry.py): canonical `platform_id` (`wave_glider`, `slocum`), kebab URL prefixes (`/wave-glider`, `/slocum`), home/API prefixes, KB toggles, ACL attribute names.
- **Brand** — Product: *Glider Buddy System* / *GBS*. In-platform chrome: *{Display} Glider Buddy System* (e.g. *Wave Glider Buddy System*).
- **HTML** — Platform pages live under `/{url_prefix}/...`; legacy Wave Glider root HTML paths redirect to `/wave-glider/...`.
- **APIs** — Prefer `/api/{platform_id}/...` for new work; existing Wave Glider `/api/...` paths remain supported (grandfathered).
- **Platform packages** — Slocum business logic lives under `app/platforms/slocum/`; routers stay in `app/routers/`. Register new platforms in the registry first; put platform-only code under `app/platforms/{id}/`.

See [conventions](./conventions.md#product--platform-naming) and [ADR 0003](../decisions/0003-platform-brand-naming.md).

## Components

- **App entry / lifespan** — FastAPI app, middleware, startup leader lock, router mounts (`app/app.py`)
- **Core** — shared business logic, data loading, auth, models, platforms registry, infra (logging, feature toggles, caching helpers) (`app/core/`)
- **Platforms** — vehicle-specific packages (e.g. Slocum ERDDAP/mirrors/checklists) (`app/platforms/`)
- **Routers** — HTTP endpoints only; depend on core/platforms/services, never the reverse (`app/routers/`)
- **Services** — higher-level orchestration (knowledge base, reporting, sensor tracker, etc.) (`app/services/`)
- **Web assets** — Jinja templates in `web/templates/` and static files in `web/static/` (wired in `app/core/templates.py` / `app/app.py`); Python form helpers in `app/forms/`
- **CLI** — admin/ops scripts such as station CSV import (`app/cli/`)
- **Data on disk** — mission CSVs under `data/`; weather/bathy/iridium/slocum caches under `data_store/`
- **Scheduler** — APScheduler jobs for cache refresh, weekly reports, weather/bathy/iridium/slocum cleanup (leader only; see [ADR 0001](../decisions/0001-gunicorn-leader-lock.md))

## Data flow

```
Remote/local sources → sync (leader) → data/ + data_store caches
                                      ↓
Client → FastAPI routers → core/services → cached telemetry / SQLite → HTML/JSON
```

Typical dashboard path: select mission → load/summarize telemetry from cache (warm on demand if needed) → charts and status widgets. Map overlays (weather, Iridium) use feature toggles and disk caches with TTL/cleanup jobs.

### Slocum resolution

Slocum mirror and overage fetches store **full ERDDAP resolution** by default (active and historical). Time thinning for charts/CSV is pilot-controlled via the dashboard **Resample** control (`granularity_minutes`). `slocum_erddap_decimation_minutes` defaults to `0` (ops escape hatch only). CTD/checklist bundles never use ERDDAP time decimation. Dashboard/checklist preprocess use exact+stem column rename so ERDDAP unit suffixes (e.g. `c_heading (rad)`, `m_coulomb_amphr_total (amp hrs)`, digifin/thruster/DMON unit variants) map to chart columns; bump `BUNDLE_SCHEMA_VERSION` when rename/preprocess semantics change so mirrors rebuild (currently **12** for digifin + thruster + DMON byte count). Shared chart toolkit (style, depth overlay, zoom/pan/reset) lives in `web/static/js/chart_*_utils.js` and `_chart_plot_controls.html`. Daily checklist Plot-it and side-by-side compare are documented in [Slocum how-to](./how-tos/slocum.md#daily-pilot-checklist). DMON sensor card (admin-toggled) adds `sci_dmon_msg_byte_count` charts plus SFMC `from-glider` `*.asc` gap checks (left-nav green/red status dot via the same `.ess-indicator` CSS as Wave Glider Waves ESS); Science checklist ASC/gap items appear only when `dmon` is enabled.

## Key files / entry points

| File | Purpose |
|------|---------|
| `app/app.py` | App factory, lifespan, router includes, startup sync/cache |
| `app/config.py` | Settings / env-backed configuration |
| `app/core/platforms/` | Product brand + platform registry |
| `app/platforms/slocum/` | Slocum ERDDAP, mirrors, checklists, deployments |
| `app/core/infra/logging_config.py` | Root logging, request IDs |
| `app/core/data/` | Data service / telemetry loading |
| `AGENTS.md` | Ops runbook (gunicorn, logging, cache inventory) |

## Things that look wrong but aren't

- **No gunicorn `--preload`** — torch, ChromaDB, SQLite, and APScheduler do not play well with preload; see [ADR 0002](../decisions/0002-no-gunicorn-preload.md) and `AGENTS.md`.
- **Only one worker runs sync/scheduler** — leader lock on `data_store/.app_leader.lock`; the other worker serves HTTP only; see [ADR 0001](../decisions/0001-gunicorn-leader-lock.md).
- **`os.replace` failures on NFS/SELinux** — copy fallback is intentional; stranded `*.tmp` are cleaned by scheduled jobs.
- **Admin scheduler status empty on non-leader** — scheduler lives on the leader worker only.
- **Slocum long windows look dense** — overage/mirror are full-res; sparse charts mean the sensor or UI Resample, not automatic >48h ERDDAP decimation.
- **Wave Glider has no `{id}_platform` feature toggle** — WG remains always-on; Slocum (and future platforms) use `{id}_platform`.
