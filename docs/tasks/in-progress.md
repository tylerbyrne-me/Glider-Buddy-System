# In Progress

What's actively being worked right now. Keep this list short — if it's not
being touched this week, it belongs back in `backlog.md`.

- [ ] Team area shell + ops tools: admin-only `/team` (title *Team Glider Buddy System*, `team_hub` toggle), entered from a second-row Team card on `/platform`. Catalog supports `kind=run` (`check_mission_files`, mission catalog dry-run) and `kind=page` tools: SFMC log-note import (`/team/sfmc-lognotes`, dry-run then post, in-process DB), Wave Glider telemetry hexbin (`/team/telemetry-hexbin`, WGMS and/or ERDDAP via `source_filter`, sync PNG under `data_store/team_hexbin_*`), Sensor Tracker browser (`/team/sensor-tracker`, live read-only), and Visualizations gallery (`/team/visualizations`, static Sensor Tracker fleet PNGs under `data_store/team_viz_*`; rebuild UI/CLI). Remaining `app/cli/*` and `scripts/*.py` catalog entries still open. Separate from WG/Slocum; does not consolidate per-platform Admin Management — idea inbox 2026-08-11
