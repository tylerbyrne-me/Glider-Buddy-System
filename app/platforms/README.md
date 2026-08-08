# Platform packages (`app/platforms/`)

Layout for platform-specific business logic (see [ADR 0003](../../docs/decisions/0003-platform-brand-naming.md)).

```text
app/platforms/
  __init__.py
  README.md          # this file
  wave_glider/       # scaffold — new WG-only modules land here
  slocum/            # live Slocum package
  {platform_id}/     # future platforms
```

## Wave Glider (`app/platforms/wave_glider/`)

Put **new** Wave Glider–only business logic here. Existing WG pipelines stay in `app/core` (data/sync/stations/shared reporting) — do not big-bang relocate them.

| Module | Role |
|--------|------|
| `summaries.py` | Left-nav sensor-card summaries + mini-trends (SSR + soft-refresh API). Reuses `app.core.data.summaries` helpers. |

HTTP: [`app/routers/wave_glider.py`](../routers/wave_glider.py) — `GET /api/sensor-summaries/{mission_id}` (also via `/api/wave_glider/...` alias). Client: `web/static/js/dashboard.js` soft-refreshes cards/charts on cache advance (same UX pattern as Slocum).

- **Later (optional):** peel one clear WG island (e.g. `stations/wg_vm4_*`) in a focused PR if the package boundary is paying off.
- **Avoid:** moving all WG out of `app/core`; keep shared data loaders/sync, map/weather/bathy/iridium, models, and auth in core. Don’t couple module moves to a full `/api/wave_glider/` URL cutover.

## Slocum (`app/platforms/slocum/`)

Import as `app.platforms.slocum.*`. Includes ERDDAP/mirrors/checklists/deployments plus summaries, weekly reports, masterdata, checklist schema, and CLI (`python -m app.platforms.slocum.cli`).

HTTP routers stay under `app/routers/slocum*.py`.

## Rules

1. Register the platform in [`app/core/platforms/registry.py`](../core/platforms/registry.py) **before** adding a package here.
2. Put platform-only business logic under `app/platforms/{id}/`.
3. Keep HTTP routers in `app/routers/` (they import from `app.platforms.{id}`).

## Product vs platform

- Product brand and shared helpers: `app/core/platforms/`
- Vehicle-platform feature code: `app/platforms/{id}/`
