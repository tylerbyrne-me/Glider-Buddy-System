# Web Folder Standards

## Purpose

The `web/` folder contains all frontend assets: HTML templates, JavaScript files, CSS stylesheets, images, and static resources. This folder is separate from the backend application code (`app/`) but is served by the FastAPI application.

## Current Structure

```
web/
├── templates/                     # Jinja2 HTML templates
│   ├── base.html                  # Base template with common layout
│   ├── _banner.html               # Banner partial
│   ├── _form_details_modal.html   # Modal partial
│   ├── admin/                     # All admin page templates
│   │   ├── announcements.html
│   │   ├── faqs.html
│   │   ├── mission_overviews.html
│   │   ├── scheduler_status.html
│   │   └── user_management.html
│   ├── email/                     # Email templates
│   └── *.html                     # Page-specific templates
└── static/                        # Static assets
    ├── css/                       # Stylesheets (custom.css, themes.css)
    ├── js/                        # JavaScript files
    │   ├── api.js                 # Shared API utilities
    │   ├── auth.js                # Authentication utilities
    │   ├── admin/                 # Admin page scripts (mirrors templates/admin/)
    │   └── *.js                   # Page-specific JS
    ├── fullcalendar/              # FullCalendar library (JS + CSS on deploy)
    ├── images/                    # Branding assets (often gitignored; deploy separately)
    ├── mission_plans/             # Mission plan documents (runtime)
    └── mission_reports/           # Generated mission reports (runtime)
```

## Statistics

- **HTML Templates:** ~35 files (including `admin/` and `email/` subfolders)
- **JavaScript Files:** ~32 files (including `admin/` subfolder)
- **CSS Files:** 2 custom files (plus Bootstrap via CDN)

---

## HTML Template Standards

### File Organization

**Location:** `web/templates/`

**Naming Convention:**
- Use `snake_case.html` for templates
- Partial templates start with `_` (e.g., `_banner.html`)
- Admin templates go in `admin/` subfolder
- Email templates go in `email/` subfolder

**Structure:**
```
web/templates/
├── base.html                      # Base template (extends from this)
├── _*.html                        # Partials (included in other templates)
├── admin/                         # Admin templates
└── *.html                         # Page templates
```

### Template Inheritance

**Standard Pattern:**
```jinja2
{% extends "base.html" %}

{% block title %}Page Title - Wave Glider Buddy{% endblock %}

{% block content %}
    <!-- Page content here -->
{% endblock %}
```

**Required Blocks:**
- `title` - Page title (recommended)
- `content` - Main page content (required)

**Optional Blocks:**
- `head_extra_css` - Additional CSS
- `body_class` - Custom body classes
- `body_data_attributes` - Custom data attributes
- `content_container_class` - Container classes
- `content_padding_top` - Padding override
- `navbar` - Custom navbar (rarely needed)
- `footer` - Custom footer (rarely needed)

### Template Context

**Standard Context Variables:**
- `current_user` - Current authenticated user (or None)
- `request` - FastAPI Request object
- Page-specific context from routers

**Usage:**
```jinja2
{% if current_user %}
    <p>Welcome, {{ current_user.username }}!</p>
{% endif %}
```

### Data Attributes

**Standard Pattern:**
```jinja2
<body data-username="{{ current_user.username if current_user else '' }}"
      data-user-role="{{ current_user.role.value if current_user else '' }}"
      data-mission-id="{{ mission_id if mission_id else '' }}">
```

**Common Data Attributes:**
- `data-username` - Current user username
- `data-user-role` - Current user role
- `data-mission-id` - Mission ID (if applicable)
- `data-is-realtime` - Boolean for realtime missions
- `data-enabled-sensors` - Comma-separated list of enabled sensors

### Best Practices

1. **Always extend base.html** (unless it's a partial)
2. **Use consistent block names** across templates
3. **Include data attributes** for JavaScript to access
4. **Use semantic HTML** and Bootstrap classes
5. **Keep templates focused** - one template per page
6. **Use partials** for reusable components (`_banner.html`, `_form_details_modal.html`)

---

## JavaScript Standards

### File Organization

**Location:** `web/static/js/`

**Naming Convention:**
- Use `snake_case.js` for JavaScript files
- Match template names (e.g., `dashboard.js` for `dashboard.html`)
- Admin-specific JS in `admin/` subfolder
- Shared utilities in root (e.g., `api.js`, `auth.js`)

**Structure:**
```
web/static/js/
├── api.js                        # Shared API utilities
├── auth.js                       # Authentication utilities
├── admin/                        # Admin-specific JS
└── *.js                          # Page-specific JS
```

### Module System

**Standard: Use ES6 Modules**

**Export Pattern:**
```javascript
// Export functions
export const functionName = () => { ... };
export const anotherFunction = () => { ... };

// Or export default
export default { functionName, anotherFunction };
```

**Import Pattern:**
```javascript
// Import from shared modules
import { apiRequest, showToast } from '/static/js/api.js';
import { checkAuth } from '/static/js/auth.js';

// Import default
import utils from '/static/js/utils.js';
```

### API Communication

**Standard: Use `apiRequest()` from `api.js`**

**DO:**
```javascript
import { apiRequest } from '/static/js/api.js';

// GET request
const data = await apiRequest('/api/endpoint', 'GET');

// POST request
const result = await apiRequest('/api/endpoint', 'POST', { key: 'value' });
```

**DON'T:**
```javascript
// Don't use fetch() directly
const response = await fetch('/api/endpoint');
```

**Exception:** Only use `fetch()` directly if:
- Making unauthenticated requests
- Need special request handling
- Document why direct fetch is needed

### Error Handling

**Standard: Use `showToast()` from `api.js`**

**DO:**
```javascript
import { showToast, apiRequest } from '/static/js/api.js';

try {
    const data = await apiRequest('/api/endpoint', 'GET');
    showToast('Success!', 'success');
} catch (error) {
    showToast(`Error: ${error.message}`, 'danger');
}
```

**DON'T:**
```javascript
// Don't use console.error() for user-facing errors
console.error('Error occurred');
```

### Authentication

**Standard: Use `checkAuth()` from `auth.js`**

**DO:**
```javascript
import { checkAuth } from '/static/js/auth.js';

document.addEventListener('DOMContentLoaded', async function() {
    if (!checkAuth()) {
        return; // Redirects handled by checkAuth
    }
    // Rest of initialization
});
```

**DON'T:**
```javascript
// Don't manually check localStorage tokens
const token = localStorage.getItem('accessToken');
if (!token) { ... }
```

### DOM Ready

**Standard Pattern:**
```javascript
document.addEventListener('DOMContentLoaded', async function() {
    // Authentication check
    if (!checkAuth()) {
        return;
    }
    
    // Initialize page
    initializePage();
});

function initializePage() {
    // Page-specific initialization
}
```

### Variable Naming

**Standard:**
- Use `camelCase` for variables and functions
- Use `UPPER_SNAKE_CASE` for constants
- Use descriptive names

**Examples:**
```javascript
// Variables
const missionId = document.body.dataset.missionId;
const chartInstance = new Chart(...);

// Constants
const API_BASE_URL = '/api';
const MAX_RETRIES = 3;

// Functions
function initializeChart() { ... }
async function fetchMissionData() { ... }
```

### Code Organization

**Standard Structure:**
```javascript
// 1. Imports
import { apiRequest, showToast } from '/static/js/api.js';
import { checkAuth } from '/static/js/auth.js';

// 2. Constants
const API_BASE_URL = '/api';

// 3. Global variables (if needed)
let chartInstance = null;

// 4. Helper functions
function helperFunction() { ... }

// 5. Main initialization
document.addEventListener('DOMContentLoaded', async function() {
    if (!checkAuth()) {
        return;
    }
    initializePage();
});

// 6. Page-specific functions
function initializePage() { ... }
```

### Comments

**Standard:**
- Use JSDoc for function documentation
- Use inline comments for complex logic
- Remove debug `console.log()` statements in production code

**Example:**
```javascript
/**
 * Fetches mission data and updates the chart.
 * @param {string} missionId - The mission identifier
 * @returns {Promise<void>}
 */
async function updateMissionChart(missionId) {
    // Fetch data
    const data = await apiRequest(`/api/missions/${missionId}`, 'GET');
    
    // Update chart
    chartInstance.data = data;
    chartInstance.update();
}
```

---

## Shared JavaScript Modules

### `api.js` - API Utilities

**Purpose:** Centralized API communication and UI feedback

**Exports:**
- `apiRequest(url, method, body)` - Authenticated API requests
- `showToast(message, type)` - Display toast notifications

**Usage:**
```javascript
import { apiRequest, showToast } from '/static/js/api.js';
```

### `auth.js` - Authentication

**Purpose:** Authentication checks and token management

**Exports:**
- `checkAuth()` - Check authentication and redirect if needed

**Usage:**
```javascript
import { checkAuth } from '/static/js/auth.js';
```

---

## CSS Standards

### File Organization

**Location:** `web/static/css/`

**Files:**
- `custom.css` - Custom application styles
- `themes.css` - Theme-specific styles (light/dark mode)

### CSS Variables

**Standard: Use CSS custom properties**

**Defined in `base.html` or `themes.css`:**
```css
:root {
    --banner-height: 110px;
    --text-color: #333;
    --bg-color: #fff;
}
```

**Usage:**
```css
.my-element {
    height: var(--banner-height);
    color: var(--text-color);
}
```

### Naming Convention

**Standard: Use BEM-like naming or descriptive classes**

**Examples:**
```css
.btn-primary { ... }
.modal-content { ... }
.mission-card { ... }
.mission-card__header { ... }
.mission-card__body { ... }
```

### Best Practices

1. **Use Bootstrap classes** when possible
2. **Override Bootstrap** in `custom.css` when needed
3. **Use CSS variables** for theme support
4. **Keep specificity low** - avoid deep nesting
5. **Mobile-first** responsive design

---

## Static Assets

### Images

**Location:** `web/static/images/`

**Naming:** Use descriptive names (e.g., `login_splash.jpg`, `wgbs_logo.svg`)

**Usage in Templates:**
```jinja2
<img src="/static/images/logo.png" alt="Logo">
```

### Third-Party Libraries

**Location:** `web/static/` (e.g., `bootstrap/`, `fullcalendar/`)

**Standard:** Keep vendor libraries in separate folders

**CDN vs Local:**
- Use CDN for major libraries (Bootstrap, Font Awesome)
- Use local copies for custom or modified libraries

---

## Best Practices Summary

### HTML Templates
- ✅ Always extend `base.html`
- ✅ Use consistent block names
- ✅ Include data attributes for JavaScript
- ✅ Use semantic HTML and Bootstrap

### JavaScript
- ✅ Use ES6 modules (`import`/`export`)
- ✅ Use `apiRequest()` for API calls
- ✅ Use `showToast()` for user feedback
- ✅ Use `checkAuth()` for authentication
- ✅ Use `DOMContentLoaded` for initialization
- ✅ Remove debug `console.log()` statements

### CSS
- ✅ Use Bootstrap classes first
- ✅ Override in `custom.css` when needed
- ✅ Use CSS variables for theming
- ✅ Keep specificity low

### General
- ✅ Match file names (template ↔ JavaScript)
- ✅ Use descriptive names
- ✅ Follow naming conventions
- ✅ Keep code organized and commented

---

## Migration Checklist

When updating existing files:

- [ ] Convert to ES6 modules (if using script tags)
- [ ] Replace `fetch()` with `apiRequest()`
- [ ] Replace manual error handling with `showToast()`
- [ ] Add `checkAuth()` to protected pages
- [ ] Ensure templates extend `base.html`
- [ ] Add data attributes for JavaScript access
- [ ] Remove debug `console.log()` statements
- [ ] Add JSDoc comments to functions
- [ ] Use consistent naming conventions

---

## Related Documentation

- `CODE_STANDARDS.md` - General coding standards
- `app/core/templates.py` - Template configuration
- `app/core/template_context.py` - Template context helpers

