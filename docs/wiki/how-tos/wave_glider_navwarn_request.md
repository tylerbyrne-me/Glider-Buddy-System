# Wave Glider NAVWARN request

Team page for the Canadian Coast Guard NAVWARN request form. Feature toggle `team_hub`; access via `can_access_team` (admins always allowed).

Open **Team → Wave Glider NAVWARN request** (`/team/navwarn`).

## What you fill

- NAVWARN desk: **Sydney** or **Port aux Basques** (Prescott is deferred until contact details are confirmed). The desk name and return email on the form update; the Atlantic Region line stays as on the official form.
- Optional catalog mission (planned or active Wave Glider) to seed title. Hull ID is **not** the platform name (`SV3-1070`); choosing a mission looks up the currently attached Sensor Tracker component `Float SV3 - C34167NS` and fills `C34167NS`.
- Contact block (telephone and email prefill from your account when set under User Settings), schedule, position (degrees / minutes formats without degree symbols), nature of operation, vessels/markers, wash/berth, and other mariner details.
- **Fill Wave Glider defaults from hull** inserts the standard vessels / markers / other-details wording with the current Float SV3 hull ID. Choosing a mission does this automatically for empty fields once the hull ID resolves.

## Helpers

- **Start / Completion:** **Now** stamps the current time; the calendar button opens a date/time picker; **Start +1 d / +7 d / +30 d** sets completion from the start. **Use catalog mission start / end** copies the mission window (also prefilled on mission select when empty). Stamps use `15:00 UTC 2026-04-21`; switching the Timezone radio converts stamps written in the old zone (`Local` = browser time).
- **Use last telemetry fix** fills lat/lon from the linked mission's newest track point (last 72 h) and shows the fix age. **Prints on the form as** previews the position rows in the chosen format.
- **Operations area map** (like ORA): **Hold station** (one point + optional radius circle), **Course**, or **Polygon**. The first point (polygon: vertex centre) becomes the form lat/lon, and the area is written to **Additional positions** in the same decimal degrees style as those fields (`44.384238, -63.340973`) until you edit that text by hand. Points save with the draft (`area_json`). Reference overlays match the ORA map.

**Save draft** stores the request in `navwarn_requests`. **Duplicate as update** copies a draft, marks it as an update, and lets you enter the previous NAVWARN number (for example `NW-N-0623-26`). Issued numbers arrive only after the Coast Guard publishes the warning, so automatic number tracking is backlog work.

## Downloads

- **Download .docx** fills the official template at `app/platforms/wave_glider/templates/navwarn_request_form.docx` (desk title, return email, value cells, and checkbox states only).
- **Download PDF** builds a ReportLab copy of the same wording for comparison.
- Filenames: `NAVWARN_Request_<hull>_YYYY-MM-DD.docx` / `.pdf` (UTC date of download; hull from the Float SV3 ID, or `Unknown` if empty).

Email the file yourself to the desk address shown on the page (copy-email button). The app does not send mail. See [ADR 0015](../../decisions/0015-navwarn-docx-template-fill.md).

## Storage

Drafts are `navwarn_requests` (not `submitted_forms`). Apply migrations `20261116_navwarn_requests`, `20261116_user_telephone`, and `20261116_navwarn_area` before using the page on a database that does not create tables from models. Set your telephone under **User Settings** so new requests can prefill it with your account email.
