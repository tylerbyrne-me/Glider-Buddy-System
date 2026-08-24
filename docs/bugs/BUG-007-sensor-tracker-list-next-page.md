---
id: BUG-007
type: bug
status: fixed
priority: medium
created: 2026-08-19
tags: [team, sensor-tracker, pagination]
---

# Sensor Tracker browser Next repeats page 1

## Repro

1. Open Team → Sensor Tracker browser.
2. Open **Deployments** (or any entity with more than 25 rows).
3. Click **Next**.

The footer page number increments (`page=2`, `page=3` in the API) but the table rows stay the first page.

## Expected

Each Next click shows the next 25 Tracker rows.

## Notes

Buddy strips `page` / `limit` / `offset` on Tracker list GETs (those keys 403). When Tracker returns a DRF payload (`next` / `previous` / `count`), `normalize_list_payload` passed that first page through unchanged and ignored Buddy’s `page`. Every Buddy page therefore re-fetched Tracker page 1.

## Resolution

`list_entities` follows Tracker’s `next` URL until it has enough rows for the requested Buddy page, then slices locally. Same walker is used for relationship lists and platform → deployments. How-to: [sensor_tracker_team_browser.md](../wiki/how-tos/sensor_tracker_team_browser.md).
