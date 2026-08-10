# AIS vessel density map layer

Toggleable DFO Northwest Atlantic AIS vessel-density rasters (2025, all vessel types by month) on authenticated home maps (Wave Glider and Slocum). Feature toggle: `vessel_density_map_layer` (default **off**).

These are **live MapServer rasters**, not git-tracked GeoJSON — they are not part of [`map_vector_layers`](./map_vector_layers.md).

Upstream: [egisp MapServer](https://egisp.dfo-mpo.gc.ca/arcgis/rest/services/open_data_donnees_ouvertes/nw_atlantic_vessel_density_2025_ais_densite_des_navires_nw_atlantique_2025_sia/MapServer) layers **7–18** (Jan–Dec). Dataset: [Open Data portal](https://open.canada.ca/data/en/dataset/eac8e835-e7c8-450d-96b0-ff42d416c815).

## Enable / deploy verify

1. Set `"vessel_density_map_layer": true` in `FEATURE_TOGGLES_FILE` or `FEATURE_TOGGLES_JSON` (see [`config/feature_toggles.example.json`](../../../config/feature_toggles.example.json)).
2. Restart the app.
3. Open `/wave-glider/` or `/slocum/` home → **AIS vessel density** → enable **Density 2025** → pick a month.
4. Confirm translucent density tiles appear under tracks; zoom/pan reloads tiles via the app proxy.
5. Optional: `GET /api/map/vessel-density/meta` returns months + default month (UTC calendar month).

## Behaviour

- Parent checkbox reveals exclusive month radios (one month at a time).
- Default month = current UTC calendar month mapped onto the 2025 monthly layers.
- Leaflet `GridLayer` requests PNG tiles from `GET /api/map/vessel-density/export` (auth + allowlisted layer ids only).
- Short-TTL disk cache under `data_store/vessel_density_cache/` reduces repeat upstream hits.
- Opacity fixed (~0.55); pane z-index 340 (under tracks / reference zones).

## APIs (authenticated)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/map/vessel-density/meta` | Month catalog, default month, attribution / Open Data URL |
| `GET /api/map/vessel-density/export` | Proxied PNG (`layer_id`, `bbox=w,s,e,n`, `size=w,h`; max 512) |

Both return **403** when `vessel_density_map_layer` is off.

## Code map

| Piece | Path |
|-------|------|
| Service | [`app/core/geo/vessel_density.py`](../../../app/core/geo/vessel_density.py) |
| Routes | [`app/routers/map.py`](../../../app/routers/map.py) |
| Client | [`web/static/js/vessel_density_map_layer.js`](../../../web/static/js/vessel_density_map_layer.js) |
| UI | `#vesselDensitySection` in `home.html` / `slocum_home.html` |

## Related

- Architecture: [AIS vessel density](../architecture.md#ais-vessel-density-map-layer)
- Static vector layers (separate): [map_vector_layers.md](./map_vector_layers.md)
- Feature toggles: [ENV_VARIABLES.md](../ENV_VARIABLES.md)
