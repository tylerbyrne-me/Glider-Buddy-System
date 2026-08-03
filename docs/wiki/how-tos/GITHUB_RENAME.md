# GitHub repository rename (GBS)

Canonical slug: **`Glider-Buddy-System`** (was `Wave-Glider-Buddy-System`).

## On GitHub (required once)

1. Open the repo → **Settings** → **General** → **Repository name** → `Glider-Buddy-System` → Rename.
2. GitHub keeps redirects from the old URL for clones, issues, and PRs.

With GitHub CLI (WorkPython / wherever `gh` is installed):

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
```

## After rename

- Confirm: `gh repo view --json name,url`
- Update any remaining hard-coded clone URLs in CI, bookmarks, or team wikis
