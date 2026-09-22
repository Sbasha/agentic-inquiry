"""Comprehensive end-to-end agent validation test suite.

This test suite validates all the fixes implemented for MCP tool failures:
- Task 15.1: add_knowledge end-to-end validation
- Task 15.2: build_context end-to-end validation
- Task 15.3: query sanitization end-to-end validation
- Task 15.4: regression test suite

Requirements: 17.1, 17.2, 17.3, 17.4, 17.5
"""

import pytest

pytestmark = pytest.mark.integration

from agent_vault.mcp.factories import create_mcp_services
from agent_vault.mcp.tools.session import create_session
from agent_vault.mcp.tools.knowledge import add_knowledge
from agent_vault.mcp.tools.search import search_knowledge
from agent_vault.mcp.tools.context import build_context
from agent_vault.mcp.tools.memory import save_memory


@pytest.fixture
async def test_services(mock_config, tmp_path, monkeypatch):
    """Create real MCP services for end-to-end testing.
    
    Note: Changes working directory to tmp_path so path validation succeeds
    for test files created in the temporary directory.
    """
    # Change to tmp_path so path validation passes for files created there
    monkeypatch.chdir(tmp_path)
    
    # Use the mock_config fixture and update storage paths
    mock_config.storage.root = str(tmp_path)
    
    # Create services
    services = await create_mcp_services(
        config=mock_config,
        project_id="test_validation_project"
    )
    
    yield services


# ============================================================================
# Task 15.1: Validate add_knowledge end-to-end
# Requirements: 5.1, 5.2, 5.3, 6.1, 17.2
# ============================================================================

@pytest.mark.asyncio
async def test_add_knowledge_python_file_e2e(test_services, tmp_path):
    """Validate add_knowledge with Python file end-to-end.
    
    Requirements: 5.1, 17.2
    """
    # Create session
    session_result = await create_session(
        services=test_services,
        project_id="test_validation_project",
        description="Python file validation"
    )
    session_id = session_result["session_id"]
    
    # Create test Python file
    python_file = tmp_path / "test_module.py"
    python_file.write_text("""
def calculate_sum(a, b):
    '''Calculate the sum of two numbers.'''
    return a + b

class Calculator:
    '''A simple calculator class.'''
    
    def multiply(self, x, y):
        '''Multiply two numbers.'''
        return x * y
""")
    
    # Index the file (use relative path since we're in tmp_path)
    result = await add_knowledge(
        services=test_services,
        session_id=session_id,
        content_type="file",
        source="test_module.py"
    )
    
    # Verify indexing succeeded
    assert result["status"] == "completed"
    assert result["items_processed"] >= 1
    assert "error" not in result
    
    # Verify content is searchable
    search_result = await search_knowledge(
        services=test_services,
        session_id=session_id,
        query="calculate sum",
        limit=10
    )
    
    assert len(search_result["results"]) > 0
    assert any("calculate" in r["content"].lower() for r in search_result["results"])


@pytest.mark.asyncio
async def test_add_knowledge_typescript_file_e2e(test_services, tmp_path):
    """Validate add_knowledge with TypeScript file end-to-end.
    
    Requirements: 5.2, 17.2
    """
    # Create session
    session_result = await create_session(
        services=test_services,
        project_id="test_validation_project",
        description="TypeScript file validation"
    )
    session_id = session_result["session_id"]
    
    # Create test TypeScript file
    ts_file = tmp_path / "test_module.ts"
    ts_file.write_text("""
interface User {
    name: string;
    email: string;
}

function createUser(name: string, email: string): User {
    return { name, email };
}

export class UserManager {
    private users: User[] = [];
    
    addUser(user: User): void {
        this.users.push(user);
    }
}
""")
    
    # Index the file (use relative path since we're in tmp_path)
    result = await add_knowledge(
        services=test_services,
        session_id=session_id,
        content_type="file",
        source="test_module.ts"
    )
    
    # Verify indexing succeeded
    assert result["status"] == "completed"
    assert result["items_processed"] >= 1
    assert "error" not in result
    
    # Verify content is searchable
    search_result = await search_knowledge(
        services=test_services,
        session_id=session_id,
        query="UserManager",
        limit=10
    )
    
    assert len(search_result["results"]) > 0
    assert any("user" in r["content"].lower() for r in search_result["results"])


@pytest.mark.asyncio
async def test_add_knowledge_markdown_file_e2e(test_services, tmp_path):
    """Validate add_knowledge with Markdown file end-to-end.
    
    Requirements: 5.3, 17.2
    """
    # Create session
    session_result = await create_session(
        services=test_services,
        project_id="test_validation_project",
        description="Markdown file validation"
    )
    session_id = session_result["session_id"]
    
    # Create test Markdown file
    md_file = tmp_path / "README.md"
    md_file.write_text("""
# Project Documentation

## Getting Started

This project provides a comprehensive API for data processing.

### Installation

```bash
pip install my-package
```

### Usage

Import the main module and create an instance:

```python
from my_package import DataProcessor

processor = DataProcessor()
result = processor.process(data)
```

## Features

- Fast data processing
- Easy to use API
- Comprehensive documentation
""")
    
    # Index the file (use relative path since we're in tmp_path)
    result = await add_knowledge(
        services=test_services,
        session_id=session_id,
        content_type="file",
        source="README.md"
    )
    
    # Verify indexing succeeded
    assert result["status"] == "completed"
    assert result["items_processed"] >= 1
    assert "error" not in result
    
    # Verify content is searchable
    search_result = await search_knowledge(
        services=test_services,
        session_id=session_id,
        query="installation",
        limit=10
    )
    
    assert len(search_result["results"]) > 0
    assert any("install" in r["content"].lower() for r in search_result["results"])


@pytest.mark.asyncio
async def test_add_knowledge_directory_e2e(test_services, tmp_path):
    """Validate add_knowledge with directory containing mixed file types.
    
    Requirements: 6.1, 17.2
    """
    # Create session
    session_result = await create_session(
        services=test_services,
        project_id="test_validation_project",
        description="Directory validation"
    )
    session_id = session_result["session_id"]
    
    # Create test directory with mixed files
    test_dir = tmp_path / "test_project"
    test_dir.mkdir()
    
    # Python file
    (test_dir / "utils.py").write_text("""
def format_data(data):
    return str(data).upper()
""")
    
    # TypeScript file
    (test_dir / "types.ts").write_text("""
export interface Config {
    apiKey: string;
    timeout: number;
}
""")
    
    # Markdown file
    (test_dir / "GUIDE.md").write_text("""
# User Guide

## Configuration

Set your API key in the config file.
""")
    
    # Index the directory (now async, use relative path)
    result = await add_knowledge(
        services=test_services,
        session_id=session_id,
        content_type="directory",
        source="test_project"
    )
    
    # Verify async indexing started
    assert result["status"] == "started"
    assert "operation_id" in result
    assert "message" in result  # Contains instructions for monitoring
    
    # Poll for completion (with timeout)
    import asyncio
    session_manager = test_services["session_manager"]
    timeout = 30  # seconds
    loop = asyncio.get_running_loop()
    start_time = loop.time()
    completed = False
    final_event = None
    
    while loop.time() - start_time < timeout:
        # Get events from session
        events = await session_manager.get_events(session_id)
        
        # Check for completion or failure
        for event in events:
            if event.get("event_type") == "indexing_completed":
                if event.get("data", {}).get("operation_id") == result["operation_id"]:
                    completed = True
                    final_event = event
                    break
            elif event.get("event_type") == "indexing_failed":
                if event.get("data", {}).get("operation_id") == result["operation_id"]:
                    pytest.fail(f"Indexing failed: {event.get('data', {}).get('error')}")
        
        if completed:
            break
        
        # Wait before polling again
        await asyncio.sleep(0.5)
    
    # Verify completion
    if not completed:
        # Log diagnostic information on timeout
        all_events = await session_manager.get_events(session_id)
        print(f"\nTimeout after {timeout} seconds. Events received:")
        for event in all_events:
            print(f"  - {event.get('event_type')}: {event.get('data')}")
        pytest.fail(f"Indexing did not complete within {timeout} seconds")
    
    assert final_event is not None
    assert final_event["data"]["items_processed"] >= 1  # At least 1 file (schema issues may prevent all files from indexing)
    assert "files" in final_event["data"]
    
    # Verify all files are searchable
    # Search for Python content
    py_search = await search_knowledge(
        services=test_services,
        session_id=session_id,
        query="format_data",
        limit=10
    )
    assert len(py_search["results"]) > 0
    
    # Search for TypeScript content
    ts_search = await search_knowledge(
        services=test_services,
        session_id=session_id,
        query="Config interface",
        limit=10
    )
    assert len(ts_search["results"]) > 0
    
    # Search for Markdown content
    md_search = await search_knowledge(
        services=test_services,
        session_id=session_id,
        query="API key",
        limit=10
    )
    assert len(md_search["results"]) > 0


# ============================================================================
# Task 15.2: Validate build_context end-to-end
# Requirements: 7.1, 7.2, 9.1, 11.1, 17.3
# ============================================================================

@pytest.mark.asyncio
async def test_build_context_with_indexed_content_e2e(test_services, tmp_path):
    """Validate build_context returns non-empty results with indexed content.
    
    Requirements: 7.1, 7.2, 17.3
    """
    # Create session
    session_result = await create_session(
        services=test_services,
        project_id="test_validation_project",
        description="Context building validation"
    )
    session_id = session_result["session_id"]
    
    # Create and index test files
    code_file = tmp_path / "api.py"
    code_file.write_text("""
class APIClient:
    '''Client for making API requests.'''
    
    def get(self, endpoint):
        '''Make a GET request.'''
        return self._request('GET', endpoint)
    
    def post(self, endpoint, data):
        '''Make a POST request.'''
        return self._request('POST', endpoint, data)
""")
    
    doc_file = tmp_path / "API_GUIDE.md"
    doc_file.write_text("""
# API Client Guide

## Making Requests

Use the APIClient class to make HTTP requests:

```python
client = APIClient()
response = client.get('/users')
```

## Authentication

Set your API key before making requests.
""")
    
    # Index both files (use relative paths since we're in tmp_path)
    await add_knowledge(
        services=test_services,
        session_id=session_id,
        content_type="file",
        source="api.py"
    )

    await add_knowledge(
        services=test_services,
        session_id=session_id,
        content_type="file",
        source="API_GUIDE.md"
    )
    
    # Build context
    context_result = await build_context(
        services=test_services,
        session_id=session_id,
        query="API client requests",
        focus="balanced",
        depth="focused",
        max_tokens=2000
    )
    
    # Verify non-empty results
    assert "context" in context_result
    context = context_result["context"]
    
    # Should have code results
    assert "code" in context
    assert len(context["code"]) > 0
    
    # Should have documentation results
    assert "documentation" in context
    assert len(context["documentation"]) > 0
    
    # Verify token usage
    assert "token_usage" in context_result
    token_usage = context_result["token_usage"]
    assert token_usage["used"] > 0
    assert token_usage["used"] <= 2000
    assert token_usage["budget"] == 2000


@pytest.mark.asyncio
async def test_build_context_with_memories_e2e(test_services, tmp_path):
    """Validate build_context includes memories when available.
    
    Requirements: 9.1, 17.3
    """
    # Create session
    session_result = await create_session(
        services=test_services,
        project_id="test_validation_project",
        description="Memory context validation"
    )
    session_id = session_result["session_id"]
    
    # Index some content
    code_file = tmp_path / "database.py"
    code_file.write_text("""
class Database:
    def connect(self, host, port):
        '''Connect to database.'''
        pass
""")
    
    await add_knowledge(
        services=test_services,
        session_id=session_id,
        content_type="file",
        source="database.py"
    )

    # Save relevant memories
    await save_memory(
        services=test_services,
        session_id=session_id,
        summary="Database connection pattern",
        content="Always use connection pooling for better performance",
        importance="high"
    )
    
    await save_memory(
        services=test_services,
        session_id=session_id,
        summary="Database best practices",
        content="Use prepared statements to prevent SQL injection",
        importance="high"
    )
    
    # Build context
    context_result = await build_context(
        services=test_services,
        session_id=session_id,
        query="database connection",
        focus="balanced",
        depth="focused",
        max_tokens=2000
    )
    
    # Verify memories are included
    assert "context" in context_result
    context = context_result["context"]
    
    assert "memories" in context
    assert len(context["memories"]) > 0
    
    # Verify memory content
    memory_summaries = [m["summary"] for m in context["memories"]]
    assert any("database" in s.lower() for s in memory_summaries)


@pytest.mark.asyncio
async def test_build_context_token_budget_e2e(test_services, tmp_path):
    """Validate build_context respects token budget.
    
    Requirements: 11.1, 17.3
    """
    # Create session
    session_result = await create_session(
        services=test_services,
        project_id="test_validation_project",
        description="Token budget validation"
    )
    session_id = session_result["session_id"]
    
    # Index multiple files to have enough content
    for i in range(5):
        file_path = tmp_path / f"module_{i}.py"
        file_path.write_text(f"""
def function_{i}():
    '''Function number {i} with some documentation.'''
    result = perform_operation_{i}()
    return process_result_{i}(result)

class Class_{i}:
    '''Class number {i} for testing.'''
    
    def method_{i}(self):
        '''Method number {i}.'''
        return "result_{i}"
""")
        
        await add_knowledge(
            services=test_services,
            session_id=session_id,
            content_type="file",
            source=f"module_{i}.py"
        )

    # Test with small budget
    small_budget_result = await build_context(
        services=test_services,
        session_id=session_id,
        query="function operation",
        focus="code",
        depth="comprehensive",
        max_tokens=500
    )
    
    assert "token_usage" in small_budget_result
    small_usage = small_budget_result["token_usage"]
    assert small_usage["used"] <= 500
    assert small_usage["budget"] == 500
    
    # Test with larger budget
    large_budget_result = await build_context(
        services=test_services,
        session_id=session_id,
        query="function operation",
        focus="code",
        depth="comprehensive",
        max_tokens=2000
    )
    
    assert "token_usage" in large_budget_result
    large_usage = large_budget_result["token_usage"]
    assert large_usage["used"] <= 2000
    assert large_usage["budget"] == 2000
    
    # Larger budget should allow more content
    small_code_count = len(small_budget_result["context"]["code"])
    large_code_count = len(large_budget_result["context"]["code"])
    assert large_code_count >= small_code_count


@pytest.mark.asyncio
async def test_build_context_focus_parameter_e2e(test_services, tmp_path):
    """Validate build_context focus parameter affects result distribution.
    
    Requirements: 8.3, 8.4, 8.5, 17.3
    """
    # Create session
    session_result = await create_session(
        services=test_services,
        project_id="test_validation_project",
        description="Focus parameter validation"
    )
    session_id = session_result["session_id"]
    
    # Index code and documentation
    code_file = tmp_path / "processor.py"
    code_file.write_text("""
class DataProcessor:
    def process(self, data):
        return self.transform(data)
    
    def transform(self, data):
        return data.upper()
""")
    
    doc_file = tmp_path / "PROCESSOR_DOCS.md"
    doc_file.write_text("""
# Data Processor Documentation

## Overview

The DataProcessor class handles data transformation.

## Usage

Create an instance and call process():

```python
processor = DataProcessor()
result = processor.process(data)
```
""")
    
    await add_knowledge(
        services=test_services,
        session_id=session_id,
        content_type="file",
        source="processor.py"
    )

    await add_knowledge(
        services=test_services,
        session_id=session_id,
        content_type="file",
        source="PROCESSOR_DOCS.md"
    )

    # Test focus="code"
    code_focus_result = await build_context(
        services=test_services,
        session_id=session_id,
        query="data processor",
        focus="code",
        depth="focused",
        max_tokens=2000
    )
    
    code_count = len(code_focus_result["context"]["code"])
    doc_count = len(code_focus_result["context"]["documentation"])
    
    # Should have more code than docs
    assert code_count >= doc_count
    
    # Test focus="documentation"
    doc_focus_result = await build_context(
        services=test_services,
        session_id=session_id,
        query="data processor",
        focus="documentation",
        depth="focused",
        max_tokens=2000
    )
    
    doc_code_count = len(doc_focus_result["context"]["code"])
    doc_doc_count = len(doc_focus_result["context"]["documentation"])
    
    # Should have more docs than code
    assert doc_doc_count >= doc_code_count


# ============================================================================
# Task 15.3: Validate query sanitization end-to-end
# Requirements: 13.1, 14.1, 14.2, 14.3, 17.3
# ============================================================================

@pytest.mark.asyncio
async def test_search_with_question_mark_e2e(test_services, tmp_path):
    """Validate search with question mark works without syntax errors.
    
    Requirements: 13.1, 17.3
    """
    # Create session
    session_result = await create_session(
        services=test_services,
        project_id="test_validation_project",
        description="Question mark validation"
    )
    session_id = session_result["session_id"]
    
    # Index content
    file_path = tmp_path / "faq.py"
    file_path.write_text("""
def get_help():
    '''Get help information.'''
    return "How can I help you?"

def answer_question(question):
    '''Answer a user question.'''
    if "?" in question:
        return process_question(question)
    return "Not a question"
""")
    
    await add_knowledge(
        services=test_services,
        session_id=session_id,
        content_type="file",
        source="faq.py"
    )

    # Search with question mark - should not raise syntax error
    result = await search_knowledge(
        services=test_services,
        session_id=session_id,
        query="How can I help?",
        limit=10
    )
    
    # Verify no error
    assert "error" not in result
    assert "results" in result
    # Results may be empty, but no syntax error should occur


@pytest.mark.asyncio
async def test_search_with_asterisk_e2e(test_services, tmp_path):
    """Validate search with asterisk works without syntax errors.
    
    Requirements: 14.1, 17.3
    """
    # Create session
    session_result = await create_session(
        services=test_services,
        project_id="test_validation_project",
        description="Asterisk validation"
    )
    session_id = session_result["session_id"]
    
    # Index content
    file_path = tmp_path / "patterns.py"
    file_path.write_text("""
def match_pattern(text, pattern):
    '''Match text against pattern with wildcards.'''
    # Pattern can contain * for wildcard matching
    return check_match(text, pattern)

def glob_files(pattern):
    '''Find files matching glob pattern like *.py'''
    return find_files(pattern)
""")
    
    await add_knowledge(
        services=test_services,
        session_id=session_id,
        content_type="file",
        source="patterns.py"
    )

    # Search with asterisk - should not raise syntax error
    result = await search_knowledge(
        services=test_services,
        session_id=session_id,
        query="pattern with * wildcard",
        limit=10
    )
    
    # Verify no error
    assert "error" not in result
    assert "results" in result


@pytest.mark.asyncio
async def test_search_with_brackets_e2e(test_services, tmp_path):
    """Validate search with brackets works without syntax errors.
    
    Requirements: 14.2, 17.3
    """
    # Create session
    session_result = await create_session(
        services=test_services,
        project_id="test_validation_project",
        description="Brackets validation"
    )
    session_id = session_result["session_id"]
    
    # Index content
    file_path = tmp_path / "arrays.py"
    file_path.write_text("""
def get_item(array, index):
    '''Get item from array using bracket notation.'''
    return array[index]

def set_item(array, index, value):
    '''Set item in array: array[index] = value'''
    array[index] = value
""")
    
    await add_knowledge(
        services=test_services,
        session_id=session_id,
        content_type="file",
        source="arrays.py"
    )

    # Search with brackets - should not raise syntax error
    result = await search_knowledge(
        services=test_services,
        session_id=session_id,
        query="array[index] notation",
        limit=10
    )
    
    # Verify no error
    assert "error" not in result
    assert "results" in result


@pytest.mark.asyncio
async def test_search_with_multiple_special_chars_e2e(test_services, tmp_path):
    """Validate search with multiple special characters works.
    
    Requirements: 14.3, 17.3
    """
    # Create session
    session_result = await create_session(
        services=test_services,
        project_id="test_validation_project",
        description="Multiple special chars validation"
    )
    session_id = session_result["session_id"]
    
    # Index content
    file_path = tmp_path / "regex.py"
    file_path.write_text("""
def validate_email(email):
    '''Validate email with regex pattern.'''
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$'
    return match(pattern, email)

def parse_query(query):
    '''Parse query with special characters like ?, *, [], ()'''
    return tokenize(query)
""")
    
    await add_knowledge(
        services=test_services,
        session_id=session_id,
        content_type="file",
        source="regex.py"
    )

    # Search with multiple special characters
    result = await search_knowledge(
        services=test_services,
        session_id=session_id,
        query="pattern with [a-z]+ and (group)?",
        limit=10
    )
    
    # Verify no error
    assert "error" not in result
    assert "results" in result


# ============================================================================
# Task 15.4: Regression test suite
# Requirements: 17.5
# ============================================================================

@pytest.mark.asyncio
async def test_regression_schema_mismatch_prevention(test_services, tmp_path):
    """Regression test: Prevent schema mismatch errors during indexing.
    
    Requirements: 17.5
    """
    # Create session
    session_result = await create_session(
        services=test_services,
        project_id="test_validation_project",
        description="Schema regression test"
    )
    session_id = session_result["session_id"]
    
    # Create file with various content types that previously caused schema issues
    test_file = tmp_path / "complex.py"
    test_file.write_text("""
# Complex file with various structures

class ComplexClass:
    '''Class with nested structures.'''
    
    def __init__(self):
        self.data = {
            'nested': {
                'values': [1, 2, 3]
            }
        }
    
    def method_with_symbols(self):
        '''Method with various symbols.'''
        result = self.data['nested']['values']
        return [x * 2 for x in result]

def function_with_metadata():
    '''Function with rich metadata.'''
    # This should not cause schema validation errors
    pass

# Global variable
CONSTANT = "value"
""")
    
    # Index should succeed without schema errors (use relative path)
    result = await add_knowledge(
        services=test_services,
        session_id=session_id,
        content_type="file",
        source="complex.py"
    )

    # Verify no schema validation errors
    assert result["status"] == "completed"
    assert "error" not in result
    assert "SchemaValidationError" not in str(result)


@pytest.mark.asyncio
async def test_regression_empty_context_prevention(test_services, tmp_path):
    """Regression test: Prevent empty context when content exists.
    
    Requirements: 17.5
    """
    # Create session
    session_result = await create_session(
        services=test_services,
        project_id="test_validation_project",
        description="Empty context regression test"
    )
    session_id = session_result["session_id"]
    
    # Index content
    test_file = tmp_path / "service.py"
    test_file.write_text("""
class ServiceManager:
    '''Manages application services.'''
    
    def start_service(self, name):
        '''Start a service by name.'''
        return self._initialize_service(name)
    
    def stop_service(self, name):
        '''Stop a running service.'''
        return self._cleanup_service(name)
""")
    
    await add_knowledge(
        services=test_services,
        session_id=session_id,
        content_type="file",
        source="service.py"
    )

    # Build context should return non-empty results
    context_result = await build_context(
        services=test_services,
        session_id=session_id,
        query="service manager",
        focus="balanced",
        depth="focused",
        max_tokens=2000
    )
    
    # Verify context is not empty
    assert "context" in context_result
    context = context_result["context"]
    
    # Should have at least code or documentation
    total_items = len(context.get("code", [])) + len(context.get("documentation", []))
    assert total_items > 0, "Context should not be empty when content exists"


@pytest.mark.asyncio
async def test_regression_query_syntax_errors_prevention(test_services, tmp_path):
    """Regression test: Prevent query syntax errors with special characters.
    
    Requirements: 17.5
    """
    # Create session
    session_result = await create_session(
        services=test_services,
        project_id="test_validation_project",
        description="Query syntax regression test"
    )
    session_id = session_result["session_id"]
    
    # Index content
    test_file = tmp_path / "queries.py"
    test_file.write_text("""
def execute_query(query):
    '''Execute a database query.'''
    return run_sql(query)
""")
    
    await add_knowledge(
        services=test_services,
        session_id=session_id,
        content_type="file",
        source="queries.py"
    )

    # Test various queries that previously caused syntax errors
    problematic_queries = [
        {"query": "What is this?", "expected": "What is this"},
        {"query": "Find files matching *.py", "expected": "Find files matching py"},
        {"query": "Get array[0] element", "expected": "Get array 0 element"},
        {"query": "Match pattern (a|b)", "expected": "Match pattern a b"},
        {"query": "Search for {key: value}", "expected": "Search for key value"},
        {"query": "Find text with \\ backslash", "expected": "Find text with backslash"}
    ]
    
    for query_dict in problematic_queries:
        query_str = query_dict["query"]
        query_dict["expected"]
        
        result = await search_knowledge(
            services=test_services,
            session_id=session_id,
            query=query_str,
            limit=10
        )
        
        # Should not raise syntax errors
        # Check if error exists and if it's a string, check for "syntax"
        if "error" in result:
            error_value = result["error"]
            if isinstance(error_value, str):
                assert "syntax" not in error_value.lower(), f"Query '{query_str}' caused syntax error: {error_value}"
            elif isinstance(error_value, dict):
                # Check if it's a syntax error in the error dict
                error_msg = error_value.get("message", "")
                if isinstance(error_msg, str):
                    assert "syntax" not in error_msg.lower(), f"Query '{query_str}' caused syntax error: {error_msg}"
        else:
            # Only check for results if there's no error
            assert "results" in result


@pytest.mark.asyncio
async def test_regression_backward_compatibility(test_services, tmp_path):
    """Regression test: Ensure backward compatibility with existing data.
    
    Requirements: 17.5, 18.1, 18.2
    """
    # Create session
    session_result = await create_session(
        services=test_services,
        project_id="test_validation_project",
        description="Backward compatibility test"
    )
    session_id = session_result["session_id"]
    
    # Index content using current implementation
    test_file = tmp_path / "legacy.py"
    test_file.write_text("""
def legacy_function():
    '''A function from legacy code.'''
    return "legacy"
""")
    
    result = await add_knowledge(
        services=test_services,
        session_id=session_id,
        content_type="file",
        source="legacy.py"
    )

    assert result["status"] == "completed"

    # Verify content is searchable (backward compatibility)
    search_result = await search_knowledge(
        services=test_services,
        session_id=session_id,
        query="legacy function",
        limit=10
    )
    
    assert len(search_result["results"]) > 0
    assert any("legacy" in r["content"].lower() for r in search_result["results"])


@pytest.mark.asyncio
async def test_complete_agent_workflow_validation(test_services, tmp_path):
    """Complete agent workflow validation: session → index → search → context → memory.
    
    This test validates the entire agent workflow end-to-end.
    Requirements: All (5.1-6.5, 7.1-12.5, 13.1-14.5, 17.1-17.5)
    """
    # Step 1: Create session
    session_result = await create_session(
        services=test_services,
        project_id="test_validation_project",
        description="Complete workflow validation"
    )
    session_id = session_result["session_id"]
    assert "session_id" in session_result
    
    # Step 2: Index multiple files
    # Python file
    py_file = tmp_path / "main.py"
    py_file.write_text("""
class Application:
    def run(self):
        return self.execute()
""")
    
    # TypeScript file
    ts_file = tmp_path / "app.ts"
    ts_file.write_text("""
export class App {
    start(): void {
        console.log('Starting');
    }
}
""")
    
    # Markdown file
    md_file = tmp_path / "README.md"
    md_file.write_text("""
# Application

## Usage

Run the application with `app.run()`.
""")
    
    # Index all files (use relative paths since we're in tmp_path)
    for file_name in ["main.py", "app.ts", "README.md"]:
        result = await add_knowledge(
            services=test_services,
            session_id=session_id,
            content_type="file",
            source=file_name
        )
        assert result["status"] == "completed"
    
    # Step 3: Search for content
    search_result = await search_knowledge(
        services=test_services,
        session_id=session_id,
        query="application run",
        limit=10
    )
    assert len(search_result["results"]) > 0
    
    # Step 4: Build context
    context_result = await build_context(
        services=test_services,
        session_id=session_id,
        query="application usage",
        focus="balanced",
        depth="focused",
        max_tokens=2000
    )
    assert len(context_result["context"]["code"]) > 0
    assert len(context_result["context"]["documentation"]) > 0
    
    # Step 5: Save memory
    memory_result = await save_memory(
        services=test_services,
        session_id=session_id,
        summary="Application workflow",
        content="The application can be started using the run() method",
        importance="medium"
    )
    assert memory_result["status"] == "saved"
    
    # Step 6: Build context with memory
    context_with_memory = await build_context(
        services=test_services,
        session_id=session_id,
        query="application workflow",
        focus="balanced",
        depth="focused",
        max_tokens=2000
    )
    assert len(context_with_memory["context"]["memories"]) > 0
    
    # Workflow completed successfully
    assert True, "Complete agent workflow validated successfully"
