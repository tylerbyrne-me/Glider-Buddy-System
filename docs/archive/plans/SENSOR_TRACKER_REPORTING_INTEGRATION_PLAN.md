# Sensor Tracker Integration Plan for Reporting

## Overview
This document outlines the plan to integrate Sensor Tracker metadata into the Wave Glider Buddy System's reporting infrastructure, supporting both active mission reporting and end-of-mission historical reporting.

## Current State Analysis

### Existing Reporting System
- **Weekly Reports**: PDF reports generated for active missions
- **Data Sources**: Telemetry, power, solar, CTD, weather, waves, errors
- **Mission Models**: `MissionOverview`, `MissionGoal`, `MissionNote`
- **Report Generation**: `generate_weekly_report()` in `app/core/reporting.py`
- **Historical Missions**: Supported but with limited metadata

### Sensor Tracker Service Capabilities
- ✅ Fetch deployments by mission number (e.g., 216) or ID
- ✅ Parse deployment metadata (timing, location, platform info)
- ✅ Extract data loggers (flight and science computers)
- ✅ Extract instruments on data loggers
- ✅ Extract sensors on instruments
- ✅ Extract platform-direct instruments

## Integration Goals

1. **Metadata Tracking**: Store and validate Sensor Tracker metadata for each mission
2. **Active Mission Reporting**: Include sensor/instrument metadata in weekly reports
3. **End-of-Mission Reports**: Comprehensive historical reports with full sensor metadata
4. **Validation**: Ensure sensor/instrument data matches between Sensor Tracker and actual mission data

## Implementation Plan

### Phase 1: Database Models for Sensor Tracker Metadata

#### 1.1 Create New Database Tables

```python
# app/core/models/database.py

class SensorTrackerDeployment(SQLModel, table=True):
    """Stores Sensor Tracker deployment metadata linked to missions."""
    __tablename__ = "sensor_tracker_deployments"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    mission_id: str = SQLModelField(index=True, unique=True, description="Mission ID (e.g., 'm216')")
    sensor_tracker_deployment_id: int = SQLModelField(index=True, description="Sensor Tracker internal ID")
    deployment_number: int = SQLModelField(index=True, description="Mission/deployment number")
    
    # Deployment metadata
    title: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    deployment_location_lat: Optional[float] = None
    deployment_location_lon: Optional[float] = None
    recovery_location_lat: Optional[float] = None
    recovery_location_lon: Optional[float] = None
    depth: Optional[float] = None
    
    # Platform info
    platform_id: Optional[int] = None
    platform_name: Optional[str] = None
    platform_type: Optional[int] = None
    
    # Full parsed data (JSON for flexibility)
    full_metadata: Optional[Dict] = SQLModelField(sa_column=Column(JSON), description="Complete parsed deployment data")
    
    # Sync metadata
    last_synced_at: Optional[datetime] = None
    sync_status: str = SQLModelField(default="pending", description="pending, synced, error")
    sync_error: Optional[str] = None
    
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)}
    )


class MissionInstrument(SQLModel, table=True):
    """Stores instrument metadata for missions."""
    __tablename__ = "mission_instruments"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    mission_id: str = SQLModelField(index=True, description="Mission ID")
    sensor_tracker_instrument_id: Optional[int] = Field(index=True, description="Sensor Tracker instrument ID")
    
    # Instrument details
    instrument_identifier: str = SQLModelField(index=True, description="e.g., 'CTD', 'ADCP', 'GPSWaves-Sensor'")
    instrument_short_name: Optional[str] = None
    instrument_serial: Optional[str] = None
    instrument_name: Optional[str] = None
    
    # Data logger association
    data_logger_type: Optional[str] = None  # 'flight' or 'science'
    data_logger_id: Optional[int] = None
    data_logger_name: Optional[str] = None
    data_logger_identifier: Optional[str] = None
    is_platform_direct: bool = SQLModelField(default=False, description="True if attached directly to platform")
    
    # Timing
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    # Validation
    validated: bool = SQLModelField(default=False, description="Whether instrument data has been validated")
    validation_notes: Optional[str] = None
    
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)}
    )


class MissionSensor(SQLModel, table=True):
    """Stores sensor metadata for missions."""
    __tablename__ = "mission_sensors"
    
    id: Optional[int] = SQLModelField(default=None, primary_key=True)
    mission_id: str = SQLModelField(index=True, description="Mission ID")
    instrument_id: int = SQLModelField(foreign_key="mission_instruments.id", description="Parent instrument")
    sensor_tracker_sensor_id: Optional[int] = Field(index=True, description="Sensor Tracker sensor ID")
    
    # Sensor details
    sensor_identifier: str = SQLModelField(index=True, description="e.g., 'dissolved_oxygen - 3151', 'ctd_pump'")
    sensor_short_name: Optional[str] = None
    sensor_serial: Optional[str] = None
    
    # Timing
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    # Validation
    validated: bool = SQLModelField(default=False)
    validation_notes: Optional[str] = None
    
    created_at_utc: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    updated_at_utc: datetime = SQLModelField(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)}
    )
    
    # Relationship
    instrument: "MissionInstrument" = Relationship(back_populates="sensors")
```

#### 1.2 Update MissionOverview Model
Add optional reference to Sensor Tracker deployment:
```python
class MissionOverview(SQLModel, table=True):
    # ... existing fields ...
    sensor_tracker_synced: bool = SQLModelField(default=False, description="Whether Sensor Tracker data has been synced")
    sensor_tracker_last_sync: Optional[datetime] = None
```

### Phase 2: Sensor Tracker Sync Service (On-Demand)

#### 2.1 Sync Strategy: On-Demand Only
**No scheduled polling** - Sensor Tracker data is fetched only when needed:
- When generating weekly reports
- When requesting reports for specific timelines
- When generating end-of-mission reports

**Caching Strategy:**
- Store fetched data in database for reuse
- Check cache age before fetching (optional: refresh if > 7 days old)
- Force refresh only when explicitly requested

#### 2.2 Create Sync Service
```python
# app/services/sensor_tracker_sync_service.py

class SensorTrackerSyncService:
    """
    Service for syncing Sensor Tracker metadata into local database.
    Uses on-demand fetching - only polls Sensor Tracker when explicitly requested.
    
    Handles:
    - Fetching deployment data from Sensor Tracker (on-demand)
    - Parsing and storing in local database
    - Caching fetched data for reuse
    - Updating existing records when refreshed
    """
    
    async def get_or_sync_mission(
        self,
        mission_id: str,
        deployment_number: Optional[int] = None,
        force_refresh: bool = False,
        max_cache_age_days: int = 7
    ) -> SensorTrackerDeployment:
        """
        Get Sensor Tracker data for a mission, fetching if needed.
        
        Args:
            mission_id: Mission ID (e.g., 'm216')
            deployment_number: Optional deployment number (extracted from mission_id if not provided)
            force_refresh: If True, always re-fetch from Sensor Tracker
            max_cache_age_days: Maximum age of cached data before auto-refresh (default 7 days)
            
        Returns:
            SensorTrackerDeployment record (from cache or freshly fetched)
        """
        # 1. Check if we have cached data
        # 2. If cached and not expired, return cached data
        # 3. If force_refresh or cache expired, fetch from Sensor Tracker
        # 4. Store/update in database
        # 5. Return record
        pass
    
    async def sync_mission(
        self,
        mission_id: str,
        deployment_number: Optional[int] = None
    ) -> SensorTrackerDeployment:
        """
        Explicitly sync (fetch and store) Sensor Tracker data for a mission.
        Called when generating reports.
        
        Args:
            mission_id: Mission ID (e.g., 'm216')
            deployment_number: Optional deployment number
            
        Returns:
            SensorTrackerDeployment record
        """
        pass
    
    async def validate_mission_instruments(
        self,
        mission_id: str
    ) -> Dict[str, Any]:
        """
        Validate that instruments/sensors in Sensor Tracker match
        what's actually being used in the mission (based on data files).
        
        Returns validation report.
        """
        pass
```

#### 2.3 Sync Workflow (On-Demand)
**When called during report generation:**
1. Check if cached data exists and is recent (< 7 days old)
2. If cached and recent, use cached data
3. If not cached or expired, fetch from Sensor Tracker:
   - Extract deployment number from mission_id (e.g., "m216" → 216)
   - Fetch deployment from Sensor Tracker API
   - Parse deployment data
   - Store/update in database
   - Extract and store instruments
   - Extract and store sensors
   - Update sync timestamp
4. Return cached or fresh data

### Phase 3: Reporting Integration

#### 3.1 Active Mission Reporting Enhancement

**Update `generate_weekly_report()` to include:**
- Instrument summary section
- Sensor summary section
- Platform metadata section
- Data logger configuration

**Integration Points:**
```python
# In generate_weekly_report() - add before generating PDF:

# Fetch Sensor Tracker metadata (on-demand, uses cache if available)
sync_service = SensorTrackerSyncService()
sensor_tracker_data = await sync_service.get_or_sync_mission(
    mission_id=mission_id,
    force_refresh=False  # Use cache if recent
)

# Generate instrument/sensor metadata section
instrument_section = await generate_instrument_metadata_section(
    mission_id=mission_id,
    sensor_tracker_data=sensor_tracker_data,
    session=session
)
```

**New Report Sections:**
```python
# Add to reporting.py

async def generate_instrument_metadata_section(
    mission_id: str,
    sensor_tracker_data: Optional[SensorTrackerDeployment],
    session: SQLModelSession
) -> str:
    """
    Generate HTML section for instrument/sensor metadata.
    Uses cached Sensor Tracker data if available.
    """
    if not sensor_tracker_data:
        return "<p>Sensor Tracker metadata not available.</p>"
    
    # Format as HTML table
    # Include: instrument name, serial, data logger, sensors
    # Query MissionInstrument and MissionSensor from database
    pass
```

#### 3.2 End-of-Mission Report Template

**New Report Type: `end_of_mission_report`**

```python
async def generate_end_of_mission_report(
    mission_id: str,
    session: SQLModelSession,
    include_full_metadata: bool = True,
    force_sensor_tracker_refresh: bool = True  # Always refresh for end-of-mission
) -> str:
    """
    Generate comprehensive end-of-mission report.
    
    Always fetches fresh Sensor Tracker data to ensure accuracy.
    
    Includes:
    1. Mission Overview (existing)
    2. Mission Goals & Achievements
    3. Timeline & Key Events
    4. Platform & Instrument Configuration (NEW - from Sensor Tracker)
    5. Sensor Summary (NEW - from Sensor Tracker)
    6. Data Quality Summary
    7. Performance Metrics
    8. Lessons Learned
    """
    # Fetch fresh Sensor Tracker data (force refresh for end-of-mission)
    sync_service = SensorTrackerSyncService()
    sensor_tracker_data = await sync_service.get_or_sync_mission(
        mission_id=mission_id,
        force_refresh=force_sensor_tracker_refresh
    )
    
    # Generate report with Sensor Tracker metadata
    pass
```

**Report Structure:**
1. **Cover Page**: Mission title, dates, platform
2. **Executive Summary**: High-level mission overview
3. **Platform Configuration**: 
   - Platform details (from Sensor Tracker)
   - Data loggers (flight/science)
   - Instrument inventory with serial numbers
   - Sensor inventory
4. **Mission Timeline**: Start/end, key events
5. **Data Summary**: All data sources, quality metrics
6. **Performance Analysis**: Power, navigation, sensor performance
7. **Issues & Resolutions**: Error logs, troubleshooting
8. **Recommendations**: For future missions

### Phase 4: Validation & Data Quality

#### 4.1 Validation Service
```python
# app/services/sensor_tracker_validation_service.py

class SensorTrackerValidationService:
    """
    Validates Sensor Tracker data against actual mission data.
    """
    
    async def validate_instruments(
        self,
        mission_id: str
    ) -> ValidationReport:
        """
        Compare Sensor Tracker instruments with:
        - Data files present (CTD files → CTD instrument exists)
        - Expected instruments based on mission type
        - Serial numbers match expected values
        """
        pass
    
    async def validate_sensors(
        self,
        mission_id: str
    ) -> ValidationReport:
        """
        Validate sensors match expected configuration.
        """
        pass
```

#### 4.2 Validation Checks
- **Instrument Presence**: Data files exist for claimed instruments
- **Serial Number Matching**: Serial numbers match expected values
- **Timing Validation**: Instrument start/end times align with mission
- **Data Logger Configuration**: Correct flight/science logger assignment
- **Sensor-Instrument Links**: Sensors match their parent instruments

### Phase 5: API Endpoints & UI

#### 5.1 New API Endpoints
```python
# app/routers/sensor_tracker.py

@router.post("/missions/{mission_id}/sync-sensor-tracker")
async def sync_sensor_tracker(
    mission_id: str,
    force_refresh: bool = False
):
    """Sync Sensor Tracker data for a mission."""
    pass

@router.get("/missions/{mission_id}/sensor-tracker")
async def get_sensor_tracker_metadata(
    mission_id: str
):
    """Get Sensor Tracker metadata for a mission."""
    pass

@router.get("/missions/{mission_id}/instruments")
async def get_mission_instruments(
    mission_id: str
):
    """Get instruments for a mission."""
    pass

@router.get("/missions/{mission_id}/sensors")
async def get_mission_sensors(
    mission_id: str
):
    """Get sensors for a mission."""
    pass

@router.post("/missions/{mission_id}/validate-sensor-tracker")
async def validate_sensor_tracker(
    mission_id: str
):
    """Validate Sensor Tracker data for a mission."""
    pass
```

#### 5.2 UI Components
- **Mission Dashboard**: Add "Sensor Configuration" card
- **Mission Settings**: Add "Sync Sensor Tracker" button
- **Report Generation**: Add "Include Sensor Metadata" option
- **End-of-Mission Report**: New report type in dropdown

### Phase 6: Historical Mission Support

#### 6.1 Bulk Sync Service
```python
async def sync_all_historical_missions(
    session: SQLModelSession,
    limit: Optional[int] = None
):
    """
    Sync Sensor Tracker data for all historical missions.
    Useful for initial population or bulk updates.
    """
    pass
```

#### 6.2 Historical Report Generation
- Generate end-of-mission reports for all historical missions
- Batch processing for efficiency
- Progress tracking

## Data Flow

```
┌─────────────────┐
│ Sensor Tracker  │
│     API         │
└────────┬────────┘
         │
         │ fetch_deployment_by_number()
         ▼
┌─────────────────┐
│ Sensor Tracker  │
│    Service      │
│  (parse data)   │
└────────┬────────┘
         │
         │ sync_mission()
         ▼
┌─────────────────┐
│  Sync Service   │
│ (store in DB)   │
└────────┬────────┘
         │
         │
         ▼
┌─────────────────┐      ┌─────────────────┐
│   Database      │◄─────┤  Validation     │
│  (Models)       │      │   Service       │
└────────┬────────┘      └─────────────────┘
         │
         │ query_metadata()
         ▼
┌─────────────────┐
│  Reporting      │
│   Service       │
│ (generate PDF)  │
└─────────────────┘
```

## Implementation Order

1. **Phase 1**: Database models (1-2 days)
   - Create migration
   - Test models

2. **Phase 2**: Sync service (2-3 days)
   - Implement sync logic
   - Test with real missions

3. **Phase 3**: Reporting integration (3-4 days)
   - Update weekly reports
   - Create end-of-mission template

4. **Phase 4**: Validation (2-3 days)
   - Implement validation logic
   - Create validation reports

5. **Phase 5**: API & UI (2-3 days)
   - Create endpoints
   - Add UI components

6. **Phase 6**: Historical support (1-2 days)
   - Bulk sync
   - Historical report generation

**Total Estimated Time: 11-17 days**

## Testing Strategy

1. **Unit Tests**: Each service method
2. **Integration Tests**: Full sync workflow
3. **Validation Tests**: Data consistency checks
4. **Report Tests**: PDF generation with Sensor Tracker data
5. **Historical Tests**: Bulk operations

## Polling Strategy Summary

### On-Demand Fetching Only
- **No scheduled polling** - Sensor Tracker is only queried when needed
- **Three trigger points:**
  1. **Weekly Report Generation**: Fetches/caches data when generating weekly reports
  2. **Timeline-Specific Reports**: Fetches when user requests report for specific date range
  3. **End-of-Mission Reports**: Always fetches fresh data (force refresh)

### Caching Strategy
- Store fetched data in database (`SensorTrackerDeployment`, `MissionInstrument`, `MissionSensor`)
- Cache is valid for 7 days (configurable)
- Use cached data if available and recent
- Force refresh only when:
  - Generating end-of-mission reports
  - User explicitly requests refresh
  - Cache is older than max age

### Benefits
- **Reduced API load**: Only fetch when actually needed
- **Faster report generation**: Use cached data when available
- **Always fresh for final reports**: End-of-mission reports always get latest data
- **Flexible**: Can force refresh when needed

## Future Enhancements

1. **Change Detection**: Alert when Sensor Tracker data changes (on next fetch)
2. **Data Reconciliation**: Compare Sensor Tracker with actual data files
3. **Export Formats**: Export metadata to various formats (CSV, JSON, XML)
4. **Visualization**: Instrument/sensor configuration diagrams
5. **Manual Sync UI**: Button to manually refresh Sensor Tracker data for a mission

