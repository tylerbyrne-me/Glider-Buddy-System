# Conventions

Rules and patterns to follow when adding or changing code. Keep this file honest —
if a rule stops being true, update it or delete it rather than letting it go stale.

Detailed standards live under [standards/](./standards/). Prefer this page for orientation; open the linked docs for full rules.

## Naming

- Python packages/modules: lowercase with underscores (e.g. `routers/user_routes.py` patterns already in tree).
- Prefer descriptive names with auxiliary verbs where helpful (`is_active`, `has_permission`).

### Product & platform naming

| Layer | Convention | Examples |
|-------|------------|----------|
| Product full | Glider Buddy System | login, `/platform`, footer |
| Product short | GBS | non-platform page titles where short brand fits |
| In-platform title | `{DisplayName} Glider Buddy System` | Wave Glider Buddy System, Slocum Glider Buddy System, Team Glider Buddy System |
| `platform_id` | snake_case | `wave_glider`, `slocum` |
| URL prefix | `/{kebab(id)}` | `/wave-glider`, `/slocum` |
| HTML pages | `{url_prefix}/{page}` | `/wave-glider/chatbot.html` |
| API (new / preferred) | `/api/{platform_id}/...` | `/api/slocum/...`; WG also accepts `/api/wave_glider/...` (aliased to legacy `/api/...`) |
| API (legacy WG) | `/api/...` | Grandfathered; first-party JS prefers `/api/wave_glider/...` via `withPlatformApiPrefix` |
| Feature gate | `{platform_id}_platform` | `slocum_platform` (WG always on) |
| KB toggle | `{platform_id}_knowledge_base` | |
| CSS product | `gbs-*` | `.gbs-navbar` |
| New platform code | `app/platforms/{id}/` | register in `app/core/platforms/` first |
| New WG-only modules | `app/platforms/wave_glider/` | leave existing WG in `app/core` unless a focused peel |

Import IDs and helpers from `app.core.platforms` instead of scattering string literals. Full decision record: [ADR 0003](../decisions/0003-platform-brand-naming.md).

## Module architecture (critical)

Dependency direction:

```text
Core → Routers → App
```

- Core must not import routers or `app.app`.
- Routers import core/services; do not import from `app.app` for shared helpers (use core modules / getters).
- Full detail: [CODE_STANDARDS.md](./standards/CODE_STANDARDS.md), [DEPENDENCY_INJECTION_STANDARDS.md](./standards/DEPENDENCY_INJECTION_STANDARDS.md).

## Code style

- Follow existing patterns in the area you edit; see also [SERVICE_STANDARDS.md](./standards/SERVICE_STANDARDS.md), [FORMS_FOLDER_STANDARDS.md](./standards/FORMS_FOLDER_STANDARDS.md), [WEB_FOLDER_STANDARDS.md](./standards/WEB_FOLDER_STANDARDS.md).
- Prefer Pydantic models for API I/O; `HTTPException` for expected errors.

## Testing expectations

- After meaningful changes: `pytest app/ -v` in WorkPython.
- Workflow: [TESTING_QUICK_REFERENCE.md](./standards/TESTING_QUICK_REFERENCE.md), [INCREMENTAL_TESTING_STRATEGY.md](./standards/INCREMENTAL_TESTING_STRATEGY.md).

## Commit / PR conventions

- **Never commit unless explicitly asked** (e.g. "commit", "create a commit"). Soft phrases like "clean up", "wrap up", or "looks good" are **not** commit requests — ask if unclear. Project rule: [`.cursor/rules/no-inferred-git-commits.mdc`](../../.cursor/rules/no-inferred-git-commits.mdc).
- When committing is requested, follow the repo’s existing commit message style.
- Do not commit secrets (`.env`, credentials).
- Always-apply Cursor rules live under [`.cursor/rules/`](../../.cursor/rules/) as `.mdc` files.

## Theme tokens

Light/dark themes are CSS custom properties on `<html data-theme="...">` (also `data-bs-theme` for Bootstrap). Source of truth: [`web/static/css/themes.css`](../../web/static/css/themes.css).

| Tier | Examples | Role |
|------|----------|------|
| Semantic `--app-*` | `--app-text`, `--app-bg`, `--app-card-border` | Preferred for custom CSS |
| Legacy aliases | `--text`, `--card-border` | Kept for existing `custom.css` |
| Bootstrap bridges | `--bs-card-bg`, `--bs-body-bg-rgb`, `--bs-border-color`, `--bs-primary` / `--bs-primary-rgb` | Keep Bootstrap components themed (buttons need RGB) |
| Comfort tokens | `--app-radius-md`, `--app-shadow-elevated`, `--app-alert-info-*`, `--app-map-frame-bg` | Shared components / maps |

### DOM hooks (User Settings → Appearance)

| Attribute | Values | Purpose |
|-----------|--------|---------|
| `data-accent` | `default`, `teal`, `high-contrast`, `slate`, `ocean`, `seafoam`, `amber` | Remap `--app-primary` / `--app-accent`, navbar/footer, active-card, Bootstrap primary |
| `data-platform` | `wave_glider`, `slocum` (omit when not a platform page) | Accent resolution + anti-FOUC |
| `data-density` | `comfortable`, `compact` | Placeholder: slight radius/shadow + `.gbs-card` / `.gbs-hint` padding only — expand once desired density is defined |
| `data-map-style` | `match-theme`, `light`, `dark` | Leaflet basemap override |

### Preference JSON (`users.ui_preferences`)

Synced with `localStorage` via [`ui_preferences.js`](../../web/static/js/ui_preferences.js) / [`auth.js`](../../web/static/js/auth.js); edited in User Settings Appearance (`GET`/`PUT /api/users/me`).

```json
{
  "theme_mode": "light | dark | system",
  "accent": "default",
  "platform_accents": {
    "wave_glider": "inherit",
    "slocum": "amber"
  },
  "density": "comfortable",
  "map_style": "match-theme"
}
```

**Accent resolution:** if the page has `data-platform` and `platform_accents[platform]` is a concrete accent (not `inherit`), use that; otherwise use general `accent`. Non-platform pages (login, settings, platform chooser) always use general. Banner `#themeSwitch` forces light/dark (exits `system`). Unauthenticated pages stay localStorage-only.

Shared UI classes: [`custom.css`](../../web/static/css/custom.css) (`.gbs-card`, `.gbs-hint`, `.gbs-empty-state`, `.platform-choice-card`). Page CSS: [`pages/login.css`](../../web/static/css/pages/login.css), [`pages/admin.css`](../../web/static/css/pages/admin.css). Maps: [`map_tiles.js`](../../web/static/js/map_tiles.js).

**Cache busting:** load `themes.css`, `custom.css`, `auth.js`, and `user_settings.js` with `?v={{ app_version }}`. `app_version` is derived from mtimes of those theme assets (plus key dashboard JS and Team Sensor Tracker JS) in [`template_context.py`](../../app/core/template_context.py). When adding theme/appearance assets, include them in that token list or browsers may keep stale CSS/JS.

## Patterns to follow

- Data loading through the data service layer (see CODE_STANDARDS).
- Feature toggles via `FEATURE_TOGGLES_FILE` (pretty JSON) or `FEATURE_TOGGLES_JSON` rather than hard-coding platform UI.
- Weekly report visual style: [weekly_report_styleguide.md](./standards/weekly_report_styleguide.md).
- **Dashboard left-nav summaries soft-refresh with charts** — do not rely on SSR + full `location.reload()` for realtime card/mini-trend/“Last data” freshness. Pattern (Wave Glider + Slocum):
  1. Card contract: `{values, latest_timestamp_str, time_ago_str, mini_trend}` (optional extras like `ess_state`).
  2. Builder in `app/platforms/{id}/summaries.py` (shared for SSR + JSON).
  3. `GET /api/{platform_id}/sensor-summaries/{resource_id}` (WG: prefer `/api/wave_glider/...`; handler may live at legacy `/api/sensor-summaries/...` via alias).
  4. On cache `last_data_timestamp` advance: quietly reload open charts **and** refresh summary cards/footers/mini-charts — no hard reload as the primary path.
  5. When changing left-nav cards or timestamps, ask: *does this update live, or only on SSR?* See [architecture](./architecture.md#dashboard-summary-soft-refresh).

## Patterns to avoid

- Circular imports via `from app.app import ...` in routers/core.
- Gunicorn `--preload` in production — see [ADR 0002](../decisions/0002-no-gunicorn-preload.md).
- Guessing project style — re-read this file and the linked standards instead.
- Leaving mission-dashboard summary cards SSR-only while charts poll/live-fetch (causes “charts fresh, cards stale” lag).
