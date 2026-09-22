# MCP Test Suite

This directory contains tests for the Model Context Protocol (MCP) server implementation.

## Overview

The MCP test suite validates the functionality of the Agentic Inquiry MCP server, including:
- Tool implementations (search, analysis, context building)
- Service layer (session management, entity resolution, impact analysis)
- Integration flows (end-to-end workflows)
- Error handling and validation
- Performance and caching

**Current Status**: 95.85% pass rate (507/529 tests passing) as of November 15, 2025

## Test Organization

### Core Tool Tests
- `test_build_context_tool.py` - BuildContext tool functionality
- `test_add_knowledge_integration.py` - Knowledge indexing integration
- `test_understand_entity_integration.py` - Entity understanding and resolution
- `test_analyze_impact_integration.py` - Impact analysis functionality

### Service Layer Tests
- `test_context_builder.py` - Context building service
- `test_entity_resolver.py` - Entity resolution service
- `test_impact_analyzer.py` - Impact analysis service
- `test_session_manager.py` - Session management
- `test_pattern_analyzer.py` - Pattern analysis service
- `test_query_optimizer.py` - Query optimization

### Integration Tests
- `test_e2e_integration_flows.py` - End-to-end workflow tests
- `test_build_context_integration.py` - Context building integration
- `test_mcp_server_integration.py` - Server integration tests
- `test_comprehensive_agent_validation.py` - Comprehensive agent validation

### Error Handling Tests
- `test_error_handler.py` - Error handler functionality
- `test_consistent_error_handling.py` - Error consistency validation
- `test_validation.py` - Input validation

### Model and Schema Tests
- `test_session_model.py` - Session data model
- `test_model_imports.py` - Model import validation
- `test_add_knowledge_schema_errors.py` - Schema error handling

### Performance Tests
- `test_performance_monitor.py` - Performance monitoring
- `test_cache_manager.py` - Cache management
- `test_token_budget.py` - Token budget management

### Utility Tests
- `test_factories.py` - Factory functions
- `test_suggestions.py` - Suggestion generation
- `test_progress_indicators.py` - Progress reporting
- `test_tool_signatures.py` - Tool signature validation

## Running Tests

### Run all MCP tests
```bash
uv run pytest tests/mcp/
```

### Run specific test file
```bash
uv run pytest tests/mcp/test_build_context_tool.py
```

### Run specific test function
```bash
uv run pytest tests/mcp/test_build_context_tool.py::test_build_context_basic
```

### Run with verbose output
```bash
uv run pytest tests/mcp/ -v
```

### Run with coverage
```bash
uv run pytest tests/mcp/ --cov=agentic_inquiry.mcp
```

## Test Categories

### Unit Tests
Focus on individual components in isolation:
- Service layer tests (entity_resolver, impact_analyzer, etc.)
- Utility tests (error_handler, suggestions, etc.)
- Model tests (session_model, etc.)

### Integration Tests
Test interactions between components:
- Tool integration tests (build_context_integration, add_knowledge_integration)
- End-to-end flows (e2e_integration_flows)
- Server integration (mcp_server_integration)

### Validation Tests
Ensure correctness and consistency:
- Error handling validation (consistent_error_handling)
- Schema validation (add_knowledge_schema_errors)
- Tool signature validation (tool_signatures)

## Common Fixtures

Available in `tests/conftest.py`:
- `test_config` - Test configuration
- `temp_db_manager` - Temporary database manager
- `test_services` - Mock MCP services
- `sample_parsed_document` - Sample document for testing

## Recent Changes

### November 14, 2025 - Legacy Test Removal
Removed 17 legacy test files that imported non-existent modules:
- test_api_middleware.py
- test_api_routes.py
- test_base_tool.py
- test_context_tool.py
- test_direct_access_tools.py
- test_entity_tool.py
- test_error_messages.py
- test_events_tool.py
- test_impact_tool.py
- test_knowledge_tool.py
- test_mcp_full_workflow.py
- test_memory_tools.py
- test_patterns_tool.py
- test_project_info_tool.py
- test_search_tool.py
- test_session_tools.py
- test_tool_execution_e2e.py

See `.kiro/storage/tasks/mcp-test-suite-cleanup/legacy-test-removal-log.md` for details.

## Test Coverage Goals

- **Unit tests**: >90% coverage of service layer
- **Integration tests**: All major workflows covered
- **Error handling**: All error paths tested
- **Validation**: All input validation tested

## Adding New Tests

When adding new tests:
1. Follow the naming convention: `test_<component>_<scenario>.py`
2. Use appropriate fixtures from `conftest.py`
3. Add docstrings explaining what is being tested
4. Group related tests in classes when appropriate
5. Use descriptive test function names
6. Add integration tests for new features

## Known Issues

### Active Issues

#### Issue #1: Graph Entity Schema Mismatch (HIGH Priority)
**Status**: Documented, awaiting fix  
**Impact**: 17 tests blocked  
**Description**: LanceDB schema missing `line_start` field for graph entities  
**Affected Tests**: All tests in `test_build_context_integration.py`  
**Workaround**: None - requires schema update  
**GitHub Issue**: See `.kiro/storage/tasks/mcp-test-suite-cleanup/github-issues.md`

#### Issue #2: Missing status Field in add_knowledge Response (MEDIUM Priority)
**Status**: Documented, awaiting fix  
**Impact**: 5 tests failing  
**Description**: Tool response missing expected `status` field  
**Affected Tests**: Tests in `test_add_knowledge_integration.py`  
**Workaround**: Update tests to match actual response format  
**GitHub Issue**: See `.kiro/storage/tasks/mcp-test-suite-cleanup/github-issues.md`

### Resolved Issues

See `.kiro/storage/tasks/mcp-test-suite-cleanup/FINAL_SUMMARY.md` for complete history of resolved issues.

## Test Maintenance Guide

### Common Issues and Fixes

#### Schema Mismatch Errors
**Symptom**: `ValueError: Field 'X' not found in target schema`  
**Cause**: Model includes field not in database schema  
**Fix**: Update schema or remove field from model  
**Prevention**: Add schema validation tests

#### Async/Await Issues
**Symptom**: `RuntimeWarning: coroutine was never awaited`  
**Cause**: Missing `await` keyword or incorrect fixture scope  
**Fix**: Ensure all async functions are awaited, use `async_to_sync` for sync contexts  
**Prevention**: Use async fixtures and test functions

#### Import Errors
**Symptom**: `ModuleNotFoundError` or `ImportError`  
**Cause**: Module moved, renamed, or removed  
**Fix**: Update imports to current module structure  
**Prevention**: Run full test suite after refactoring

#### Assertion Failures on Error Format
**Symptom**: Test expects different error structure  
**Cause**: Error handler format changed  
**Fix**: Update test expectations to match `MCPErrorHandler` format  
**Prevention**: Use error handler fixtures

#### Fixture Not Found
**Symptom**: `fixture 'X' not found`  
**Cause**: Fixture removed or renamed  
**Fix**: Update fixture name or create new fixture  
**Prevention**: Document fixture changes in conftest.py

### Adding New Tests

When adding new tests to the MCP test suite:

1. **Choose the Right Location**
   - Unit tests for services: `test_<service_name>.py`
   - Integration tests: `test_<feature>_integration.py`
   - End-to-end tests: `test_e2e_<workflow>.py`
   - Error handling: `test_<component>_error_handling.py`

2. **Follow Naming Conventions**
   - Test files: `test_<component>_<aspect>.py`
   - Test functions: `test_<functionality>_<scenario>`
   - Test classes: `Test<Component><Aspect>`

3. **Use Appropriate Fixtures**
   - Database: `temp_db_manager`, `in_memory_db`
   - Configuration: `test_config`, `temp_config_file`
   - Services: `test_services`, `mock_entity_resolver`
   - Documents: `sample_parsed_document`, `sample_code_file`

4. **Structure Tests Clearly**
   ```python
   async def test_feature_scenario():
       """Test that feature works in specific scenario."""
       # Arrange - Set up test data and dependencies
       config = Config.load()
       service = MyService(config=config)
       
       # Act - Execute the functionality
       result = await service.do_something()
       
       # Assert - Verify expected behavior
       assert result.status == "success"
       assert len(result.items) > 0
   ```

5. **Test Error Paths**
   - Test both success and failure scenarios
   - Verify error messages are helpful
   - Check error codes are correct
   - Ensure proper cleanup on errors

6. **Document Complex Tests**
   - Add docstrings explaining what is tested
   - Document any non-obvious setup
   - Explain expected behavior
   - Note any known limitations

7. **Keep Tests Independent**
   - Each test should run independently
   - Don't rely on test execution order
   - Clean up resources in fixtures
   - Use unique identifiers (UUIDs)

8. **Verify Test Quality**
   ```bash
   # Run new tests
   uv run pytest tests/mcp/test_new_feature.py -v
   
   # Check coverage
   uv run pytest tests/mcp/test_new_feature.py --cov=agentic_inquiry.mcp
   
   # Run with diagnostics
   uv run pytest tests/mcp/test_new_feature.py -vv --tb=short
   ```

### Maintaining Existing Tests

#### When Code Changes
1. Run affected tests immediately
2. Update test expectations if behavior changed intentionally
3. Fix tests if they reveal bugs
4. Update test documentation

#### When Tests Fail
1. Determine if failure is legitimate (bug) or test issue
2. For bugs: Document and create GitHub issue
3. For test issues: Fix test expectations
4. For flaky tests: Investigate timing or state issues

#### When Refactoring
1. Run full test suite before starting
2. Update tests incrementally with code changes
3. Don't skip failing tests - fix or document
4. Run full suite again after completion

#### Regular Maintenance
- Review test coverage monthly
- Remove obsolete tests promptly
- Update fixtures when APIs change
- Keep test documentation current
- Monitor test execution time

### Test Categories and Guidelines

#### Unit Tests
**Purpose**: Test individual components in isolation  
**Scope**: Single class or function  
**Dependencies**: Minimal, use mocks for external dependencies  
**Speed**: Fast (<100ms per test)  
**Example**: `test_entity_resolver.py`, `test_impact_analyzer.py`

#### Integration Tests
**Purpose**: Test interactions between components  
**Scope**: Multiple components working together  
**Dependencies**: Real implementations, minimal mocking  
**Speed**: Medium (100ms-1s per test)  
**Example**: `test_build_context_integration.py`, `test_add_knowledge_integration.py`

#### End-to-End Tests
**Purpose**: Test complete workflows from user perspective  
**Scope**: Full system with all components  
**Dependencies**: Real database, real services  
**Speed**: Slow (1s+ per test)  
**Example**: `test_e2e_integration_flows.py`, `test_comprehensive_agent_validation.py`

#### Validation Tests
**Purpose**: Ensure correctness and consistency  
**Scope**: Cross-cutting concerns (error handling, validation)  
**Dependencies**: Varies by test  
**Speed**: Fast to medium  
**Example**: `test_consistent_error_handling.py`, `test_tool_signatures.py`

### Best Practices

#### Do's ✅
- Use descriptive test names that explain what is tested
- Test both success and failure paths
- Use fixtures for common setup
- Clean up resources (files, database entries)
- Add docstrings to complex tests
- Use async/await consistently
- Verify error messages are helpful
- Test edge cases and boundary conditions

#### Don'ts ❌
- Don't use hardcoded paths or IDs
- Don't rely on test execution order
- Don't skip tests without documenting why
- Don't test implementation details
- Don't use sleep() for timing (use polling)
- Don't leave commented-out code
- Don't commit failing tests without documentation
- Don't mock everything (integration tests need real components)

### Debugging Failed Tests

1. **Run with verbose output**
   ```bash
   uv run pytest tests/mcp/test_failing.py -vv --tb=long
   ```

2. **Run single test**
   ```bash
   uv run pytest tests/mcp/test_failing.py::test_specific_case -vv
   ```

3. **Add debug logging**
   ```python
   import logging
   logging.basicConfig(level=logging.DEBUG)
   ```

4. **Use pytest debugging**
   ```bash
   uv run pytest tests/mcp/test_failing.py --pdb
   ```

5. **Check fixtures**
   ```bash
   uv run pytest tests/mcp/test_failing.py --fixtures
   ```

6. **Inspect test output**
   - Check assertion messages
   - Review stack traces
   - Examine logged errors
   - Verify test data

## Contributing

See `docs/CONTRIBUTING.md` for general testing guidelines and best practices.
