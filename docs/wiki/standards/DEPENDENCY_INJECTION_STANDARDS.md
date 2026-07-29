# Dependency Injection Standards

This document defines the standard patterns for dependency injection across all routers.

## Standard Patterns

### 1. Database Session Only
```python
@router.get("/endpoint")
async def endpoint(
    session: SQLModelSession = Depends(get_db_session),
):
    """Endpoint that only needs database access."""
    pass
```

### 2. Authenticated User Only
```python
@router.get("/endpoint")
async def endpoint(
    current_user: User = Depends(get_current_active_user),
):
    """Endpoint that requires authentication but no database."""
    pass
```

### 3. Database + Authenticated User
```python
@router.get("/endpoint")
async def endpoint(
    session: SQLModelSession = Depends(get_db_session),
    current_user: User = Depends(get_current_active_user),
):
    """Most common pattern - database + authenticated user."""
    pass
```

### 4. Admin Only
```python
@router.get("/endpoint")
async def endpoint(
    current_user: User = Depends(get_current_admin_user),
):
    """Admin-only endpoint."""
    pass
```

### 5. Database + Admin
```python
@router.get("/endpoint")
async def endpoint(
    session: SQLModelSession = Depends(get_db_session),
    current_user: User = Depends(get_current_admin_user),
):
    """Admin endpoint with database access."""
    pass
```

### 6. Optional Authentication
```python
@router.get("/endpoint")
async def endpoint(
    current_user: Optional[User] = Depends(get_optional_current_user),
):
    """Endpoint that works for both authenticated and anonymous users."""
    pass
```

## Using Dependency Helpers

For consistency, use the helper functions from `app.core.dependencies`:

```python
from app.core.dependencies import get_session, get_active_user

@router.get("/endpoint")
async def endpoint(
    session: SQLModelSession = get_session(),
    current_user: User = get_active_user(),
):
    """Consistent dependency pattern."""
    pass
```

## Router-Level Dependencies

For routers where all endpoints require the same authentication:

```python
from ..core.auth import get_current_admin_user

router = APIRouter(
    prefix="/api/admin",
    tags=["Admin"],
    dependencies=[Depends(get_current_admin_user)],  # All endpoints require admin
)
```

**Note:** Router-level dependencies apply to ALL endpoints in the router. Use carefully.

## Parameter Order Convention

Standard order for endpoint parameters:
1. Path parameters (e.g., `mission_id: str`)
2. Query parameters (e.g., `hours_back: int = Query(...)`)
3. Request body (e.g., `options: Body(...)`)
4. Dependencies (session, current_user, etc.)

Example:
```python
async def endpoint(
    mission_id: str,  # Path param
    hours_back: int = Query(72),  # Query param
    options: MyModel = Body(...),  # Body
    session: SQLModelSession = Depends(get_db_session),  # Dependency
    current_user: User = Depends(get_current_active_user),  # Dependency
):
    pass
```

## When to Use Which Dependency

### `get_current_active_user`
- **Use for:** Most authenticated endpoints
- **Provides:** Active, authenticated user
- **Rejects:** Disabled users, unauthenticated requests

### `get_current_admin_user`
- **Use for:** Admin-only operations
- **Provides:** Active admin user
- **Rejects:** Non-admin users, disabled users, unauthenticated requests

### `get_optional_current_user`
- **Use for:** Public endpoints that may show different content for logged-in users
- **Provides:** User if authenticated, None otherwise
- **Rejects:** Nothing (always returns None for anonymous)

### `get_db_session`
- **Use for:** Any endpoint that needs database access
- **Provides:** SQLModel database session
- **Note:** Automatically closed after request

## Best Practices

1. **Always use `get_current_active_user` for authenticated endpoints** (not `get_current_user`)
2. **Order dependencies consistently** - session before user
3. **Use router-level dependencies sparingly** - only when ALL endpoints need the same auth
4. **Document any deviations** from standard patterns
5. **Use `CommonDependencies` for consistency** when possible

