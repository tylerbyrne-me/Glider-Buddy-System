# cmocean colormap reference and adoption flags

This project already uses **`cmocean.cm.speed`** for speed-over-ground on PDF telemetry maps ([`app/core/plotting.py`](../app/core/plotting.py): `plot_telemetry_page_with_notes`, `plot_telemetry_for_report`).

Below: Python accessor is always `import cmocean.cm as cmo` then `cmo.<name>` (same as the **name** column).

## Colormap quick reference

| Name | `cmo.*` | Typical physical use |
|------|---------|----------------------|
| Thermal | `thermal` | Temperature (water, air, fluorometer) |
| Haline | `haline` | Salinity / practical salinity |
| Solar | `solar` | Irradiance, solar input (positive-only fields) |
| Ice | `ice` | Sea ice concentration / thickness |
| Gray | `gray` | Neutral sequential / print-friendly |
| Oxygen | `oxy` | Dissolved oxygen (not “oxygent”) |
| Depth | `deep` | Bathymetry, depth below surface |
| Dense | `dense` | Seawater density |
| Algae | `algae` | Chlorophyll-like pigments |
| Matter | `matter` | CDOM / colored dissolved organic matter |
| Turbid | `turbid` | Turbidity, suspended matter |
| Speed | `speed` | Speed magnitude (SOG, current speed) — **in use** |
| Amp | `amp` | Amplitude (wave height, signal envelope) |
| Tempo | `tempo` | Velocity / period-style fields (package docs: “velocity”) |
| Rain | `rain` | Precipitation |
| Phase | `phase` | Cyclic / phase quantities (e.g. tidal phase, 0–360°) |
| Topo | `topo` | Land elevation / topographic shading |
| Balance | `balance` | Diverging data around a meaningful center (e.g. anomalies) |
| Delta | `delta` | Rate of change, differences |
| Curl | `curl` | Vorticity, vertical component of curl |
| Diff | `diff` | Difference between two fields |
| Tarn | `tarn` | Velocity along bathymetric gradient (cmocean “tarn” semantics) |

## Flagged code areas (this repo)

### Matplotlib / PDF reports — [`app/core/plotting.py`](../app/core/plotting.py)

| Location | Current style | cmocean opportunity |
|----------|----------------|---------------------|
| `generate_power_plot`, `plot_power_for_report` | Fixed line colors (`blue`, `orange`, …) | **solar** if you add a 2D or map-based irradiance / power density field; otherwise line charts stay as-is unless you add a **scalar-colored** trajectory or calendar heatmap. |
| `generate_ctd_plot`, `plot_ctd_for_report` | Line plots (`r-`, `orange`, `b-`) | **thermal** for water temp, **haline** for salinity, **oxy** for oxygen if you add **scatter / pcolormesh / TS diagram** (time–depth or S–T) instead of only time series. |
| `generate_weather_plot`, `plot_weather_for_report` | Line colors | **thermal** for air temp fields; **rain** for precipitation grids; wind remains line-friendly unless you add **speed-colored** quiver norm → **speed** or **tempo**. |
| `generate_wave_plot`, `plot_wave_for_report` | Line colors | **amp** for significant wave height or spectral energy maps; **phase** for mean wave direction wrapped 0–360° on a polar or map grid. |
| `plot_c3_for_report` | `tab:*` lines for C1–C3 RFU | **algae** / **matter** / **turbid** if channels map to those proxies and you move to **depth–time** or **map** pseudocolor. |

### Seaborn heatmaps — [`app/services/error_plotting_service.py`](../app/services/error_plotting_service.py)

| Function | Current `cmap` | cmocean opportunity |
|----------|----------------|---------------------|
| `plot_error_heatmap` | `'YlOrRd'` | **`matter`** or **`amp`** for sequential counts; **`gray`** for print-safe counts. |
| `plot_confidence_heatmap` | `'RdYlGn'` (diverging good/bad) | **`balance`** (diverging, perceptually uniform) is the closest cmocean analogue; **`delta`** if the quantity is explicitly a change score. |

### Maps and KML — [`app/core/map_utils.py`](../app/core/map_utils.py), [`web/static/js/map_generator.js`](../web/static/js/map_generator.js)

| Context | Current style | cmocean opportunity |
|---------|----------------|---------------------|
| KML tracks, Leaflet polylines | Discrete hex palette per track | cmocean is **not** applied in-browser today. To mirror **speed**, **deep**, **haline**, etc., sample `cmo.<name>` to a hex LUT in Python and pass colors per segment, or generate a small JS gradient from exported stops. |

### Dashboard (Chart.js) — [`web/static/js/dashboard.js`](../web/static/js/dashboard.js)

| Context | Current style | cmocean opportunity |
|---------|----------------|---------------------|
| `CHART_COLORS` line charts | Fixed RGBA per series | Same as maps: only relevant if you add **scalar-colored** points/bubbles; would need a **LUT** derived from cmocean, not the colormap object itself. |

### CLI PNG trends — [`app/cli/cli.py`](../app/cli/cli.py)

Calls `generate_*_plot` in `plotting.py`; any cmocean work there follows the same flags as the `generate_*` rows above.

## Suggested priority (optional)

1. **Error heatmaps** — drop-in `cmap=cmo.matter` / `cmap=cmo.balance` with no data model change.  
2. **CTD / wave 2D panels** — highest science payoff if you add TS or frequency–energy plots (`thermal` + `haline`, or **`amp`** for spectra).  
3. **Web map parity** — only if product needs SOG-colored tracks in Leaflet; export stops from `cmo.speed`.

## Package note

Install is already satisfied via [`requirements.txt`](../requirements.txt) (`cmocean`). Import pattern used in code: `import cmocean.cm as cmo`.
