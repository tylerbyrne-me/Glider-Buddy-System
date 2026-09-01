# Forms Folder Standards

## Purpose

The `app/forms/` folder contains **form schema definitions** - the static structure and templates for mission forms. This folder is separate from form submission handling (which is in `app/routers/forms.py`) and form models (which are in `app/core/models/`).

**Submission storage, list vs detail APIs, and interactive retention windows** are documented in [FORM_SUBMISSION_POLICIES.md](./FORM_SUBMISSION_POLICIES.md) (ADR [0006](../../decisions/0006-form-submission-retention-windows.md)). Do not put retention or list-payload rules in this folder-standards file.

## Current State Analysis

### ✅ Still Needed - YES

The forms folder **IS still needed** and serves an important purpose:
- Contains form schema definitions (templates)
- Wave Glider form types in `form_definitions.py`:
  - `pre_deployment_checklist` - Pre-deployment checklist
  - `pic_handoff_checklist` - PIC handoff checklist
- Slocum daily checklist schema in `app/platforms/slocum/checklist_definitions.py` (`slocum_daily_checklist`); WG schemas stay in `form_definitions.py`
- Provides `get_static_form_schema()` / checklist schema helpers used by routers

### Folder Structure

```
app/forms/
├── __init__.py
└── form_definitions.py                 # WG mission form schemas (+ lazy import of Slocum checklist schema)

app/platforms/slocum/
└── checklist_definitions.py            # Slocum daily pilot checklist schema
```

## What Belongs in `app/forms/`

### ✅ **Form Schema Definitions** (Current Content)

**Location:** `app/forms/form_definitions.py`

**Purpose:** Define the static structure of form templates (fields, sections, validation rules)

**Contains:**
- Functions that return form schema objects (`MissionFormSchema`)
- Form type definitions (e.g., "pre_deployment_checklist", "pic_handoff_checklist")
- Static form structure (sections, items, labels, placeholders)
- Form metadata (title, description)

**Example:**
```python
def get_static_form_schema(form_type: str) -> models.MissionFormSchema:
    """Returns the static structure of a form schema."""
    if form_type == "pre_deployment_checklist":
        return models.MissionFormSchema(
            form_type=form_type,
            title="Pre-Deployment Checklist",
            sections=[...]
        )
```

### ✅ **Form Template Utilities** (Future)

**Can Add:**
- Form validation rules specific to form definitions
- Form schema builders/helpers
- Form type registry
- Form versioning utilities

### ✅ **Form Configuration** (Future)

**Can Add:**
- Form feature flags
- Form-specific settings
- Form metadata management

---

## What Does NOT Belong in `app/forms/`

### ❌ **Form Models** → `app/core/models/`

**Reason:** Models are shared across the application and belong in core

**Examples:**
- `FormItem`, `FormSection`, `MissionFormSchema` → `app/core/models/schemas.py`
- `SubmittedForm` → `app/core/models/database.py`
- `FormItemTypeEnum` → `app/core/models/enums.py`

### ❌ **Form Submission Endpoints** → `app/routers/forms.py`

**Reason:** API endpoints belong in routers

**Examples:**
- `POST /api/forms/{mission_id}` → `app/routers/forms.py`
- `GET /api/forms/all` → `app/routers/forms.py`
- `GET /api/forms/{mission_id}/template/{form_type}` → `app/routers/forms.py`

### ❌ **Form Business Logic** → `app/services/` (if complex)

**Reason:** Complex business logic should be in services

**Examples:**
- Form data processing
- Form validation beyond schema
- Form aggregation/analysis

### ❌ **Form Templates (HTML)** → `web/templates/`

**Reason:** HTML templates belong in web templates folder

**Examples:**
- `mission_form.html` → `web/templates/`
- `view_forms.html` → `web/templates/`

### ❌ **Form Storage/Data Access** → `app/core/db.py` or `app/core/crud/`

**Reason:** Database operations belong in core

**Examples:**
- Database queries for `SubmittedForm`
- CRUD operations for forms

### ❌ **Form Data Loading** → `app/core/data_service.py`

**Reason:** Data loading belongs in data service

**Examples:**
- Loading mission data for form autofill
- Data preprocessing for forms

---

## Standards for Forms Folder

### 1. File Organization

**Standard Pattern:**
```
app/forms/
├── __init__.py                    # Exports: get_static_form_schema (if needed)
├── form_definitions.py            # Main form schema definitions
├── form_validators.py             # (Future) Form-specific validation
└── form_registry.py               # (Future) Form type registry
```

### 2. Function Naming

**Standard:**
- `get_static_form_schema(form_type: str)` - Get form schema by type
- `get_form_types()` - Get list of available form types
- `validate_form_schema(schema: MissionFormSchema)` - Validate schema structure
- `register_form_type(form_type: str, schema: MissionFormSchema)` - Register new form type

### 3. Import Standards

**From forms folder:**
```python
from ..forms.form_definitions import get_static_form_schema
```

**Forms folder imports:**
```python
from ..core import models  # Import models, not individual classes
from ..core.models import MissionFormSchema, FormSection, FormItem  # Or specific if needed
```

### 4. Error Handling

**Standard:**
```python
def get_static_form_schema(form_type: str) -> models.MissionFormSchema:
    """Get form schema by type."""
    if form_type == "pre_deployment_checklist":
        return ...
    elif form_type == "pic_handoff_checklist":
        return ...
    
    logger.error(f"Form schema definition not found for form_type: {form_type}")
    raise HTTPException(status_code=404, detail=f"Form type '{form_type}' definition not found.")
```

### 5. Type Hints

**Standard:**
- All functions must have complete type hints
- Use `models.MissionFormSchema` for return types
- Import from `..core.models` for type hints

### 6. Documentation

**Standard:**
- Each form type definition should have a docstring
- Document what the form is used for
- Document required vs optional fields

**Example:**
```python
def get_static_form_schema(form_type: str) -> models.MissionFormSchema:
    """
    Returns the static structure of a form schema, without auto-filled data.
    
    Args:
        form_type: Type identifier for the form (e.g., "pre_deployment_checklist")
        
    Returns:
        MissionFormSchema object containing form structure
        
    Raises:
        HTTPException: If form_type is not found
    """
```

---

## Relationship with Other Modules

### Forms Folder → Core Models
- **Imports:** `from ..core import models`
- **Uses:** `MissionFormSchema`, `FormSection`, `FormItem`, `FormItemTypeEnum`
- **Does NOT:** Define models or database tables

### Forms Folder → Routers
- **Used by:** `app/routers/forms.py`
- **Provides:** `get_static_form_schema()` function
- **Does NOT:** Handle HTTP requests or responses

### Forms Folder → Services
- **Potentially used by:** Form processing services (if created)
- **Provides:** Form schema definitions
- **Does NOT:** Contain business logic

---

## Migration/Consolidation Considerations

### Could Forms Be Moved to Core?

**Option 1: Move to `app/core/forms/`**
- ✅ Pro: Centralizes core functionality
- ❌ Con: Forms are more of a feature than core utility
- ❌ Con: Would mix feature-specific code with core utilities

**Option 2: Keep in `app/forms/`** (RECOMMENDED)
- ✅ Pro: Keeps feature-specific code separate
- ✅ Pro: Easy to find and manage form definitions
- ✅ Pro: Can expand to include form-specific utilities
- ✅ Pro: Clear separation of concerns

**Recommendation:** Keep forms folder in current location (`app/forms/`)

### Could Forms Be Consolidated?

**Currently:**
- Form definitions: `app/forms/form_definitions.py`
- Form models: `app/core/models/`
- Form endpoints: `app/routers/forms.py`

**This separation is GOOD:**
- ✅ Clear separation of concerns
- ✅ Form definitions are feature-specific
- ✅ Models are shared across application
- ✅ Endpoints are HTTP handling

**Recommendation:** Keep current structure

---

## Future Enhancements

### Potential Additions to Forms Folder:

1. **Form Validation Utilities** (`form_validators.py`)
   - Form-specific validation rules
   - Field validation helpers
   - Cross-field validation

2. **Form Registry** (`form_registry.py`)
   - Dynamic form type registration
   - Form type discovery
   - Form metadata management

3. **Form Builders** (`form_builders.py`)
   - Programmatic form schema building
   - Form schema merging
   - Form schema versioning

4. **Form Configuration** (`form_config.py`)
   - Form-specific settings
   - Form feature flags
   - Form metadata

---

## Summary

### ✅ Forms Folder IS Needed

The `app/forms/` folder serves a clear purpose:
- Contains form schema definitions (templates)
- Separates form definitions from form handling
- Provides a clear location for form-related code

### ✅ Current Structure is Appropriate

**Keep:**
- `app/forms/form_definitions.py` - Form schema definitions
- Current separation from models, routers, and core

### ✅ Standards Established

**What belongs in forms/:**
- Form schema definitions ✅
- Form template utilities (future) ✅
- Form configuration (future) ✅

**What does NOT belong in forms/:**
- Form models → `app/core/models/` ❌
- Form endpoints → `app/routers/forms.py` ❌
- Form business logic → `app/services/` ❌
- Form HTML templates → `web/templates/` ❌
- Form data access → `app/core/db.py` ❌

---

## Related Documentation

- [FORM_SUBMISSION_POLICIES.md](./FORM_SUBMISSION_POLICIES.md) — submission retention and list/detail contract
- `CODE_STANDARDS.md` - General coding standards
- `SERVICE_STANDARDS.md` - Service layer guidelines
- `MODULE_TEMPLATES_README.md` - Module templates
- `app/routers/forms.py` - Form submission endpoints
- `app/core/models/schemas.py` - Form models

