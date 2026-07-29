# Sensor Tracker Parser Improvements

## Overview
The Sensor Tracker deployment parser has been significantly improved to properly extract and structure all metadata from Sensor Tracker deployments.

## Key Improvements

### 1. Mission ID Mapping
- **Before**: Only extracted `deployment_id` (Sensor Tracker ID)
- **After**: Extracts `deployment_number` and maps it to `mission_id` (e.g., 216 → m216)
- This enables linking Sensor Tracker deployments to local mission records

### 2. Structured Data Organization
The parser now organizes data into logical sections:

#### Core Identifiers
- `sensor_tracker_deployment_id`: The Sensor Tracker deployment ID (e.g., 4291)
- `deployment_number`: The deployment number (e.g., 216)
- `mission_id`: Mapped mission ID (e.g., m216)

#### Location Data
- `deployment_location`: {latitude, longitude}
- `recovery_location`: {latitude, longitude}
- `depth`: Deployment depth in meters

#### Metadata Sections
- `deployment_details`: Cruise info, personnel, WMO ID, etc.
- `publication`: Publisher information, data repository links
- `attribution`: Creator, contributor information
- `program_info`: Program, agencies, sea name, site
- `technical`: Transmission system, positioning system, references

#### Related Entity IDs
- `related_ids`: Institution, project, platform_power_type IDs for fetching full details later

### 3. Platform Data Handling
- Properly handles platform as ID reference (int) vs full object (dict)
- Added `enrich_deployment_with_platform()` method to fetch full platform details
- Extracts platform name, type, and data logger information

### 4. Instrument and Sensor History
- Properly extracts `instrument_on_platform_history`
- Properly extracts `sensor_on_instrument_history`
- Handles different history data structures (list, dict, nested by option)

### 5. Better Error Handling
- Handles list responses (takes first item)
- Handles missing fields gracefully
- Type checking for platform data
- Defensive parsing throughout

## Example Output Structure

```json
{
  "sensor_tracker_deployment_id": 4291,
  "deployment_number": 216,
  "mission_id": "m216",
  "start_time": "2025-10-10 12:41:34",
  "end_time": "2025-11-07 13:36:19",
  "deployment_location": {
    "latitude": "44.53285",
    "longitude": "-63.45028"
  },
  "recovery_location": {
    "latitude": "44.56274",
    "longitude": "-63.45665"
  },
  "title": "OTN HFX Line Offloads",
  "comment": "...",
  "platform_id": 287,
  "related_ids": {
    "institution_id": 1,
    "project_id": 9,
    "platform_power_type_id": 1
  },
  "deployment_details": {
    "deployment_cruise": "Dominion Bearcat",
    "recovery_cruise": "Dominion Bearcat",
    "deployment_personnel": "...",
    "recovery_personnel": "..."
  },
  "program_info": {
    "program": "Ocean Tracking Network glider program",
    "agencies": "Ocean Tracking Network",
    "sea_name": "Northwest Atlantic Ocean"
  },
  "sensors": [],
  "instruments": [],
  "sensor_on_instrument": []
}
```

## Usage

### Basic Parsing
```python
from app.services.sensor_tracker_service import SensorTrackerService

service = SensorTrackerService(skip_auth=True)
deployment_data = await service.fetch_deployment(4291)
parsed = await service.parse_deployment(deployment_data)
```

### With Platform Enrichment
```python
parsed = await service.parse_deployment(deployment_data)
parsed = await service.enrich_deployment_with_platform(parsed)
```

## Next Steps

1. **Fetch Related Data**: Use `related_ids` to fetch full institution, project details
2. **Fetch Instruments**: Use `instrument_on_platform_history` to get instrument details
3. **Fetch Sensors**: Use `sensor_on_instrument_history` to get sensor details
4. **Database Integration**: Store parsed data in local database
5. **Mission Linking**: Use `mission_id` to link to local `MissionOverview` records

## Testing

Test with deployment 4291 (mission m216):
```bash
python scripts/test_sensor_tracker.py 4291
```

The script will:
- Fetch the deployment
- Parse all metadata
- Optionally fetch platform details
- Save raw and parsed JSON files
- Display a summary

