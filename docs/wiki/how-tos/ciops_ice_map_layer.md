# CIOPS-East ice forecast map layer

Toggleable MSC GeoMet **CIOPS-East** sea ice area fraction (48-hour hourly forecast) on authenticated home maps (Wave Glider and Slocum). Feature toggle: `ciops_ice_map_layer` (default **off**).

This is a **live WMS raster**, not git-tracked GeoJSON — it is not part of [`map_vector_layers`](./map_vector_layers.md).

Upstream: [MSC GeoMet WMS](https://geo.weather.gc.ca/geomet) layer `CIOPS-East_2km_SeaIceAreaFraction`. Dataset: [Open Data portal](https://open.canada.ca/data/en/dataset/bfe44cce-a9c4-467f-9172-c8800b32e4ec). Docs: [CIOPS on GeoMet](https://eccc-msc.github.io/open-data/msc-data/nwp_ciops/readme_ciops-geomet_en/).

## Enable / deploy verify

1. Set `"ciops_ice_map_layer": true` in `FEATURE_TOGGLES_FILE` or `FEATURE_TOGGLES_JSON` (see [`config/feature_toggles.example.json`](../../../config/feature_toggles.example.json)).
2. Restart the app.
3. Open `/wave-glider/` or `/slocum/` home → **Sea ice forecast** → enable **Ice forecast** → drag the forecast-hour slider.
4. Confirm the control works: legend image loads; status line shows a valid UTC time; zoom/pan issues `GET /api/map/ciops-ice/export` with **200**.
5. Optional: `GET /api/map/ciops-ice/meta` returns `times`, `default_time`, `reference_time`, and `domain` (~77°W–37°W, 35°N–55°N).
6. **Visible ice on the map is seasonal.** Late summer (e.g. August) concentration over much of the east domain is often near 0 — a blank overlay with 200 tile responses is expected. Prefer a winter soak or a GeoMet GetMap cross-check over the Newfoundland / Labrador / GSL box before treating “no paint” as a bug (see [Empty tiles](#empty-tiles--how-to-tell-ok-vs-broken)).

## Behaviour

- Parent checkbox reveals the hourly time slider + legend.
- Default time = last forecast hour ≤ now UTC within the GeoMet `time` Dimension window (else first available).
- Leaflet `GridLayer` requests PNG tiles from `GET /api/map/ciops-ice/export` (auth + allowlisted layer/style/time only).
- WMS 1.3.0 GetMap uses `CRS=EPSG:4326` with axis order **south,west,north,east**.
- Default style `SEA_ICECONC-CIS` (CIS-like palette).
- Short-TTL disk cache under `data_store/ciops_ice_cache/`; GetCapabilities cached in memory (~10 min).
- Opacity ~0.65; pane z-index **345** (above AIS vessel density 340, below weather/vector 350, under tracks).
- Copy clarifies: model forecast (not CIS charts); east-coast domain only; often near 0 in summer.

## Empty tiles — how to tell OK vs broken

`200 OK` on export only means a PNG came back (often fully transparent). v1 has no in-app “opaque pixel” or domain-outline helper.

| Observation | Likely meaning |
|-------------|----------------|
| Tiles over Pacific / world zoom, empty map | Out of CIOPS-East domain — OK |
| Tiles overlapping ~77°W–37°W / 35°N–55°N in late summer, empty map | Model concentration near 0 — usually OK |
| Legend missing or meta/export 4xx/5xx | Proxy / toggle / upstream problem |
| GeoMet GetMap shows ice for the same bbox+time, Buddy blank | Investigate (axis order, cache, pane) |

Quick cross-check (WMS 1.3 BBOX is **south,west,north,east**):

`https://geo.weather.gc.ca/geomet?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=CIOPS-East_2km_SeaIceAreaFraction&STYLES=SEA_ICECONC-CIS&CRS=EPSG:4326&BBOX=45,-70,55,-50&WIDTH=512&HEIGHT=512&FORMAT=image/png&TRANSPARENT=TRUE&TIME=<iso-from-meta>`

Cached PNGs under `data_store/ciops_ice_cache/` are another ground truth for what the UI paints.

## APIs (authenticated)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/map/ciops-ice/meta` | Time axis, default time, style, attribution / Open Data URL, domain |
| `GET /api/map/ciops-ice/export` | Proxied PNG (`bbox=w,s,e,n`, `size`, `time`, optional `style`; max 512) |
| `GET /api/map/ciops-ice/legend` | Proxied GetLegendGraphic PNG |

All return **403** when `ciops_ice_map_layer` is off.

## Code map

| Piece | Path |
|-------|------|
| Service | [`app/core/geo/ciops_ice.py`](../../../app/core/geo/ciops_ice.py) |
| Routes | [`app/routers/map.py`](../../../app/routers/map.py) |
| Client | [`web/static/js/ciops_ice_map_layer.js`](../../../web/static/js/ciops_ice_map_layer.js) |
| UI | `#ciopsIceSection` in `home.html` / `slocum_home.html` |
| Tests | [`app/core/geo/test_ciops_ice.py`](../../../app/core/geo/test_ciops_ice.py) |

## Related

- Architecture: [CIOPS ice map layer](../architecture.md#ciops-east-ice-forecast-map-layer)
- AIS vessel density (same proxy pattern): [vessel_density_map_layer.md](./vessel_density_map_layer.md)
- Feature toggles: [ENV_VARIABLES.md](../ENV_VARIABLES.md)

## Not in v1

- Public login map; CIOPS-West; ice thickness/drift; GetFeatureInfo click; style picker; animation; scheduled cache cleanup.
- In-app empty-vs-broken UX (domain outline, “view outside CIOPS-East”, opaque-pixel hint) — deferred; winter visual soak is the practical confirmation for now (backlog).
