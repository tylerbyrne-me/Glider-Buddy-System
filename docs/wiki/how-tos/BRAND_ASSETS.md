# Brand asset deploy notes (GBS)

## Logo

- Canonical: `web/static/images/gbs_logo.svg`
- Do **not** ship `wgbs_logo.svg` on new deploys (legacy name retired).

On a host that only has the old file:

```bash
cd /path/to/Glider-Buddy-System   # or current WorkingDirectory
mv web/static/images/wgbs_logo.svg web/static/images/gbs_logo.svg
```

## Favicon

| Asset | Path |
|-------|------|
| Primary (ICO) | `web/static/favicon.ico` |
| SVG (modern browsers) | `web/static/images/gbs_favicon.svg` |
| Optional PNG 32 / apple-touch | `web/static/images/gbs_favicon-32.png`, `gbs_favicon-180.png` |

Templates use `{{ app_favicon }}` / `{{ app_favicon_svg }}` from the brand registry ([`base.html`](../../web/templates/base.html)).

**Replace without code changes:** drop new files at the paths above. Interim SVG is copied from `gbs_logo.svg` until a designed mark is ready.

## Platform placeholder

- `web/static/images/platforms/placeholder.svg` — default for future platform chrome
