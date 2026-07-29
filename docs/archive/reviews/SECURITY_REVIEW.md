# Security Configuration Review

## Summary
This document outlines the security review of configuration files and the changes made to ensure all sensitive credentials are stored in the `.env` file rather than hardcoded in source code.

## Critical Security Issues Found and Fixed

### 1. **Sensor Tracker Credentials (CRITICAL)**
**Location:** `app/config.py`  
**Issue:** Hardcoded real credentials in source code:
- `sensor_tracker_token`: `"3c62f39804729f9e8aff90d0220c8aa07eed9e77"`
- `sensor_tracker_username`: `"tylerbyrne"`
- `sensor_tracker_password`: `"sJdujK3P7bYMth8"`

**Fix:** Removed hardcoded values, now defaults to `None` and must be set in `.env`

### 2. **Email/SMTP Credentials**
**Location:** `app/config.py`  
**Issue:** Email settings had placeholder defaults that could be accidentally committed

**Fix:** Changed to `Optional[str] = None` to force configuration via `.env`

### 3. **CLI Admin Credentials**
**Location:** `app/cli/station_cli.py`  
**Issue:** Hardcoded admin username and password:
- `ADMIN_USERNAME = "adminuser"`
- `ADMIN_PASSWORD = "adminpass"`

**Fix:** Now reads from environment variables `CLI_ADMIN_USERNAME` and `CLI_ADMIN_PASSWORD`

### 4. **OpenWeatherMap API Key**
**Location:** `app/config.py`  
**Issue:** API key was commented out in `.env` but not properly configured in code

**Fix:** Added `openweathermap_api_key` field to config (defaults to `None`)

## Required .env Variables

### Security-Critical (MUST be set)

#### JWT Authentication
```env
# Generate a strong key using: python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET_KEY=your_strong_secret_key_here
```

#### Email/SMTP Settings
```env
MAIL_USERNAME=your-email@example.com
MAIL_PASSWORD=your-email-password
MAIL_FROM=no-reply@wgbuddy.com
MAIL_SERVER=smtp.example.com
MAIL_PORT=587
MAIL_STARTTLS=True
MAIL_SSL_TLS=False
```

#### Sensor Tracker Credentials
```env
# Use either token OR username/password (token preferred)
SENSOR_TRACKER_TOKEN=your_token_here
SENSOR_TRACKER_USERNAME=your_username
SENSOR_TRACKER_PASSWORD=your_password
```

#### OpenWeatherMap API
```env
OPENWEATHERMAP_API_KEY=your_api_key_here
```

#### CLI Admin Credentials (for CLI tools)
```env
CLI_ADMIN_USERNAME=your_admin_username
CLI_ADMIN_PASSWORD=your_admin_password
CLI_ADMIN_API_URL=http://localhost:8000/api  # Optional, defaults to localhost:8000
```

#### Default User Accounts (Seed Users)
These are default accounts created on first database initialization. **PASSWORDS ARE REQUIRED IN .env - NO DEFAULTS IN SOURCE CODE!**

```env
# Admin User (default seed account)
# Username has a default in config.py, but password MUST be set here
DEFAULT_ADMIN_USERNAME=adminuser  # Optional - defaults to "adminuser" if not set
DEFAULT_ADMIN_PASSWORD=your_secure_admin_password  # REQUIRED - no default in code
DEFAULT_ADMIN_EMAIL=admin@example.com

# Pilot User (default seed account)
DEFAULT_PILOT_USERNAME=pilotuser  # Optional - defaults to "pilotuser" if not set
DEFAULT_PILOT_PASSWORD=your_secure_pilot_password  # REQUIRED - no default in code
DEFAULT_PILOT_EMAIL=pilot@example.com

# Realtime Pilot User (default seed account)
DEFAULT_PILOT_RT_USERNAME=pilot_rt_only  # Optional - defaults to "pilot_rt_only" if not set
DEFAULT_PILOT_RT_PASSWORD=your_secure_rt_pilot_password  # REQUIRED - no default in code
DEFAULT_PILOT_RT_EMAIL=pilot_rt@example.com

# LRI Pilot (special disabled user for blocking shifts)
DEFAULT_LRI_PILOT_USERNAME=LRI_PILOT  # Optional - defaults to "LRI_PILOT" if not set
DEFAULT_LRI_PILOT_PASSWORD=any_password  # Optional - user is disabled, password doesn't matter
DEFAULT_LRI_PILOT_EMAIL=lri@example.com
```

**Security Notes:**
- **Passwords have NO defaults in source code** - they MUST be set in `.env` or users won't be created
- Usernames have defaults in `config.py` for convenience, but can be overridden in `.env`
- If a password is missing, the user creation will be skipped with a warning log
- These default users are only created if they don't already exist
- Once created, changing these values in `.env` won't update existing users - change passwords through the admin interface or database directly

### Configuration Variables (Already in your .env)

These are already properly configured in your `.env` file:
- `FEATURE_TOGGLES_JSON`
- `LOCAL_DATA_BASE_PATH`
- `LOG_FILE_PATH`
- `REMOTE_DATA_URL`
- `ACTIVE_REALTIME_MISSIONS`
- `REMOTE_MISSION_FOLDER_MAP_JSON`
- `BACKGROUND_CACHE_REFRESH_INTERVAL_MINUTES`
- `FORMS_STORAGE_MODE`
- `SQLITE_DATABASE_URL`
- `SQLITE_ECHO_LOG`
- `KNOWLEDGE_BASE_MAX_UPLOAD_SIZE_MB`

## Files Modified

1. **app/config.py**
   - Removed hardcoded sensor tracker credentials
   - Changed email settings to require `.env` configuration
   - Added `openweathermap_api_key` field

2. **app/cli/station_cli.py**
   - Removed hardcoded admin credentials
   - Now reads from environment variables with proper error handling

## Security Best Practices

1. ✅ **Never commit `.env` file** - Already in `.gitignore`
2. ✅ **Use strong, randomly generated secrets** - JWT secret should be 32+ bytes
3. ✅ **Rotate credentials regularly** - Especially API keys and passwords
4. ✅ **Use environment-specific `.env` files** - Different files for dev/staging/prod
5. ✅ **Review access to `.env` files** - Limit file permissions (chmod 600 on Linux)

## Next Steps

1. **Update your `.env` file** with all the required security-critical variables listed above
2. **Remove any commented-out credentials** from your `.env` file
3. **Verify all sensitive values are set** before deploying to production
4. **Consider using a secrets manager** (AWS Secrets Manager, HashiCorp Vault) for production environments

## Verification

After updating your `.env` file, verify that:
- Email functionality works (test sending an email)
- Sensor Tracker integration works
- CLI tools can authenticate
- Weather API calls work (if using that feature)
- Application starts without credential-related errors
