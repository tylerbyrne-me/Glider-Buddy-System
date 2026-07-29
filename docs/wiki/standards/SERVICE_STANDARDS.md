# Service Layer Standards

This document defines when and how to create services in the Wave Glider Buddy System.

## Service Layer Purpose

Services contain **business logic** that doesn't belong in routers or core modules. They serve as an intermediary layer between routers (HTTP handling) and core (data access/utilities).

## When to Create a Service

### ✅ Create a Service When:

1. **Complex Business Logic**
   - Operations that require multiple steps or decisions
   - Domain-specific calculations or transformations
   - Logic that spans multiple data sources or core modules

2. **Orchestration**
   - Coordinating multiple core operations
   - Managing complex workflows
   - Handling multi-step processes

3. **Large Router Endpoints**
   - Endpoint logic exceeds ~200 lines
   - Complex processing that would clutter the router
   - Logic that could be reused across multiple endpoints

4. **Domain-Specific Operations**
   - Feature-specific business rules
   - Complex validations beyond Pydantic models
   - Data transformations specific to a domain

### ❌ Do NOT Create a Service When:

1. **Simple CRUD Operations**
   - Use routers directly with database session
   - Example: Create, read, update, delete operations

2. **Data Loading**
   - Use `app.core.data_service` instead
   - Example: Loading mission data, sensor data

3. **Simple Validation**
   - Use Pydantic models for validation
   - Example: Request/response validation

4. **Shared Utilities**
   - Use `app.core.utils` or create new core utilities
   - Example: Date formatting, string manipulation

5. **HTTP Request/Response Handling**
   - Keep in routers
   - Example: Request parsing, response formatting

## Service Structure

### Class-Based Services (Recommended)

Use when service needs to:
- Maintain state (e.g., database session, cached data)
- Have multiple related methods
- Be testable with dependency injection

```python
class YourService:
    def __init__(self, db_session: SQLModelSession):
        self.db_session = db_session
    
    def method1(self, ...):
        """First service method"""
        pass
    
    def method2(self, ...):
        """Second service method"""
        pass
```

### Function-Based Services

Use when service:
- Is stateless
- Has simple, independent operations
- Doesn't need to maintain state

```python
def process_data(db_session: SQLModelSession, input_data: Dict) -> Dict:
    """Standalone service function"""
    pass
```

## Service Standards

### 1. Imports and Dependencies

```python
# Standard imports
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from sqlmodel import Session as SQLModelSession
from pandas import DataFrame

from ..core import models
from ..core.error_handlers import handle_processing_error, ErrorContext
```

### 2. Logging

```python
logger = logging.getLogger(__name__)

class YourService:
    def process_data(self, data: Dict):
        logger.info(f"Processing data: {data}")
        # ... logic ...
        logger.info("Data processed successfully")
```

### 3. Error Handling

Always use `error_handlers` for consistent error responses:

```python
from ..core.error_handlers import handle_processing_error, ErrorContext

try:
    # Your logic
    pass
except ValueError as e:
    raise handle_processing_error(
        operation="processing data",
        error=e,
        context=ErrorContext(
            operation="process_data",
            resource=str(data),
        )
    )
except Exception as e:
    raise handle_processing_error(
        operation="processing data",
        error=e,
        context=ErrorContext(...)
    )
```

### 4. Type Hints

All methods should have complete type hints:

```python
def process_data(
    self,
    input_data: Dict[str, Any],
    mission_id: str,
    options: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Process data with type hints."""
    pass
```

### 5. Documentation

Use Google-style docstrings:

```python
def process_data(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process input data and return results.
    
    Args:
        input_data: Dictionary containing input parameters
            - key1: Description of key1
            - key2: Description of key2
            
    Returns:
        Dictionary with processed results:
            - status: Processing status
            - data: Processed data
            
    Raises:
        HTTPException: If processing fails or validation errors occur
    """
    pass
```

## Service Dependencies

### What Services Can Import

✅ **Allowed:**
- `app.core.*` modules (models, data_service, utils, etc.)
- Other services (with caution to avoid circular dependencies)
- Standard library and third-party packages

❌ **Not Allowed:**
- `app.routers.*` (creates circular dependency)
- `app.app` (creates circular dependency)
- Direct database access (use SQLModelSession passed as parameter)

### Example Service Dependencies

```python
from ..core import models
from ..core.data_service import get_data_service
from ..core.processors import preprocess_telemetry_df
from ..core.error_handlers import handle_processing_error
```

## Using Services in Routers

### Pattern 1: Class-Based Service

```python
from ..services.your_service import YourService

@router.get("/api/endpoint")
async def endpoint(
    mission_id: str,
    session: SQLModelSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    service = YourService(db_session=session)
    result = service.process_data({"mission_id": mission_id})
    return result
```

### Pattern 2: Function-Based Service

```python
from ..services.your_service import process_data_standalone

@router.get("/api/endpoint")
async def endpoint(
    mission_id: str,
    session: SQLModelSession = Depends(get_db_session),
):
    result = process_data_standalone(session, {"mission_id": mission_id})
    return result
```

## Service Examples

### Good Service Example: ErrorAnalysisService

```python
class ErrorAnalysisService:
    """Service for analyzing and tracking error data"""
    
    def __init__(self, db_session: Session):
        self.db_session = db_session
        self.classifier = ErrorClassifier()
    
    def process_error_dataframe(self, error_df: pd.DataFrame, mission_id: str):
        """Complex business logic for error processing"""
        # Orchestrates multiple operations:
        # 1. Preprocess data
        # 2. Classify errors
        # 3. Store in database
        # 4. Calculate statistics
        pass
```

**Why this is a good service:**
- Contains complex business logic
- Orchestrates multiple operations
- Handles domain-specific calculations
- Keeps router clean and focused

### Bad Service Example: Simple CRUD

```python
class UserService:
    def get_user(self, user_id: int):
        """Just a simple database query"""
        return self.db_session.get(User, user_id)
```

**Why this shouldn't be a service:**
- Too simple - just a database query
- Should be in router directly
- No business logic, just data access

## Best Practices

1. **Keep services focused** - One service per domain/feature
2. **Pass dependencies** - Don't import database sessions, pass them as parameters
3. **Use error handlers** - Consistent error responses
4. **Log important operations** - Help with debugging and monitoring
5. **Test services independently** - Services should be testable without routers
6. **Avoid circular dependencies** - Services can import core, but not routers
7. **Document complex logic** - Explain business rules and calculations

## Service Template

See `templates/service_template.py` for a complete service template with examples.

## Related Documentation

- `CODE_STANDARDS.md` - General coding standards
- `DEPENDENCY_INJECTION_STANDARDS.md` - Dependency patterns
- `MODULE_TEMPLATES_README.md` - Template usage guide

