# Static vector map layers

Toggleable GeoJSON reference zones on authenticated home maps (Wave Glider and Slocum). First shipped layers: **GOSL DSZ** and **GOSL safe zones** (Newfoundland). Feature toggle: `map_vector_layers` (default **off**).

Public login map and PDF weekly reports do **not** draw these layers yet — see backlog.

## Enable

1. Set `"map_vector_layers": true` in `FEATURE_TOGGLES_FILE` or `FEATURE_TOGGLES_JSON` (see [`config/feature_toggles.example.json`](../../../config/feature_toggles.example.json)).
2. Restart the app (or reload if your process picks up toggle file changes).
3. Open `/wave-glider/` or `/slocum/` home → **Reference zones** → toggle **GOSL DSZ** / **GOSL safe zones**.

Layers sit under tracks (Leaflet pane z-index 350). Click a polygon for its placemark name.

## On-disk layout (git-tracked)

```
config/map_layers/
  manifest.json                 # catalog: id, name, style, bounds, platforms
  published/*.geojson           # canonical geometry served to the browser
  sources/*.kml                 # optional archived originals (audit / re-ingest)
```

Config setting: `map_layers_dir` (default `config/map_layers`) in [`app/config.py`](../../../app/config.py).

**Deploy model:** convert on a developer/ops machine → commit `published/` + `manifest.json` (+ source KML) → production gets layers via the normal git deploy. Runtime does **not** need geopandas/pyogrio; the API only reads published GeoJSON.

## Ingest (KML → GeoJSON)

WorkPython:

```powershell
conda activate WorkPython
python scripts/convert_map_layer_kml.py `
  --input "path\to\zones.kml" `
  --layer-id gosl `
  --archive-source
```

Current script splits placemarks named `DSZ *` vs `safe zone*` into `gosl_dsz` / `gosl_safe_zones`. Uses **pyogrio** (Fiona is not required). Re-run after source edits, then commit the updated files.

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
| Client | [`web/static/js/vector_map_layer.js`](../../../web/static/js/vector_map_layer.js) (wired from `map_generator.js`) |
| UI | `vectorOverlaySection` in `home.html` / `slocum_home.html` |

## Adding another static layer (ops)

1. Convert or hand-author WGS84 GeoJSON under `config/map_layers/published/`.
2. Add a `manifest.json` entry (`id`, `name`, `description`, `platforms`, `path`, `style`, `bounds`).
3. Commit and deploy.
4. **Near-term gap:** home UI toggles are still hardcoded for GOSL. New layers need either a temporary checkbox in templates + `TOGGLE_BINDINGS` in `vector_map_layer.js`, or the catalog-driven UI backlog item.

## Related

- Architecture: [Static vector map layers](../architecture.md#static-vector-map-layers)
- Public login map (tracks only for now): [public_login_map.md](./public_login_map.md)
- Feature toggles: [ENV_VARIABLES.md](../ENV_VARIABLES.md)
