# MCP Test Suite Maintenance Guide

**Last Updated**: November 15, 2025  
**Maintainers**: Agentic Inquiry Development Team

## Overview

This guide provides comprehensive instructions for maintaining the MCP test suite, including common issues, fixes, best practices, and troubleshooting procedures.

## Table of Contents

1. [Daily Maintenance](#daily-maintenance)
2. [Common Issues and Fixes](#common-issues-and-fixes)
3. [Test Lifecycle](#test-lifecycle)
4. [Debugging Procedures](#debugging-procedures)
5. [Performance Monitoring](#performance-monitoring)
6. [Documentation Updates](#documentation-updates)
7. [Release Checklist](#release-checklist)

---

## Daily Maintenance

### Morning Routine

1. **Check Test Status**
   ```bash
   # Run full test suite
   uv run pytest tests/mcp/ -v
   
   # Check for new failures
   uv run pytest tests/mcp/ --lf  # Last failed
   ```

2. **Review Test Output**
   - Check pass rate (target: >95%)
   - Identify new failures
   - Review warnings
   - Check execution time

3. **Triage Failures**
   - Legitimate bugs → Create GitHub issues
   - Test issues → Fix immediately
   - Flaky tests → Investigate and stabilize
   - Known issues → Update documentation

### Weekly Tasks

1. **Coverage Review**
   ```bash
   uv run pytest tests/mcp/ --cov=agentic_inquiry.mcp --cov-report=html
   open htmlcov/index.html
   ```

2. **Performance Check**
   ```bash
   uv run pytest tests/mcp/ --durations=10
   ```

3. **Documentation Update**
   - Update README.md with any changes
   - Update KNOWN_LIMITATIONS.md
   - Review and update this guide

4. **Cleanup**
   - Remove obsolete tests
   - Archive old test data
   - Clean up temporary files

### Monthly Tasks

1. **Test Health Review**
   - Analyze test trends
   - Identify flaky tests
   - Review test coverage gaps
   - Plan improvements

2. **Dependency Updates**
   - Update test dependencies
   - Verify compatibility
   - Update fixtures if needed

3. **Documentation Audit**
   - Verify all docs are current
   - Update examples
   - Review troubleshooting guides

---

## Common Issues and Fixes

### Issue 1: Schema Mismatch Errors

**Symptom**:
```
ValueError: Field 'X' not found in target schema
```

**Diagnosis**:
1. Check which field is missing
2. Verify model definition includes field
3. Check database schema definition
4. Review recent schema changes

**Fix**:
```python
# Option 1: Add field to schema
# In agentic_inquiry/database/lancedb_manager.py
schema = {
    "existing_field": "type",
    "missing_field": "type",  # Add missing field
}

# Option 2: Remove field from model
# In agentic_inquiry/models/entity.py
@dataclass
class Entity:
    existing_field: str
    # missing_field: str  # Remove if not needed
```

**Prevention**:
- Add schema validation tests
- Document schema changes
- Use schema migration scripts

### Issue 2: Async/Await Errors

**Symptom**:
```
RuntimeWarning: coroutine 'function' was never awaited
```

**Diagnosis**:
1. Find the unawaited coroutine
2. Check if function is async
3. Verify test function is async
4. Check fixture scope

**Fix**:
```python
# ❌ Wrong
def test_something():
    result = async_function()  # Missing await

# ✅ Correct
async def test_something():
    result = await async_function()

# ❌ Wrong fixture scope
@pytest.fixture
def async_fixture():
    return await something()  # Can't await in sync fixture

# ✅ Correct fixture scope
@pytest.fixture
async def async_fixture():
    return await something()
```

**Prevention**:
- Use async test functions consistently
- Use async fixtures for async setup
- Enable async warnings in pytest

### Issue 3: Import Errors

**Symptom**:
```
ModuleNotFoundError: No module named 'X'
ImportError: cannot import name 'Y' from 'X'
```

**Diagnosis**:
1. Check if module exists
2. Verify import path is correct
3. Check for circular imports
4. Review recent refactoring

**Fix**:
```python
# ❌ Old import (module moved)
from agentic_inquiry.mcp.tools.cognitive import SearchTool

# ✅ New import
from agentic_inquiry.mcp.tools.search import search_knowledge

# ❌ Circular import
# file_a.py imports file_b.py
# file_b.py imports file_a.py

# ✅ Break circular dependency
# Move shared code to separate module
```

**Prevention**:
- Update imports immediately after refactoring
- Use absolute imports
- Avoid circular dependencies
- Run tests after moving modules

### Issue 4: Fixture Not Found

**Symptom**:
```
fixture 'X' not found
```

**Diagnosis**:
1. Check fixture name spelling
2. Verify fixture is defined in conftest.py
3. Check fixture scope
4. Review fixture dependencies

**Fix**:
```python
# ❌ Wrong fixture name
def test_something(temp_db):  # Fixture is 'temp_db_manager'
    pass

# ✅ Correct fixture name
def test_something(temp_db_manager):
    pass

# ❌ Fixture not in conftest.py
# Define in test file (not recommended)

# ✅ Add to conftest.py
# tests/mcp/conftest.py
@pytest.fixture
async def my_fixture():
    return await setup()
```

**Prevention**:
- Document all fixtures in conftest.py
- Use consistent fixture names
- List available fixtures: `pytest --fixtures`

### Issue 5: Assertion Failures on Error Format

**Symptom**:
```
AssertionError: Error format does not match expected structure
```

**Diagnosis**:
1. Check actual error format
2. Compare with expected format
3. Review error handler changes
4. Check if error handler is used

**Fix**:
```python
# ❌ Old error format
assert error["message"] == "Error"
assert error["code"] == "ERROR_CODE"

# ✅ New error format (MCPErrorHandler)
assert error["error"]["message"] == "Error"
assert error["error"]["code"] == "ERROR_CODE"
assert "suggestions" in error["error"]

# Update test to match current format
def test_error_format():
    result = tool.execute_with_error()
    assert "error" in result
    assert "message" in result["error"]
    assert "code" in result["error"]
    assert "suggestions" in result["error"]
```

**Prevention**:
- Use error handler fixtures
- Document error format changes
- Update all tests when format changes

### Issue 6: Flaky Tests

**Symptom**:
- Test passes sometimes, fails other times
- Different results on different runs
- Timing-dependent failures

**Diagnosis**:
1. Run test multiple times
2. Check for timing dependencies
3. Look for shared state
4. Review async operations
5. Check for race conditions

**Fix**:
```python
# ❌ Timing-dependent
await async_operation()
time.sleep(0.1)  # Hope it's done
assert result.ready

# ✅ Polling with timeout
async def wait_for_ready(result, timeout=5.0):
    start = time.time()
    while not result.ready:
        if time.time() - start > timeout:
            raise TimeoutError("Operation did not complete")
        await asyncio.sleep(0.1)
    return result

await async_operation()
result = await wait_for_ready(result)
assert result.ready

# ❌ Shared state
global_counter = 0

def test_increment():
    global global_counter
    global_counter += 1
    assert global_counter == 1  # Fails if tests run in parallel

# ✅ Isolated state
def test_increment():
    counter = 0
    counter += 1
    assert counter == 1
```

**Prevention**:
- Avoid fixed delays (use polling)
- Isolate test state
- Use unique identifiers
- Clean up resources properly

### Issue 7: Database State Issues

**Symptom**:
- Tests fail when run together but pass individually
- Unexpected data in database
- Constraint violations

**Diagnosis**:
1. Check if tests clean up properly
2. Look for shared database instances
3. Review transaction handling
4. Check for data leakage between tests

**Fix**:
```python
# ❌ Shared database state
@pytest.fixture(scope="module")  # Wrong scope
async def db_manager():
    return LanceDBManager(config)

# ✅ Isolated database per test
@pytest.fixture
async def db_manager(tmp_path):
    config = Config.load()
    config.storage.uri = f"file://{tmp_path}/test.db"
    manager = LanceDBManager(config)
    yield manager
    # Cleanup happens automatically when tmp_path is removed

# ❌ No cleanup
async def test_add_data(db_manager):
    await db_manager.add_entity(entity)
    # Entity remains in database

# ✅ Proper cleanup
async def test_add_data(db_manager):
    entity_id = str(uuid.uuid4())
    entity = Entity(id=entity_id, ...)
    await db_manager.add_entity(entity)
    # Test assertions
    await db_manager.delete_entity(entity_id)  # Cleanup
```

**Prevention**:
- Use function-scoped fixtures
- Clean up in fixture teardown
- Use unique identifiers
- Use temporary databases

---

## Test Lifecycle

### Creating New Tests

1. **Identify What to Test**
   - New feature added
   - Bug discovered
   - Coverage gap identified
   - Integration point added

2. **Choose Test Type**
   - Unit test: Single component
   - Integration test: Multiple components
   - E2E test: Full workflow
   - Validation test: Cross-cutting concern

3. **Write Test**
   ```python
   async def test_new_feature_basic_usage():
       """Test that new feature works in basic scenario.
       
       This test verifies that the new feature correctly handles
       the most common use case with valid input.
       """
       # Arrange
       config = Config.load()
       service = NewService(config=config)
       input_data = create_test_data()
       
       # Act
       result = await service.process(input_data)
       
       # Assert
       assert result.status == "success"
       assert result.output is not None
       assert len(result.items) > 0
   ```

4. **Add Test Documentation**
   - Docstring explaining purpose
   - Comments for complex setup
   - Link to related tests
   - Note any limitations

5. **Verify Test**
   ```bash
   # Run new test
   uv run pytest tests/mcp/test_new_feature.py::test_new_feature_basic_usage -v
   
   # Run with coverage
   uv run pytest tests/mcp/test_new_feature.py --cov=agentic_inquiry.mcp.new_feature
   
   # Verify test fails when it should
   # (temporarily break the code to ensure test catches it)
   ```

6. **Update Documentation**
   - Add to README.md test list
   - Update coverage goals
   - Document any new fixtures

### Updating Existing Tests

1. **Identify Need for Update**
   - Code behavior changed
   - API modified
   - Bug fix changes behavior
   - Test is flaky

2. **Understand Current Test**
   - Read test code and docstring
   - Understand what it tests
   - Check test history (git log)
   - Review related tests

3. **Make Changes**
   - Update test expectations
   - Fix broken assertions
   - Update test data
   - Improve test clarity

4. **Verify Changes**
   ```bash
   # Run updated test
   uv run pytest tests/mcp/test_updated.py -v
   
   # Run related tests
   uv run pytest tests/mcp/ -k "related_feature" -v
   
   # Check for regressions
   uv run pytest tests/mcp/ -v
   ```

5. **Document Changes**
   - Update docstring if needed
   - Add comment explaining change
   - Update README if significant
   - Note in commit message

### Removing Obsolete Tests

1. **Identify Obsolete Tests**
   - Feature removed
   - Functionality replaced
   - Test duplicates another
   - Test no longer relevant

2. **Verify Safe to Remove**
   - Check test coverage impact
   - Verify functionality tested elsewhere
   - Review test dependencies
   - Check for references

3. **Document Removal**
   ```markdown
   # In legacy-test-removal-log.md
   
   ## Test: test_old_feature
   **File**: tests/mcp/test_old_feature.py
   **Reason**: Feature removed in v2.0
   **Date**: 2025-11-15
   **Replaced By**: test_new_feature in test_new_feature.py
   ```

4. **Remove Test**
   ```bash
   # Remove test file
   rm tests/mcp/test_old_feature.py
   
   # Update README
   # Remove from test list
   
   # Commit with clear message
   git commit -m "Remove obsolete test_old_feature (feature removed in v2.0)"
   ```

---

## Debugging Procedures

### Step 1: Reproduce the Failure

```bash
# Run failing test
uv run pytest tests/mcp/test_failing.py::test_case -v

# Run with full output
uv run pytest tests/mcp/test_failing.py::test_case -vv --tb=long

# Run with debug logging
uv run pytest tests/mcp/test_failing.py::test_case -v --log-cli-level=DEBUG
```

### Step 2: Analyze the Error

1. **Read Error Message**
   - What is the error type?
   - What is the error message?
   - Where did it occur?

2. **Review Stack Trace**
   - Which function failed?
   - What was the call chain?
   - What were the arguments?

3. **Check Test Output**
   - What was printed?
   - What was logged?
   - What assertions failed?

### Step 3: Isolate the Problem

```python
# Add debug output
async def test_failing_case():
    result = await service.process(data)
    print(f"DEBUG: result = {result}")  # Add debug print
    print(f"DEBUG: result.status = {result.status}")
    assert result.status == "success"

# Use pytest debugging
uv run pytest tests/mcp/test_failing.py::test_case --pdb

# Add breakpoint in code
async def process(data):
    breakpoint()  # Execution will pause here
    return result
```

### Step 4: Form Hypothesis

- What do you think is causing the failure?
- Is it a test issue or code issue?
- Is it timing-related?
- Is it state-related?

### Step 5: Test Hypothesis

```python
# Test hypothesis: timing issue
async def test_with_longer_timeout():
    result = await service.process(data)
    await asyncio.sleep(1.0)  # Add delay
    assert result.ready  # Does this pass now?

# Test hypothesis: state issue
async def test_with_fresh_state():
    service = NewService()  # Create fresh instance
    result = await service.process(data)
    assert result.status == "success"
```

### Step 6: Fix the Issue

```python
# If test issue: Update test
async def test_corrected():
    result = await service.process(data)
    # Wait for completion instead of fixed delay
    await wait_for_completion(result)
    assert result.ready

# If code issue: Fix code and verify test passes
# In agentic_inquiry/mcp/service.py
async def process(data):
    # Fix the bug
    result = await correct_implementation(data)
    return result
```

### Step 7: Verify Fix

```bash
# Run fixed test
uv run pytest tests/mcp/test_fixed.py::test_case -v

# Run related tests
uv run pytest tests/mcp/ -k "related" -v

# Run full suite
uv run pytest tests/mcp/ -v
```

### Step 8: Document

- Add comment explaining fix
- Update test docstring if needed
- Document in commit message
- Update KNOWN_LIMITATIONS.md if needed

---

## Performance Monitoring

### Measuring Test Performance

```bash
# Show slowest tests
uv run pytest tests/mcp/ --durations=10

# Show all test durations
uv run pytest tests/mcp/ --durations=0

# Profile test execution
uv run pytest tests/mcp/ --profile

# Generate performance report
uv run pytest tests/mcp/ --benchmark-only
```

### Performance Targets

- **Unit tests**: <100ms per test
- **Integration tests**: <1s per test
- **E2E tests**: <5s per test
- **Full suite**: <5 minutes

### Optimizing Slow Tests

1. **Identify Bottlenecks**
   ```bash
   uv run pytest tests/mcp/test_slow.py --durations=0 -v
   ```

2. **Common Causes**
   - Unnecessary database operations
   - Large test data
   - Synchronous operations in async code
   - Repeated setup/teardown

3. **Optimization Strategies**
   ```python
   # ❌ Slow: Create database for each test
   @pytest.fixture
   async def db_manager():
       manager = await create_database()
       yield manager
       await cleanup_database(manager)
   
   # ✅ Fast: Reuse database, clean data
   @pytest.fixture(scope="module")
   async def db_manager():
       manager = await create_database()
       yield manager
       await cleanup_database(manager)
   
   @pytest.fixture
   async def clean_db(db_manager):
       yield db_manager
       await db_manager.clear_all_data()
   
   # ❌ Slow: Large test data
   test_data = [create_item() for _ in range(10000)]
   
   # ✅ Fast: Minimal test data
   test_data = [create_item() for _ in range(10)]
   
   # ❌ Slow: Synchronous in async
   async def test_something():
       result = sync_function()  # Blocks event loop
   
   # ✅ Fast: Async all the way
   async def test_something():
       result = await async_function()
   ```

---

## Documentation Updates

### When to Update Documentation

1. **Test Organization Changes**
   - New test file added
   - Test file removed
   - Tests reorganized

2. **New Fixtures Added**
   - Document in conftest.py
   - Add to README.md
   - Provide usage examples

3. **Known Issues**
   - Update KNOWN_LIMITATIONS.md
   - Document workarounds
   - Link to GitHub issues

4. **Test Procedures**
   - Update this guide
   - Document new patterns
   - Add troubleshooting steps

### Documentation Checklist

- [ ] README.md updated
- [ ] KNOWN_LIMITATIONS.md updated
- [ ] MAINTENANCE_GUIDE.md updated (this file)
- [ ] Docstrings added/updated
- [ ] Examples provided
- [ ] Links verified

---

## Release Checklist

### Pre-Release

- [ ] Run full test suite
- [ ] Verify pass rate >95%
- [ ] Check for warnings
- [ ] Review known issues
- [ ] Update documentation
- [ ] Run performance tests
- [ ] Check test coverage

### Release

- [ ] Tag release version
- [ ] Update CHANGELOG
- [ ] Archive old test data
- [ ] Document breaking changes
- [ ] Update version numbers

### Post-Release

- [ ] Monitor test results
- [ ] Address new issues
- [ ] Update documentation
- [ ] Plan improvements

---

## Quick Reference

### Essential Commands

```bash
# Run all tests
uv run pytest tests/mcp/

# Run specific test
uv run pytest tests/mcp/test_file.py::test_function

# Run with coverage
uv run pytest tests/mcp/ --cov=agentic_inquiry.mcp

# Run last failed
uv run pytest tests/mcp/ --lf

# Run with debugging
uv run pytest tests/mcp/ --pdb

# Show fixtures
uv run pytest tests/mcp/ --fixtures

# Show durations
uv run pytest tests/mcp/ --durations=10
```

### Common Patterns

```python
# Async test
async def test_something():
    result = await async_function()
    assert result.success

# Async fixture
@pytest.fixture
async def my_fixture():
    resource = await setup()
    yield resource
    await cleanup(resource)

# Parametrized test
@pytest.mark.parametrize("input,expected", [
    ("a", 1),
    ("b", 2),
])
async def test_cases(input, expected):
    result = await process(input)
    assert result == expected

# Skip test
@pytest.mark.skip(reason="Waiting for bug fix")
async def test_broken():
    pass

# Expected failure
@pytest.mark.xfail(reason="Known issue #123")
async def test_known_issue():
    pass
```

---

## Getting Help

### Resources

- **Test README**: `tests/mcp/README.md`
- **Known Limitations**: `tests/mcp/KNOWN_LIMITATIONS.md`
- **Contributing Guide**: `docs/CONTRIBUTING.md`
- **MCP Documentation**: `docs/mcp/README.md`

### Contacts

- **Test Suite Issues**: Create GitHub issue
- **General Questions**: See `docs/CONTRIBUTING.md`
- **Bug Reports**: See `.kiro/storage/tasks/mcp-test-suite-cleanup/bug-reports.md`

---

## Appendix: Test Patterns

### Pattern 1: Arrange-Act-Assert

```python
async def test_feature():
    # Arrange: Set up test data and dependencies
    config = Config.load()
    service = MyService(config=config)
    input_data = create_test_data()
    
    # Act: Execute the functionality
    result = await service.process(input_data)
    
    # Assert: Verify expected behavior
    assert result.status == "success"
    assert result.output is not None
```

### Pattern 2: Given-When-Then

```python
async def test_feature():
    # Given: Initial state
    service = MyService()
    service.set_state("initial")
    
    # When: Action occurs
    result = await service.transition()
    
    # Then: Expected outcome
    assert service.state == "final"
    assert result.success
```

### Pattern 3: Setup-Exercise-Verify-Teardown

```python
async def test_feature():
    # Setup
    resource = await create_resource()
    
    try:
        # Exercise
        result = await use_resource(resource)
        
        # Verify
        assert result.valid
    finally:
        # Teardown
        await cleanup_resource(resource)
```

---

**End of Maintenance Guide**
