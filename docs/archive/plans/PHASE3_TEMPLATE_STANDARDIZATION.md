# Phase 3: HTML Template Standardization - Complete

## Summary

Phase 3 focused on standardizing HTML templates to ensure consistent structure, block usage, and data attributes across all templates.

## Audit Results

### Template Inheritance
- **All page templates** extend `base.html` ✅
- **Exception** (expected):
  - `base.html` - The base template itself

### Block Usage
- **21/22 templates** use `body_extra_js` block ✅
- All templates use standard blocks from `base.html`
- **Fixed issues:**
  - Removed non-standard `banner_actions_dropdown_items` block from `mission_form.html`
  - Removed deprecated `scripts` block from `base.html`

### Standard Blocks Available

All templates should use these standard blocks from `base.html`:

1. **`title`** - Page title (required)
2. **`head_extra_css`** - Additional CSS in `<head>`
3. **`body_class`** - Additional CSS classes for `<body>` tag
4. **`body_data_attributes`** - Additional data attributes for `<body>` tag
5. **`navbar`** - Override navbar (rarely needed)
6. **`content`** - Main page content (required)
7. **`content_container_class`** - Override container class
8. **`content_padding_top`** - Override content padding
9. **`footer`** - Override footer (rarely needed)
10. **`body_extra_js`** - JavaScript files at end of `<body>` (use this for all scripts)

### Data Attributes

Common data attributes used across templates:

#### User Context (from base.html)
- `data-username` - Current user's username
- `data-user-role` - Current user's role (pilot/admin)

#### Mission Context
- `data-mission-id` - Mission identifier
- `data-form-type` - Form type (for mission forms)
- `data-enabled-sensors` - Comma-separated list of enabled sensors
- `data-is-realtime` - Whether mission is realtime

#### UI State
- `data-bs-toggle` - Bootstrap toggle
- `data-bs-target` - Bootstrap target
- `data-bs-dismiss` - Bootstrap dismiss

#### Page-Specific
- `data-active-missions` - Active missions (JSON array)
- `data-default-hours` - Default hours for map
- `data-category` - Category for charts
- `data-report-type` - Report type
- `data-mini-trend` - Mini trend data (JSON)

## Changes Made

### 1. Fixed Non-Standard Blocks

**`mission_form.html`:**
- Removed unused `banner_actions_dropdown_items` block (not defined in base.html)

**`base.html`:**
- Removed deprecated `scripts` block
- All scripts now use `body_extra_js` block

### 2. Standardized Script Loading

All templates now use the `body_extra_js` block for loading JavaScript files:

```jinja2
{% block body_extra_js %}
    <script type="module" src="/static/js/page_name.js"></script>
{% endblock %}
```

## Block Usage Statistics

| Block | Usage | Percentage |
|-------|-------|------------|
| `title` | 21/22 | 95.5% |
| `content` | 21/22 | 95.5% |
| `body_extra_js` | 21/22 | 95.5% |
| `body_class` | 13/22 | 59.1% |
| `head_extra_css` | 12/22 | 54.5% |
| `body_data_attributes` | 5/22 | 22.7% |
| `content_padding_top` | 6/22 | 27.3% |
| `navbar` | 3/22 | 13.6% |
| `content_container_class` | 2/22 | 9.1% |
| `footer` | 1/22 | 4.5% |

## Template Structure Pattern

All templates should follow this pattern:

```jinja2
{% extends "base.html" %}

{% block title %}Page Title - Wave Glider Buddy{% endblock %}

{% block head_extra_css %}
    {# Additional CSS if needed #}
{% endblock %}

{% block body_class %}container mt-4{% endblock %}

{% block body_data_attributes %}
    data-custom-attr="value"
{% endblock %}

{% block content %}
    {# Main page content #}
{% endblock %}

{% block body_extra_js %}
    <script type="module" src="/static/js/page_name.js"></script>
{% endblock %}
```

## Next Steps

Phase 3 is complete. All templates are now standardized:

✅ All templates extend `base.html` (except expected exceptions)
✅ All templates use standard blocks
✅ All scripts use `body_extra_js` block
✅ Data attributes are consistent

## Related Documentation

- `WEB_FOLDER_STANDARDS.md` - Standards for web folder
- `WEB_FOLDER_REVIEW_PLAN.md` - Review plan
- `base.html` - Base template with all available blocks

