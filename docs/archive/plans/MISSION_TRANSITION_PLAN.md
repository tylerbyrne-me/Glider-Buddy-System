# Mission Transition Plan: Real-Time to Historical

## Overview

This document outlines the process and considerations for transitioning missions from active/real-time status to historical status. This ensures that all mission documentation, comments, reports, and configurations are preserved and accessible after the mission ends.

## Current System Architecture

### Mission Status Determination

**Active Missions:**
- Defined in `app/config.py` → `settings.active_realtime_missions` (list)
- Stored in `.env` file as comma-separated values
- Used for:
  - Real-time data caching and refresh
  - Active mission dashboard display
  - Pilot access control

**Historical Missions:**
- Discovered dynamically by checking remote server's `output_past_missions/` folder
- Only accessible to admin users
- No explicit "historical" flag in database - determined by absence from active list

### Mission Data Storage

All mission-related data is stored by `mission_id` as the primary key:

1. **MissionOverview** (Database Table: `mission_overview`)
   - `mission_id` (primary key)
   - `document_url` - Link to mission plan document
   - `comments` - High-level mission comments
   - `enabled_sensor_cards` - JSON string of sensor configurations
   - `weekly_report_url` - Link to generated weekly reports
   - `created_at_utc`, `updated_at_utc`

2. **MissionGoal** (Database Table: `mission_goals`)
   - Linked by `mission_id` foreign key
   - Mission-specific goals and objectives

3. **MissionNote** (Database Table: `mission_notes`)
   - Linked by `mission_id` foreign key
   - Time-stamped notes and observations

4. **Mission Plan Documents** (File System)
   - Location: `web/static/mission_plans/`
   - Naming: `{mission_id}_plan.{ext}` (e.g., `m209_plan.pdf`)
   - Referenced via `document_url` in MissionOverview

5. **Weekly Reports** (File System)
   - Location: `web/static/mission_reports/`
   - Generated PDF reports
   - Referenced via `weekly_report_url` in MissionOverview

## Data Persistence Guarantee

**✅ Good News:** Since all mission data is keyed by `mission_id`:
- Database records persist automatically when mission transitions
- File-based documents remain in place
- No data migration is required
- Historical missions can access all their data immediately

## Transition Process

### Phase 1: Pre-Transition Checklist

Before transitioning a mission, verify:

- [ ] **Mission Data Completeness**
  - [ ] Mission overview documentation is up-to-date
  - [ ] All important notes have been added
  - [ ] Final weekly report has been generated (if applicable)
  - [ ] Mission plan document is finalized and uploaded

- [ ] **Data Verification**
  - [ ] Verify mission overview exists in database
  - [ ] Check that all goals and notes are saved
  - [ ] Confirm mission plan document exists and is accessible
  - [ ] Verify weekly reports are generated and linked

- [ ] **Remote Data Migration**
  - [ ] Confirm mission data has been moved to `output_past_missions/` on remote server
  - [ ] Verify data is accessible via historical mission endpoint

### Phase 2: Transition Steps

#### Step 1: Generate Final Mission Summary

Create a final mission summary document:
- Export mission overview data
- List all goals and their completion status
- Compile all mission notes
- Document sensor configurations used

**Recommended:** Create an admin endpoint or CLI command to generate this summary.

#### Step 2: Remove from Active List

Update configuration to remove mission from active list:

1. **Edit `.env` file:**
   ```env
   active_realtime_missions=m209,m211  # Remove completed mission
   ```

2. **Or update `app/config.py`** (if not using .env):
   ```python
   active_realtime_missions: list[str] = [
       "m211"  # Remove completed mission
   ]
   ```

3. **Restart application** to apply changes

#### Step 3: Verify Historical Access

After transition:
- [ ] Mission no longer appears in active missions dropdown
- [ ] Mission appears in historical missions dropdown (admin only)
- [ ] Historical mission dashboard loads correctly
- [ ] All mission data is accessible via historical view
- [ ] Mission overview, goals, and notes are visible
- [ ] Mission plan document is accessible
- [ ] Weekly reports are accessible

### Phase 3: Post-Transition Tasks

#### Data Archival (Optional but Recommended)

Consider creating a backup/archive of mission data:

1. **Database Export**
   - Export all MissionOverview, MissionGoal, MissionNote records for the mission
   - Store in `data_store/archive/missions/{mission_id}/`

2. **File Backup**
   - Copy mission plan documents
   - Copy weekly reports
   - Store in archive location

3. **Metadata Documentation**
   - Create a transition log entry
   - Document transition date
   - Record who performed the transition
   - Note any special circumstances

## Implementation Recommendations

### Option 1: Manual Transition (Current Approach)

**Pros:**
- Simple, straightforward
- Full admin control
- No code changes required

**Cons:**
- Manual process prone to errors
- No automated verification
- No transition audit trail

**Process:**
1. Admin manually edits `.env` file
2. Restarts application
3. Manually verifies data accessibility

### Option 2: Admin UI for Mission Transition (Recommended)

Create an admin interface to transition missions:

**Features:**
- List of active missions with transition button
- Pre-transition checklist
- Automatic data verification
- Transition confirmation dialog
- Post-transition verification
- Transition audit log

**Implementation:**
- New admin page: `/admin/mission_transitions.html`
- API endpoint: `POST /api/admin/missions/{mission_id}/transition`
- Transition log table in database

### Option 3: Automated Transition Detection

Automatically detect when missions should transition:

**Triggers:**
- Mission end date reached
- No new data received for X days
- Manual flag set by admin

**Implementation:**
- Add `mission_end_date` field to MissionOverview
- Scheduled job to check for missions to transition
- Admin notification before auto-transition
- Admin approval required for transition

## Database Schema Considerations

### Current Schema (No Changes Required)

The current schema supports transitions without modification:
- All tables use `mission_id` as key
- No "status" field needed (determined by active list)
- Historical missions query same tables

### Optional Enhancements

If implementing transition tracking:

```python
class MissionTransition(SQLModel, table=True):
    """Track mission transitions from active to historical."""
    __tablename__ = "mission_transitions"
    
    id: int = SQLModelField(primary_key=True)
    mission_id: str = SQLModelField(index=True)
    transitioned_at: datetime = SQLModelField(default_factory=lambda: datetime.now(timezone.utc))
    transitioned_by: int = SQLModelField(foreign_key="users.id")
    pre_transition_summary: Optional[str] = None  # JSON snapshot of mission state
    notes: Optional[str] = None
```

## File Management

### Mission Plan Documents

**Current Location:** `web/static/mission_plans/{mission_id}_plan.{ext}`

**Recommendation:** No changes needed
- Files remain accessible for historical missions
- URLs in database continue to work
- No file movement required

### Weekly Reports

**Current Location:** `web/static/mission_reports/`

**Recommendation:** No changes needed
- Reports remain accessible via URLs
- Historical missions can view all past reports

### Archive Strategy (Optional)

If implementing archival:
- Create `web/static/mission_plans/archive/{mission_id}/`
- Create `web/static/mission_reports/archive/{mission_id}/`
- Move files after transition
- Update database URLs to point to archive locations

## Access Control

### Current Behavior

**Active Missions:**
- All authenticated users can access
- Real-time data updates
- Full feature access

**Historical Missions:**
- Admin-only access
- No real-time updates
- Forecasts disabled
- WG-VM4 processing disabled

### No Changes Required

The existing access control already handles historical missions correctly.

## Testing Checklist

Before implementing any transition process, test:

1. **Data Persistence**
   - [ ] Create test mission overview
   - [ ] Add goals and notes
   - [ ] Upload mission plan
   - [ ] Generate weekly report
   - [ ] Remove from active list
   - [ ] Verify all data accessible as historical mission

2. **UI Functionality**
   - [ ] Mission disappears from active dropdown
   - [ ] Mission appears in historical dropdown (admin)
   - [ ] Historical dashboard loads correctly
   - [ ] Mission overview page works
   - [ ] All data displays correctly

3. **API Endpoints**
   - [ ] `/api/missions/{mission_id}/info` works for historical
   - [ ] `/api/missions/{mission_id}/overview` works for historical
   - [ ] Mission overview admin page works for historical
   - [ ] Historical mission data loads correctly

## Recommended Implementation Plan

### Phase 1: Immediate (Manual Process)

1. Document the manual transition process
2. Create transition checklist template
3. Test transition with a non-critical mission

### Phase 2: Short-Term (Enhanced Manual)

1. Create transition summary export function
2. Add transition verification endpoint
3. Create transition documentation template

### Phase 3: Long-Term (Automated UI)

1. Build admin transition UI
2. Implement transition audit logging
3. Add automated verification
4. Create transition reports

## Migration Notes

### For Existing Historical Missions

If you have missions that were never in the active list but have data:
- They will automatically appear in historical missions
- All their data will be accessible
- No migration needed

### For Missions Already Transitioned

If missions were previously removed from active list:
- They should already appear in historical missions
- Verify data accessibility
- If data is missing, check database and file system

## Rollback Procedure

If a mission needs to be reactivated:

1. Add mission ID back to `active_realtime_missions` in `.env`
2. Restart application
3. Mission will appear in active missions again
4. All data remains intact (no data loss)

## Summary

**Key Points:**
- ✅ No data migration required - data persists automatically
- ✅ No database schema changes needed
- ✅ File-based documents remain accessible
- ✅ Transition is reversible (can reactivate missions)
- ✅ Current system already supports historical missions

**Next Steps:**
1. Test transition process with a test mission
2. Document manual transition procedure
3. Consider implementing admin UI for future transitions
4. Create transition checklist for operations team




