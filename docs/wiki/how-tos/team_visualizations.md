# Team Visualizations gallery

Admin-only gallery of **named, static** fleet charts built from Sensor Tracker.
Images sit on disk under `data_store/team_viz_outputs/` until you rebuild (UI or CLI).
Inspired by [RU-COOL Glider Viz](https://marine.rutgers.edu/cool/data/gliders/viz/) hosting style; v1 is not public and not interactive d3.

## Access

- Feature toggle: `team_hub`
- Role: admin
- URL: `/team/visualizations` (also listed on `/team` as **Visualizations gallery**)

## Charts (v1)

| Slug | Chart | Meaning |
|------|--------|---------|
| `platform_share` | Grouped bars per hull | Deployment count and days at sea |
| `sensor_days_by_platform` | Stacked bars | At-sea days by **sensor identifier** (top ~12 + Other) |
| `use_over_time` | Year × month heatmap (or yearly bars if sparse) | Glider-days from deployment windows |

All values are **at-sea days** (not shelf time) on **Wave Glider and Slocum platforms only**. Other Sensor Tracker platform types (buoys, etc.) are excluded using the same allowlist as the mission catalog (`allowed_platform_models` in `config/mission_data_providers.json`, with name heuristics when the model is missing). Open-ended Tracker windows run through the snapshot `as_of`. Totals may be low if a join list hit the fleet fetch cap.

Sensor days use the same intersection rule as Team Sensor Tracker detail: sensor-on-instrument ∩ instrument attachment ∩ that hull’s deployments (including logger-mounted instruments). The gallery does **not** page the full `/api/sensor/` catalog.

Wave Glider telemetry hexbin stays at `/team/telemetry-hexbin` (parameterized, generate-on-demand).

## Rebuild

1. Open Team → Visualizations.
2. **Rebuild all** (or per-card **Rebuild**). Optional **Reuse snapshot** skips a new Tracker walk and re-renders from `data_store/team_viz_cache/fleet_snapshot.json`.
3. Prefer the CLI for the first full rebuild if gunicorn’s ~200s timeout is a risk:

```powershell
conda activate WorkPython
python -m app.cli.team_visualizations --chart all
python -m app.cli.team_visualizations --chart platform_share --reuse-snapshot
```

## On disk

| Path | Contents |
|------|----------|
| `data_store/team_viz_cache/fleet_snapshot.json` | One Tracker snapshot shared by all charts |
| `data_store/team_viz_outputs/{slug}/latest.png` | Chart image |
| `data_store/team_viz_outputs/{slug}/meta.json` | generated_at, as_of, notes, row counts |

GET `/api/team/visualizations` and `/api/team/visualizations/{slug}/image` never contact Tracker.

## APIs

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/team/visualizations` | Registry + meta |
| POST | `/api/team/visualizations/generate-all` | Body `{ "reuse_snapshot": false }` |
| POST | `/api/team/visualizations/{slug}/generate` | Same body |
| GET | `/api/team/visualizations/{slug}/image` | PNG `FileResponse` |

## Out of scope (v1)

- Public `/viz` hosting
- Ad-hoc upload/drop folder (separate backlog: one-off plotting space)
- Scheduled rebuild, track distance, calibration/lifetime
