---
status: accepted
date: 2026-08-04
supersedes: null
---

# Title: Cache Robots4Whales DMON analyst-review HTML, do not scrape on request

## Context

Slocum DMON missions publish daily analyst-reviewed whale occurrence on WHOI
Robots4Whales / `dcs.whoi.edu` deployment pages. There is no stable public API;
pages are HTML tables colored by detection status. Glider Buddy needs this data
on the DMON dashboard and in Slocum weekly reports without presenting it as
first-party telemetry.

## Decision

Store a per-deployment `robots4whales_url` on `SlocumDeployment` (admin Mission
Overviews). A leader-only job fetches and parses eligible pages every 12 hours
into `data_store/dmon_review_cache/{mission_key}.json`. HTTP APIs and reports
read the cache only. Dashboard shows site/program attribution; reports also
credit scraped Analysts (PIs stay with Sensor Tracker metadata).

## Alternatives considered

- **Live scrape on dashboard open** — rejected: load latency, brittle under
  concurrent pilots, impolite to WHOI.
- **Env JSON mission→URL map only** — rejected: harder for ops; admin field
  matches existing sensor-card workflow.
- **Official WHOI API** — not available for this table.

## Consequences

Scraping can break if WHOI changes HTML; unknown colors are flagged as
`UNKNOWN(...)`. Cache may be up to ~12h stale. Ops must set the URL and enable
the `dmon` sensor card. Attribution must remain on reports when the section is
included. Weekly PDF table uses shared `styled_data_table` fonts/palette with
Detected / Possibly detected cell color mapping.
