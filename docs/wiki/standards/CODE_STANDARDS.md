# Code Standards & Rules
## Quick Reference Guide

This document defines the standards and rules that should be followed when working with core and router modules.

---

## 1. MODULE ARCHITECTURE RULES

### Dependency Direction (CRITICAL)
```
Core → Routers → App
```
- ✅ Core modules can import from other core modules
- ✅ Routers can import from core modules
- ✅ App can import from routers and core
- ❌ **NEVER** import from `app.py` in routers
- ❌ **NEVER** import from routers in core modules

### Module Responsibilities
- **Core**: Business logic, data processing, utilities, models
- **Routers**: HTTP endpoints, request/response handling
- **App**: Application setup, middleware, main entry point

---

## 2. DATA LOADING STANDARDS

### Data Service Pattern
All data loading should go through the data service layer:

```python
# ✅ CORRECT
from ..core.data.data_service import DataService

data_service = DataService()
df, path = await data_service.load_telemetry(mission_id, hours_back=72)

# ❌ WRONG
from ..app import load_data_source  # Circular dependency!
```

### Data Loading Flow
1. **Request** → Router endpoint
2. **Service** → Data service layer (`app/core/data/data_service.py`)
3. **Loader** → Low-level loader (`app/core/data/loaders.py`)
4. **Processor** → Data processor (`app/core/data/processors.py`)
5. **Response** → Return processed data

---

## 3. ERROR HANDLING STANDARDS

### Standard Error Pattern
```python
from ..core.error_handlers import handle_processing_error, ErrorContext
from fastapi import HTTPException
import logging

logger = logging.getLogger(__name__)

@router.get("/api/endpoint")
async def endpoint(...):
    try:
        # Business logic
        result = await service.do_something()
        return result
    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
```

### HTTP Status Codes
- **400**: Bad Request (validation errors, invalid input)
- **401**: Unauthorized (authentication required)
- **403**: Forbidden (authorization failed)
- **404**: Not Found (resource doesn't exist)
- **500**: Internal Server Error (unexpected errors)

### Error Logging
- **WARNING**: Expected errors (validation, missing data)
- **ERROR**: Unexpected errors (with exc_info=True)
- **INFO**: Normal operations (data loading, processing)

---

## 4. DEPENDENCY INJECTION STANDARDS

### Standard Dependency Pattern
```python
from ..core.db import get_db_session, SQLModelSession
from ..core.auth import get_current_active_user
from ..core import models

@router.get("/api/endpoint")
async def endpoint(
    # Path/Query parameters first
    mission_id: str,
    hours_back: int = Query(72),
    
    # Dependencies next
    session: SQLModelSession = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user),
):
    # Endpoint logic
    pass
```

### Dependency Order
1. Path parameters
2. Query parameters
3. Request body (if POST/PUT)
4. Database session
5. Authentication dependencies
6. Other dependencies

---

## 5. MODEL ORGANIZATION STANDARDS

### Model File Structure
```
app/core/models/
├── __init__.py      # Public exports only
├── database.py      # SQLModel tables
├── schemas.py       # Pydantic request/response models
└── enums.py         # Enum definitions
```

### Core Subpackages (post–org review)
```
app/core/
├── auth/            # session auth, security, SQLAdmin auth backends
├── data/            # loaders, processors, data_service, summaries
├── stations/        # VM4 station services, registry policy, ESS waypoints
├── geo/             # map_utils, bathymetry, forecast
├── infra/           # db, scheduler, feature toggles, error handlers
├── models/          # ORM tables and API schemas
└── reporting/       # PDF report pipeline
```

Flat modules at `app/core/` root (e.g. `plotting.py`, `utils.py`, `sync_service.py`, `vessel_categories.py`) remain at the top level. Import moved modules from their subpackage (e.g. `from app.core.data.processors import ...`, `from app.core.infra.db import get_db_session`).

### Model Naming Conventions
- **Database Models**: `UserInDB`, `StationMetadata`, `MissionOverview`
- **Request Models**: `UserCreate`, `StationMetadataUpdate`
- **Response Models**: `UserResponse`, `StationMetadataRead`
- **Enums**: `ReportTypeEnum`, `UserRoleEnum`

### Model Rules
- ✅ Database models inherit from `SQLModel` with `table=True`
- ✅ Request/response models inherit from `BaseModel` (Pydantic)
- ✅ Enums inherit from `str, Enum`
- ❌ No business logic in models
- ❌ No database queries in models

---

## 6. ROUTER STANDARDS

### Router Structure
```python
"""
Module docstring describing the router's purpose.
"""

from fastapi import APIRouter, Depends, HTTPException
from ..core import models
from ..db import get_db_session, SQLModelSession
from ..auth_utils import get_current_active_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["RouterName"])


@router.get("/api/resource/{id}")
async def get_resource(
    id: str,
    session: SQLModelSession = Depends(get_db_session),
    current_user: models.User = Depends(get_current_active_user),
):
    """
    Endpoint docstring describing what it does.
    
    Args:
        id: Resource identifier
        session: Database session
        current_user: Authenticated user
    
    Returns:
        Resource data
    
    Raises:
        HTTPException: 404 if resource not found
    """
    # Implementation
    pass
```

### Router Rules
- ✅ One router per domain/resource
- ✅ Use descriptive endpoint paths (`/api/resource/action`)
- ✅ Include docstrings for all endpoints
- ✅ Use proper HTTP methods (GET, POST, PUT, DELETE)
- ❌ Don't duplicate logic across routers
- ❌ Don't import from `app.py`

---

## 7. DATA PROCESSING STANDARDS

### Processor Pattern
```python
# ✅ CORRECT - Use processor functions
from ..core.processors import preprocess_telemetry_df

df_processed = preprocess_telemetry_df(raw_df)

# ❌ WRONG - Don't duplicate processing logic
def my_endpoint():
    # Don't reimplement preprocessing here
    df = df.rename(columns={...})
    df['Timestamp'] = pd.to_datetime(df['Timestamp'])
    # etc...
```

### Processing Flow
1. Load raw data (via data service)
2. Preprocess data (via processor functions)
3. Apply business logic
4. Return processed data

---

## 8. IMPORT STANDARDS

### Import Order
1. Standard library imports
2. Third-party imports
3. Local application imports
4. Relative imports (within same package)

### Import Example
```python
# Standard library
import logging
from datetime import datetime
from typing import Optional

# Third-party
from fastapi import APIRouter, Depends
from sqlmodel import Session

# Local application
from ..core import models
from ..db import get_db_session
from ..auth_utils import get_current_active_user
```

### Import Rules
- ✅ Use absolute imports when possible
- ✅ Use relative imports for same-package modules
- ✅ Group imports as shown above
- ❌ Don't use wildcard imports (`from module import *`)
- ❌ Don't import from `app.py` in routers

---

## 9. CODE ORGANIZATION STANDARDS

### File Size Limits
- **Maximum**: 500 lines per file
- **Ideal**: 200-300 lines per file
- **Action**: Split files that exceed 500 lines

### Function Size Limits
- **Maximum**: 50 lines per function
- **Ideal**: 20-30 lines per function
- **Action**: Extract logic into helper functions

### Class Size Limits
- **Maximum**: 300 lines per class
- **Ideal**: 100-200 lines per class
- **Action**: Split large classes into smaller classes

---

## 10. TESTING STANDARDS

### Test Organization
- One test file per module
- Test file naming: `test_<module_name>.py`
- Test function naming: `test_<function_name>_<scenario>`

### Test Coverage
- Minimum: 80% coverage for core modules
- Minimum: 70% coverage for routers
- Target: 90% coverage for critical paths

---

## 11. DOCUMENTATION STANDARDS

### Module Docstrings
```python
"""
Brief description of the module's purpose.

This module provides functionality for [purpose].
It handles [key responsibilities].
"""

# Module code...
```

### Function Docstrings
```python
def function_name(param1: str, param2: int) -> dict:
    """
    Brief description of what the function does.
    
    Args:
        param1: Description of param1
        param2: Description of param2
    
    Returns:
        Description of return value
    
    Raises:
        ValueError: When param1 is invalid
    """
    # Implementation
```

### Type Hints
- ✅ Use type hints for all function parameters
- ✅ Use type hints for return values
- ✅ Use `Optional[T]` for nullable values
- ✅ Use `List[T]`, `Dict[K, V]` for collections

---

## 12. COMMON ANTI-PATTERNS TO AVOID

### ❌ Circular Dependencies
```python
# DON'T DO THIS
# In router:
from ..app import load_data_source  # Circular!
```

### ❌ Duplicate Code
```python
# DON'T DO THIS
def endpoint1():
    df = load_data()
    df = df.rename(...)
    df['col'] = pd.to_datetime(df['col'])
    # ... duplicate processing

def endpoint2():
    df = load_data()
    df = df.rename(...)
    df['col'] = pd.to_datetime(df['col'])
    # ... same processing
```

### ❌ Business Logic in Models
```python
# DON'T DO THIS
class User(SQLModel):
    def calculate_hours(self):
        # Business logic doesn't belong in models
        return sum(self.shifts)
```

### ❌ Inconsistent Error Handling
```python
# DON'T DO THIS
def endpoint1():
    try:
        # ...
    except:
        return {}  # Silent failure

def endpoint2():
    try:
        # ...
    except Exception as e:
        raise HTTPException(500, str(e))  # Different pattern
```

---

## 13. CHECKLIST FOR NEW CODE

Before submitting new code, verify:

- [ ] No circular dependencies
- [ ] Follows dependency direction (Core → Routers → App)
- [ ] Uses data service layer for data loading
- [ ] Consistent error handling pattern
- [ ] Proper type hints on all functions
- [ ] Docstrings for all public functions
- [ ] File size < 500 lines
- [ ] Function size < 50 lines
- [ ] No duplicate code
- [ ] Proper logging (INFO, WARNING, ERROR)
- [ ] Appropriate HTTP status codes
- [ ] Tests written for new functionality

---

**Document Version:** 1.0  
**Last Updated:** Initial Creation

