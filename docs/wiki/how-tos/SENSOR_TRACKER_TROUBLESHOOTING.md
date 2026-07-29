# Sensor Tracker Troubleshooting Guide

## Common Issues and Solutions

### 1. `.env` File Parsing Errors

**Error:**
```
python-dotenv could not parse statement starting at line 57
```

**Cause:** The `.env` file may have syntax issues or special characters that aren't properly quoted.

**Solution:**
- Ensure each line follows the format: `KEY=VALUE`
- If values contain special characters, spaces, or special symbols, wrap them in quotes:
  ```env
  sensor_tracker_token="your-token-here"
  sensor_tracker_password="password with spaces"
  ```
- Check for trailing spaces or hidden characters
- Make sure there are no comments on the same line as values

**Note:** If you've hardcoded credentials in `app/config.py` (not recommended for production), the `.env` parsing errors are just warnings and won't prevent the script from running.

### 2. Library Compatibility Error: `_EventBundle.__init__()`

**Error:**
```
TypeError: _EventBundle.__init__() takes 1 positional argument but 2 were given
```

**Cause:** This is a compatibility issue between `urllib3`, `h11`, and `requests` libraries. The `sensor_tracker_client` library tries to validate the token by making a POST request, which triggers this error.

**Solution:**
The service has been updated to handle this gracefully:
- Authentication setup failures are caught and logged as warnings
- The service can continue without authentication for GET operations
- The test script will automatically retry without authentication if auth setup fails

**Workaround:**
1. The script will automatically skip authentication if it fails
2. GET operations (like fetching deployments) don't require authentication
3. You can manually skip auth by using: `SensorTrackerService(skip_auth=True)`

**For POST/PUT operations (future):**
- You may need to update library versions or contact the Sensor Tracker client maintainers
- Alternative: Use direct HTTP requests with `requests` or `httpx` instead of the client library

### 3. Connection Test Fails

**Error:**
```
Sensor Tracker connection test failed
```

**Possible Causes:**
- Network connectivity issues
- Incorrect host URL
- Firewall blocking the connection
- Sensor Tracker server is down

**Solution:**
- Verify the `sensor_tracker_host` URL is correct
- Test connectivity: `curl http://bugs.ocean.dal.ca/sensor_tracker/` (or use your browser)
- Check firewall/network settings
- Try enabling debug mode to test against localhost

### 4. Deployment Not Found

**Error:**
```
Deployment {id} not found
```

**Possible Causes:**
- Invalid deployment ID
- Deployment doesn't exist
- Authentication required for this deployment (unlikely for GET)

**Solution:**
- Verify the deployment ID exists in Sensor Tracker
- Try fetching deployments by platform name instead
- Check if you have access to this deployment

## Testing Without Authentication

Since GET operations don't require authentication, you can test the basic functionality even if auth setup fails:

```python
from app.services.sensor_tracker_service import SensorTrackerService

# Skip authentication
service = SensorTrackerService(skip_auth=True)

# Fetch deployment (GET operation - no auth needed)
deployment = await service.fetch_deployment(211)
```

## Library Version Compatibility

If you continue to experience issues, you may need to:

1. **Check library versions:**
   ```bash
   pip list | grep -E "(urllib3|requests|h11)"
   ```

2. **Try updating libraries:**
   ```bash
   pip install --upgrade urllib3 requests
   ```

3. **Or pin specific versions** that are known to work with `sensor_tracker_client`

## Getting Help

1. Check the generated JSON files in `test_data/` to see what data was successfully fetched
2. Review logs for specific error messages
3. Test with a known-good deployment ID
4. Try fetching a simpler resource first (e.g., institutions) to test connectivity

## Best Practices

1. **Don't hardcode credentials** in `config.py` - use `.env` file
2. **Keep credentials secure** - never commit them to git
3. **Test connectivity first** before trying to parse complex data
4. **Start with simple operations** (GET) before attempting POST/PUT
5. **Inspect raw JSON** to understand the actual data structure

