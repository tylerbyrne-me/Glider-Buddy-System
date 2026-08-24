# Project Wiki

Start here. This folder is the source of truth for "how does this work."

## Pages

- [Architecture](./architecture.md) — how the pieces fit together (includes platforms)
- [Setup](./setup.md) — getting a dev environment running
- [Conventions](./conventions.md) — coding/naming rules (links to detailed standards)
- [Environment variables](./ENV_VARIABLES.md) — config reference
- [Public login map](./how-tos/public_login_map.md) — unauthenticated login-page tracks / KML / labels
- [Static vector map layers](./how-tos/map_vector_layers.md) — GOSL / DFO FMA & LFA / NOAA shipping GeoJSON overlays on home maps (KML + ArcGIS ingest)
- [AIS vessel density map layer](./how-tos/vessel_density_map_layer.md) — DFO NW Atlantic AIS density rasters (2025 monthly) on home maps
- [CIOPS-East ice forecast map layer](./how-tos/ciops_ice_map_layer.md) — MSC GeoMet sea ice concentration WMS on home maps
- [NAVWARN map layer](./how-tos/navwarn_map_layer.md) — CCG navigational warnings on home maps (HTML scrape + cache)
- [Mission catalog cutover](./how-tos/mission_catalog_cutover.md) — local soak done; production replay (ADR 0005)
- [Sensor Tracker Team browser](./how-tos/sensor_tracker_team_browser.md) — admin Team hub live inventory search
- [Team Visualizations gallery](./how-tos/team_visualizations.md) — static fleet charts from Sensor Tracker
- [Glossary template](./GLOSSARY_TEMPLATE.md) — RAG/glossary authoring
- [Module templates](./MODULE_TEMPLATES_README.md) — module scaffolding notes

Rebrand ops how-tos: [BRAND_ASSETS](./how-tos/BRAND_ASSETS.md), [GITHUB_RENAME](./how-tos/GITHUB_RENAME.md), [PROD_PATH_RENAME](./how-tos/PROD_PATH_RENAME.md).

## How-tos

Operational and sensor guides: [how-tos/README.md](./how-tos/README.md).

## Standards

Detailed coding and folder standards: [standards/README.md](./standards/README.md). Prefer [conventions.md](./conventions.md) first; open standards files for depth.

## Tracking

- [Backlog](../tasks/backlog.md) / [In progress](../tasks/in-progress.md) / [Done](../tasks/done.md)
- [Bugs](../bugs/README.md)
- [Decisions (ADRs)](../decisions/0000-template.md) — [0001 leader lock](../decisions/0001-gunicorn-leader-lock.md), [0002 no preload](../decisions/0002-no-gunicorn-preload.md), [0003 platform/brand naming](../decisions/0003-platform-brand-naming.md), [0004 DMON Robots4Whales cache](../decisions/0004-dmon-robots4whales-review-cache.md), [0005 mission catalog live keys](../decisions/0005-mission-catalog-live-keys.md)

## Archive

Historical plans, reviews, and analyses: [archive/README.md](../archive/README.md) (`plans/`, `reviews/`, `analyses/`). Prefer wiki + tasks for current work.

## For the AI assistant

If you're an AI assistant picking up this project for the first time (or resuming after a break), for **non-trivial** work read in this order:

1. This file
2. `architecture.md`
3. `conventions.md`
4. `../decisions/` — skim filenames, read any that touch the area you're working on
5. `../tasks/backlog.md` and `../tasks/in-progress.md` for current state

Don't assume prior context carries over between sessions — always re-read before making non-trivial changes.
