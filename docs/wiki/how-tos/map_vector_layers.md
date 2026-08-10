# Static vector map layers

Toggleable GeoJSON reference zones on authenticated home maps (Wave Glider and Slocum). Feature toggle: `map_vector_layers` (default **off**). Home UI builds toggles from `GET /api/map/layers` (catalog-driven).

## Shipped layers

| Layer id | Notes |
|----------|--------|
| `gosl_dsz`, `gosl_safe_zones` | KML-derived GOSL study / safe zones |
| `dfo_lobster_lfa_2022` | DFO Maritimes lobster fishing areas (LFAs), 2022 |
| `dfo_fma_crab`, `dfo_fma_snow_crab`, `dfo_fma_scallop`, `dfo_fma_capelin`, `dfo_fma_mackerel`, `dfo_fma_herring`, `dfo_fma_squid`, `dfo_fma_salmon`, `dfo_fma_northern_shrimp` | DFO Atlantic Fisheries Management Areas (FMAs). Cartographic reference only — not for navigation or enforcement. |
| `noaa_shipping_lanes_nw_atlantic` | NOAA ENC shipping lanes clipped to NW Atlantic approaches (US-focused; little/no Canadian TSS) |

**Caveats**

- Several `dfo_fma_*` GeoJSON files are ~2–4 MB each; they load only when toggled on.
- `dfo_fma_northern_shrimp` is **22 of 23** polygons: egisp `OBJECTID` 19 returns HTTP 500 and is omitted (see `sources/dfo_fma_northern_shrimp_arcgis_source.json`).
- Public login map and PDF weekly reports do **not** draw these layers yet — see [backlog](../../tasks/backlog.md).

## Enable / deploy verify

1. Set `"map_vector_layers": true` in `FEATURE_TOGGLES_FILE` or `FEATURE_TOGGLES_JSON` (see [`config/feature_toggles.example.json`](../../../config/feature_toggles.example.json)).
2. Restart the app (or reload if your process picks up toggle file changes).
3. Open `/wave-glider/` or `/slocum/` home → **Reference zones** → toggle layers (GOSL, LFA, FMA species, NOAA shipping).
4. Confirm `GET /api/map/layers` lists the expected ids; toggle one FMA and confirm polygons + popup labels appear under tracks.

Layers sit under tracks (Leaflet pane z-index 350). Click a polygon for its label (area name / LFA / species when present).

## On-disk layout (git-tracked)

```
config/map_layers/
  manifest.json                 # catalog: id, name, style, bounds, platforms, optional source
  published/*.geojson           # canonical geometry served to the browser
  sources/*                     # optional archived KML / ArcGIS fetch metadata
```

Config setting: `map_layers_dir` (default `config/map_layers`) in [`app/config.py`](../../../app/config.py).

**Deploy model:** convert/fetch on a developer/ops machine → commit `published/` + `manifest.json` (+ `sources/` notes) → production gets layers via the normal git deploy. Runtime does **not** need geopandas/pyogrio or live ArcGIS access; the API only reads published GeoJSON.

## Ingest

### KML → GeoJSON

```powershell
conda activate WorkPython
python scripts/convert_map_layer_kml.py `
  --input "path\to\zones.kml" `
  --layer-id gosl `
  --archive-source
```

Splits placemarks named `DSZ *` vs `safe zone*` into `gosl_dsz` / `gosl_safe_zones`. Uses **pyogrio**.

### ArcGIS REST Feature Layer → GeoJSON

Example — DFO Maritimes lobster districts ([layer 14](https://egisp.dfo-mpo.gc.ca/arcgis/rest/services/open_data_donnees_ouvertes/historical_lobster_fishing_districts_maritimes_region/MapServer/14)):

```powershell
conda activate WorkPython
python scripts/fetch_map_layer_arcgis.py `
  --url "https://egisp.dfo-mpo.gc.ca/arcgis/rest/services/open_data_donnees_ouvertes/historical_lobster_fishing_districts_maritimes_region/MapServer/14" `
  --layer-id dfo_lobster_lfa_2022 `
  --name "DFO Lobster LFAs (2022)" `
  --description "DFO Maritimes lobster fishing areas (LFAs), 2022 snapshot." `
  --simplify 0.001 `
  --archive-source
```

Queries `f=geojson&outSR=4326` (paginated), lightly simplifies for web size, writes `published/` + manifest. Re-run when the upstream service updates, then commit.

**DFO egisp quirks:** the Atlantic FMA MapServer often 500s on `f=geojson`, large `resultRecordCount`, or `outFields=*`. The fetch script falls back to ArcGIS JSON, then automatically shrinks page size and uses lean fields. Prefer `PYTHONUNBUFFERED=1` when debugging long fetches. If a single feature is corrupt (northern shrimp), fetch by `OBJECTID` and skip failures.

DFO Atlantic Fisheries Management Areas ([MapServer](https://egisp.dfo-mpo.gc.ca/arcgis/rest/services/open_data_donnees_ouvertes/atlantic_fisheries_management_areas/MapServer)) — polygon layers shipped:

| MapServer id | Published layer id |
|--------------|--------------------|
| 1 | `dfo_fma_scallop` |
| 4 | `dfo_fma_capelin` |
| 7 | `dfo_fma_mackerel` |
| 10 | `dfo_fma_herring` |
| 13 | `dfo_fma_squid` |
| 16 | `dfo_fma_crab` |
| 19 | `dfo_fma_salmon` |
| 22 | `dfo_fma_snow_crab` |
| 25 | `dfo_fma_northern_shrimp` |

NOAA ENC shipping lanes ([MarineTransportation /0](https://encdirect.noaa.gov/arcgis/rest/services/NavigationChartData/MarineTransportation/MapServer/0)) — clip with `--bbox` (full national extent is too large for git):

```powershell
python scripts/fetch_map_layer_arcgis.py `
  --url "https://encdirect.noaa.gov/arcgis/rest/services/NavigationChartData/MarineTransportation/MapServer/0" `
  --layer-id noaa_shipping_lanes_nw_atlantic `
  --name "NOAA Shipping Lanes (NW Atlantic)" `
  --bbox=-72,40,-50,52 `
  --simplify 0.001 `
  --archive-source
```

## APIs (authenticated)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/map/layers` | Catalog (id, name, style, bounds — no geometry). Optional `?platform=` filter; empty `platforms` in manifest = all platforms |
| `GET /api/map/layers/{id}` | Published GeoJSON; `ETag` + `Cache-Control: private, max-age=3600` |

Both return **403** when `map_vector_layers` is off.

## Code map

| Piece | Path |
|-------|------|
| Service | [`app/core/geo/map_layers.py`](../../../app/core/geo/map_layers.py) |
| Routes | [`app/routers/map.py`](../../../app/routers/map.py) |
| Client | [`web/static/js/vector_map_layer.js`](../../../web/static/js/vector_map_layer.js) (wired from `map_generator.js`; builds toggles from catalog) |
| UI | `#vectorLayerToggleGroup` in `home.html` / `slocum_home.html` |

## Adding another static layer (ops)

1. Convert/fetch WGS84 GeoJSON under `config/map_layers/published/`.
2. Add a `manifest.json` entry (`id`, `name`, `description`, `platforms`, `path`, `style`, `bounds`).
3. Optionally add the id to `LAYER_ORDER` in `vector_map_layer.js` for a preferred toggle order (unknown ids still appear after known ones).
4. Commit and deploy. Home maps pick up new layers from the catalog automatically.

## Related

- Architecture: [Static vector map layers](../architecture.md#static-vector-map-layers)
- Public login map (tracks only for now): [public_login_map.md](./public_login_map.md)
- Feature toggles: [ENV_VARIABLES.md](../ENV_VARIABLES.md)
- Remaining work: [backlog](../../tasks/backlog.md) (public map, PDF overlays, FMA simplify, fishery notices ↔ FMA map linkage)
