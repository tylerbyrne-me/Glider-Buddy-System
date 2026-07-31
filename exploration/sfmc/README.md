# SFMC REST API exploration

Read-only probes against **Teledyne Slocum Fleet Mission Control** (not Salesforce Marketing Cloud).

## Prerequisites

Add to project-root `.env` (never commit):

```env
SFMC_BASE_URL=https://your-sfmc-host
SFMC_CLIENT_ID=...
SFMC_CLIENT_SECRET=...
```

Generate Client ID + Secret from the SFMC web UI: user menu → **API Access** → **Generate**.

## Run

From project root with `WorkPython`:

```powershell
conda activate WorkPython
python exploration/sfmc/probe_sfmc.py --discover --sfmc-only --insecure
python exploration/sfmc/probe_sfmc.py --fetch --insecure
python exploration/sfmc/probe_sfmc.py --fetch --glider hostglider1 --insecure
```

| Flag | Purpose |
|------|---------|
| `--discover` | Try auth patterns + candidate paths; append `discovery_log.jsonl` |
| `--fetch` | Save JSON samples under `samples/` (after auth works) |
| `--sfmc-only` | Limit discovery to `/sfmc/api/*` (recommended) |
| `--insecure` | Skip TLS verify (self-signed SFMC certs) |
| `--glider NAME` | Per-glider folder/script probes in fetch mode |
| `--max-requests N` | Cap discovery requests (default 120) |

## Confirmed endpoint inventory (from Teledyne ``sfmc`` Node package)

Auth (was the 401 root cause):

```http
POST /sfmc/api/signin
Content-Type: application/json

{"clientId":"...","secret":"..."}
→ {"token":"..."}
```

Then:

```http
Authorization: Bearer <token>
GET /sfmc/api/v1/gliders/{glider}
GET /sfmc/api/v1/active-deployment/{glider}
GET /sfmc/api/v1/scripts-for-glider/{glider}
GET /sfmc/api/v1/glider-folder-file-listing/{glider}/{folder}?page=0&filter=*_goto_*.ma
GET /sfmc/api/v1/download-glider-file/{glider}/{folder}/{fileName}

# Surface dialog / Device Status (t/m/s) — UI path; Bearer may work:
GET /sfmc/glider-requests/get-last-x-bytes-of-glider-log-file/{gliderId}/{logFileName}/{bytes}
```

Reference tree (outside this repo): `…/Data/sfmc-nodejs-rest-programs/node_modules/sfmc/`.

### Run Teledyne smoke test

```powershell
python exploration/sfmc/probe_sfmc.py --v1-smoke --glider peggy --insecure
```

| Flag | Purpose |
|------|---------|
| `--v1-smoke` | Signin + `/sfmc/api/v1/*` reads (default when no other mode) |
| `--discover` | Blind path walk (legacy) |
| `--fetch` | Dump samples after discovery |
| `--insecure` | Skip TLS verify |
| `--glider NAME` | Glider name (default `peggy` for v1-smoke) |

**Live smoke (2026-07-20):** `https://gliderbak.ceotr.ca` — signin 200 + all v1 GETs 200 for `peggy`.

| Endpoint | Checklist use |
|----------|---------------|
| `/sfmc/api/v1/newest-mission-details/{glider}` | `mission_file_running_val` ← `data.missionName` |
| `/sfmc/api/v1/scripts-for-glider/{glider}` | `script_running_val` ← assigned script when present |
| `/sfmc/api/v1/glider-folder-file-listing/.../from-glider` | `offloaded_24h_val` ← any `results` in last 24h; DMON `dmon_asc_files` ← `filter=*.asc` last 48h (timestamps kept) |
| `/sfmc/api/v1/glider-folder-file-listing/.../archive` + download | `goto_state_val` ← newest `*_goto_*.ma` |
| `/sfmc/api/v1/active-deployment/{glider}` | deployment context / aborts when present |

Response notes: most GETs wrap payload in `{"data": ...}`; folder listings use `{results:[{fileName, dateTimeModified, fileSize}]}`.

**Archived SFMC missions (future):** The live client only covers **active** SFMC deployments. Archived missions / historical logs may have separate API paths; they are not explored or implemented. Buddy soft-archived `SlocumDeployment` rows must not be polled on the active SFMC refresh loop. On-demand historical SFMC autofill would be a later, separate path.


## Fallbacks if auth stays 401

1. **Browser DevTools** (no SSH): Log into SFMC → Network tab → open Active Deployment / glider files → copy request URL, method, headers, and body for a successful call.
2. **`sfmc.tgz`** (needs server access): Copy `/opt/sfmc-toolbox/sfmc-nodejs-rest-lib/sfmc.tgz`, unpack, read auth + endpoint code. Template config: `/opt/sfmc-toolbox/sfmc-nodejs-rest-config/local.json` (`hostname`, `client_id`, `secret`).
3. **Regenerate API credentials** on the API Access page if the current pair is stale or tied to a disabled user.

## Outputs

| Path | Contents |
|------|----------|
| `discovery_log.jsonl` | One JSON object per probe (gitignored) |
| `samples/*.json` | Raw API payloads when fetch succeeds (gitignored) |
| [checklist_field_mapping.md](checklist_field_mapping.md) | Checklist field → SFMC endpoint mapping |

## Next phase (app integration)

After auth works and samples exist:

- Add optional `sfmc_*` settings to `app/config.py`
- Implement `app/core/sfmc_client.py`
- Merge into `load_checklist_autofill_values()` in `app/core/slocum_checklist_autofill.py`
- Map glider host name on `SlocumDeployment` (new `sfmc_glider_name` field)

See project plan: SFMC API Exploration and Checklist Autofill Groundwork.
