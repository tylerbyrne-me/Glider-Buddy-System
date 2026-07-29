# Code Review & Consolidation Gameplan
## Core & Router Modules - Phase 1

**Goal**: Streamline and optimize core components and routers for readability, eliminate redundancy, and improve adaptability for adding/removing modules.

---

## 1. STANDARDS & PRINCIPLES

### 1.1 Code Organization Standards
- **Single Responsibility**: Each module should have one clear purpose
- **Dependency Direction**: Core → Routers → App (never reverse)
- **Separation of Concerns**: Data loading, processing, business logic, and routing should be distinct layers
- **DRY Principle**: Eliminate duplicate code and data requests

### 1.2 Import & Dependency Rules
- **No Circular Imports**: Routers should NOT import from `app.py`
- **Explicit Dependencies**: All dependencies should be injected via FastAPI Depends()
- **Centralized Utilities**: Common functionality goes in `app/core/`
- **Module Boundaries**: Clear boundaries between core, routers, and app layers

### 1.3 Error Handling Standards
- **Consistent Patterns**: Standardize error handling across all routers
- **User-Friendly Messages**: Clear error messages without exposing internals
- **Logging**: Structured logging with appropriate levels
- **HTTP Status Codes**: Use appropriate status codes consistently

### 1.4 Data Loading Standards
- **Single Source of Truth**: One function for loading each data type
- **Caching Strategy**: Consistent caching approach across all data types
- **Error Recovery**: Graceful fallback mechanisms
- **Type Safety**: Proper typing for all data operations

---

## 2. CORE MODULES ANALYSIS

### 2.1 Current Structure
```
app/core/
├── models.py              [754 lines] ⚠️ TOO LARGE - Multiple concerns
├── loaders.py             [93 lines] ✅ Good structure
├── processors.py          [672 lines] ⚠️ Some duplication
├── utils.py               [338 lines] ✅ Good utilities
├── map_utils.py           [Unknown size]
├── plotting.py            [Unknown size]
├── summaries.py           [Unknown size]
├── forecast.py            [Unknown size]
├── templates.py           [Unknown size]
├── template_context.py    [Unknown size]
├── security.py            [Unknown size]
├── feature_guards.py     [Unknown size]
├── feature_toggles.py    [Unknown size]
├── error_types.py         [Unknown size]
├── vessel_categories.py   [Unknown size]
├── wg_vm4_payload_parser.py [Unknown size]
└── wg_vm4_station_service.py [Unknown size]
```

### 2.2 Critical Issues Identified

#### **models.py** - MAJOR RESTRUCTURING NEEDED
**Issues:**
- 754 lines - contains models, enums, validation, and business logic
- Mixed concerns: Database models, Pydantic models, validation logic
- Forward declarations scattered throughout
- Duplicate model definitions (StationMetadataBase vs StationMetadataCore)

**Recommendations:**
1. **Split into multiple files:**
   - `models/database.py` - SQLModel tables only
   - `models/schemas.py` - Pydantic request/response models
   - `models/enums.py` - All Enum definitions
   - `models/validation.py` - Field validators and custom validation
2. **Create proper model hierarchy:**
   - Base models → Domain models → API models
3. **Remove business logic** from models (move to services)

#### **processors.py** - MODERATE REFACTORING
**Issues:**
- Duplicate preprocessing patterns across functions
- `_apply_common_processing` is good but could be more generalized
- Some functions have similar structure (timestamp handling, renaming, numeric conversion)

**Recommendations:**
1. **Create a generic processor framework:**
   ```python
   class DataProcessor:
       def __init__(self, config: ProcessorConfig):
           self.config = config
       
       def process(self, df: pd.DataFrame) -> pd.DataFrame:
           # Standard pipeline: timestamp → rename → convert → validate
   ```
2. **Extract common patterns:**
   - Timestamp standardization → `standardize_timestamp_column()`
   - Column renaming → `apply_rename_map()`
   - Numeric conversion → `ensure_numeric_columns()`
   - Validation → `validate_schema()`
3. **Create processor registry** for different report types

#### **loaders.py** - GOOD STRUCTURE
**Issues:**
- Minimal - looks well-structured
- Could benefit from type hints improvement

**Recommendations:**
1. Add comprehensive type hints
2. Consider error handling improvements
3. Document retry logic more clearly

#### **Circular Import Pattern** - CRITICAL
**Issue:** Routers import `load_data_source` from `app.py` to avoid circular imports
```python
# Found in: map_router.py, live_kml_router.py, reporting.py, sensor_csv.py, error_analysis.py
from ..app import load_data_source  # ⚠️ Circular dependency risk
```

**Recommendations:**
1. **Move `load_data_source` to `app/core/data_service.py`**
2. Create a proper data service layer:
   ```python
   # app/core/data_service.py
   class DataService:
       async def load(self, report_type: str, mission_id: str, ...):
           # Centralized data loading logic
   ```
3. Update all routers to import from core instead of app

---

## 3. ROUTER MODULES ANALYSIS

### 3.1 Current Structure
```
app/routers/
├── admin.py
├── announcements.py
├── auth.py
├── error_analysis.py
├── error_analysis_models.py  ⚠️ Models should be in core/models
├── forms.py
├── home.py
├── live_kml_router.py
├── map_router.py
├── missions.py
├── reporting.py
├── sensor_csv.py
└── station_metadata_router.py
```

### 3.2 Critical Issues Identified

#### **Circular Dependencies** - CRITICAL
**Issue:** Multiple routers import from `app.py`:
- `map_router.py` (3 instances)
- `live_kml_router.py` (1 instance)
- `reporting.py` (1 instance)
- `sensor_csv.py` (1 instance)
- `error_analysis.py` (2 instances)

**Impact:**
- Makes testing difficult
- Tight coupling between routers and app
- Prevents modular architecture

**Solution:**
1. Move `load_data_source` to `app/core/data_service.py`
2. Create service layer for data operations
3. Update all routers to use new service

#### **Duplicate Data Loading Patterns** - HIGH PRIORITY
**Examples:**
```python
# Pattern repeated in map_router.py, live_kml_router.py, reporting.py
df, source_path = await load_data_source(
    "telemetry",
    mission_id,
    source_preference=None,
    custom_local_path=None,
    force_refresh=False,
    current_user=current_user,
    hours_back=hours_back
)
# Then immediate preprocessing
processed_df = preprocess_telemetry_df(df)
```

**Recommendations:**
1. **Create helper functions** in data service:
   ```python
   async def load_and_preprocess_telemetry(mission_id, hours_back, ...):
       df, path = await load_data_source(...)
       return preprocess_telemetry_df(df), path
   ```
2. **Create data loading decorators** for common patterns
3. **Batch loading utilities** for multiple data types

#### **Inconsistent Error Handling** - MODERATE
**Issues:**
- Some routers use try/except with HTTPException
- Some return empty DataFrames
- Some log errors, some don't
- Inconsistent error messages

**Recommendations:**
1. **Create error handling utilities:**
   ```python
   # app/core/errors.py
   def handle_data_error(e: Exception, context: str) -> HTTPException:
       logger.error(f"{context}: {e}")
       return HTTPException(status_code=500, detail=f"Error: {context}")
   ```
2. **Standardize error responses:**
   - 404 for missing data
   - 500 for processing errors
   - 400 for validation errors
3. **Create error handling decorator** for routers

#### **Inconsistent Dependency Patterns** - MODERATE
**Issues:**
- Some endpoints use `Depends(get_db_session)` explicitly
- Some use `Depends(get_current_active_user)` 
- Some use both inconsistently
- Some routers have router-level dependencies

**Recommendations:**
1. **Standardize dependency injection:**
   ```python
   # Standard pattern for all endpoints
   async def endpoint(
       session: SQLModelSession = Depends(get_db_session),
       current_user: models.User = Depends(get_current_active_user),
       ...
   ):
   ```
2. **Document dependency requirements** per endpoint
3. **Create dependency aliases** for common combinations

#### **Code Duplication in map_router.py** - HIGH PRIORITY
**Issue:** `get_mission_track` and `get_multiple_mission_tracks` have nearly identical logic

**Recommendations:**
1. Extract common logic to helper function
2. Use single endpoint with optional multi-mission support
3. Create shared data preparation function

---

## 4. RESTRUCTURING PLAN

### Phase 1: Core Module Restructuring

#### Step 1.1: Split models.py
**Target:** Break into logical modules
- Create `app/core/models/` directory
- Move database models to `database.py`
- Move Pydantic models to `schemas.py`
- Move enums to `enums.py`
- Update all imports

**Estimated Impact:** High - touches many files

#### Step 1.2: Create Data Service Layer
**Target:** Eliminate circular dependencies
- Create `app/core/data_service.py`
- Move `load_data_source` from `app.py` to data service
- Create service class with proper methods
- Update all router imports

**Estimated Impact:** High - eliminates circular dependencies

#### Step 1.3: Refactor Processors
**Target:** Create generic processor framework
- Create `ProcessorConfig` dataclass
- Create base `DataProcessor` class
- Refactor existing processors to use framework
- Maintain backward compatibility

**Estimated Impact:** Medium - improves maintainability

### Phase 2: Router Module Optimization

#### Step 2.1: Eliminate Circular Dependencies
**Target:** Update all routers to use data service
- Update `map_router.py`
- Update `live_kml_router.py`
- Update `reporting.py`
- Update `sensor_csv.py`
- Update `error_analysis.py`

**Estimated Impact:** High - enables modular architecture

#### Step 2.2: Consolidate Duplicate Code
**Target:** Extract common patterns
- Create data loading helpers
- Extract error handling patterns
- Create shared response builders
- Consolidate duplicate preprocessing calls

**Estimated Impact:** Medium - reduces maintenance burden

#### Step 2.3: Standardize Error Handling
**Target:** Consistent error handling across routers
- Create error handling utilities
- Add error handling decorator
- Standardize error responses
- Update all routers

**Estimated Impact:** Medium - improves user experience

### Phase 3: Documentation & Standards

#### Step 3.1: Create Architecture Documentation
- Document module boundaries
- Document dependency rules
- Create developer guidelines
- Document data flow

#### Step 3.2: Create Module Templates
- Router template
- Service template
- Model template
- Test template

---

## 5. PRIORITY MATRIX

### CRITICAL (Do First)
1. ✅ Move `load_data_source` to core (eliminate circular dependencies)
2. ✅ Split `models.py` into logical modules
3. ✅ Update all routers to use new data service

### HIGH PRIORITY (Do Next)
4. ✅ Consolidate duplicate data loading patterns
5. ✅ Extract common error handling
6. ✅ Refactor `map_router.py` duplicate code

### MEDIUM PRIORITY (Do Soon)
7. ⚠️ Create generic processor framework
8. ⚠️ Standardize dependency injection patterns
9. ⚠️ Create module templates

### LOW PRIORITY (Nice to Have)
10. ⚠️ Add comprehensive type hints
11. ⚠️ Improve documentation
12. ⚠️ Create developer guidelines

---

## 6. SPECIFIC AREAS NEEDING RESTRUCTURING

### 6.1 models.py - Immediate Action Required
**Current State:** 754 lines, mixed concerns
**Proposed Structure:**
```
app/core/models/
├── __init__.py           # Public exports
├── database.py           # SQLModel tables
├── schemas.py            # Pydantic request/response models
├── enums.py              # All Enum definitions
└── validation.py         # Field validators
```

**Migration Strategy:**
1. Create new directory structure
2. Move models incrementally (test after each move)
3. Update imports gradually
4. Remove old models.py after migration complete

### 6.2 Data Loading Architecture
**Current State:** Function in `app.py`, imported by routers (circular)
**Proposed Structure:**
```
app/core/
├── data_service.py       # Main data service
├── loaders.py            # Low-level loaders (keep as-is)
└── cache/                # Caching logic (if needed)
    ├── __init__.py
    └── strategies.py
```

**Migration Strategy:**
1. Create `data_service.py` with `DataService` class
2. Move `load_data_source` logic to service
3. Update one router at a time
4. Test thoroughly after each router update

### 6.3 Router Error Handling
**Current State:** Inconsistent patterns
**Proposed Structure:**
```
app/core/
└── errors.py             # Error handling utilities
    ├── handlers.py       # Error handlers
    ├── exceptions.py     # Custom exceptions
    └── decorators.py     # Error handling decorators
```

---

## 7. METRICS & SUCCESS CRITERIA

### Code Quality Metrics
- **Circular Dependencies:** 0 (currently 5+)
- **Code Duplication:** < 5% (currently ~15-20%)
- **Module Size:** < 500 lines per file (models.py currently 754)
- **Import Depth:** < 3 levels

### Architecture Metrics
- **Dependency Direction:** Core → Routers → App (unidirectional)
- **Service Layer:** All data operations go through service layer
- **Error Handling:** 100% consistent across routers

### Maintainability Metrics
- **Test Coverage:** Increase coverage for refactored modules
- **Documentation:** All modules have docstrings
- **Type Hints:** 100% type coverage for public APIs

---

## 8. RISK MITIGATION

### Risks
1. **Breaking Changes:** Refactoring may break existing functionality
2. **Migration Complexity:** Large codebase requires careful migration
3. **Testing Gaps:** Need comprehensive testing after refactoring

### Mitigation Strategies
1. **Incremental Migration:** One module/router at a time
2. **Comprehensive Testing:** Test after each change
3. **Backward Compatibility:** Maintain compatibility during transition
4. **Version Control:** Use feature branches for each refactoring step

---

## 9. NEXT STEPS

1. **Review & Approve:** Review this gameplan with team
2. **Start Phase 1:** Begin with critical items (circular dependencies)
3. **Create Branch:** Create feature branch for refactoring
4. **Incremental Changes:** Make small, testable changes
5. **Document Progress:** Update gameplan as work progresses

---

## 10. QUESTIONS TO ANSWER

Before starting implementation:
1. Can we break models.py into multiple files immediately?
2. Should we create a service layer or keep functions?
3. What's the testing strategy for refactored code?
4. Do we need to maintain backward compatibility?
5. What's the timeline for this refactoring?

---

**Document Version:** 1.0  
**Last Updated:** Initial Creation  
**Status:** Planning Phase

