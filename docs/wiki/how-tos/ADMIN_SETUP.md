# Admin Interfaces Setup

This project includes **SQLAdmin** for database administration.

## Overview

- **SQLAdmin** (`/admin`): Admin-only interface for operational data (users, stations, missions, etc.)

---

## 1. SQLAdmin (Admin Interface)

**Location:** `/admin`  
**Focus:** Core operational database management

### Features
- Full CRUD operations for operational models
- Search and filtering capabilities
- Sortable columns
- Modern, responsive UI
- **Admin-only access with authentication**

### Models Available
**Core Operations:**
- Users
- Station Metadata
- Offload Logs
- Field Seasons
- Mission Overviews
- Mission Media
- Mission Goals
- Mission Notes
- Submitted Forms
- Mission Instruments
- Mission Sensors
- Sensor Tracker Deployments
- Sensor Tracker Outbox
- Live KML Tokens
- Announcements

### Authentication
SQLAdmin uses a custom authentication backend (`app/core/admin_auth.py`) that:
- Integrates with the existing application authentication system
- Requires admin role (`UserRoleEnum.admin`)
- Supports both session-based and cookie-based token authentication
- Validates user credentials against the database
- Blocks disabled users and non-admin users

### Access
1. Navigate to `http://localhost:8000/admin`
2. You'll be redirected to a login page
3. Enter admin credentials (username/password)
4. Only users with `admin` role can access

### Setup
SQLAdmin is automatically configured on application startup. No additional setup required.

---

## Security & Authentication

### Admin-only

SQLAdmin enforces strict access control:

1. **Authentication Required**: Users must log in with valid credentials
2. **Admin Role Required**: Only users with `UserRoleEnum.admin` can access
3. **Active Users Only**: Disabled users are blocked
4. **Database Validation**: Credentials are validated against the database on every request

### Authentication Implementation

- **SQLAdmin**: Uses `SQLAdminAuthBackend` in `app/core/admin_auth.py`
  - Session-based authentication
  - Cookie token fallback
  - Validates admin role on every request

### Security Notes

- Both interfaces use the same JWT secret key from application settings
- Passwords are verified using the same password hashing system
- User roles are checked against the database
- All authentication attempts are logged

---

## Production URL and HTTP/HTTPS

Set these in `.env` on the production server so the app knows its public URL and whether it’s served over HTTPS.

| Env var | Example | Purpose |
|--------|---------|--------|
| `APP_BASE_URL` | `http://192.168.1.18:8080` | Public URL of the app (links, KML, etc.). No trailing slash. |
| `APP_USE_HTTPS` | `false` (HTTP) or `true` (HTTPS) | When `true`, cookies are set with `Secure` (required for HTTPS). |
| `APP_ADMIN_BASE_URL` | `/admin` | Path where SQLAdmin is mounted. Use e.g. `/app/admin` if the app is under a path prefix. |

**Example for your production server (HTTP, port 8080):**

```env
APP_BASE_URL=http://192.168.1.18:8080
APP_USE_HTTPS=false
```

**Example when you later use HTTPS:**

```env
APP_BASE_URL=https://your-domain.com
APP_USE_HTTPS=true
```

---

## Configuration Files

- **SQLAdmin:** `app/core/admin_sqladmin.py`
- **Shared Auth:** `app/core/admin_auth.py`
- **Integration:** `app/app.py` (startup event)
- **App URL / cookies:** `app/config.py` (`app_base_url`, `app_use_https`), `app/routers/auth.py` (cookie `secure`)

---

## Customization

### SQLAdmin
To customize SQLAdmin views, edit the `ModelView` classes in `app/core/admin_sqladmin.py`. You can:
- Modify `column_list` to show/hide columns
- Add `column_searchable_list` for searchable fields
- Add `column_sortable_list` for sortable fields
- Customize `form_excluded_columns` to hide fields in forms

### Authentication
To modify authentication behavior, edit `app/core/admin_auth.py`:
- `SQLAdminAuthBackend`: SQLAdmin authentication logic

---

## Troubleshooting

### SQLAdmin Issues

**Problem:** Can't access `/admin`  
**Solution:** 
- Ensure you're logged in with an admin account
- Check that your user has `role = UserRoleEnum.admin`
- Verify the user is not disabled

**Problem:** Authentication fails  
**Solution:**
- Check JWT secret key in settings
- Verify database connection
- Check application logs for authentication errors

**Problem:** `Error setting up SQLAdmin: No module named 'itsdangerous'`  
**Solution:** SQLAdmin’s auth backend requires `itsdangerous` for session signing. Install it and restart:
- `pip install itsdangerous`  
- Or reinstall from project requirements: `pip install -r requirements.txt`

---

## Production vs localhost

If `/admin` works locally but **not** on production (e.g. you see 404 or a blank page at `http://192.168.1.18:8080/admin`), use this checklist.

### 0. Confirm SQLAdmin is registered on production

- In **production** startup logs you must see:  
  `SQLAdmin configured successfully at /admin ... Full URL: http://192.168.1.18:8080/admin`
- If that line is missing, startup failed or production is running an older build. Fix startup errors or redeploy the latest code.
- From the **production server** (or a host that can reach it), run:  
  `curl -s -o /dev/null -w "%{http_code}" http://192.168.1.18:8080/admin`  
  You should get `200` or `307` (redirect to login), not `404`.

### 1. Reverse proxy (nginx, Caddy, etc.)

- **Cause:** Proxy may be routing `/admin` elsewhere, stripping the path, or not forwarding it to the app.
- **Check:** In the proxy config, ensure `/admin` (and `/admin/...`) are passed through to the FastAPI app (e.g. `proxy_pass` to uvicorn).
- **Fix:** Route `/admin` and `/admin/*` to the same backend as the rest of the app; avoid serving a different app or static folder at `/admin`. Example (nginx):  
  `location /admin { proxy_pass http://127.0.0.1:8080; proxy_set_header Host $host; proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for; proxy_set_header X-Forwarded-Proto $scheme; }`

### 2. App served under a path prefix

- **Cause:** If the app is mounted at a prefix (e.g. `https://example.com/app/`), the admin is at `https://example.com/app/admin`, not `https://example.com/admin`.
- **Check:** Open `https://<production-host>/<prefix>/admin` (e.g. `/app/admin`).
- **Fix:** Set in production `.env`:  
  `APP_ADMIN_BASE_URL=/app/admin`  
  so SQLAdmin mounts at that path. Restart the app and use the full URL.

### 3. Session / cookie issues (HTTPS, domain, Secure)

- **Cause:** Production uses HTTPS; session cookies may require `Secure`, or the domain/path may differ so the session cookie is not sent.
- **Check:** In the browser, check Application → Cookies for the production site; confirm the session cookie is present when you hit `/admin` and that it’s sent on the next request.
- **Fix:** Ensure the session backend (e.g. SQLAdmin’s auth) is configured for your production domain and HTTPS (secret key, cookie options). If you add explicit cookie settings later, use `Secure=True` and correct `SameSite` for HTTPS.

### 4. JWT secret / environment

- **Cause:** Different or missing `JWT_SECRET_KEY` (or env) in production; auth or session signing fails.
- **Check:** Production env has the same (or intended) `JWT_SECRET_KEY` and that the app starts without config errors.
- **Fix:** Set `JWT_SECRET_KEY` in production env; use a strong value and keep it consistent across restarts.

### 5. Database / startup errors

- **Cause:** Production DB unreachable or different; `setup_sqladmin(app)` or DB access during auth fails.
- **Check:** Production logs on startup and when you open `/admin` (500s, tracebacks, “database not found”, etc.).
- **Fix:** Point production config at the correct DB; ensure the app can create/use the DB and that migrations are applied.

### 6. What you see on production

- **404 on `/admin`:** Usually proxy or path prefix (see 1 and 2). Confirm the request reaches the FastAPI app and that SQLAdmin is registered (startup logs: “SQLAdmin configured successfully”).
- **Login page then redirect loop or 403:** Often session/cookie or secret (see 3 and 4).
- **500 error:** Check app logs; often DB or config (see 4 and 5).

## Notes

- SQLAdmin is the admin interface (no Redis dependency).
- **Admin-only**: non-admin users will be denied access.
- All authentication attempts are logged for security auditing
