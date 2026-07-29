# Web Folder Audit Report - Phase 1

**Date:** Generated automatically  
**Scope:** All JavaScript files (22) and HTML templates (22) in `web/` folder

---

## Executive Summary

### JavaScript Files (22 total)
- ✅ **19/22** use ES6 modules (86%)
- ⚠️ **3/22** use `apiRequest()` (14%) - **NEEDS STANDARDIZATION**
- ⚠️ **16/22** use `fetchWithAuth()` (73%) - **SHOULD USE `apiRequest()`**
- ⚠️ **6/22** use direct `fetch()` (27%) - **SHOULD USE `apiRequest()`**
- ⚠️ **3/22** use `showToast()` (14%) - **NEEDS STANDARDIZATION**
- ✅ **16/22** use `checkAuth()` (73%)
- ⚠️ **5/22** have `console.log()` statements (23%) - **NEEDS CLEANUP**

### HTML Templates (22 total)
- ✅ **20/22** extend `base.html` (91%) - *2 exceptions are expected (base.html itself, email template)*
- ✅ **21/22** have title block (95%)
- ✅ **21/22** have content block (95%)
- ⚠️ **11/22** have data attributes (50%) - *Some may not need them*

---

## Detailed Findings

### JavaScript Files - Critical Issues

#### 1. API Call Standardization (HIGH PRIORITY)

**Issue:** Most files use `fetchWithAuth()` or direct `fetch()` instead of `apiRequest()`

**Files Using `fetchWithAuth()` (16 files):**
- `admin_announcements.js`
- `admin_mission_overviews.js`
- `admin_user_management.js`
- `dashboard.js`
- `home.js`
- `mission_form.js`
- `my_pic_handoffs.js`
- `view_forms.js`
- `view_pic_handoffs.js`
- `view_station_status.js`
- `wg_vm4.js`

**Files Using Direct `fetch()` (6 files):**
- `api.js` (expected - it's the utility)
- `auth.js` (login endpoint - may be acceptable)
- `dashboard.js` (mixed usage)
- `home.js` (CSV download - may be acceptable)
- `map_generator.js` (needs review)
- `user_settings.js` (needs review)

**Files Using `apiRequest()` (3 files):**
- `admin/scheduler_status.js` ✅
- `auth.js` (partial - for some endpoints)
- `home.js` (partial - for some endpoints)

**Recommendation:**
- Replace `fetchWithAuth()` with `apiRequest()` in all files
- Review direct `fetch()` usage - keep only if unauthenticated or special cases
- Document any exceptions

---

#### 2. Error Handling Standardization (HIGH PRIORITY)

**Issue:** Most files use `console.error()` or manual error handling instead of `showToast()`

**Files Using `showToast()` (3 files):**
- `admin/scheduler_status.js` ✅
- `home.js` (partial)
- `user_settings.js` ✅

**Files Using `console.error()` (14 files):**
- `admin_mission_overviews.js`
- `admin_user_management.js`
- `api.js` (expected - utility function)
- `auth.js` (partial - also has manual error handling)
- `dashboard.js`
- `map_generator.js`
- `mission_form.js`
- `my_pic_handoffs.js`
- `view_forms.js`
- `view_pic_handoffs.js`
- `view_station_status.js`
- `wg_vm4.js`

**Recommendation:**
- Replace `console.error()` with `showToast()` for user-facing errors
- Keep `console.error()` only for debugging (remove in production)
- Use `showToast()` for all user feedback

---

#### 3. ES6 Module Conversion (MEDIUM PRIORITY)

**Issue:** 3 files don't use ES6 modules

**Files Not Using ES6 Modules (3 files):**
- `map_generator.js` - Uses global functions
- `view_forms.js` - Uses global functions (references `checkAuth()` and `fetchWithAuth()`)
- `wg_vm4.js` - Uses global functions

**Recommendation:**
- Convert to ES6 modules
- Add `import` statements for shared utilities
- Update HTML templates to use `type="module"` for script tags

---

#### 4. Debug Code Cleanup (MEDIUM PRIORITY)

**Issue:** 5 files have `console.log()` statements (51 total occurrences)

**Files with `console.log()`:**
- `auth.js` - 1 occurrence
- `dashboard.js` - 38 occurrences (extensive debugging)
- `map_generator.js` - 13 occurrences
- `view_forms.js` - 1 occurrence

**Recommendation:**
- Remove all `console.log()` statements
- Replace with proper logging if needed
- Keep only critical error logging

---

#### 5. Documentation (LOW PRIORITY)

**Issue:** Most files lack JSDoc comments

**Files with JSDoc Comments:**
- `api.js` ✅
- `dashboard.js` (partial)
- `home.js` (partial)
- `map_generator.js` (partial)

**Files Without JSDoc Comments (18 files):**
- All admin files
- All view files
- Most form files
- Most other files

**Recommendation:**
- Add JSDoc comments to all functions
- Document parameters and return types
- Add file-level documentation

---

### HTML Templates - Issues

#### 1. Template Inheritance (MINOR)

**Status:** ✅ Good - 20/22 extend `base.html`

**Exceptions (Expected):**
- `base.html` - Base template itself ✅

**Recommendation:** No action needed

---

#### 2. Data Attributes (LOW PRIORITY)

**Issue:** 11 templates don't have data attributes

**Templates Without Data Attributes:**
- `admin/scheduler_status.html`
- `admin_mission_overviews.html`
- `login.html` (may not need them)
- `my_pic_handoffs.html`
- `register.html` (may not need them)
- `user_settings.html`
- `view_pic_handoffs.html`

**Recommendation:**
- Add data attributes only if JavaScript needs them
- Review each file to determine necessity
- Document which data attributes are required

---

## Priority Matrix

### HIGH PRIORITY (Do First)
1. **Standardize API Calls** - Replace `fetchWithAuth()` with `apiRequest()`
2. **Standardize Error Handling** - Replace `console.error()` with `showToast()`

### MEDIUM PRIORITY (Do Soon)
3. **Convert to ES6 Modules** - Convert 3 files to use modules
4. **Remove Debug Code** - Remove 51 `console.log()` statements

### LOW PRIORITY (Nice to Have)
5. **Add Documentation** - Add JSDoc comments to all files
6. **Add Data Attributes** - Review and add where needed

---

## File-by-File Action Items

### JavaScript Files

#### Critical Updates Needed

1. **`map_generator.js`**
   - [ ] Convert to ES6 modules
   - [ ] Replace `fetch()` with `apiRequest()`
   - [ ] Replace `console.error()` with `showToast()`
   - [ ] Remove 13 `console.log()` statements

2. **`view_forms.js`**
   - [ ] Convert to ES6 modules
   - [ ] Replace `fetchWithAuth()` with `apiRequest()`
   - [ ] Replace `console.error()` with `showToast()`
   - [ ] Remove 1 `console.log()` statement
   - [ ] Add JSDoc comments

3. **`wg_vm4.js`**
   - [ ] Convert to ES6 modules
   - [ ] Replace `fetchWithAuth()` with `apiRequest()`
   - [ ] Replace `console.error()` with `showToast()`
   - [ ] Add JSDoc comments

4. **`dashboard.js`**
   - [ ] Replace `fetch()` and `fetchWithAuth()` with `apiRequest()`
   - [ ] Replace `console.error()` with `showToast()`
   - [ ] Remove 38 `console.log()` statements

5. **All Admin Files** (7 files)
   - [ ] Replace `fetchWithAuth()` with `apiRequest()`
   - [ ] Replace `console.error()` with `showToast()`
   - [ ] Add JSDoc comments

6. **All View Files** (4 files)
   - [ ] Replace `fetchWithAuth()` with `apiRequest()`
   - [ ] Replace `console.error()` with `showToast()`
   - [ ] Add JSDoc comments

7. **Form/User Files** (4 files)
   - [ ] Replace `fetchWithAuth()` with `apiRequest()`
   - [ ] Replace `console.error()` with `showToast()`
   - [ ] Add JSDoc comments

8. **`auth.js`**
   - [ ] Replace `console.error()` with `showToast()` where appropriate
   - [ ] Remove 1 `console.log()` statement
   - [ ] Add JSDoc comments
   - [ ] Review direct `fetch()` usage (login endpoint may be acceptable)

10. **`user_settings.js`**
    - [ ] Replace direct `fetch()` with `apiRequest()` where appropriate
    - [ ] Review if all calls should be authenticated

---

### HTML Templates

#### Minor Updates Needed

1. **Templates Missing Data Attributes** (11 files)
   - [ ] Review if data attributes are needed
   - [ ] Add `data-user-role`, `data-username` if JavaScript needs them
   - [ ] Document which data attributes are required per template

---

## Statistics Summary

### JavaScript Files
- **Total Files:** 22
- **ES6 Modules:** 19 (86%)
- **Using apiRequest():** 3 (14%) ⚠️
- **Using fetchWithAuth():** 16 (73%) ⚠️
- **Using direct fetch():** 6 (27%) ⚠️
- **Using showToast():** 3 (14%) ⚠️
- **Using checkAuth():** 16 (73%) ✅
- **Has console.log():** 5 (23%) ⚠️
- **Has JSDoc:** 4 (18%) ⚠️

### HTML Templates
- **Total Files:** 22
- **Extends base.html:** 20 (91%) ✅
- **Has title block:** 21 (95%) ✅
- **Has content block:** 21 (95%) ✅
- **Has data attributes:** 11 (50%) ⚠️

---

## Recommendations

### Immediate Actions (Phase 2)
1. **Standardize API calls** - Replace `fetchWithAuth()` with `apiRequest()` in all files
2. **Standardize error handling** - Replace `console.error()` with `showToast()` for user feedback
3. **Convert remaining files to ES6 modules** - 3 files need conversion

### Short-term Actions (Phase 3)
4. **Remove debug code** - Remove 51 `console.log()` statements
5. **Add data attributes** - Review and add where JavaScript needs them

### Long-term Actions (Phase 4)
6. **Add JSDoc documentation** - Document all functions
7. **Review and optimize** - Performance and code quality improvements

---

## Next Steps

1. **Review this audit report** - Confirm priorities and approach
2. **Start Phase 2** - Begin standardizing API calls and error handling
3. **Test incrementally** - Test each file after updates
4. **Document exceptions** - Document any files that can't use standard patterns

---

## Related Documentation

- `WEB_FOLDER_STANDARDS.md` - Standards for web folder
- `WEB_FOLDER_REVIEW_PLAN.md` - Review plan and phases
- `CODE_STANDARDS.md` - General coding standards

