# MCP Test Suite - Known Limitations

**Last Updated**: November 15, 2025  
**Test Suite Version**: Post-cleanup (95.85% pass rate)

## Overview

This document describes known limitations in the MCP test suite, including tests that require core library fixes, temporary workarounds, and areas where test coverage is incomplete.

## Active Limitations

### 1. Graph Entity Schema Mismatch

**Priority**: HIGH  
**Status**: Documented, awaiting core library fix  
**Impact**: 17 tests blocked (3.21% of test suite)

#### Description

The LanceDB schema for graph entities is missing the `line_start` field that the indexing pipeline attempts to write. This causes all tests that index code files and create graph entities to fail with a schema mismatch error.

#### Error Message

```
ValueError: Field 'line_start' not found in target schema
```

#### Affected Tests

All tests in `test_build_context_integration.py`:
- `TestBuildContextWithIndexedContent` (2 tests)
- `TestBuildContextFocusParameter` (3 tests)
- `TestBuildContextDepthParameter` (3 tests)
- `TestBuildContextTokenBudget` (3 tests)
- `TestBuildContextWithMemories` (3 tests)
- `TestBuildContextFallbackStrategy` (3 tests)

#### Root Cause

Mismatch between:
- **Graph Entity Model**: Includes `line_start` field in entity data
- **Database Schema**: Does not define `line_start` field in graph_entities table

#### Workaround

**None available**. Tests cannot pass until schema is updated.

#### Required Fix

1. Update `graph_entities` table schema to include `line_start` field
2. Create migration for existing databases
3. Add schema validation tests to prevent future mismatches

#### Files Requiring Changes

- `agent_vault/models/graph_entity.py` (or equivalent)
- `agent_vault/database/lancedb_manager.py` (schema definition)
- `agent_vault/indexing/graph_builder.py` (entity creation)
- Migration script (if needed)

#### Estimated Fix Effort

**MEDIUM** - 4-6 hours
- Schema investigation: 1 hour
- Schema update/migration: 2-3 hours
- Testing and validation: 1-2 hours

#### GitHub Issue

See `.kiro/storage/tasks/mcp-test-suite-cleanup/github-issues.md` for detailed issue report.

---

### 2. Missing status Field in add_knowledge Response

**Priority**: MEDIUM  
**Status**: Documented, awaiting investigation  
**Impact**: 5 tests failing (0.95% of test suite)

#### Description

Integration tests for the `add_knowledge` tool expect a `status` field in the response to indicate operation status (e.g., "completed", "failed"). However, the actual response does not include this field.

#### Error Message

```python
KeyError: 'status'
```

#### Affected Tests

Tests in `test_add_knowledge_integration.py`:
- `test_add_knowledge_python_file`
- `test_add_knowledge_typescript_file`
- `test_add_knowledge_markdown_file`
- `test_add_knowledge_error_handling_unsupported_file`
- `test_add_knowledge_text_content`

#### Root Cause

**Unclear** - Requires investigation to determine if:
1. Response format changed but tests not updated
2. Tests expect wrong format
3. `status` field should be added to response

#### Workaround

**Option 1**: Update tests to match actual response format (if format is correct)  
**Option 2**: Add `status` field to response (if tests are correct)

#### Required Fix

1. Investigate actual response format from `add_knowledge` tool
2. Determine if `status` field should be present
3. Either update tests or add field to response
4. Document correct response format

#### Files Requiring Changes

- `agent_vault/mcp/tools/knowledge.py` (if adding field)
- `tests/mcp/test_add_knowledge_integration.py` (if updating tests)
- `docs/mcp/tools/README.md` (documentation)

#### Estimated Fix Effort

**LOW** - 1-2 hours
- Investigation: 30 minutes
- Code update: 30 minutes
- Testing: 30 minutes
- Documentation: 30 minutes

#### GitHub Issue

See `.kiro/storage/tasks/mcp-test-suite-cleanup/github-issues.md` for detailed issue report.

---

## Test Coverage Gaps

### 1. Schema Validation

**Area**: Database schema validation  
**Gap**: No tests verify schema consistency before operations  
**Impact**: Schema mismatches only discovered at runtime  
**Recommendation**: Add schema validation tests that run before test suite

### 2. Tool Response Format Standardization

**Area**: MCP tool responses  
**Gap**: No standard format enforced across all tools  
**Impact**: Inconsistent response structures, difficult to validate  
**Recommendation**: Define and test standard response format for all tools

### 3. Migration Testing

**Area**: Database schema migrations  
**Gap**: No tests for schema migration scenarios  
**Impact**: Cannot verify migrations work correctly  
**Recommendation**: Add migration tests for schema changes

### 4. Performance Regression

**Area**: Performance monitoring  
**Gap**: No automated performance regression tests  
**Impact**: Performance degradation may go unnoticed  
**Recommendation**: Add performance benchmarks to test suite

### 5. Concurrent Operations

**Area**: Concurrent tool execution  
**Gap**: Limited testing of concurrent operations  
**Impact**: Race conditions may exist  
**Recommendation**: Add tests for concurrent tool calls

---

## Temporary Workarounds

### Skipping Schema-Dependent Tests

If you need to run the test suite while schema issues are unresolved:

```bash
# Skip build_context_integration tests
uv run pytest tests/mcp/ -k "not build_context_integration"

# Skip add_knowledge_integration tests
uv run pytest tests/mcp/ -k "not add_knowledge_integration"

# Skip both
uv run pytest tests/mcp/ -k "not (build_context_integration or add_knowledge_integration)"
```

### Using In-Memory Database

For tests that don't require persistent storage:

```python
@pytest.fixture
async def in_memory_db():
    """Use in-memory database to avoid schema issues."""
    config = Config.load()
    config.storage.uri = "memory://test"
    return LanceDBManager(config=config)
```

### Mocking Problematic Components

For integration tests blocked by schema issues:

```python
@pytest.fixture
def mock_graph_builder(mocker):
    """Mock graph builder to avoid schema issues."""
    mock = mocker.Mock()
    mock.build_entities.return_value = []
    return mock
```

---

## Test Flakiness

### Known Flaky Tests

**None currently identified**

### Potential Flakiness Sources

1. **Timing Issues**: Tests that rely on async operations may be timing-sensitive
2. **Database State**: Tests that don't properly clean up may affect subsequent tests
3. **File System**: Tests that create files may conflict if run concurrently
4. **Network**: Tests that make external calls may fail intermittently

### Preventing Flakiness

1. Use polling instead of fixed delays
2. Clean up resources in fixtures
3. Use unique identifiers (UUIDs) for test data
4. Isolate tests with proper fixtures
5. Avoid shared mutable state

---

## Deprecated Features

### Recently Removed

The following modules were removed during refactoring (November 2025):
- `agent_vault.mcp.models.requests` - Replaced by tool-specific models
- `agent_vault.mcp.tools.base` - Replaced by FastMCP decorators
- `agent_vault.mcp.tools.cognitive` - Split into specific tool modules

### Migration Guide

If you have tests that import from removed modules:

**Old**:
```python
from agent_vault.mcp.tools.cognitive.search import SearchKnowledgeTool
from agent_vault.mcp.models.requests import SearchRequest
```

**New**:
```python
from agent_vault.mcp.tools.search import search_knowledge
# Request models are now defined inline or in tool modules
```

---

## Future Improvements

### Short Term (Next Sprint)

1. Fix graph entity schema mismatch (HIGH priority)
2. Resolve add_knowledge response format issue (MEDIUM priority)
3. Add schema validation tests
4. Document all tool response formats

### Medium Term (Next Quarter)

1. Implement standard response format for all tools
2. Add migration testing framework
3. Improve test coverage for error paths
4. Add performance regression tests

### Long Term (Next Year)

1. Implement automated test health monitoring
2. Add mutation testing for test quality
3. Create test generation templates
4. Build test quality metrics dashboard

---

## Getting Help

### Reporting New Limitations

If you discover a new limitation:

1. Document the issue in this file
2. Create a bug report in `.kiro/storage/tasks/mcp-test-suite-cleanup/bug-reports.md`
3. Create a GitHub issue if it requires core library changes
4. Update affected test files with skip markers and comments

### Asking Questions

- **Test-specific questions**: See `tests/mcp/README.md`
- **General testing guidelines**: See `docs/CONTRIBUTING.md`
- **MCP documentation**: See `docs/mcp/README.md`
- **Bug reports**: See `.kiro/storage/tasks/mcp-test-suite-cleanup/bug-reports.md`

---

## Appendix: Test Statistics

### Current State (November 15, 2025)

- **Total Tests**: 529
- **Passing**: 507 (95.85%)
- **Failing**: 5 (0.95%)
- **Errors**: 17 (3.21%)
- **Warnings**: 0 (0%)

### Historical Comparison

| Date | Total | Passing | Failing | Pass Rate |
|------|-------|---------|---------|-----------|
| Nov 13, 2025 | 529 | 468 | 61 | 88.47% |
| Nov 15, 2025 | 529 | 507 | 22 | 95.85% |

### Improvement

- **Failures Reduced**: 64% (from 61 to 22)
- **Pass Rate Increased**: 7.38 percentage points
- **Warnings Resolved**: 100% (from 39 to 0)

---

## Document History

| Date | Change | Author |
|------|--------|--------|
| 2025-11-15 | Initial creation | MCP Test Suite Cleanup |
| 2025-11-15 | Added schema mismatch limitation | Task 13.2 |
| 2025-11-15 | Added response format limitation | Task 13.2 |
