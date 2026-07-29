# Bugs

One file per bug. Filename: `BUG-NNN-short-slug.md` (zero-padded number, kebab-case slug).

## Frontmatter

```yaml
---
id: BUG-001
type: bug
status: open          # open | investigating | fixed | wontfix
priority: medium      # low | medium | high | critical
created: YYYY-MM-DD
tags: []
---
```

## Body sections

- Title (H1) — short symptom statement
- `## Repro` — steps
- `## Expected` — correct behavior
- `## Notes` — suspects, links to code
- `## Resolution` — fill when `status` is `fixed` (cause, change, PR/commit if useful)

When fixed: set `status: fixed`, complete Resolution, and move the related line from `tasks/in-progress.md` or `backlog.md` to `tasks/done.md` with today’s date.
