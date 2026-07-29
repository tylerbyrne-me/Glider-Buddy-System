# Offload Log Archiving Plan

## Problem Statement

The WG-VM4 payload parser automatically creates and updates offload logs from real-time mission data. However, when historical mission data is loaded, this same processing runs and overwrites current station offload logs with outdated historical data.

## Short-Term Solution (Implemented)

**Status: ✅ Complete**

The WG-VM4 processing has been modified to skip execution when loading historical missions:

- Modified `_render_dashboard()` in `app/app.py` to check the `is_historical` flag
- When `is_historical=True`, WG-VM4 offload log processing is skipped
- A log message is recorded when processing is skipped for historical missions

**Code Location:**
```1897:1932:app/app.py
# Process WG-VM4 info data for automatic offload logging
# Skip processing for historical missions to prevent overwriting current offload logs
if "wg_vm4_info" in report_types_to_load and not is_historical:
    # ... processing code ...
elif "wg_vm4_info" in report_types_to_load and is_historical:
    logger.info(f"Skipping WG-VM4 offload log processing for historical mission {mission} to prevent overwriting current logs")
```

## Long-Term Archiving Strategy

### Option 1: Export to CSV/JSON (Recommended for Quick Implementation)

**Pros:**
- Simple to implement
- Easy to review and share
- No database schema changes required
- Can be done manually or via CLI command

**Cons:**
- Not integrated into database
- Requires manual management
- No automatic archival

**Implementation:**
- Create a CLI command or admin endpoint to export all offload logs for a given season/date range
- Export to CSV or JSON format
- Store in `data_store/archive/offload_logs_YYYY-MM-DD.csv`
- Include metadata: export date, season identifier, total records

### Option 2: Archive Table in Database

**Pros:**
- Integrated with existing database
- Can query archived logs
- Maintains referential integrity
- Can track when logs were archived

**Cons:**
- Requires database migration
- More complex implementation
- Need to manage data movement

**Implementation:**
- Create `OffloadLogArchive` table with same schema as `OffloadLog`
- Add `archived_at` timestamp field
- Add `season_id` or `archive_batch_id` field
- Create migration script to move logs older than X date to archive table
- Modify queries to exclude archived logs from active views (or create separate views)

### Option 3: Separate Archive Database

**Pros:**
- Complete separation of active and archived data
- Can archive entire database snapshots
- Easy to restore if needed
- No impact on active database performance

**Cons:**
- More complex to query across databases
- Requires database management overhead
- Need to handle cross-database relationships

**Implementation:**
- Create separate SQLite database: `data_store/archive/offload_logs_YYYY.sqlite`
- Export offload logs to archive database at end of season
- Create utility functions to query archive databases
- Store archive metadata in main database (which archives exist, dates, record counts)

### Option 4: Timestamp-Based Archival Flag

**Pros:**
- Simple schema change (add one boolean field)
- Easy to filter archived vs active logs
- No data movement required
- Can un-archive if needed

**Cons:**
- All data stays in same table (grows over time)
- Need to ensure queries filter archived records
- Potential performance impact on large datasets

**Implementation:**
- Add `is_archived: bool` field to `OffloadLog` model
- Add `archived_at: Optional[datetime]` field
- Add `archived_by: Optional[str]` field (username)
- Create migration to add these fields
- Create admin endpoint/CLI to mark logs as archived
- Modify queries to filter `is_archived=False` by default

## Recommended Approach

**Phase 1 (Immediate):** Use Option 1 (CSV Export) for end-of-season archival
- Quick to implement
- Provides immediate backup capability
- Can be done manually or via simple CLI command

**Phase 2 (Future Enhancement):** Implement Option 4 (Archive Flag) for integrated archival
- Add `is_archived`, `archived_at`, and `archived_by` fields to `OffloadLog`
- Create admin interface to archive logs by date range or season
- Maintains data in database but clearly separates active from archived

## Implementation Checklist

### Short-Term (Complete)
- [x] Skip WG-VM4 processing for historical missions
- [x] Add logging when processing is skipped

### Phase 1: CSV Export (Recommended Next Step)
- [ ] Create CLI command: `python -m app.cli.archive_offload_logs --season 2024 --output data_store/archive/`
- [ ] Or create admin endpoint: `POST /api/admin/archive/offload-logs`
- [ ] Export includes: all offload log fields, station metadata snapshot, export metadata
- [ ] Document export format and location

### Phase 2: Database Archive Flag (Future)
- [ ] Create Alembic migration to add archive fields
- [ ] Update `OffloadLog` model with archive fields
- [ ] Create archive service/function to mark logs as archived
- [ ] Update queries to filter archived logs (or create separate views)
- [ ] Create admin UI for archiving logs
- [ ] Add un-archive capability if needed

## Archive File Naming Convention

Recommended format:
- CSV exports: `offload_logs_YYYY-MM-DD_season-YYYY.csv`
- Archive databases: `offload_logs_archive_YYYY.sqlite`
- Include metadata file: `offload_logs_archive_YYYY_metadata.json`

Metadata should include:
- Export/archive date
- Season identifier
- Date range of archived logs
- Total record count
- Exported by (username)
- Mission IDs included

## Considerations

1. **Station Metadata Updates**: When offload logs are archived, consider whether to:
   - Keep last_offload_timestamp_utc pointing to most recent active log
   - Create snapshot of station metadata at archive time
   - Maintain relationship between archived logs and current station state

2. **Data Retention**: Define policy for:
   - How long to keep active logs before archiving
   - How long to keep archived logs
   - When to permanently delete archived data (if ever)

3. **Access Control**: Ensure archived data:
   - Is accessible to admins for historical analysis
   - Is clearly marked as archived in UI
   - Cannot be accidentally modified

4. **Backup Strategy**: Archive exports should be:
   - Stored in version control or backup system
   - Documented with metadata
   - Tested for restore capability

