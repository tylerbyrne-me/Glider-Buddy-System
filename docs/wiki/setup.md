# Setup

## Prerequisites

- Python via conda environment **`WorkPython`** (see `AGENTS.md` and `.cursor/rules/workpython-env.mdc`)
- Project dependencies from `requirements.txt`
- Optional: access to remote mission data paths / ERDDAP as configured in `.env`

## Install

```powershell
conda activate WorkPython
cd "path\to\Wave Glider Buddy System"
pip install -r requirements.txt
```

Copy or create a `.env` from your team’s template. Full variable reference: [ENV_VARIABLES.md](./ENV_VARIABLES.md).

## Running locally

From the repo root, with WorkPython active:

```powershell
conda activate WorkPython
uvicorn app.app:app --reload --host 127.0.0.1 --port 8000
```

Production-style (no reload) matches the app object used by gunicorn: `app.app:app`. Ops flags for the Linux service live in root [`AGENTS.md`](../../AGENTS.md).

## Running tests

```powershell
conda activate WorkPython
pytest app/ -v
```

See also [TESTING_QUICK_REFERENCE.md](./standards/TESTING_QUICK_REFERENCE.md).

## Common gotchas

- **git** / **gh** live in WorkPython (like `pip`), not on the default system PATH — `conda activate WorkPython` before git, or use `conda run -n WorkPython git ...`.
- On Windows, `conda run -n WorkPython python -c "..."` does not support multiline `-c` strings — use a `.py` file or `$env:USERPROFILE\.conda\envs\WorkPython\python.exe`.
- Templates and static files are under `web/templates/` and `web/static/` (not a top-level `templates/` app package).
- Production ops (systemd, gunicorn flags, cache cleanup) live in root [`AGENTS.md`](../../AGENTS.md), not only here.
- Admin setup notes: [how-tos/ADMIN_SETUP.md](./how-tos/ADMIN_SETUP.md).
