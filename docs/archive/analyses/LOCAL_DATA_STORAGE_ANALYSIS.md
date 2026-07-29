# Local Mission Data Storage Analysis

## Current Situation

### Storage Requirements
- **Per Mission**: ~100MB total (all report types combined)
- **Real-time Missions**: 2 active (m209, m211) = ~200MB
- **Past Missions**: ~16 missions = ~1.6GB
- **Total Estimated**: ~1.8GB for all missions

### Current Architecture
- **Remote Primary**: Data loaded from `http://129.173.20.180:8086/`
  - Real-time: `output_realtime_missions/`
  - Past: `output_past_missions/`
- **Local Fallback**: Only used when remote fails
- **Cache**: In-memory only (lost on restart)

---

## Recommendation: **YES, Store Locally**

### Why This Makes Sense

#### 1. **Storage Cost is Minimal**
- 1.8GB is trivial for modern servers
- Even with 50 missions = 5GB (still very manageable)
- Cost per GB is essentially zero

#### 2. **Performance Benefits**
- **No Network Latency**: Local disk I/O is much faster than HTTP requests
- **Predictable Performance**: No dependency on remote server availability
- **Better for Historical Data**: Past missions can be served instantly
- **Reduced Remote Load**: Less stress on the remote data server

#### 3. **Reliability**
- **Offline Capability**: System works even if remote server is down
- **Data Redundancy**: Backup copy of mission data
- **No Single Point of Failure**: Not dependent on remote server

#### 4. **Better User Experience**
- **Faster Dashboard Loads**: No waiting for remote HTTP requests
- **Instant Historical Access**: Past missions load immediately
- **Better Reporting**: Can process large date ranges quickly

#### 5. **Architecture Benefits**
- **Simpler Cache Strategy**: Can use disk-based cache with memory overlay
- **Better for Analytics**: Can run complex queries on local data
- **Easier Backup**: All data in one place

---

## Implementation Strategy

### Option 1: Mirror All Remote Data (Recommended)

**Approach**: Periodically sync all mission data from remote to local storage

**Structure**:
```
local_data_base_path/
├── m209/  (realtime)
│   ├── Telemetry 6 Report by WGMS Datetime.csv
│   ├── Amps Power Summary Report.csv
│   ├── Seabird CTD Records with D.O..csv
│   └── ... (all report types)
├── m211/  (realtime)
│   └── ...
├── m169/  (past)
│   └── ...
├── m170/  (past)
│   └── ...
└── ...
```

**Sync Strategy**:
- **Real-time Missions**: Sync every 10 minutes (same as cache refresh)
- **Past Missions**: Sync once daily (or on-demand when accessed)
- **Incremental Updates**: Only download new data since last sync

**Pros**:
- Complete data availability
- Fast access to everything
- Works offline

**Cons**:
- Need sync logic
- Disk space grows over time
- Need cleanup strategy for very old missions

---

### Option 2: Hybrid - Cache Frequently Accessed

**Approach**: Store only missions that are actively accessed

**Structure**: Same as Option 1, but only for:
- Active real-time missions (always stored)
- Past missions accessed in last 30 days
- Missions explicitly requested by users

**Sync Strategy**:
- Real-time: Always synced
- Past: On-demand when first accessed, then cached

**Pros**:
- Minimal disk usage
- Only stores what's needed
- Automatic cleanup of unused missions

**Cons**:
- First access to past mission requires download
- More complex logic

---

### Option 3: Full Local + Incremental Sync

**Approach**: Initial full download, then incremental updates

**Structure**: Same as Option 1

**Sync Strategy**:
- **Initial**: Download full dataset for all missions (one-time)
- **Updates**: Only sync new data since last timestamp
- **Real-time**: Every 10 minutes
- **Past**: Daily or weekly

**Pros**:
- Fastest access (everything local)
- Efficient updates (only new data)
- Best performance

**Cons**:
- Initial sync takes time
- Need to track last sync timestamp per mission

---

## Recommended Implementation: Option 1 (Full Mirror)

### Why Option 1?

1. **Storage is Cheap**: 1.8GB is nothing
2. **Simplicity**: No complex logic about what to store
3. **Performance**: Everything is always available
4. **Reliability**: Complete redundancy

### Implementation Plan

#### Phase 1: Local Storage Structure
```python
# Update config to support mission-specific paths
local_data_base_path/
├── realtime/
│   ├── m209/
│   └── m211/
└── past/
    ├── m169/
    ├── m170/
    └── ...
```

#### Phase 2: Background Sync Service
```python
async def sync_mission_data(mission_id: str, is_realtime: bool):
    """Sync mission data from remote to local"""
    base_url = "output_realtime_missions" if is_realtime else "output_past_missions"
    
    for report_type in CACHE_STRATEGIES.keys():
        # Download CSV file
        # Save to local_data_base_path/{realtime|past}/{mission_id}/
        # Update last_sync_timestamp
```

#### Phase 3: Update Data Loading Priority
```python
# New priority order:
# 1. Check local storage first (fastest)
# 2. Fall back to remote if local missing
# 3. Background sync keeps local updated
```

#### Phase 4: Cache Strategy Update
- **L1 Cache**: In-memory (hot data, 512 entries)
- **L2 Cache**: Local disk files (all mission data)
- **L3 Source**: Remote (for initial sync and updates)

---

## Benefits for Your Use Case

### 1. **Historical Data Access**
- Past missions load instantly from local disk
- No need to wait for remote server
- Can serve historical data even if remote is down

### 2. **Dashboard Performance**
- Initial page load: Load from local (fast)
- Background sync: Keep local updated (non-blocking)
- User experience: Always fast, always available

### 3. **Reporting & Analytics**
- Can process large date ranges quickly
- No network timeouts for big queries
- Better for complex aggregations

### 4. **Cache Architecture**
- Can implement disk-based cache persistence
- Faster startup (load from disk instead of remote)
- Better cache hit rates

---

## Storage Management

### Cleanup Strategy
```python
# Options:
# 1. Keep all missions forever (recommended - only 1.8GB)
# 2. Archive old missions after X months
# 3. Compress old missions (CSV -> Parquet)
# 4. Move to cold storage after Y months
```

**Recommendation**: Keep all missions (storage is cheap, data is valuable)

### Monitoring
- Track disk usage per mission
- Alert if storage exceeds threshold (e.g., 10GB)
- Log sync success/failure rates

---

## Comparison: Current vs. Proposed

| Aspect | Current (Remote Only) | Proposed (Local Mirror) |
|--------|----------------------|------------------------|
| **Initial Load** | Slow (HTTP request) | Fast (disk read) |
| **Historical Access** | Slow (HTTP request) | Fast (disk read) |
| **Offline Capability** | ❌ No | ✅ Yes |
| **Remote Dependency** | ✅ Required | ⚠️ Optional |
| **Storage Cost** | 0 GB | ~1.8 GB |
| **Sync Complexity** | None | Medium |
| **Performance** | Variable | Consistent |
| **Reliability** | Single point of failure | Redundant |

---

## Implementation Considerations

### 1. **Sync Frequency**
- **Real-time missions**: Every 10 minutes (same as cache refresh)
- **Past missions**: Daily or on-demand
- **Failed syncs**: Retry with exponential backoff

### 2. **Data Integrity**
- Verify file checksums after download
- Handle partial downloads gracefully
- Track sync status per mission/report_type

### 3. **Concurrent Access**
- Sync in background (non-blocking)
- Lock files during sync to prevent corruption
- Atomic file replacement (write to temp, then rename)

### 4. **Error Handling**
- If local file missing/corrupt: fall back to remote
- If remote unavailable: use local (stale but available)
- Log all sync failures for monitoring

---

## Recommended Next Steps

1. ✅ **Phase 1**: Implement local storage structure
2. ✅ **Phase 2**: Create background sync service
3. ✅ **Phase 3**: Update data loading to prefer local
4. ✅ **Phase 4**: Add sync status monitoring
5. ⚠️ **Phase 5**: Consider disk-based cache persistence (optional)

---

## Conclusion

**YES, absolutely store mission data locally.**

Given:
- 100MB per mission is tiny
- 1.8GB total is trivial
- Server space is available
- Performance benefits are significant
- Reliability improves dramatically

**The benefits far outweigh the minimal storage cost.**

The only consideration is implementing the sync logic, but that's a one-time development cost that pays dividends in performance and reliability.



