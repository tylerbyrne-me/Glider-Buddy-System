# Conventions

Rules and patterns to follow when adding or changing code. Keep this file honest —
if a rule stops being true, update it or delete it rather than letting it go stale.

Detailed standards live under [standards/](./standards/). Prefer this page for orientation; open the linked docs for full rules.

## Naming

- Python packages/modules: lowercase with underscores (e.g. `routers/user_routes.py` patterns already in tree).
- Prefer descriptive names with auxiliary verbs where helpful (`is_active`, `has_permission`).

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

- Only commit when asked; follow the repo’s existing commit message style.
- Do not commit secrets (`.env`, credentials).

## Patterns to follow

- Data loading through the data service layer (see CODE_STANDARDS).
- Feature toggles via config / `FEATURE_TOGGLES_JSON` rather than hard-coding platform UI.
- Weekly report visual style: [weekly_report_styleguide.md](./standards/weekly_report_styleguide.md).

## Patterns to avoid

- Circular imports via `from app.app import ...` in routers/core.
- Gunicorn `--preload` in production — see [ADR 0002](../decisions/0002-no-gunicorn-preload.md).
- Guessing project style — re-read this file and the linked standards instead.
