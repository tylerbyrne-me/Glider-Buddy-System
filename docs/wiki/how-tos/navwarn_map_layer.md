# NAVWARN map layer

Toggleable Leaflet overlays for Canadian Coast Guard navigational warnings on authenticated home maps (Wave Glider and Slocum). Feature toggle: `navwarn_map_layer` (default **off**).

Two layers:

1. **Active NAVWARNs** — published warning geometries (`POINT` / `POLYLINE` / `POLYGON`) with popups linking to the official message page
2. **NAVWARN areas** — series-level (`l2`) area reference polygons (Pacific Coast, Maritimes, …); root Canada rectangle excluded

Public login map is out of scope (same as weather/Iridium overlays).

Upstream: [CCG NIS search](https://nis.ccg-gcc.gc.ca/public/rest/messages/en/search). There is no public JSON search API; Glider Buddy scrapes HTML and caches GeoJSON under `data_store/navwarn_cache/`.

## Enable

1. Set `"navwarn_map_layer": true` in `FEATURE_TOGGLES_FILE` or `FEATURE_TOGGLES_JSON` (see [`config/feature_toggles.example.json`](../../../config/feature_toggles.example.json)).
2. Restart the app.
3. Open `/wave-glider/` or `/slocum/` home → **NAVWARN Overlay** → toggle **Active NAVWARNs** and/or **NAVWARN areas**.

Layers use Leaflet pane z-index **360** (above static reference zones, below tracks/Iridium).

## Data flow

```
nis.ccg-gcc.gc.ca search HTML ──► message IDs
nis.ccg-gcc.gc.ca /message/{id} ──► var data = {features…}
                          │
                          ▼
              app/core/geo/navwarn_cache.py
                          │
                          ▼
           data_store/navwarn_cache/*.geojson
                          │
                          ▼
        GET /api/map/navwarn/active|areas  ──► navwarn_map_layer.js
```

Refresh is **two-tier**:

| Mode | When | Search | Details | Removals |
|------|------|--------|---------|----------|
| **incremental** | 30-min prefetch | page 1 only | new IDs only | do not prune |
| **reconcile** | daily cleanup (`force_full`) / on-demand when stale | full `page=1..N` | new IDs only | drop IDs absent from catalog |

Empty or truncated cache always escalates incremental → reconcile. Upstream hard-caps ~50 IDs per page (`startIndex` is ignored). Check completeness via `GET /api/map/navwarn/cache/status` → `"truncated": false`.

## API

| Endpoint | Who | Purpose |
|----------|-----|---------|
| `GET /api/map/navwarn/active` | active user (toggle on) | GeoJSON + ETag (`max-age=300`) |
| `GET /api/map/navwarn/areas` | active user (toggle on) | GeoJSON + ETag (`max-age=3600`) |
| `GET /api/map/navwarn/cache/status` | user when on; admin when off | freshness, counts, rate gate |
| `POST /api/map/navwarn/cache/purge?force_all=` | admin | purge disk cache (no upstream contact) |

## Cache / scheduler

| Path | Role |
|------|------|
| `data_store/navwarn_cache/active_warnings.geojson` | merged published warnings |
| `data_store/navwarn_cache/areas.geojson` | area reference polygons |
| `data_store/navwarn_cache/meta.json` | last fetch / errors |
| `data_store/navwarn_cache/upstream_rate_limit.json` | min-interval gate |

Leader jobs:

- `system_navwarn_prefetch_job` — every 30 min when toggle on (incremental page-1 probe)
- `system_navwarn_cleanup_job` — daily :30 UTC (stranded `.tmp` + catalog reconcile when toggle on)

Config knobs in [`app/config.py`](../../../app/config.py): `navwarn_cache_dir`, `navwarn_cache_ttl_seconds` (1800), `navwarn_areas_ttl_seconds` (86400), `navwarn_search_max_hits` (5000 safety ceiling), `navwarn_search_max_pages` (100), `navwarn_upstream_min_interval_seconds` (300), `navwarn_prefetch_interval_minutes` (30).

## Deploy verify

1. Enable toggle, restart `gliderbuddy.service`.
2. Leader logs: `NAVWARN search page=…` then `NAVWARN published ID list complete` (or prefetch summary with a large `active_warning_count`).
3. `GET /api/map/navwarn/cache/status` — expect `"truncated": false` and message count well above 50.
4. Home map → enable Active NAVWARNs → geometries + official popup links.
5. Enable NAVWARN areas → series-level polygons (not the Canada-wide box).

```bash
sudo journalctl -u gliderbuddy --since "10 min ago" | grep -E 'NAVWARN'
du -sh /home/cove/Glider-Buddy-System/data_store/navwarn_cache 2>/dev/null
```

## Attribution

Data © Canadian Coast Guard / NAVWARN. Official source: https://nis.ccg-gcc.gc.ca/

## Related

- Architecture: [NAVWARN map layer](../architecture.md#navwarn-map-layer)
- Code: [`app/core/geo/navwarn_cache.py`](../../../app/core/geo/navwarn_cache.py), [`web/static/js/navwarn_map_layer.js`](../../../web/static/js/navwarn_map_layer.js)
