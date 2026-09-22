# Project Isolation Test Summary

## Overview

This test suite (TEST-008) adds comprehensive project isolation tests to verify that multi-project deployments properly isolate data and prevent cross-contamination.

## Test Coverage

### Test Categories

1. **Cross-Project Data Leakage** (4 tests)
   - Chunks isolated between projects
   - Vector search isolated between projects
   - Entities isolated between projects
   - Relationships isolated between projects

2. **Concurrent Project Access** (3 tests)
   - Concurrent chunk upserts don't interfere
   - Concurrent entity upserts don't interfere
   - Concurrent read/write on different projects

3. **Project-Scoped Queries** (3 tests)
   - Count respects project scope
   - Delete by file respects project scope
   - Get entities by type respects project scope

4. **Project Deletion Cleanup** (4 tests)
   - Delete all chunks for a project
   - Delete all entities for a project
   - Delete relationships cascade respects project
   - Complete project cleanup

5. **Edge Cases** (3 tests)
   - Whitespace in project IDs handled safely
   - Special characters in project IDs
   - Many projects isolation scales

**Total: 17 unique test scenarios**

## Results by Provider

### InMemoryProvider (In-Memory Storage)
- **Status**: 17/17 tests passing (100%) ✅
- **Passing**: All tests after bug fix
- **Previous Issue**: Test was passing `project_id` as positional arg mapped to `direction`

The InMemoryProvider implementation is correct. The failing tests were due to incorrect test code that passed `project_id` as the second positional argument, which mapped to the `direction` parameter instead of `project_id`. Fixed by using keyword argument: `project_id=project_a`.

### LanceDBProvider (File-Based Storage)
- **Status**: 17/17 tests passing (100%) ✅
- **Previous Issue**: Provider filtered by initialization project_id instead of method parameter
- **Fix Applied**: Methods now pass `project_id=None` to disable auto-filtering when project_id is in filters dict

The LanceDB project isolation bug has been fixed. The root cause was in `query_builder.py` where `_add_project_filter()` would overwrite the filter dict's project_id with the default when `project_id=CURRENT_PROJECT_ID`. Fixed by:
1. Passing `project_id=None` to `advanced_filter` when project_id is already in filters
2. Adding cascade delete for relationships when entities are deleted

### PostgresProvider (PostgreSQL + pgvector)
- **Status**: Skipped (requires PostgreSQL running)
- **How to test**:
  ```bash
  docker-compose -f docker-compose.dev.yaml up -d
  pytest tests/storage/test_project_isolation.py -v -k postgres
  ```

## Bugs Found

### RESOLVED: LanceDB Project Isolation Bug

**Severity**: N/A (FIXED)
**Status**: ✅ FIXED

**Description**: The LanceDB provider filtered queries by the provider's initialization `project_id` instead of the method parameter `project_id`. This completely broke project isolation for multi-project scenarios.

**Root Cause**: In `query_builder.py`, `_add_project_filter()` would overwrite filter dict values when `project_id=CURRENT_PROJECT_ID` (the default).

**Fix**: Modified `vector.py` methods (`delete_chunks_by_file`, `get_chunks_by_file`) to pass `project_id=None` which disables auto-filtering when project_id is already in the filters dict. Also added cascade delete for relationships when entities are deleted in `graph.py`.

### RESOLVED: InMemory Provider Relationship Isolation "Bug"

**Severity**: N/A (was a test bug, not implementation bug)
**Status**: ✅ FIXED

**Description**: The `get_relationships_by_entity()` implementation was correct. The tests were passing `project_id` as a positional argument which mapped to `direction` instead of `project_id`.

**Fix**: Changed test calls from:
```python
await graph_provider.get_relationships_by_entity("a_caller", project_a)
```
to:
```python
await graph_provider.get_relationships_by_entity("a_caller", project_id=project_a)
```

**Affected Tests** (now passing):
- `test_relationships_isolated_between_projects`
- `test_delete_relationships_cascade_respects_project`

## Files Created

1. **tests/storage/test_project_isolation.py** - Main test file with 17 test scenarios
2. **tests/storage/conftest.py** - Updated with test fixtures and provider factories
3. **tests/storage/TEST_PROJECT_ISOLATION_SUMMARY.md** - This summary document

## Running the Tests

```bash
# Run all tests (memory provider only, skips postgres if not available)
pytest tests/storage/test_project_isolation.py -v

# Run with working providers only
pytest tests/storage/test_project_isolation.py -v -k "memory or postgres"

# Run specific test category
pytest tests/storage/test_project_isolation.py -v -k "DataLeakage"
pytest tests/storage/test_project_isolation.py -v -k "Concurrent"
pytest tests/storage/test_project_isolation.py -v -k "ScopedQueries"
pytest tests/storage/test_project_isolation.py -v -k "Cleanup"

# See LanceDB failures (demonstrates the bug)
pytest tests/storage/test_project_isolation.py -v -k "lancedb"
```

## Success Criteria Met

- [x] Tests for cross-project data leakage
- [x] Tests for isolation during concurrent access
- [x] Tests for project-scoped queries
- [x] Tests for project deletion cleanup
- [x] Tests run against multiple storage providers
- [x] Tests identify real bugs in production code

## Recommendations

1. **Fix LanceDB project isolation** - This is a critical bug that prevents multi-tenant use
2. **Fix InMemory provider relationships** - For consistency in test environments
3. **Add PostgreSQL to CI** - To ensure ongoing test coverage
4. **Document project isolation requirements** - Add to architecture docs

## Next Steps

1. Create tickets for the bugs found:
   - HIGH PRIORITY: Fix LanceDB project isolation
   - MEDIUM PRIORITY: Fix InMemory relationship filtering
2. Run tests against PostgreSQL provider (requires Docker setup)
3. Add tests to CI pipeline
4. Update storage provider documentation with project isolation guarantees
