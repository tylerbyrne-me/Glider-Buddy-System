# Incremental Testing Strategy
## Safe Refactoring with Continuous Validation

This document outlines a step-by-step testing approach to ensure each modification is validated before moving to the next step.

---

## 1. TESTING PHILOSOPHY

### Core Principles
1. **Test After Each Change**: Never make multiple changes without testing
2. **Maintain Functionality**: Ensure existing features work after each step
3. **Isolated Changes**: One logical change per commit/branch
4. **Rollback Ready**: Each step should be easily reversible
5. **Automated When Possible**: Use tests to catch regressions quickly

---

## 2. PRE-REFACTORING PREPARATION

### Step 0: Baseline Testing (Before Any Changes)

#### 2.1 Create Test Suite Baseline
```bash
# Run existing tests to establish baseline
pytest app/ --cov=app --cov-report=html

# Document current test coverage
# Save test results for comparison
```

#### 2.2 Manual Smoke Tests
Create a checklist of critical user flows:

**Critical Endpoints to Test:**
- [ ] `/api/map/telemetry/{mission_id}` - Map data loading
- [ ] `/api/data/{report_type}/{mission_id}` - Data API
- [ ] `/api/missions/{mission_id}/info` - Mission info
- [ ] `/api/reporting/missions/{mission_id}/generate-weekly-report` - Report generation
- [ ] Dashboard page loads with all sensor cards
- [ ] Login/authentication works
- [ ] Admin functions work

**Test Data:**
- Use a known mission ID (e.g., `m211`)
- Document expected results for comparison

#### 2.3 Create Test Branch
```bash
# Create feature branch for refactoring
git checkout -b refactor/core-consolidation

# Create backup branch
git checkout -b backup/pre-refactor-state
git checkout refactor/core-consolidation
```

#### 2.4 Document Current State
- Note current import patterns
- Document which routers import from `app.py`
- Save current test results

---

## 3. INCREMENTAL TESTING WORKFLOW

### Workflow Template (Repeat for Each Change)

```
1. Make Small Change
   ↓
2. Run Tests (Automated)
   ↓
3. Manual Smoke Test
   ↓
4. Verify No Regressions
   ↓
5. Commit (if passing)
   ↓
6. Move to Next Change
```

---

## 4. PHASE 1: ELIMINATE CIRCULAR DEPENDENCIES

### Step 1.1: Create Data Service Layer (No Router Changes Yet)

#### Change
Create `app/core/data_service.py` with service class structure

#### Testing Steps
```bash
# 1. Create the new file
touch app/core/data_service.py

# 2. Write minimal implementation (just structure, no logic yet)
# 3. Add to __init__.py exports
# 4. Run tests to ensure no import errors
pytest app/core/ -v

# 5. Verify app still starts
python -m app.app  # or however you start the app
```

**Success Criteria:**
- ✅ App starts without errors
- ✅ No import errors
- ✅ Existing functionality unchanged

#### Rollback
```bash
# If something breaks
git checkout app/core/data_service.py
git checkout app/core/__init__.py
```

---

### Step 1.2: Move load_data_source to Data Service

#### Change
Copy `load_data_source` function from `app.py` to `data_service.py`

#### Testing Steps
```python
# 1. Create test file: tests/test_data_service.py
"""
Test data service in isolation
"""
import pytest
from app.core.data_service import DataService

@pytest.mark.asyncio
async def test_load_telemetry_data():
    """Test that data service can load telemetry"""
    service = DataService()
    df, path = await service.load(
        "telemetry",
        "m211",
        hours_back=72
    )
    assert df is not None
    assert not df.empty
```

**Run Tests:**
```bash
# Run new tests
pytest tests/test_data_service.py -v

# Run all tests to ensure nothing broke
pytest app/ -v
```

**Manual Verification:**
```bash
# Start app and test an endpoint manually
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/data/telemetry/m211
```

**Success Criteria:**
- ✅ New tests pass
- ✅ Existing tests still pass
- ✅ Manual endpoint test works
- ✅ Data loading works identically to before

**Rollback:**
```bash
git checkout app/core/data_service.py
```

---

### Step 1.3: Update ONE Router (map_router.py)

#### Change
Update `map_router.py` to import from data service instead of `app.py`

**Before:**
```python
from ..app import load_data_source  # ❌
```

**After:**
```python
from ..core.data_service import DataService  # ✅
```

#### Testing Steps

**1. Create Router-Specific Test:**
```python
# tests/test_map_router.py
import pytest
from fastapi.testclient import TestClient
from app.app import app

client = TestClient(app)

@pytest.mark.asyncio
async def test_get_mission_track():
    """Test map router endpoint"""
    response = client.get(
        "/api/map/telemetry/m211",
        headers={"Authorization": "Bearer test_token"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "track_points" in data
    assert "mission_id" in data
```

**2. Run Tests:**
```bash
# Test the specific router
pytest tests/test_map_router.py -v

# Test all routers
pytest app/routers/ -v

# Full test suite
pytest app/ -v
```

**3. Manual Testing:**
```bash
# Test in browser or with curl
# 1. Open map page
# 2. Verify track loads
# 3. Verify KML download works
# 4. Verify multiple missions endpoint works
```

**4. Integration Test:**
```bash
# Test the full flow
# 1. Start app
# 2. Login
# 3. Navigate to map page
# 4. Select mission
# 5. Verify data loads
# 6. Test KML export
```

**Success Criteria:**
- ✅ Router tests pass
- ✅ Manual testing works
- ✅ No import errors
- ✅ Functionality identical to before
- ✅ Other routers still work (unchanged)

**Rollback:**
```bash
git checkout app/routers/map_router.py
```

**If Tests Pass:**
```bash
# Commit this isolated change
git add app/routers/map_router.py
git commit -m "refactor: Update map_router to use data service (eliminate circular dependency)"
```

---

### Step 1.4: Update Remaining Routers (One at a Time)

Repeat Step 1.3 for each router:
1. `live_kml_router.py`
2. `reporting.py`
3. `sensor_csv.py`
4. `error_analysis.py`

**Testing for Each:**
- Run router-specific tests
- Manual smoke test for that router's endpoints
- Verify other routers still work
- Commit if passing

---

## 5. PHASE 2: SPLIT MODELS.PY

### Step 2.1: Create New Model Structure (No Changes Yet)

#### Change
Create directory structure and empty files

#### Testing Steps
```bash
# 1. Create directory
mkdir -p app/core/models

# 2. Create files
touch app/core/models/__init__.py
touch app/core/models/database.py
touch app/core/models/schemas.py
touch app/core/models/enums.py
touch app/core/models/validation.py

# 3. Verify imports still work
python -c "from app.core import models; print('OK')"

# 4. Run tests
pytest app/ -v
```

**Success Criteria:**
- ✅ App starts
- ✅ No import errors
- ✅ All tests pass

---

### Step 2.2: Move Enums First (Easiest, No Dependencies)

#### Change
Move all Enum classes to `models/enums.py`

#### Testing Steps
```python
# tests/test_enums.py
from app.core.models.enums import ReportTypeEnum, UserRoleEnum

def test_report_type_enum():
    """Test enum values"""
    assert ReportTypeEnum.telemetry == "telemetry"
    assert ReportTypeEnum.power == "power"

def test_user_role_enum():
    """Test user role enum"""
    assert UserRoleEnum.admin == "admin"
    assert UserRoleEnum.pilot == "pilot"
```

**Run Tests:**
```bash
# Test enums
pytest tests/test_enums.py -v

# Test all imports
python -c "from app.core.models.enums import *; print('OK')"

# Full test suite
pytest app/ -v
```

**Manual Check:**
- Start app
- Verify it loads
- Test one endpoint that uses enums

**Success Criteria:**
- ✅ Enum tests pass
- ✅ All imports work
- ✅ App functionality unchanged

**Commit:**
```bash
git add app/core/models/enums.py
git commit -m "refactor: Extract enums to separate module"
```

---

### Step 2.3: Move Database Models

#### Change
Move SQLModel tables to `models/database.py`

#### Testing Steps
```python
# tests/test_database_models.py
from app.core.models.database import UserInDB, StationMetadata
from sqlmodel import SQLModel

def test_user_model():
    """Test UserInDB model"""
    user = UserInDB(
        username="test",
        hashed_password="hash",
        email="test@example.com"
    )
    assert user.username == "test"

def test_station_metadata_model():
    """Test StationMetadata model"""
    station = StationMetadata(station_id="CBS001")
    assert station.station_id == "CBS001"
```

**Run Tests:**
```bash
# Test database models
pytest tests/test_database_models.py -v

# Test database operations
pytest app/db.py -v  # if you have db tests

# Full test suite
pytest app/ -v
```

**Manual Database Test:**
```python
# Create a test script: test_db_models_manual.py
from app.db import get_db_session
from app.core.models.database import UserInDB

def test_db_operations():
    session = next(get_db_session())
    # Try to query
    users = session.query(UserInDB).all()
    print(f"Found {len(users)} users")
```

**Success Criteria:**
- ✅ Model tests pass
- ✅ Database operations work
- ✅ All tests pass
- ✅ App starts and works

**Commit:**
```bash
git add app/core/models/database.py
git commit -m "refactor: Extract database models to separate module"
```

---

### Step 2.4: Move Pydantic Schemas

Repeat process for schemas (request/response models)

---

## 6. PHASE 3: CONSOLIDATE DUPLICATE CODE

### Step 3.1: Extract Common Data Loading Helper

#### Change
Create helper function in data service for common pattern:
```python
async def load_and_preprocess_telemetry(mission_id, hours_back, ...):
    df, path = await self.load(...)
    return preprocess_telemetry_df(df), path
```

#### Testing Steps

**1. Create Test:**
```python
# tests/test_data_service_helpers.py
@pytest.mark.asyncio
async def test_load_and_preprocess_telemetry():
    service = DataService()
    df, path = await service.load_and_preprocess_telemetry(
        "m211", hours_back=72
    )
    assert df is not None
    assert "Latitude" in df.columns
    assert "Longitude" in df.columns
    assert "Timestamp" in df.columns
```

**2. Update Router to Use Helper:**
```python
# In map_router.py
df, path = await data_service.load_and_preprocess_telemetry(
    mission_id, hours_back
)
```

**3. Test Router:**
```bash
pytest tests/test_map_router.py -v
```

**4. Manual Test:**
- Verify map endpoint still works
- Compare response to previous version

**Success Criteria:**
- ✅ Helper function works
- ✅ Router uses helper
- ✅ Functionality identical
- ✅ Code is cleaner

---

## 7. CONTINUOUS TESTING STRATEGY

### 7.1 Automated Tests

**Unit Tests** (run on every change):
```bash
# Quick unit tests
pytest app/core/ -v --tb=short

# Full unit test suite
pytest app/ -v
```

**Integration Tests** (run before commit):
```bash
# Full test suite with coverage
pytest app/ --cov=app --cov-report=term-missing

# Integration tests
pytest tests/integration/ -v
```

### 7.2 Manual Testing Checklist

Create a checklist that you run after each major change:

**After Each Router Update:**
- [ ] App starts without errors
- [ ] Router endpoint responds (200, 404, or appropriate status)
- [ ] Data loads correctly
- [ ] Error handling works (test invalid inputs)
- [ ] Authentication works (test with/without token)

**After Model Changes:**
- [ ] App starts
- [ ] Database queries work
- [ ] API endpoints that use models work
- [ ] Validation works

**After Data Service Changes:**
- [ ] Data loads correctly
- [ ] Caching works (if applicable)
- [ ] Error handling works
- [ ] All routers using service work

### 7.3 Regression Testing

**Before Each Commit:**
```bash
# Run full test suite
pytest app/ -v

# Check test coverage didn't decrease
pytest app/ --cov=app --cov-report=html
# Compare coverage report to baseline
```

**Compare Functionality:**
- Use same test data/mission ID
- Compare API responses before/after
- Verify response structure unchanged

---

## 8. TESTING TOOLS & SETUP

### 8.1 Test Structure
```
tests/
├── conftest.py           # Shared fixtures
├── test_core/
│   ├── test_data_service.py
│   ├── test_processors.py
│   └── test_models.py
├── test_routers/
│   ├── test_map_router.py
│   ├── test_reporting.py
│   └── test_missions.py
└── integration/
    └── test_full_flows.py
```

### 8.2 Test Fixtures
```python
# tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from app.app import app

@pytest.fixture
def client():
    """Test client fixture"""
    return TestClient(app)

@pytest.fixture
def test_mission_id():
    """Standard test mission ID"""
    return "m211"

@pytest.fixture
def authenticated_client(client):
    """Client with authentication"""
    # Setup auth token
    token = "test_token"  # Get from test user
    client.headers = {"Authorization": f"Bearer {token}"}
    return client
```

### 8.3 Test Data
```python
# tests/fixtures/test_data.py
TEST_MISSION_ID = "m211"
TEST_STATION_ID = "CBS001"

# Create test data files if needed
```

---

## 9. VERIFICATION CHECKLIST

### Before Making Each Change
- [ ] Current tests pass
- [ ] App runs successfully
- [ ] Manual smoke tests pass
- [ ] Created backup branch

### After Making Each Change
- [ ] Code runs without syntax errors
- [ ] No import errors
- [ ] Unit tests pass
- [ ] Integration tests pass (if applicable)
- [ ] Manual smoke test passes
- [ ] No new warnings/errors in logs

### Before Committing
- [ ] All tests pass
- [ ] Code follows standards
- [ ] No circular dependencies introduced
- [ ] Documentation updated (if needed)
- [ ] Changes are isolated and reversible

### After Committing
- [ ] Can rollback if needed
- [ ] Changes documented in commit message
- [ ] Ready for next incremental change

---

## 10. ROLLBACK PROCEDURES

### Quick Rollback (Single File)
```bash
# Rollback specific file
git checkout HEAD -- app/routers/map_router.py

# Verify app works
python -m app.app
```

### Rollback Last Commit
```bash
# Soft rollback (keep changes)
git reset --soft HEAD~1

# Hard rollback (discard changes)
git reset --hard HEAD~1
```

### Rollback to Branch
```bash
# Switch to backup branch
git checkout backup/pre-refactor-state

# Or create new branch from backup
git checkout -b recovery/from-backup backup/pre-refactor-state
```

### Emergency Rollback
```bash
# If production is broken
git checkout main
git pull origin main
# Deploy previous working version
```

---

## 11. TESTING TEMPLATES

### Template: Testing a Router Change
```python
# tests/test_router_change.py
"""
Test template for router changes
"""
import pytest
from fastapi.testclient import TestClient
from app.app import app

client = TestClient(app)

def test_router_endpoint_basic():
    """Test basic endpoint functionality"""
    response = client.get("/api/endpoint/test_id")
    assert response.status_code in [200, 401, 404]  # Expected statuses
    
def test_router_endpoint_with_auth():
    """Test endpoint with authentication"""
    token = "test_token"
    response = client.get(
        "/api/endpoint/test_id",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200

def test_router_endpoint_error_handling():
    """Test error handling"""
    response = client.get("/api/endpoint/invalid_id")
    assert response.status_code in [400, 404, 500]
```

### Template: Testing a Model Change
```python
# tests/test_model_change.py
"""
Test template for model changes
"""
import pytest
from app.core.models.database import TestModel

def test_model_creation():
    """Test model can be created"""
    obj = TestModel(field1="value1")
    assert obj.field1 == "value1"

def test_model_validation():
    """Test model validation"""
    # Test valid data
    obj = TestModel(field1="valid")
    assert obj.field1 == "valid"
    
    # Test invalid data (should raise ValidationError)
    with pytest.raises(ValueError):
        TestModel(field1="invalid")
```

### Template: Testing a Service Change
```python
# tests/test_service_change.py
"""
Test template for service changes
"""
import pytest
from app.core.data_service import DataService

@pytest.mark.asyncio
async def test_service_method():
    """Test service method"""
    service = DataService()
    result = await service.method("test_param")
    assert result is not None
```

---

## 12. EXAMPLE: COMPLETE ITERATION

### Example: Updating map_router.py

**Step 1: Create Test First**
```bash
# Create test file
touch tests/test_map_router_refactor.py
```

**Step 2: Write Test**
```python
# tests/test_map_router_refactor.py
import pytest
from fastapi.testclient import TestClient
from app.app import app

client = TestClient(app)

def test_map_telemetry_endpoint():
    """Test map telemetry endpoint"""
    response = client.get(
        "/api/map/telemetry/m211",
        headers={"Authorization": "Bearer test_token"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "track_points" in data
    assert "mission_id" in data
    assert data["mission_id"] == "m211"
```

**Step 3: Run Test (Should Pass)**
```bash
pytest tests/test_map_router_refactor.py -v
```

**Step 4: Make Change**
```python
# In map_router.py
# Change: from ..app import load_data_source
# To: from ..core.data_service import DataService
```

**Step 5: Update Code**
```python
# In map_router.py
data_service = DataService()
df, path = await data_service.load(...)
```

**Step 6: Run Test Again**
```bash
pytest tests/test_map_router_refactor.py -v
# Should still pass
```

**Step 7: Manual Test**
- Open browser
- Navigate to map page
- Verify it works

**Step 8: Commit if All Pass**
```bash
git add app/routers/map_router.py
git commit -m "refactor: Update map_router to use data service"
```

---

## 13. MONITORING & METRICS

### Track These Metrics
- **Test Coverage**: Should not decrease
- **Test Execution Time**: Should not significantly increase
- **Import Errors**: Should be zero
- **Functionality**: Should remain identical

### Compare Before/After
- API response times
- Memory usage
- Error rates
- Test pass rates

---

## 14. SUCCESS CRITERIA

### Phase Complete When:
- ✅ All automated tests pass
- ✅ All manual smoke tests pass
- ✅ No circular dependencies
- ✅ Code is cleaner/more maintainable
- ✅ Functionality unchanged
- ✅ Performance not degraded
- ✅ Ready for next phase

---

**Document Version:** 1.0  
**Last Updated:** Initial Creation  
**Status:** Ready for Use

