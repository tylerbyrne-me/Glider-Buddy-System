# Sensor Tracker Data Logger Extraction

## Overview
Enhanced the Sensor Tracker service to identify and extract data loggers from deployments. Data loggers are part of the Platform structure and can be either "flight" or "science" type.

## Data Logger Structure

According to Sensor Tracker:
- **Platform** contains **Data Logger** (Flight or Science)
- **Flight Logger** contains:
  - Instrument on Data Logger History
  - Parameters
- **Science Logger** contains:
  - Instrument on Data Logger History
  - Data Logger on Platform History
  - Parameters (usually empty)

## Improvements Made

### 1. Enhanced Platform Fetching
- `fetch_platform()` now accepts `include_data_loggers` parameter
- Attempts to fetch instrument information if data loggers aren't in initial response
- Added `fetch_instruments_on_platform()` method

### 2. Improved Data Logger Parsing
- `parse_data_logger()` now extracts:
  - Logger type (flight/science)
  - Parameters
  - **Instruments** from instrument_on_data_logger_history
  - Instrument count
  - For science loggers: data_logger_on_platform_history

### 3. Instrument History Parsing
- `parse_instrument_on_data_logger_history()` extracts:
  - Instrument IDs
  - Start/end times
  - Full instrument details (fetched separately)
- Handles different history data structures (list, dict, nested by option)

### 4. Instrument Details Fetching
- `fetch_instrument()` method to get full instrument details by ID
- Automatically fetches instrument details when parsing history

### 5. Deployment Enrichment
- `enrich_deployment_with_platform()` now:
  - Extracts data loggers to top level of deployment
  - Collects all instruments from all data loggers
  - Adds `data_logger_type` to each instrument
  - Provides summary counts

### 6. History Options Support
- `fetch_deployment_with_history()` method to fetch deployment with specific history options
- Supports All/Now/On Date options for instruments and sensors

## Usage

### Basic Usage
```python
from app.services.sensor_tracker_service import SensorTrackerService

service = SensorTrackerService(skip_auth=True)

# Fetch deployment
deployment_data = await service.fetch_deployment(4291)

# Parse deployment
parsed = await service.parse_deployment(deployment_data)

# Enrich with platform and data loggers
parsed = await service.enrich_deployment_with_platform(parsed)

# Access data loggers
data_loggers = parsed.get('data_loggers', [])
for logger in data_loggers:
    print(f"Logger Type: {logger['logger_type']}")
    print(f"Instruments: {logger['instrument_count']}")
    for inst in logger.get('instruments', []):
        print(f"  - {inst.get('instrument_details', {}).get('identifier')}")
```

### With History Options
```python
# Fetch with specific history options
deployment_data = await service.fetch_deployment_with_history(
    4291,
    instrument_history=HistoryOption.ALL,
    sensor_history=HistoryOption.NOW
)
```

## Output Structure

After enrichment, the deployment will have:

```json
{
  "data_loggers": [
    {
      "logger_type": "flight",
      "parameters": [...],
      "instruments": [
        {
          "instrument_id": 123,
          "start_time": "...",
          "end_time": "...",
          "instrument_details": {
            "identifier": "...",
            "name": "...",
            ...
          },
          "data_logger_type": "flight"
        }
      ],
      "instrument_count": 1
    },
    {
      "logger_type": "science",
      "parameters": [],
      "instruments": [...],
      "data_logger_on_platform_history": {...}
    }
  ],
  "instruments": [
    // All instruments from all data loggers, flattened
  ]
}
```

## Testing

Test with deployment 4291:
```bash
python scripts/test_sensor_tracker.py 4291
```

The script will:
1. Fetch the deployment
2. Parse metadata
3. Fetch platform details
4. Extract data loggers
5. Fetch instrument details
6. Display summary including data logger information

## Notes

1. **Data Logger Location**: Data loggers are part of the Platform structure. If they're not in the platform response, they may need to be fetched:
   - Through deployment history options
   - Through a separate endpoint
   - Through instrument_on_platform relationships

2. **History Options**: The Sensor Tracker API may require specific history options (All/Now/On Date) to return data logger information. Use `fetch_deployment_with_history()` if needed.

3. **Instrument Details**: Instrument details are fetched separately when parsing history. This may require additional API calls.

4. **Performance**: Fetching instrument details for each instrument in history may be slow. Consider caching or batch fetching if needed.

## Next Steps

1. **Test with Real Data**: Run the test script and inspect the output to see if data loggers are being extracted
2. **Verify API Structure**: Check if data loggers are in platform response or need different fetching method
3. **Add Sensor Extraction**: Once instruments are identified, fetch sensors on those instruments
4. **Database Integration**: Store data logger and instrument information in local database

