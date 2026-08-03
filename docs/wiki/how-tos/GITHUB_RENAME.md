# GitHub repository rename (GBS)

Canonical slug: **`Glider-Buddy-System`** (was `Wave-Glider-Buddy-System`).

## Before rename (backup gate)

Do this **before** changing the repository name:

1. Record inventory: `git remote -v`, `git rev-parse HEAD`, `git log -1 --oneline`, current branch.
2. Push an annotated tag, e.g. `pre-gbs-rename-YYYYMMDD`.
3. Take a bare mirror outside the working tree:

```powershell
conda activate WorkPython
git clone --mirror "https://github.com/tylerbyrne-me/Wave-Glider-Buddy-System.git" "$env:USERPROFILE\backups\Wave-Glider-Buddy-System.git"
```

4. Save rollback notes (rename back + restore from mirror if needed).

### Rollback

1. Rename the repo back to `Wave-Glider-Buddy-System` (Settings or `gh repo rename Wave-Glider-Buddy-System --yes`).
2. On each clone: `git remote set-url origin https://github.com/tylerbyrne-me/Wave-Glider-Buddy-System.git`
3. If history were lost (should not happen on rename alone): `git clone $env:USERPROFILE\backups\Wave-Glider-Buddy-System.git restored-repo`

## On GitHub (required once)

1. Open the repo → **Settings** → **General** → **Repository name** → `Glider-Buddy-System` → Rename.
2. GitHub keeps redirects from the old URL for clones, issues, and PRs.

With GitHub CLI (after `gh auth login`):

```powershell
conda activate WorkPython
gh repo rename Glider-Buddy-System --yes
```

## On every clone

```powershell
conda activate WorkPython
cd "path\to\repo"
git remote set-url origin https://github.com/tylerbyrne-me/Glider-Buddy-System.git
git remote -v
git fetch
```

## After rename

- Confirm: `gh repo view --json name,url` (or open the new URL in a browser)
- Update any remaining hard-coded clone URLs in CI, bookmarks, or team wikis
- Local inventory/mirror from the backup gate (e.g. under `%USERPROFILE%\backups\`) can be kept until soak is done
