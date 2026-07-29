# Module Templates Guide

This directory contains templates for creating new modules following the project's standards.

## Available Templates

### 1. Router Template (`router_template.py`)

Use this template when creating a new API router.

**Location:** `app/routers/your_module.py`

**Features:**
- Standardized imports (error handlers, dependencies, data service)
- Example GET, POST, and path parameter endpoints
- Proper error handling with standardized functions
- Consistent dependency injection patterns
- Logging setup

**Usage:**
1. Copy `templates/router_template.py` to `app/routers/your_module.py`
2. Replace `[MODULE_NAME]`, `[module_name]`, `[Module Name]` placeholders
3. Update endpoint paths, models, and logic
4. Register router in `app/app.py`:
   ```python
   from .routers import your_module as your_module_router
   app.include_router(your_module_router.router)
   ```

**Key Standards:**
- Use `get_session()`, `get_active_user()` from `app.core.dependencies`
- Use `handle_processing_error()`, `handle_validation_error()`, `handle_data_not_found()` for errors
- Use `get_data_service()` for data loading
- Follow parameter order: path → query → body → dependencies

### 2. Core Module Template (`core_module_template.py`)

Use this template when creating a new core utility module.

**Location:** `app/core/your_module.py`

**Features:**
- Standard logging setup
- Type hints for all functions
- Docstrings following Google style
- Error handling patterns
- Example sync and async functions
- Example class structure

**Usage:**
1. Copy `templates/core_module_template.py` to `app/core/your_module.py`
2. Replace placeholders with your module name
3. Implement your functionality
4. Export from `app/core/__init__.py` if needed:
   ```python
   from . import your_module
   __all__ = [..., "your_module"]
   ```

**Key Standards:**
- Use `logger = logging.getLogger(__name__)` for logging
- Include type hints for all parameters and return values
- Write comprehensive docstrings
- Handle errors appropriately (ValueError for validation, Exception for unexpected)
- Use `_private_helper` naming convention for private functions

### 3. Processor Template (`processor_template.py`)

Use this template when creating a new data processor.

**Location:** `app/core/processors.py` (add function) or `app/core/your_processor.py`

**Features:**
- Standard preprocessing pipeline
- Uses `apply_common_processing()` from `processor_utils`
- Column renaming and numeric conversion
- Custom processing section

**Usage:**
1. Copy the function from `templates/processor_template.py`
2. Add to `app/core/processors.py` or create new processor module
3. Replace `[data_type]` with your data type name
4. Define `rename_map` and `numeric_cols`
5. Add custom processing if needed
6. Register in `app/core/processors.py`:
   ```python
   _processor_registry.register("your_type", preprocess_your_type_df)
   ```

**Key Standards:**
- Use `timestamp_col = "Timestamp"` for standard timestamp column
- Define `rename_map` for column standardization
- List numeric columns in `numeric_cols`
- Use `apply_common_processing()` for standard pipeline
- Add custom processing after common processing

## Template Customization Checklist

When using a template, make sure to:

- [ ] Replace all `[MODULE_NAME]`, `[module_name]`, `[Module Name]` placeholders
- [ ] Update docstrings with actual descriptions
- [ ] Remove example code and implement real functionality
- [ ] Update imports to match your needs
- [ ] Add proper type hints
- [ ] Follow error handling patterns
- [ ] Use standardized dependencies (from `app.core.dependencies`)
- [ ] Use standardized error handlers (from `app.core.error_handlers`)
- [ ] Register router/processor as needed
- [ ] Test the new module

## Quick Start Example

**Creating a new router:**

```bash
# 1. Copy template
cp templates/router_template.py app/routers/my_feature.py

# 2. Edit and replace placeholders
# [MODULE_NAME] → MyFeature
# [module_name] → my_feature
# [Module Name] → My Feature

# 3. Implement your endpoints

# 4. Register in app/app.py
from .routers import my_feature as my_feature_router
app.include_router(my_feature_router.router)
```

**Creating a new core module:**

```bash
# 1. Copy template
cp templates/core_module_template.py app/core/my_utils.py

# 2. Edit and implement functionality

# 3. Export from app/core/__init__.py (optional)
from . import my_utils
```

## Best Practices

1. **Follow Naming Conventions:**
   - Routers: `snake_case.py` (e.g., `sensor_csv.py`)
   - Core modules: `snake_case.py` (e.g., `map_utils.py`)
   - Functions: `snake_case` (e.g., `get_data()`)
   - Classes: `PascalCase` (e.g., `DataProcessor`)

2. **Import Order:**
   - Standard library imports
   - Third-party imports (pandas, fastapi, etc.)
   - Local application imports (from ..core import ...)

3. **Error Handling:**
   - Use standardized error handlers from `app.core.error_handlers`
   - Log errors appropriately (warning for expected, error for unexpected)
   - Re-raise HTTPException from error handlers

4. **Dependencies:**
   - Use `get_session()`, `get_active_user()` from `app.core.dependencies`
   - Don't import from `app.py` in routers
   - Use `get_data_service()` for data loading

5. **Documentation:**
   - Write docstrings for all public functions
   - Include Args, Returns, Raises sections
   - Add examples for complex functions

### 4. Service Template (`service_template.py`)

Use this template when creating a new business logic service.

**Location:** `app/services/your_service.py`

**Features:**
- Class-based service pattern (recommended)
- Function-based service pattern (alternative)
- Error handling with error_handlers
- Database session management
- Type hints and documentation

**Usage:**
1. Copy `templates/service_template.py` to `app/services/your_service.py`
2. Replace `YourService` with your service name
3. Implement your business logic
4. Use in routers by instantiating the service:
   ```python
   from ..services.your_service import YourService
   
   service = YourService(db_session=session)
   result = service.process_data(data)
   ```

**Key Standards:**
- Use `handle_processing_error()` for error handling
- Pass `db_session` as parameter to `__init__`
- Use `ErrorContext` for structured error context
- Log important operations
- See `SERVICE_STANDARDS.md` for detailed guidelines

## Related Documentation

- `CODE_STANDARDS.md` - General coding standards
- `DEPENDENCY_INJECTION_STANDARDS.md` - Dependency patterns
- `SERVICE_STANDARDS.md` - Service layer guidelines and when to create services
- `CODE_REVIEW_GAMEPLAN.md` - Architecture overview

