# Web Folder Review Plan

## Overview

This plan outlines the review and standardization process for the `web/` folder, which contains 22 HTML templates and 21 JavaScript files.

## Current State

### Files to Review

**HTML Templates (22 files):**
- `base.html` - Base template ✅ (Review for consistency)
- `_banner.html` - Banner partial ✅
- `_form_details_modal.html` - Modal partial ✅
- `admin/` - 1 admin template
- `email/` - 1 email template
- 17 page templates

**JavaScript Files (21 files):**
- `api.js` - Shared API utilities ✅ (Standard)
- `auth.js` - Authentication utilities ✅ (Standard)
- `admin/` - 1 admin JS file
- 18 page-specific JS files

### Issues Identified

1. **Inconsistent API Usage:**
   - Some files use `apiRequest()` from `api.js` ✅
   - Some files use direct `fetch()` calls ❌

2. **Module System:**
   - Some files use ES6 modules (`import`/`export`) ✅
   - Some files may use script tags ❌

3. **Error Handling:**
   - Some files use `showToast()` ✅
   - Some files use manual error handling ❌

4. **Authentication:**
   - Some files use `checkAuth()` ✅
   - Some files may have manual auth checks ❌

5. **Code Organization:**
   - Inconsistent structure across files
   - May have debug `console.log()` statements

---

## Review Phases

### Phase 1: Audit and Documentation (HIGH PRIORITY)

**Goal:** Understand current state and document standards

**Tasks:**
1. ✅ Create `WEB_FOLDER_STANDARDS.md` - Complete
2. ✅ Create `WEB_FOLDER_REVIEW_PLAN.md` - This document
3. Audit all JavaScript files for:
   - Module usage (ES6 vs script tags)
   - API call patterns (`apiRequest()` vs `fetch()`)
   - Error handling patterns
   - Authentication checks
   - Code organization
4. Audit all HTML templates for:
   - Template inheritance (`extends base.html`)
   - Block usage consistency
   - Data attributes
   - Structure consistency

**Output:**
- Standards document ✅
- Review plan ✅
- Audit report (JavaScript files)
- Audit report (HTML templates)

---

### Phase 2: JavaScript Standardization (HIGH PRIORITY)

**Goal:** Standardize all JavaScript files to use shared utilities

**Tasks:**

#### 2.1 Audit Shared Modules
- [ ] Review `api.js` - ensure it covers all use cases
- [ ] Review `auth.js` - ensure it covers all use cases
- [ ] Document any missing utilities

#### 2.2 Standardize API Calls
- [ ] Identify all files using direct `fetch()`
- [ ] Replace with `apiRequest()` where appropriate
- [ ] Document any exceptions (unauthenticated requests, etc.)

#### 2.3 Standardize Error Handling
- [ ] Identify all manual error handling
- [ ] Replace with `showToast()` where appropriate
- [ ] Ensure consistent error messages

#### 2.4 Standardize Authentication
- [ ] Identify all manual auth checks
- [ ] Replace with `checkAuth()` where appropriate
- [ ] Ensure consistent redirect behavior

#### 2.5 Convert to ES6 Modules
- [ ] Identify files using script tags
- [ ] Convert to ES6 modules (`import`/`export`)
- [ ] Update HTML templates to use `type="module"`

#### 2.6 Code Organization
- [ ] Standardize file structure across all JS files
- [ ] Remove debug `console.log()` statements
- [ ] Add JSDoc comments to functions
- [ ] Ensure consistent naming conventions

**Testing:**
- Test each page after changes
- Verify API calls work correctly
- Verify error handling displays properly
- Verify authentication redirects work

---

### Phase 3: HTML Template Standardization (MEDIUM PRIORITY)

**Goal:** Ensure all templates follow consistent patterns

**Tasks:**

#### 3.1 Template Inheritance
- [ ] Verify all templates extend `base.html`
- [ ] Document any exceptions and why

#### 3.2 Block Usage
- [ ] Audit block usage across templates
- [ ] Ensure consistent block names
- [ ] Document standard block pattern

#### 3.3 Data Attributes
- [ ] Audit data attributes across templates
- [ ] Standardize data attribute names
- [ ] Ensure JavaScript can access needed data

#### 3.4 Structure Consistency
- [ ] Review template structure
- [ ] Ensure consistent layout patterns
- [ ] Document common patterns

**Testing:**
- Visual review of each page
- Verify JavaScript can access data attributes
- Verify responsive design works

---

### Phase 4: Code Quality (MEDIUM PRIORITY)

**Goal:** Improve code quality and maintainability

**Tasks:**

#### 4.1 Remove Debug Code
- [ ] Remove all `console.log()` statements
- [ ] Remove commented-out code
- [ ] Clean up unused variables

#### 4.2 Add Documentation
- [ ] Add JSDoc comments to all functions
- [ ] Add inline comments for complex logic
- [ ] Document any non-standard patterns

#### 4.3 Code Organization
- [ ] Standardize file structure
- [ ] Group related functions
- [ ] Ensure consistent formatting

#### 4.4 Performance
- [ ] Review for performance issues
- [ ] Optimize API calls (batching, caching)
- [ ] Review chart initialization

**Testing:**
- Performance testing
- Code review
- Browser console checks

---

### Phase 5: CSS Review (LOW PRIORITY)

**Goal:** Review and standardize CSS

**Tasks:**

#### 5.1 CSS Variables
- [ ] Audit CSS variable usage
- [ ] Standardize variable names
- [ ] Document theme variables

#### 5.2 Custom CSS
- [ ] Review `custom.css` for consistency
- [ ] Review `themes.css` for completeness
- [ ] Ensure Bootstrap overrides are minimal

#### 5.3 Responsive Design
- [ ] Review responsive breakpoints
- [ ] Test on multiple screen sizes
- [ ] Ensure mobile-first approach

**Testing:**
- Visual review on multiple devices
- Browser compatibility testing

---

## Prioritization Matrix

### High Priority (Do First)
1. ✅ **Create Standards Document** - Complete
2. ✅ **Create Review Plan** - Complete
3. **Audit JavaScript Files** - Identify issues
4. **Standardize API Calls** - Use `apiRequest()`
5. **Standardize Error Handling** - Use `showToast()`
6. **Standardize Authentication** - Use `checkAuth()`

### Medium Priority (Do Soon)
7. **Convert to ES6 Modules** - Modern JavaScript
8. **Standardize HTML Templates** - Consistent structure
9. **Remove Debug Code** - Clean up
10. **Add Documentation** - JSDoc comments

### Low Priority (Nice to Have)
11. **CSS Review** - Styling consistency
12. **Performance Optimization** - Speed improvements
13. **Advanced Features** - Future enhancements

---

## File-by-File Review Checklist

For each JavaScript file:

- [ ] Uses ES6 modules (`import`/`export`)
- [ ] Uses `apiRequest()` for API calls (or documented exception)
- [ ] Uses `showToast()` for error handling
- [ ] Uses `checkAuth()` for authentication (if needed)
- [ ] Has JSDoc comments on functions
- [ ] No debug `console.log()` statements
- [ ] Consistent code organization
- [ ] Consistent naming conventions
- [ ] Matches corresponding HTML template name

For each HTML template:

- [ ] Extends `base.html` (unless partial)
- [ ] Uses consistent block names
- [ ] Includes necessary data attributes
- [ ] Uses semantic HTML
- [ ] Uses Bootstrap classes appropriately
- [ ] Matches corresponding JavaScript file name

---

## Implementation Strategy

### Incremental Approach

1. **Start with High Priority:**
   - Audit all files first
   - Create issue list
   - Fix one file at a time

2. **Test After Each Change:**
   - Test the specific page
   - Verify functionality
   - Check browser console

3. **Document Exceptions:**
   - If a file can't use `apiRequest()`, document why
   - If a file needs special handling, document it

### Testing Strategy

1. **Manual Testing:**
   - Test each page after changes
   - Verify all functionality works
   - Check browser console for errors

2. **Visual Testing:**
   - Review pages visually
   - Check responsive design
   - Verify theme switching works

3. **User Testing:**
   - Test with different user roles
   - Test authentication flows
   - Test error scenarios

---

## Success Criteria

### JavaScript Files
- ✅ All files use ES6 modules
- ✅ All API calls use `apiRequest()` (or documented exception)
- ✅ All error handling uses `showToast()`
- ✅ All authentication uses `checkAuth()`
- ✅ All functions have JSDoc comments
- ✅ No debug code in production

### HTML Templates
- ✅ All templates extend `base.html` (unless partial)
- ✅ Consistent block usage
- ✅ Consistent data attributes
- ✅ Semantic HTML structure

### Overall
- ✅ Consistent code patterns
- ✅ Clear documentation
- ✅ Maintainable structure
- ✅ No breaking changes

---

## Next Steps

1. **Start with Phase 1:**
   - Complete audit of all JavaScript files
   - Complete audit of all HTML templates
   - Create detailed issue list

2. **Begin Phase 2:**
   - Start with high-priority JavaScript files
   - Standardize one file at a time
   - Test after each change

3. **Continue Incrementally:**
   - Work through priority list
   - Test thoroughly
   - Document progress

---

## Related Documentation

- `WEB_FOLDER_STANDARDS.md` - Standards for web folder
- `CODE_STANDARDS.md` - General coding standards
- `app/core/templates.py` - Template configuration

