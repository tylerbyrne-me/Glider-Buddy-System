# Wave Glider ORA request

Team page for the Liquid Robotics Operational Risk Assessment (ORA). Feature toggle `team_hub`; access via `can_access_team` (admins always allowed).

Open **Team → Wave Glider ORA request** (`/team/ora`).

## What you fill

- Optional catalog mission (planned or active Wave Glider). That fills hull, dates, and SV2/SV3, and applies the last saved vehicle config for that hull.
- Request header: requester, project code, client, purpose, priority.
- Operations area on the map: the mode buttons pick what the next click adds. Hold station adds one point, box takes two clicks and adds four corner rows, and course adds one point per click. Every mode adds to the end of the existing list, so one request can mix a course, hold stations, and boxes; use **Clear points** to start over. Each run of `Box NW/NE/SE/SW` rows is drawn as a filled polygon. The table stays editable. Glider tracks from the last 48 hours can be shown for context, along with the same reference overlays as the home map when those features are on.
- Vehicle config and the device power table. **Load from Sensor Tracker** merges currently attached instruments on that hull and on its own flight/science data loggers with the local watts/duty-cycle library (logger instruments are filtered by logger id, not the shared type label). Uncheck a row to leave it out of the PDF.
- Notes.

**Save draft** stores the request and remembers non-empty vehicle fields for the hull. **Download PDF** builds the request with the same ReportLab styles as the mission reports. The coordinates table has a `#` column and is preceded by an operations-area map drawn on the server (`app/platforms/wave_glider/ora_map.py`). It uses the weekly-report Cartopy base: land/ocean, ETOPO depth contours when `report_bathymetry_contours` is on, compass, scale bar, and regional inset. Points are numbered to match the table, hold stations are stars, and box runs are shaded. The map does not copy the on-screen Leaflet view or its overlays. If no row has a lat/lon, or the map fails to render, the PDF is produced without the map (the failure is logged). Email the file to `opscenter@liquid-robotics.com`. The app does not send mail.

## Storage

Drafts are `ora_requests`. Hull memory is `ora_hull_profiles`. Neither table is `submitted_forms`. See [ADR 0010](../../decisions/0010-team-ora-drafts.md).

Apply the migration `20260928_ora_requests` before using the page on a database that does not create tables from models.
