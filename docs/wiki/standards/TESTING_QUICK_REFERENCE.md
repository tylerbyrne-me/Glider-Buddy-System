# Testing Quick Reference
## One-Page Guide for Incremental Testing

---

## 🔄 TESTING WORKFLOW (Repeat for Each Change)

```
1. Make Small Change
   ↓
2. pytest app/ -v          # Run tests
   ↓
3. Manual Smoke Test        # Test in browser/app
   ↓
4. All Pass? ✅            # Commit & Continue
   ↓
5. Something Fails? ❌     # Rollback & Fix
```

---

## 📋 BEFORE EACH CHANGE

```bash
# 1. Ensure current state works
pytest app/ -v

# 2. Start app manually
python -m app.app  # or your start command

# 3. Create checkpoint (optional)
git add -A
git commit -m "checkpoint: before [change description]"
```

---

## ✅ AFTER EACH CHANGE

### Quick Test (30 seconds)
```bash
# 1. Syntax check
python -m py_compile app/path/to/changed_file.py

# 2. Import check
python -c "from app.path import module; print('OK')"

# 3. Run tests
pytest app/ -v --tb=short
```

### Full Test (2-3 minutes)
```bash
# 1. All tests
pytest app/ -v

# 2. Test coverage
pytest app/ --cov=app --cov-report=term

# 3. Manual test
# - Start app
# - Test changed endpoint/feature
# - Verify it works
```

---

## 🧪 TEST COMMANDS

### Run Specific Tests
```bash
# Test single file
pytest tests/test_map_router.py -v

# Test single module
pytest app/routers/ -v

# Test with coverage
pytest app/ --cov=app --cov-report=html

# Test with verbose output
pytest app/ -v -s
```

### Test Import Changes
```bash
# Test imports work
python -c "from app.core.data_service import DataService; print('OK')"

# Test app starts
python -c "from app.app import app; print('App loaded')"
```

---

## 🚨 ROLLBACK COMMANDS

### Quick Rollback
```bash
# Rollback single file
git checkout HEAD -- app/routers/map_router.py

# Rollback last commit (keep changes)
git reset --soft HEAD~1

# Rollback last commit (discard changes)
git reset --hard HEAD~1
```

### Emergency Rollback
```bash
# Switch to backup branch
git checkout backup/pre-refactor-state

# Or restore from main
git checkout main
git pull origin main
```

---

## 📝 TESTING CHECKLIST

### Before Change
- [ ] Current tests pass
- [ ] App starts successfully
- [ ] Manual smoke test passes
- [ ] Backup/checkpoint created

### After Change
- [ ] Code runs (no syntax errors)
- [ ] Imports work
- [ ] Unit tests pass
- [ ] Manual test passes
- [ ] No new errors in logs

### Before Commit
- [ ] All tests pass
- [ ] Functionality unchanged
- [ ] No circular dependencies
- [ ] Code follows standards

---

## 🎯 TESTING PRIORITIES

### Critical Tests (Run Always)
1. **Import Tests**: `python -c "from app.module import X"`
2. **App Startup**: App should start without errors
3. **Basic Functionality**: Changed feature should work

### Important Tests (Run Before Commit)
1. **Full Test Suite**: `pytest app/ -v`
2. **Manual Smoke Test**: Test in browser/app
3. **Integration Test**: Test full flow

### Nice-to-Have Tests (Run Periodically)
1. **Coverage Report**: `pytest --cov=app`
2. **Performance Test**: Compare response times
3. **Load Test**: Test under load (if applicable)

---

## 🔍 COMMON TESTING SCENARIOS

### Testing Router Change
```bash
# 1. Test router imports
python -c "from app.routers.map_router import router; print('OK')"

# 2. Test router endpoint
pytest tests/test_map_router.py -v

# 3. Manual test
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/map/telemetry/m211
```

### Testing Model Change
```bash
# 1. Test model imports
python -c "from app.core.models.database import UserInDB; print('OK')"

# 2. Test model creation
pytest tests/test_models.py -v

# 3. Test database operations
# Run app and test database queries
```

### Testing Service Change
```bash
# 1. Test service imports
python -c "from app.core.data_service import DataService; print('OK')"

# 2. Test service methods
pytest tests/test_data_service.py -v

# 3. Test integration
# Test routers that use the service
```

---

## 📊 TESTING METRICS

### Track These
- **Test Pass Rate**: Should be 100%
- **Test Coverage**: Should not decrease
- **Import Errors**: Should be 0
- **Functionality**: Should remain identical

### Compare
- Before/after test results
- Before/after API responses
- Before/after performance

---

## 🛠️ DEBUGGING TESTS

### Test Verbose Output
```bash
pytest app/ -v -s  # Show print statements
```

### Test Specific Failure
```bash
pytest app/path/to/test.py::test_function -v
```

### Run with Debugger
```bash
pytest app/ --pdb  # Drop into debugger on failure
```

---

## ⚡ QUICK FIXES

### Import Error
```bash
# Check import path
python -c "from app.module import X"

# Fix import path in code
# Re-test
```

### Test Failure
```bash
# Run with verbose output
pytest tests/test_failing.py -v -s

# Check what changed
git diff tests/test_failing.py

# Rollback if needed
git checkout HEAD -- path/to/file.py
```

### App Won't Start
```bash
# Check for syntax errors
python -m py_compile app/app.py

# Check imports
python -c "import app.app; print('OK')"

# Check logs
# Look for error messages
```

---

## 📚 TESTING RESOURCES

### Test Files Location
```
tests/
├── test_core/          # Core module tests
├── test_routers/       # Router tests
└── integration/        # Integration tests
```

### Test Template
See `TEST_TEMPLATE.py` for example test structure

---

**Remember**: Test early, test often, test incrementally! 🧪

