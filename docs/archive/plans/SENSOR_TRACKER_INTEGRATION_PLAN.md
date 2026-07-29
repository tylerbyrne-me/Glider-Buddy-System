# Sensor Tracker Integration Plan

## Overview
This document outlines the plan for integrating Sensor Tracker metadata into the Wave Glider Buddy System. Sensor Tracker manages deployment metadata including platforms, instruments, sensors, and their hierarchical relationships.

## Current System Architecture

### Existing Models
- **MissionOverview**: Stores mission metadata (mission_id, comments, enabled_sensor_cards)
- **StationMetadata**: Stores station deployment information
- Sensor data is processed via processors (telemetry, power, CTD, weather, waves, VR2C, fluorometer, WG-VM4)

### Key Components
- `app/core/models/`: Database models and schemas
- `app/core/data_service.py`: Data loading and caching
- `app/routers/`: API endpoints
- `app/services/`: Business logic services

## Sensor Tracker Data Structure

### Deployment Hierarchy
```
Deployment
├── Platform
│   ├── Instrument on Platform History (All/Now/On Date)
│   ├── Data Logger
│   │   ├── flight
│   │   │   ├── Instrument on Data Logger History
│   │   │   └── parameter
│   │   └── science
│   │       ├── Instrument on Data Logger History
│   │       ├── Data Logger on Platform History
│   │       └── parameter (usually empty)
│   └── Custom Fields
├── Regular Fields (lat/lon, dates, etc.)
├── Instrument on Platform History (All/Now/On Date)
├── Sensor on Instrument History (All/Now/On Date)
├── Images
└── Custom Fields
```

## Integration Strategy

### Phase 1: Foundation - Single Deployment Parser
**Goal**: Parse and understand a single deployment's structure

#### 1.1 Install and Configure Sensor Tracker Client
- Add `sensor_tracker_client` to `requirements.txt`
- Create configuration module for Sensor Tracker connection
- Set up authentication (token or username/password)

#### 1.2 Create Data Models
Create new database models to store Sensor Tracker data:

**SensorTrackerDeployment** (main deployment record)
- `deployment_id`: Primary key (from Sensor Tracker)
- `platform_name`: Platform identifier
- `start_time`: Deployment start
- `end_time`: Deployment end (optional)
- `deployment_latitude`: Deployment location
- `deployment_longitude`: Deployment location
- `mission_id`: Link to local MissionOverview (nullable, for mapping)
- `raw_deployment_data`: JSON field storing full deployment response
- `last_synced_at`: Timestamp of last sync
- `sync_status`: Status of sync (success, error, pending)

**SensorTrackerPlatform** (platform metadata)
- `platform_id`: Primary key
- `platform_name`: Unique platform identifier
- `platform_type_id`: Reference to platform type
- `raw_platform_data`: JSON field

**SensorTrackerInstrument** (instrument metadata)
- `instrument_id`: Primary key
- `identifier`: Instrument identifier
- `manufacturer_id`: Reference to manufacturer
- `raw_instrument_data`: JSON field

**SensorTrackerSensor** (sensor metadata)
- `sensor_id`: Primary key
- `identifier`: Sensor identifier
- `short_name`: Short name
- `long_name`: Full name
- `raw_sensor_data`: JSON field

**SensorTrackerInstrumentOnPlatform** (relationship table)
- `id`: Primary key
- `instrument_id`: Foreign key
- `platform_id`: Foreign key
- `start_time`: When instrument was added
- `end_time`: When instrument was removed (optional)
- `deployment_id`: Which deployment this belongs to

**SensorTrackerSensorOnInstrument** (relationship table)
- `id`: Primary key
- `sensor_id`: Foreign key
- `instrument_id`: Foreign key
- `start_time`: When sensor was added
- `end_time`: When sensor was removed (optional)
- `deployment_id`: Which deployment this belongs to

**SensorTrackerDataLogger** (data logger metadata)
- `id`: Primary key
- `platform_id`: Foreign key
- `logger_type`: Enum ('flight' or 'science')
- `parameters`: JSON field for parameters
- `raw_data_logger_data`: JSON field

**SensorTrackerInstrumentOnDataLogger** (relationship table)
- `id`: Primary key
- `instrument_id`: Foreign key
- `data_logger_id`: Foreign key
- `start_time`: When instrument was added
- `end_time`: When instrument was removed (optional)

#### 1.3 Create Parser Service
Create `app/services/sensor_tracker_service.py`:

```python
class SensorTrackerService:
    """
    Service for interacting with Sensor Tracker API and parsing deployment data.
    """
    
    async def fetch_deployment(self, deployment_id: int) -> dict:
        """Fetch a single deployment from Sensor Tracker."""
        
    async def parse_deployment(self, deployment_data: dict) -> SensorTrackerDeploymentParsed:
        """Parse deployment data into structured format."""
        
    async def parse_platform(self, platform_data: dict) -> SensorTrackerPlatformParsed:
        """Parse platform data."""
        
    async def parse_data_logger(self, data_logger_data: dict, logger_type: str) -> SensorTrackerDataLoggerParsed:
        """Parse data logger (flight or science) data."""
        
    async def parse_instrument_on_platform_history(self, history_data: dict, option: str = "Now") -> List[InstrumentOnPlatform]:
        """Parse instrument on platform history (All/Now/On Date)."""
        
    async def parse_sensor_on_instrument_history(self, history_data: dict, option: str = "Now") -> List[SensorOnInstrument]:
        """Parse sensor on instrument history (All/Now/On Date)."""
```

#### 1.4 Create Pydantic Schemas
Create response/request schemas in `app/core/models/schemas.py`:

- `SensorTrackerDeploymentResponse`: Full deployment with nested data
- `SensorTrackerDeploymentParsed`: Parsed deployment structure
- `SensorTrackerPlatformParsed`: Parsed platform structure
- `SensorTrackerDataLoggerParsed`: Parsed data logger structure

### Phase 2: Database Integration
**Goal**: Store parsed deployment data in local database

#### 2.1 Create Database Migration
- Create Alembic migration for new Sensor Tracker tables
- Add foreign key relationships
- Add indexes for common queries

#### 2.2 Create CRUD Operations
Create `app/core/crud/sensor_tracker_crud.py`:

- `create_or_update_deployment()`: Upsert deployment
- `get_deployment_by_stc_id()`: Get by Sensor Tracker ID
- `get_deployments_by_platform()`: Get all deployments for a platform
- `link_deployment_to_mission()`: Map deployment to local mission

### Phase 3: API Integration
**Goal**: Expose Sensor Tracker data via API endpoints

#### 3.1 Create Router
Create `app/routers/sensor_tracker.py`:

**Endpoints:**
- `GET /api/sensor_tracker/deployments/{deployment_id}`: Get single deployment
- `GET /api/sensor_tracker/deployments`: List deployments (with filters)
- `POST /api/sensor_tracker/deployments/{deployment_id}/sync`: Sync deployment from Sensor Tracker
- `POST /api/sensor_tracker/deployments/{deployment_id}/link-mission`: Link deployment to mission
- `GET /api/sensor_tracker/platforms/{platform_name}`: Get platform details
- `GET /api/sensor_tracker/deployments/{deployment_id}/instruments`: Get instruments for deployment
- `GET /api/sensor_tracker/deployments/{deployment_id}/sensors`: Get sensors for deployment

### Phase 4: Mission Mapping
**Goal**: Map Sensor Tracker deployments to local missions

#### 4.1 Mapping Strategy
- **Automatic**: Match by platform_name and deployment dates
- **Manual**: Admin interface to link deployments to missions
- **Hybrid**: Suggest matches, allow manual override

#### 4.2 Update MissionOverview
- Add optional `sensor_tracker_deployment_id` field
- Add method to fetch Sensor Tracker metadata for a mission

### Phase 5: UI Integration
**Goal**: Display Sensor Tracker data in the web interface

#### 5.1 Mission Overview Enhancement
- Add "Sensor Tracker Metadata" section to mission pages
- Display platform, instruments, sensors
- Show deployment timeline

#### 5.2 Admin Interface
- Admin page to sync deployments
- Interface to link deployments to missions
- View deployment details

## Implementation Details

### Configuration
Create `app/config.py` section or environment variables:
```python
SENSOR_TRACKER_HOST: str = "http://bugs.ocean.dal.ca/sensor_tracker/"
SENSOR_TRACKER_TOKEN: Optional[str] = None
SENSOR_TRACKER_USERNAME: Optional[str] = None
SENSOR_TRACKER_PASSWORD: Optional[str] = None
SENSOR_TRACKER_DEBUG: bool = False
SENSOR_TRACKER_DEBUG_HOST: str = "http://127.0.0.1:8000/"
```

### Error Handling
- Handle API connection errors gracefully
- Log sync failures
- Provide retry mechanisms
- Store partial data if full sync fails

### Caching Strategy
- Cache deployment data locally
- Periodic background sync (optional)
- Manual sync on-demand
- Track last sync timestamp

## Testing Strategy

### Unit Tests
- Test parser functions with sample deployment data
- Test CRUD operations
- Test mapping logic

### Integration Tests
- Test API endpoints
- Test Sensor Tracker client connection
- Test database operations

### Manual Testing
- Fetch a real deployment from Sensor Tracker
- Parse and store in database
- Verify data integrity
- Test mission mapping

## Next Steps

1. **Start with Phase 1.1**: Install sensor_tracker_client and configure connection
2. **Phase 1.2**: Design and create initial data models (start simple, expand as needed)
3. **Phase 1.3**: Create basic parser for a single deployment
4. **Test with real data**: Fetch one deployment and parse it
5. **Iterate**: Refine models and parser based on actual data structure
6. **Phase 2**: Store parsed data in database
7. **Phase 3**: Create API endpoints
8. **Phase 4 & 5**: Mission mapping and UI integration

## Questions to Resolve

1. **Deployment ID Mapping**: How do Sensor Tracker deployment IDs relate to mission_ids (m203, etc.)?
2. **Sync Frequency**: Should we sync automatically or only on-demand?
3. **Data Retention**: Keep all historical data or only active deployments?
4. **Custom Fields**: How should we handle custom fields from Sensor Tracker?
5. **Images**: Do we need to store/download deployment images?
6. **History Options**: Default to "Now" or "All" when parsing history?

## Notes

- Start simple: Parse one deployment end-to-end before scaling
- Store raw JSON: Keep original data for reference and debugging
- Flexible schema: Use JSON fields for complex/nested data
- Incremental approach: Build and test each phase before moving forward

