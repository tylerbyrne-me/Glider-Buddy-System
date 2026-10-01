# Wave Glider ORA request

Team page for the Liquid Robotics Operational Risk Assessment (ORA). Admin only, feature toggle `team_hub`.

Open **Team → Wave Glider ORA request** (`/team/ora`).

## What you fill

- Optional catalog mission (planned or active Wave Glider). That fills hull, dates, and SV2/SV3, and applies the last saved vehicle config for that hull.
- Request header: requester, project code, client, purpose, priority.
- Operations area on the map: hold station (one click), box (two corners become four coordinate rows), or a course (each click appends a point). The table stays editable. Glider tracks from the last 48 hours can be shown for context, along with the same reference overlays as the home map when those features are on.
- Vehicle config and the device power table. **Load from Sensor Tracker** merges instruments on that hull (and on its data loggers) with the local watts/duty-cycle library. Uncheck a row to leave it out of the PDF.
- Notes.

**Save draft** stores the request and remembers non-empty vehicle fields for the hull. **Download PDF** builds the request with the same ReportLab styles as the mission reports. Email the file to `opscenter@liquid-robotics.com`. The app does not send mail.

## Storage

Drafts are `ora_requests`. Hull memory is `ora_hull_profiles`. Neither table is `submitted_forms`. See [ADR 0010](../../decisions/0010-team-ora-drafts.md).

Apply the migration `20260928_ora_requests` before using the page on a database that does not create tables from models.
