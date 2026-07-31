# Backlog

Roughly ordered by priority, top = next up. Move an item to `in-progress.md`
when you start it; move it to `done.md` when it ships.

Keep each line self-contained enough that the AI assistant can pick it up cold:
what, where, and any constraint that matters.

Seeded 2026-07-29 from recent unfinished-work review
([Review of unfinished tasks](81c85f36-51b6-4c5b-9258-b0923532df06)) plus a light archive skim.

## High priority

- [ ] Confirm prod `data/` and `data_store/` ownership (`chown cove:cove` or service user) and reclaim stranded `*.tmp` if mission CSV sync still fails — see AGENTS.md NFS/`os.replace` notes; chat [Mission CSV rename fix](c7ca764b-4f6c-42b2-a304-54183c563871)
- [ ] Commit, QA, and deploy the outstanding theme + chart hover/crosshair UI batch (keep as its own commit — not mixed with docs) — [Theme consistency](80b24643-2d50-47fd-96bb-2731d082fd3b), [Chart hover fix](c7ac3551-0b33-4987-a8c6-4d2e34e41304)
- [ ] Prod verify: auto-checklist actually submitting, Iridium map toggle on prod, UTC hardening / sensor cards as applicable; DMON card on a DMON-equipped glider (byte-count chart + ASC 48h list + green/red gap status dot + gated checklist Science items after schema **12** mirror rebuild + SFMC refresh)

## Medium priority

- [ ] Slocum weekly report polish Phase 2+: landscape multi-panel sensors, checklist-bundle charts, end-of-mission mode, persist `weekly_report_url` — [Report polish Phase 1](b8a79301-0344-450e-99c7-0d8d67d64032)
- [ ] Chart platform follow-ups: ERDDAP/narrow bulk API (drop client `rowsToSeries`), server-owned chart config registry, optional spectrum/doughnut/mini-trends/forecast into declarative system, WG↔Slocum schema convergence, JS test harness — [WG declarative rewrite](bcc8cb49-ec97-49b6-b793-8a04926f4140)

## Low priority / someday

- [ ] Slocum checklist history follow-ups (multi-day matrix / sparklines); side-by-side compare shipped 2026-07-29 — [Checklist history ideas](378f5e79-578b-4f7a-99cd-ca202e222768)
- [ ] Dockerize app for a more stable host — [Docker migration options](3357a043-5fd2-46e6-bfb5-fd14329e8c7e)
- [ ] Rebrand to “Glider Buddy System” (repo + product); Phase 3 ops called out as separate — [Glider Buddy rebrand](048fab21-2379-425a-935a-b58c0cb17690)
- [ ] Optionally standardize complex error handling in `app/routers/forms.py` and `app/routers/live_kml_router.py` (acceptable as-is; see `docs/archive/reviews/HIGH_PRIORITY_COMPLETION_SUMMARY.md`)
