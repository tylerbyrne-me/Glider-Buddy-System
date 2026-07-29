# Data Caching Architecture Review

## Current Implementation Overview

### Architecture
- **Cache Type**: In-memory LRU cache (`cachetools.LRUCache`)
- **Max Size**: 512 entries
- **Storage**: Python dictionaries in memory (no persistence)
- **Cache Key Structure**: `(report_type, mission_id, time_key, source_preference, custom_local_path)`
- **Cache Value Structure**: `(DataFrame, source_path, cache_timestamp, last_data_timestamp, file_modification_time)`

### Data Source Structure
- **Real-time Missions**: `http://129.173.20.180:8086/output_realtime_missions/`
  - Active missions (e.g., m209, m211)
  - Currently cached on startup
  - Background refresh enabled
  
- **Past Missions**: `http://129.173.20.180:8086/output_past_missions/`
  - Historical missions (e.g., m169, m170, m171, m176, etc.)
  - **Currently commented out in code** (line 536 in `data_service.py`)
  - Not loaded on startup
  - Not included in background refresh

### Key Features
1. **Incremental Loading**: Loads only new data since last known timestamp with overlap
2. **Time-Aware Caching**: Cache keys include time ranges for better hit rates
3. **Data-Type Specific Strategies**: Different overlap hours and incremental settings per report type
4. **Background Refresh**: APScheduler job runs every 10 minutes (configured via `BACKGROUND_CACHE_REFRESH_INTERVAL_MINUTES` in .env)
5. **User Activity Tracking**: Only refreshes data for active users (30-minute threshold)
6. **Startup Cache Initialization**: Pre-loads 24 hours of data for active missions

### Cache Strategies
```python
CACHE_STRATEGIES = {
    "power": {"expiry_minutes": None, "incremental": True, "overlap_hours": 1},
    "solar": {"expiry_minutes": None, "incremental": True, "overlap_hours": 1},
    "ctd": {"expiry_minutes": None, "incremental": True, "overlap_hours": 2},
    # ... all use incremental=True, expiry_minutes=None
}
```

---

## Pros of Current Implementation

### ✅ Advantages

1. **Memory Efficiency**
   - LRU eviction prevents unbounded memory growth
   - Only caches frequently accessed data
   - Automatic cleanup of least-used entries

2. **Performance**
   - Fast in-memory access (no I/O overhead)
   - Incremental loading reduces network/disk reads
   - Time-aware keys improve cache hit rates

3. **Smart Refresh Logic**
   - Only refreshes data for active users
   - Incremental updates prevent full reloads
   - Overlap mechanism prevents data gaps

4. **Flexibility**
   - Per-report-type configuration
   - Supports both local and remote sources
   - Custom local paths supported

5. **No External Dependencies**
   - Pure Python implementation
   - No database or Redis required
   - Simple deployment

---

## Cons of Current Implementation

### ❌ Disadvantages

1. **No Persistence**
   - Cache lost on server restart
   - Startup cache initialization adds delay
   - Historical data must be reloaded

2. **Cache Eviction Issues**
   - LRU may evict data still needed
   - 512 entries may be insufficient for multiple missions/time ranges
   - No priority system (active vs historical)

3. **Frontend Synchronization Problems**
   - **Root Cause of Hard Refresh Bug**: Frontend has no way to know when cache updates
   - Background refresh happens server-side, frontend unaware
   - Full page reload (`window.location.reload()`) is the only refresh mechanism
   - No real-time updates or notifications

4. **Historical Data Limitations**
   - `output_past_missions` path is commented out in code (not accessible)
   - No distinction between real-time and historical data in cache
   - Historical data would compete with real-time in LRU cache
   - No on-demand loading strategy for past missions
   - Startup cache only loads active missions from `output_realtime_missions`
   - Past missions must be explicitly enabled and integrated

5. **Cache Key Complexity**
   - Time range normalization may cause cache misses
   - Multiple keys checked for same data (inefficient)
   - No cache warming for common queries

6. **Memory Constraints**
   - Large DataFrames consume significant memory
   - No size-based eviction (only count-based)
   - Multiple time ranges for same data = multiple cache entries

7. **Background Refresh Limitations**
   - 10-minute interval (configured) is reasonable, but frontend still needs to detect updates
   - Only refreshes if users active in last 30 minutes
   - No immediate refresh on user return after inactivity

8. **No Cache Invalidation Strategy**
   - No way to invalidate specific entries
   - No TTL mechanism (relies on LRU only)
   - No cache versioning or staleness detection

---

## Current Bug Analysis: Hard Refresh Required

### Problem
Dashboard requires Ctrl+Shift+R hard refresh after inactive periods to see updated data.

### Root Causes

1. **Frontend Cache Stale**
   - Browser caches API responses
   - No cache-busting headers or ETags
   - Frontend doesn't know when to refresh

2. **Server Cache Updated, Frontend Unaware**
   - Background refresh updates server cache
   - Frontend still has old data in memory/browser cache
   - No WebSocket/SSE for real-time updates
   - No polling mechanism to check for updates

3. **Auto-Refresh Mechanism**
   - Uses `window.location.reload()` which may use browser cache
   - No `force_refresh` parameter in API calls
   - No timestamp-based cache invalidation

4. **User Activity Tracking Gap**
   - If user inactive >30 minutes, background refresh may skip their data
   - On return, cache may be stale but not refreshed
   - No "refresh on user return" mechanism

---

## Alternative Caching Strategies

### Option 1: Multi-Tier Cache with Persistence

**Architecture:**
- **L1**: In-memory LRU (current, for hot data)
- **L2**: Disk-based cache (SQLite/Parquet files)
- **L3**: Historical data archive (separate storage)

**Pros:**
- Persistence across restarts
- Faster startup (load from disk)
- Historical data doesn't compete with real-time
- Can implement size-based eviction

**Cons:**
- More complex implementation
- Disk I/O overhead
- Need to manage file cleanup
- Requires serialization/deserialization

**Best For:**
- Production environments
- Historical data requirements
- Multiple server instances

---

### Option 2: Redis-Based Distributed Cache

**Architecture:**
- Redis for cache storage
- In-memory for very hot data
- TTL-based expiration
- Pub/Sub for cache invalidation notifications

**Pros:**
- Distributed (multiple server instances)
- Built-in TTL and expiration
- Pub/Sub can notify frontend of updates
- Can implement cache warming
- Better for horizontal scaling

**Cons:**
- External dependency (Redis)
- Network latency
- Additional infrastructure
- Serialization overhead

**Best For:**
- Multi-server deployments
- High availability requirements
- Real-time update needs

---

### Option 3: Hybrid: In-Memory + Database Cache

**Architecture:**
- In-memory LRU for active/real-time data
- SQLite table for historical data cache
- Separate tables: `cache_realtime`, `cache_historical`
- On-demand loading for historical

**Pros:**
- No external dependencies
- Clear separation of real-time vs historical
- Historical data loaded only when accessed
- Can persist cache metadata

**Cons:**
- Database overhead
- More complex queries
- Need migration strategy

**Best For:**
- Current infrastructure
- Historical data requirements
- Single-server deployment

---

### Option 4: Time-Based Cache Segments

**Architecture:**
- Separate cache pools: `realtime_cache`, `historical_cache`
- Real-time: LRU, 24-72 hour window
- Historical: On-demand, longer TTL, separate storage
- Cache warming for common historical queries

**Pros:**
- Clear separation of concerns
- Historical doesn't evict real-time
- Can optimize each pool differently
- Better for reporting/visualization

**Cons:**
- More complex cache management
- Need to decide which pool to use
- Potential duplication

**Best For:**
- Mixed real-time and historical use cases
- Reporting/visualization features

---

### Option 5: Enhanced Current + Frontend Polling

**Architecture:**
- Keep current cache system
- Add cache version/timestamp to API responses
- Frontend polls for cache updates
- WebSocket/SSE for real-time notifications (optional)

**Pros:**
- Minimal backend changes
- Solves frontend sync issue
- Can implement incrementally
- No infrastructure changes

**Cons:**
- Polling overhead
- Still no persistence
- Historical data still an issue

**Best For:**
- Quick fix for current bug
- Minimal disruption

---

## Recommended Solution: Hybrid Approach

### Phase 1: Fix Frontend Sync (Immediate)
1. **Add Cache Timestamps to API Responses**
   - Include `cache_timestamp` and `last_data_timestamp` in all data endpoints
   - Frontend compares timestamps to detect stale data

2. **Implement Frontend Polling**
   - Poll `/api/cache-status` endpoint every 30-60 seconds
   - Check if data needs refresh based on timestamps
   - Auto-refresh charts when data updated

3. **Add Cache-Busting Headers**
   - `Cache-Control: no-cache` for data endpoints
   - Or use ETags for conditional requests

### Phase 2: Historical Data Support (Short-term)
1. **Enable Past Missions Access**
   - Uncomment `output_past_missions` in `_load_from_remote_sources()`
   - Add logic to determine if mission is historical (not in `active_realtime_missions`)
   - Try `output_realtime_missions` first, then `output_past_missions` as fallback

2. **Separate Cache Pools**
   - `realtime_cache`: Current LRU for active missions (from `output_realtime_missions`)
   - `historical_cache`: On-demand, longer retention, separate LRU (from `output_past_missions`)

3. **Historical Data Loading**
   - Load only when user requests historical mission or date range
   - Store in separate cache pool
   - Longer TTL (e.g., 24 hours) for historical data
   - **Never load on startup** - only on user request

4. **Cache Key Enhancement**
   - Add `is_historical` flag to cache keys
   - Add `data_source_path` to distinguish realtime vs past missions
   - Different eviction policies per pool

### Phase 3: Persistence (Long-term)
1. **Disk-Based Cache**
   - SQLite for cache metadata
   - Parquet files for DataFrame storage
   - Load on startup for active missions only

2. **Cache Warming**
   - Pre-load common queries
   - Background prefetch for likely requests

---

## Implementation Plan for Historical Data

### Requirements
- Historical datasets should NOT load on bootup
- Load only when accessed by user
- Separate from real-time cache
- Support visualization and reporting

### Design

```python
# Separate cache pools
realtime_cache: LRUCache = LRUCache(maxsize=256)  # Active missions from output_realtime_missions
historical_cache: LRUCache = LRUCache(maxsize=128)  # Past missions from output_past_missions

# Determine if mission is historical
def is_historical_mission(mission_id: str) -> bool:
    """Check if mission is in past missions (not in active_realtime_missions)"""
    return mission_id not in settings.active_realtime_missions

# Cache key includes data source path
def create_cache_key(
    report_type: str,
    mission_id: str,
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    data_source_path: str = "output_realtime_missions",  # or "output_past_missions"
    ...
) -> Tuple:
    # Different key structure for historical
    is_historical = data_source_path == "output_past_missions"
    
    if is_historical:
        # Historical keys include full date range (critical for cache hits)
        time_key = (start_date.isoformat(), end_date.isoformat()) if start_date and end_date else "full"
    else:
        # Real-time uses hours_back or recent window
        time_key = f"hours_{hours_back}" if hours_back else "realtime"
    
    return (report_type, mission_id, time_key, data_source_path, ...)

# Enhanced loading logic with source detection
async def _load_from_remote_sources(
    report_type: str,
    mission_id: str,
    current_user: Optional[models.User],
    prefer_historical: bool = False  # Explicit flag for historical requests
) -> Tuple[Optional[pd.DataFrame], str, Optional[datetime]]:
    """Load from remote, trying realtime first, then past missions"""
    base_remote_url = settings.remote_data_url.rstrip("/")
    remote_base_urls_to_try: List[str] = []
    
    # Determine which sources to try
    is_historical_mission = is_historical_mission(mission_id)
    
    if prefer_historical or is_historical_mission:
        # For historical requests, try past missions first
        remote_base_urls_to_try.append(f"{base_remote_url}/output_past_missions")
        # Also try realtime as fallback (in case mission moved)
        remote_base_urls_to_try.append(f"{base_remote_url}/output_realtime_missions")
    else:
        # For real-time requests, try realtime first
        remote_base_urls_to_try.append(f"{base_remote_url}/output_realtime_missions")
        # Try past missions as fallback (for recently completed missions)
        remote_base_urls_to_try.append(f"{base_remote_url}/output_past_missions")
    
    # Try each source in order...
    # (existing retry logic)

# Loading logic with cache pool selection
async def load(
    self,
    report_type: str,
    mission_id: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    is_historical: bool = False,
    ...
):
    # Determine data source and cache pool
    is_historical_mission = is_historical_mission(mission_id)
    prefer_historical = is_historical or is_historical_mission
    
    # Select appropriate cache pool
    if prefer_historical:
        cache = historical_cache
        data_source_path = "output_past_missions"
        # Historical: Load full range (no incremental)
        use_incremental = False
    else:
        cache = realtime_cache
        data_source_path = "output_realtime_missions"
        # Real-time: Use incremental loading
        use_incremental = True
    
    # Create cache key with data source
    cache_key = create_cache_key(
        report_type, mission_id, start_date, end_date,
        data_source_path=data_source_path, ...
    )
    
    # Check cache and load if needed...
```

### Benefits
- Historical data doesn't compete with real-time
- On-demand loading prevents startup delays
- Can implement different retention policies
- Better for reporting/visualization workflows
- Leverages existing `output_past_missions` structure
- Clear separation: realtime vs past mission sources

### Implementation Notes
- **Past missions are already available** at `http://129.173.20.180:8086/output_past_missions/`
- Code currently has this path **commented out** (line 536 in `data_service.py`)
- Need to:
  1. Uncomment and enable `output_past_missions` access
  2. Add logic to detect historical missions
  3. Implement separate cache pools
  4. Add UI controls for accessing historical missions
  5. Ensure historical data never loads on startup

---

## Comparison Matrix

| Feature | Current | Multi-Tier | Redis | Hybrid DB | Time Segments | Enhanced + Polling |
|--------|---------|------------|-------|-----------|---------------|-------------------|
| **Persistence** | ❌ | ✅ | ✅ | ✅ | ❌ | ❌ |
| **Frontend Sync** | ❌ | ❌ | ✅ | ❌ | ❌ | ✅ |
| **Historical Support** | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ |
| **Complexity** | Low | Medium | High | Medium | Medium | Low |
| **External Deps** | None | None | Redis | None | None | None |
| **Scalability** | Single | Single | Multi | Single | Single | Single |
| **Startup Time** | Slow | Fast | Fast | Medium | Slow | Slow |
| **Memory Usage** | Medium | Medium | Low | Medium | Medium | Medium |

---

## Recommendations

### Immediate (Fix Current Bug)
1. ✅ Add cache timestamps to API responses
2. ✅ Implement frontend polling for cache status
3. ✅ Add cache-busting headers
4. ✅ Improve auto-refresh to use API timestamps

### Short-term (Historical Data)
1. ✅ Implement separate cache pools (realtime vs historical)
2. ✅ On-demand loading for historical data
3. ✅ Different eviction policies per pool
4. ✅ Enhanced cache keys with `is_historical` flag

### Long-term (Scalability)
1. ⚠️ Consider disk-based persistence (SQLite + Parquet)
2. ⚠️ Implement cache warming for common queries
3. ⚠️ Add cache metrics and monitoring
4. ⚠️ Consider Redis if multi-server deployment needed

---

## Questions to Consider

1. **How often is historical data accessed?**
   - If rare: On-demand loading is fine
   - If frequent: May need persistence

2. **What's the typical historical data size?**
   - Small: Current approach may work
   - Large: Need disk-based storage

3. **Do you need multi-server support?**
   - Yes: Redis or shared storage
   - No: Current approach sufficient

4. **What's the acceptable startup time?**
   - Fast: Need persistence
   - Acceptable: Current approach OK

5. **How real-time do updates need to be?**
   - Seconds: WebSocket/SSE
   - Minutes: Polling sufficient
   - On-demand: Current approach OK

---

## Summary: Past Missions Integration

### Current State
- **Real-time missions**: `http://129.173.20.180:8086/output_realtime_missions/` ✅ Active
  - Missions: m209, m211 (from config)
  - Cached on startup
  - Background refresh enabled
  
- **Past missions**: `http://129.173.20.180:8086/output_past_missions/` ❌ Disabled
  - Missions: m169, m170, m171, m176, m177, m181, m182, m183, m186, m189, m193, m199, m203, m211, m216, private
  - **Commented out in code** (line 536 in `data_service.py`)
  - Not accessible to users
  - Not cached

### Key Findings
1. **Infrastructure exists**: Past missions directory is available and populated
2. **Code ready**: Path is already in code, just commented out
3. **Separation needed**: Past missions should use separate cache pool
4. **On-demand only**: Historical data must NOT load on startup

### Immediate Actions Required

#### 1. Enable Past Missions Access
```python
# In app/core/data_service.py, line ~536
# Change from:
# f"{base_remote_url}/output_past_missions",  # Commented out

# To:
f"{base_remote_url}/output_past_missions",  # Enable for historical data
```

#### 2. Add Historical Mission Detection
```python
def is_historical_mission(mission_id: str) -> bool:
    """Determine if mission is historical (not in active_realtime_missions)"""
    return mission_id not in settings.active_realtime_missions
```

#### 3. Implement Separate Cache Pools
- Create `historical_cache` separate from `realtime_cache`
- Use different eviction policies
- Historical cache: Longer retention, larger maxsize for reporting

#### 4. Update Loading Logic
- Try `output_realtime_missions` first for active missions
- Fall back to `output_past_missions` if not found
- For explicitly historical requests, try `output_past_missions` first
- Never load past missions during startup cache initialization

### Recommended Implementation Order
1. ✅ **Phase 1**: Fix frontend sync bug (add timestamps, polling)
2. ✅ **Phase 2**: Enable past missions access with separate cache pool
3. ✅ **Phase 3**: Add UI for historical mission selection
4. ⚠️ **Phase 4**: Consider persistence for frequently accessed historical data

