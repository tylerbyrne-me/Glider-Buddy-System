# Sensor Tracker Metadata Expansion Plan

## Overview
This document outlines the plan for expanding the Sensor Tracker integration to include additional metadata beyond sensors and instruments, such as deployment comments, acknowledgements, agencies, data repository links, images, and more.

## Current State

### Currently Stored
- Basic deployment info (title, dates, locations, depth)
- Platform information
- Instruments and sensors (via separate tables)
- Full metadata JSON (stored but not structured)

### Currently Available in Parsed Data (but not stored in structured fields)
Based on `test_data/sensor_tracker_deployment_4291_parsed.json`, the following metadata is available:

1. **Deployment Comments** (`comment` field)
   - Long-form text description of the deployment
   - Example: "A Liquid Robotics SV3 v300 Wave Glider was deployed..."

2. **Deployment Details** (`deployment_details`)
   - `deployment_cruise`: Vessel name for deployment
   - `recovery_cruise`: Vessel name for recovery
   - `deployment_personnel`: Names of personnel involved in deployment
   - `recovery_personnel`: Names of personnel involved in recovery
   - `wmo_id`: WMO identifier (if applicable)
   - `until`: Additional timing information

3. **Publication Information** (`publication`)
   - `publisher_name`: Organization publishing the data
   - `publisher_email`: Contact email
   - `publisher_url`: Publisher website
   - `publisher_country`: Country of publisher
   - `data_repository_link`: Link to data repository (e.g., ERDDAP)
   - `metadata_link`: Link to metadata documentation

4. **Attribution** (`attribution`)
   - `creator_name`: Data creator
   - `creator_email`: Creator contact
   - `creator_url`: Creator website
   - `creator_sector`: Creator sector (academic, government, etc.)
   - `contributor_name`: Contributors
   - `contributor_role`: Role of contributors
   - `contributors_email`: Contributor contact
   - `acknowledgement`: Acknowledgement text

5. **Program Information** (`program_info`)
   - `program`: Program name
   - `agencies`: Funding/supporting agencies
   - `agencies_role`: Role of agencies (e.g., "Funding agency")
   - `site`: Site name
   - `sea_name`: Geographic region

6. **Technical Details** (`technical`)
   - `transmission_system`: Communication systems (e.g., "Iridium, Cellular")
   - `positioning_system`: Navigation systems (e.g., "GPS")
   - `references`: Technical references

7. **Related Entities** (`related_ids`)
   - `institution_id`: Full institution details (name, address, contact)
   - `project_id`: Project information
   - `platform_power_type_id`: Power system details

8. **Additional Endpoints to Explore**
   - `deployment_comment` endpoint (may have structured comments with depth/history)
   - Image endpoints (deployment photos, platform images)
   - Custom fields (deployment-specific custom metadata)

## Proposed Database Schema Changes

### Option 1: Add Structured Fields to `SensorTrackerDeployment`
Add new columns to store commonly accessed metadata:

```python
class SensorTrackerDeployment(SQLModel, table=True):
    # ... existing fields ...
    
    # Deployment details
    deployment_cruise: Optional[str] = None
    recovery_cruise: Optional[str] = None
    deployment_personnel: Optional[str] = None  # Comma-separated or JSON array
    recovery_personnel: Optional[str] = None
    
    # Publication and data access
    data_repository_link: Optional[str] = None
    metadata_link: Optional[str] = None
    publisher_name: Optional[str] = None
    publisher_url: Optional[str] = None
    
    # Attribution
    acknowledgement: Optional[str] = None
    creator_name: Optional[str] = None
    creator_email: Optional[str] = None
    contributor_name: Optional[str] = None
    contributor_role: Optional[str] = None
    
    # Program and agencies
    program: Optional[str] = None
    agencies: Optional[str] = None  # Could be JSON array for multiple
    agencies_role: Optional[str] = None
    
    # Technical
    transmission_system: Optional[str] = None
    positioning_system: Optional[str] = None
    
    # Comments (long text)
    deployment_comment: Optional[str] = SQLModelField(sa_column=Column(Text))
    
    # Keep full_metadata for flexibility and additional fields
    full_metadata: Optional[Dict] = SQLModelField(sa_column=Column(JSON))
```

### Option 2: Create Separate Related Tables
For more complex relationships (e.g., multiple agencies, multiple contributors):

```python
class DeploymentAgency(SQLModel, table=True):
    """Agencies associated with a deployment."""
    id: Optional[int] = SQLModelField(primary_key=True)
    deployment_id: int = SQLModelField(foreign_key="sensor_tracker_deployments.id")
    agency_name: str
    agency_role: Optional[str] = None
    order: int = SQLModelField(default=0)  # For ordering multiple agencies

class DeploymentContributor(SQLModel, table=True):
    """Contributors to a deployment."""
    id: Optional[int] = SQLModelField(primary_key=True)
    deployment_id: int = SQLModelField(foreign_key="sensor_tracker_deployments.id")
    contributor_name: str
    contributor_role: Optional[str] = None
    contributor_email: Optional[str] = None
    order: int = SQLModelField(default=0)

class DeploymentImage(SQLModel, table=True):
    """Images associated with a deployment."""
    id: Optional[int] = SQLModelField(primary_key=True)
    deployment_id: int = SQLModelField(foreign_key="sensor_tracker_deployments.id")
    image_url: str
    image_type: Optional[str] = None  # e.g., "deployment", "recovery", "platform"
    caption: Optional[str] = None
    order: int = SQLModelField(default=0)
    sensor_tracker_image_id: Optional[int] = None  # Reference to Sensor Tracker

class DeploymentComment(SQLModel, table=True):
    """Structured comments for a deployment (from deployment_comment endpoint)."""
    id: Optional[int] = SQLModelField(primary_key=True)
    deployment_id: int = SQLModelField(foreign_key="sensor_tracker_deployments.id")
    comment_text: str = SQLModelField(sa_column=Column(Text))
    comment_type: Optional[str] = None  # e.g., "general", "technical", "operational"
    depth: Optional[int] = None  # Depth level from Sensor Tracker
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None
    sensor_tracker_comment_id: Optional[int] = None
```

### Recommendation
**Hybrid Approach**: Use Option 1 for simple, single-value fields (most common case) and keep `full_metadata` JSON for complex/nested data. Add Option 2 tables only if we discover deployments with multiple agencies/contributors that need proper relational structure.

## Implementation Phases

### Phase 1: Expand Parsing and Storage (Structured Fields)
**Goal**: Extract and store commonly used metadata in structured database fields.

**Tasks**:
1. Update `SensorTrackerService.parse_deployment()` to extract additional fields:
   - Deployment details (cruise, personnel)
   - Publication info (data repository, publisher)
   - Attribution (acknowledgement, creator, contributors)
   - Program info (program, agencies, agencies_role)
   - Technical details
   - Deployment comment

2. Update `SensorTrackerDeployment` model with new fields (Option 1 approach)

3. Update `SensorTrackerSyncService` to populate new fields during sync

4. Create Alembic migration to add new columns

5. Update sync logic to handle existing deployments (backfill)

**Estimated Effort**: 2-3 days

### Phase 2: Explore Additional Endpoints
**Goal**: Discover and integrate additional Sensor Tracker endpoints.

**Tasks**:
1. Research `deployment_comment` endpoint:
   - Test API access and response structure
   - Determine if it provides structured comments vs. single comment field
   - Check for comment history/versioning

2. Research image endpoints:
   - Find endpoint for deployment/platform images
   - Understand image storage (URLs vs. file uploads)
   - Determine image metadata (captions, types, ordering)

3. Research custom fields:
   - Check if deployments have custom metadata fields
   - Understand structure and access patterns

4. Document findings and update service layer

**Estimated Effort**: 1-2 days

### Phase 3: Enhanced Reporting Integration
**Goal**: Include expanded metadata in PDF reports.

**Tasks**:
1. Update report generation to include:
   - Deployment details section (cruise, personnel)
   - Attribution section (acknowledgements, creators, contributors)
   - Program and agency information
   - Data repository links
   - Technical specifications

2. Add new report sections:
   - "Deployment Information" (expanded from current basic info)
   - "Attribution and Acknowledgements"
   - "Data Access" (repository links, metadata links)
   - "Program and Funding" (agencies, roles)

3. Format long-form comments appropriately (wrapping, spacing)

4. Consider adding images to reports (if available)

**Estimated Effort**: 2-3 days

### Phase 4: UI Integration
**Goal**: Display expanded metadata in admin and public-facing UIs.

**Tasks**:
1. Create admin page section for viewing Sensor Tracker metadata:
   - Expandable sections for different metadata types
   - Read-only display (data comes from Sensor Tracker)
   - Link to Sensor Tracker source

2. Add metadata display to mission overview pages:
   - Show key metadata (program, agencies, data repository)
   - Link to data repository if available
   - Display acknowledgements

3. Consider metadata editing (if needed):
   - Note: Most metadata should be managed in Sensor Tracker
   - May want read-only display with link to edit in Sensor Tracker

**Estimated Effort**: 2-3 days

### Phase 5: Advanced Features (If Needed)
**Goal**: Handle complex cases and edge cases.

**Tasks**:
1. Implement Option 2 tables if multiple agencies/contributors are common
2. Add image handling and display
3. Implement deployment comment history tracking
4. Add custom field support
5. Create metadata validation and sync status reporting

**Estimated Effort**: 3-5 days (as needed)

## API Endpoints to Implement

### New Service Methods

```python
# In SensorTrackerService

async def fetch_deployment_comments(
    self, 
    deployment_id: int, 
    depth: int = 1
) -> List[Dict[str, Any]]:
    """Fetch structured comments from deployment_comment endpoint."""
    pass

async def fetch_deployment_images(
    self, 
    deployment_id: int
) -> List[Dict[str, Any]]:
    """Fetch images associated with a deployment."""
    pass

async def fetch_institution_details(
    self, 
    institution_id: int
) -> Dict[str, Any]:
    """Fetch full institution details."""
    pass

async def fetch_project_details(
    self, 
    project_id: int
) -> Dict[str, Any]:
    """Fetch full project details."""
    pass
```

## Data Flow

```
Sensor Tracker API
    ↓
SensorTrackerService (fetch & parse)
    ↓
SensorTrackerSyncService (sync to DB)
    ↓
Database (SensorTrackerDeployment + related tables)
    ↓
Report Generation / UI Display
```

## Considerations

### Data Synchronization
- **On-demand sync**: Continue current approach (sync when generating reports)
- **Incremental updates**: Only fetch changed data if possible
- **Conflict resolution**: Sensor Tracker is source of truth
- **Error handling**: Gracefully handle missing or malformed data

### Data Storage Strategy
- **Structured fields**: For commonly accessed, simple data
- **JSON field**: For complex/nested data and flexibility
- **Related tables**: For one-to-many relationships (agencies, contributors, images)

### Performance
- **Caching**: Cache parsed metadata to avoid repeated API calls
- **Lazy loading**: Load images/comments only when needed
- **Batch operations**: Fetch related entities in batches when possible

### User Experience
- **Progressive disclosure**: Show summary, expand for details
- **Source attribution**: Always link back to Sensor Tracker
- **Read-only by default**: Prevent accidental edits to synced data

## Testing Strategy

1. **Unit Tests**:
   - Test parsing of each metadata type
   - Test database model updates
   - Test sync service logic

2. **Integration Tests**:
   - Test full sync workflow with real API (if possible) or mocked responses
   - Test report generation with expanded metadata
   - Test UI display of metadata

3. **Manual Testing**:
   - Test with multiple deployments (different metadata configurations)
   - Verify data accuracy against Sensor Tracker source
   - Test edge cases (missing fields, null values, long text)

## Success Criteria

- [ ] All identified metadata types are parsed and stored
- [ ] Metadata appears correctly in PDF reports
- [ ] Metadata is accessible via admin UI
- [ ] Data repository links are functional
- [ ] Acknowledgements and attribution are properly displayed
- [ ] Sync process handles errors gracefully
- [ ] Performance is acceptable (no significant slowdown)

## Next Steps

1. **Review and approve plan** with stakeholders
2. **Start with Phase 1** (structured fields)
3. **Test with real deployment data** (e.g., mission 216)
4. **Iterate based on findings** from Phase 2 exploration
5. **Prioritize phases** based on business needs

## Questions Resolved

1. **Deployment Comments**: Only from the `comment` field (not a separate endpoint)
2. **Images**: Stored in IMAGES field as .jpg files with title, link, created/modified date fields
3. **Multiple Agencies**: Comma-separated values that should preserve order (represents funding hierarchy)
4. **Priority Order**:
   - **Priority 1**: Agencies, Agencies Role, Comment, Acknowledgements
   - **Priority 2**: All other metadata (in order as discovered)
   - Note: Some fields may be empty/null - handle gracefully

## Implementation Priority

### Phase 1A: Core Priority Fields (First)
1. Agencies (comma-separated, preserve order)
2. Agencies Role
3. Comment (deployment comment)
4. Acknowledgements

### Phase 1B: Additional Metadata (Second)
5. Deployment Details (cruise, personnel)
6. Publication Info (data repository, publisher)
7. Attribution (creator, contributors)
8. Program Info (program name, site, sea_name)
9. Technical Details
10. Images (if available in IMAGES field)

