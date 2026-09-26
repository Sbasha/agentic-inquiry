"""Integration tests for add_knowledge tool with real file indexing.

Tests the complete flow of indexing Python, TypeScript, and Markdown files,
verifying that files are successfully indexed and searchable.
"""

import pytest

pytestmark = pytest.mark.integration

from agentic_inquiry.mcp.tools.knowledge import add_knowledge


@pytest.fixture
def patch_indexing_pipeline(mcp_services):
    """No patching needed - IndexingPipeline now accepts event_system parameter.

    The add_knowledge function passes event_system from services to IndexingPipeline,
    so the mock event_system from mcp_services will be used.
    """
    yield None


@pytest.mark.asyncio
async def test_add_knowledge_python_file(
    mcp_services, patch_indexing_pipeline, tmp_path, monkeypatch
):
    """Test indexing a Python file end-to-end.

    Requirements: 5.1, 5.5, 17.2
    """
    # Change to tmp_path so relative paths work
    monkeypatch.chdir(tmp_path)

    # Create test Python file with known content
    test_file = tmp_path / "test_module.py"
    test_content = '''"""Test module for integration testing."""

def calculate_sum(a: int, b: int) -> int:
    """Calculate the sum of two numbers."""
    return a + b

class Calculator:
    """A simple calculator class."""
    
    def multiply(self, x: float, y: float) -> float:
        """Multiply two numbers."""
        return x * y
'''
    test_file.write_text(test_content)

    # Index the file using relative path and the session_id from fixture
    result = await add_knowledge(
        services=mcp_services,
        session_id=mcp_services["test_session_id"],
        content_type="file",
        source="test_module.py",  # Use relative path
    )

    # Verify status is "completed"
    assert result["status"] == "completed", f"Expected completed status, got: {result}"

    # Verify items_processed count is correct
    assert result["items_processed"] == 1, (
        f"Expected 1 item processed, got: {result['items_processed']}"
    )

    # Verify chunks were created
    assert result["chunks_created"] > 0, "Expected chunks to be created"

    # Verify entities were created (functions and classes)
    assert result["entities_created"] > 0, "Expected entities to be created"

    # Search for content and verify results using the search_service from fixture
    search_service = mcp_services["search_service"]

    # Search for function name using FTS
    search_results = await search_service.fts_search(
        query_fts="calculate_sum", project_id="test_integration_project", limit=10
    )

    assert len(search_results) > 0, "Expected search results for 'calculate_sum'"
    # SearchResult.data contains the content
    assert any("calculate_sum" in r.data.get("content", "") for r in search_results), (
        "Expected to find 'calculate_sum' in search results"
    )

    # Search for class name
    search_results = await search_service.fts_search(
        query_fts="Calculator", project_id="test_integration_project", limit=10
    )

    assert len(search_results) > 0, "Expected search results for 'Calculator'"
    assert any("Calculator" in r.data.get("content", "") for r in search_results), (
        "Expected to find 'Calculator' in search results"
    )


@pytest.mark.asyncio
async def test_add_knowledge_typescript_file(
    mcp_services, patch_indexing_pipeline, tmp_path, monkeypatch
):
    """Test indexing a TypeScript file end-to-end.

    Requirements: 5.2, 5.5
    """
    # Change to tmp_path so relative paths work
    monkeypatch.chdir(tmp_path)

    # Create test TypeScript file
    test_file = tmp_path / "test_component.ts"
    test_content = """/**
 * User interface component
 */
export interface User {
    id: string;
    name: string;
    email: string;
}

/**
 * Fetch user data from API
 */
export async function fetchUser(userId: string): Promise<User> {
    const response = await fetch(`/api/users/${userId}`);
    return response.json();
}

/**
 * User service class
 */
export class UserService {
    private baseUrl: string;
    
    constructor(baseUrl: string) {
        this.baseUrl = baseUrl;
    }
    
    async getUser(id: string): Promise<User> {
        return fetchUser(id);
    }
}
"""
    test_file.write_text(test_content)

    # Index the file using relative path and the session_id from fixture
    result = await add_knowledge(
        services=mcp_services,
        session_id=mcp_services["test_session_id"],
        content_type="file",
        source="test_component.ts",  # Use relative path
    )

    # Verify successful indexing
    assert result["status"] == "completed"
    assert result["items_processed"] == 1
    assert result["chunks_created"] > 0

    # Verify searchable content
    from agentic_inquiry.search.service import SearchService

    search_service = SearchService(
        storage=mcp_services["storage"],  # Use StorageFacade for SearchService
        config=mcp_services["config"],
        event_system=mcp_services["event_system"],
        project_id="test_integration_project",
    )

    # Search for interface
    search_results = await search_service.fts_search(
        query_fts="User interface", project_id="test_integration_project", limit=10
    )

    assert len(search_results) > 0, "Expected search results for TypeScript interface"

    # Search for function
    search_results = await search_service.fts_search(
        query_fts="fetchUser", project_id="test_integration_project", limit=10
    )

    assert len(search_results) > 0, "Expected search results for 'fetchUser'"
    assert any("fetchUser" in r.data.get("content", "") for r in search_results)


@pytest.mark.asyncio
async def test_add_knowledge_markdown_file(
    mcp_services, patch_indexing_pipeline, tmp_path, monkeypatch
):
    """Test indexing a Markdown file end-to-end.

    Requirements: 5.3, 5.5
    """
    # Change to tmp_path so relative paths work
    monkeypatch.chdir(tmp_path)

    # Create test Markdown file
    test_file = tmp_path / "README.md"
    test_content = """# Test Documentation

This is a test documentation file for integration testing.

## Features

The system provides the following features:

- **Semantic Search**: Find code by meaning, not just keywords
- **Knowledge Graph**: Track relationships between code entities
- **Multi-language Support**: Works with Python, TypeScript, and more

## Getting Started

To get started with the system:

1. Install dependencies
2. Configure your project
3. Index your codebase

### Configuration

Configure the system using YAML:

```yaml
storage:
  root: ./data
search:
  default_limit: 10
```

## API Reference

The main API includes:

- `add_knowledge()` - Index files into the knowledge base
- `search_knowledge()` - Search indexed content
- `build_context()` - Build intelligent context
"""
    test_file.write_text(test_content)

    # Index the file using relative path and the session_id from fixture
    result = await add_knowledge(
        services=mcp_services,
        session_id=mcp_services["test_session_id"],
        content_type="file",
        source="README.md",  # Use relative path
    )

    # Verify successful indexing
    assert result["status"] == "completed"
    assert result["items_processed"] == 1
    assert result["chunks_created"] > 0

    # Verify searchable content
    from agentic_inquiry.search.service import SearchService

    search_service = SearchService(
        storage=mcp_services["storage"],  # Use StorageFacade for SearchService
        config=mcp_services["config"],
        event_system=mcp_services["event_system"],
        project_id="test_integration_project",
    )

    # Search for heading content
    search_results = await search_service.fts_search(
        query_fts="Semantic Search", project_id="test_integration_project", limit=10
    )

    assert len(search_results) > 0, "Expected search results for 'Semantic Search'"

    # Search for API reference
    search_results = await search_service.fts_search(
        query_fts="add_knowledge", project_id="test_integration_project", limit=10
    )

    assert len(search_results) > 0, "Expected search results for 'add_knowledge'"
    assert any("add_knowledge" in r.data.get("content", "") for r in search_results)


@pytest.mark.asyncio
async def test_add_knowledge_directory_mixed_files(
    mcp_services, patch_indexing_pipeline, tmp_path, monkeypatch
):
    """Test indexing a directory with mixed file types.

    Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
    """
    # Change to tmp_path so relative paths work
    monkeypatch.chdir(tmp_path)

    # Create test directory with mixed file types
    test_dir = tmp_path / "test_project"
    test_dir.mkdir()

    # Create Python file
    (test_dir / "utils.py").write_text('''def helper_function():
    """A helper function."""
    return "helper"
''')

    # Create TypeScript file
    (test_dir / "types.ts").write_text("""export interface Config {
    name: string;
    value: number;
}
""")

    # Create Markdown file
    (test_dir / "docs.md").write_text("""# Documentation

This is documentation content.
""")

    # Create a subdirectory with more files
    sub_dir = test_dir / "subdir"
    sub_dir.mkdir()
    (sub_dir / "module.py").write_text("""class MyClass:
    pass
""")

    # Get session_id from fixture
    session_id = mcp_services["test_session_id"]

    # Index entire directory (now async) using relative path
    result = await add_knowledge(
        services=mcp_services,
        session_id=session_id,
        content_type="directory",
        source="test_project",
    )

    # Verify async indexing started
    assert result["status"] == "started"
    assert "operation_id" in result

    # Poll for completion (with timeout)
    import asyncio

    session_manager = mcp_services["session_manager"]
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
                    pytest.fail(
                        f"Indexing failed: {event.get('data', {}).get('error')}"
                    )

        if completed:
            break

        # Wait before polling again
        await asyncio.sleep(0.5)

    # Verify completion
    if not completed:
        pytest.fail(f"Indexing did not complete within {timeout} seconds")

    # Verify all files processed
    assert final_event is not None
    expected_files = 4  # utils.py, types.ts, docs.md, module.py
    assert final_event["data"]["items_processed"] == expected_files, (
        f"Expected {expected_files} files processed, got: {final_event['data']['items_processed']}"
    )
    assert final_event["data"]["chunks_created"] > 0, "Expected chunks to be created"

    # Verify all files are searchable
    from agentic_inquiry.search.service import SearchService

    search_service = SearchService(
        storage=mcp_services["storage"],  # Use StorageFacade for SearchService
        config=mcp_services["config"],
        event_system=mcp_services["event_system"],
        project_id="test_integration_project",
    )

    # Search for Python content
    search_results = await search_service.fts_search(
        query_fts="helper_function", project_id="test_integration_project", limit=10
    )
    assert len(search_results) > 0, "Expected to find Python content"

    # Search for TypeScript content
    search_results = await search_service.fts_search(
        query_fts="Config", project_id="test_integration_project", limit=10
    )
    assert len(search_results) > 0, "Expected to find TypeScript content"

    # Search for Markdown content
    search_results = await search_service.fts_search(
        query_fts="Documentation", project_id="test_integration_project", limit=10
    )
    assert len(search_results) > 0, "Expected to find Markdown content"

    # Search for subdirectory content
    search_results = await search_service.fts_search(
        query_fts="MyClass", project_id="test_integration_project", limit=10
    )
    assert len(search_results) > 0, "Expected to find subdirectory content"


@pytest.mark.asyncio
async def test_add_knowledge_error_handling_invalid_path(
    mcp_services, patch_indexing_pipeline, tmp_path, monkeypatch
):
    """Test error handling with invalid file path.

    Requirements: 6.4, 15.1, 15.2, 15.3
    """
    # Change to tmp_path so relative paths work
    monkeypatch.chdir(tmp_path)

    # Test with non-existent file using the session_id from fixture
    result = await add_knowledge(
        services=mcp_services,
        session_id=mcp_services["test_session_id"],
        content_type="file",
        source="nonexistent.py",  # Use relative path
    )

    # Verify clear error message - MCPErrorHandler returns nested error structure
    assert "error" in result, f"Expected error in result, got: {result}"

    # Extract error message from nested structure
    error_info = result["error"]
    if isinstance(error_info, dict):
        error_msg = error_info.get("message", "")
    else:
        error_msg = str(error_info)

    # Verify the error message contains relevant information about missing file
    assert error_msg, f"Expected non-empty error message, got result: {result}"
    assert any(
        keyword in error_msg.lower()
        for keyword in ["not found", "does not exist", "file", "no such"]
    ), f"Expected error message about missing file, got: {error_msg}"


@pytest.mark.asyncio
async def test_add_knowledge_error_handling_unsupported_file(
    mcp_services, patch_indexing_pipeline, tmp_path, monkeypatch
):
    """Test error handling with unsupported file type.

    Requirements: 6.4, 15.1, 15.2, 15.3
    """
    # Change to tmp_path so relative paths work
    monkeypatch.chdir(tmp_path)

    # Create unsupported file type
    test_file = tmp_path / "test.bin"
    test_file.write_bytes(b"\x00\x01\x02\x03")

    # Try to index it using relative path and the session_id from fixture
    result = await add_knowledge(
        services=mcp_services,
        session_id=mcp_services["test_session_id"],
        content_type="file",
        source="test.bin",  # Use relative path
    )

    # Should still complete (fallback parser handles it)
    # or fail gracefully with clear error
    assert result["status"] in ["completed", "error", "failed"]
    if result["status"] in ["error", "failed"]:
        assert "error" in result


@pytest.mark.asyncio
async def test_add_knowledge_directory_continues_on_error(
    mcp_services, patch_indexing_pipeline, tmp_path, monkeypatch
):
    """Test that directory indexing continues when some files fail.

    Requirements: 6.4, 15.1, 15.2, 15.3
    """
    # Change to tmp_path so relative paths work
    monkeypatch.chdir(tmp_path)

    # Create test directory
    test_dir = tmp_path / "test_project"
    test_dir.mkdir()

    # Create valid Python file
    (test_dir / "valid.py").write_text("""def valid_function():
    return True
""")

    # Create another valid file
    (test_dir / "also_valid.py").write_text("""def another_function():
    return False
""")

    # Create a file that might cause issues (empty file)
    (test_dir / "empty.py").write_text("")

    # Get session_id from fixture
    session_id = mcp_services["test_session_id"]

    # Index directory (now async) using relative path
    result = await add_knowledge(
        services=mcp_services,
        session_id=session_id,
        content_type="directory",
        source="test_project",  # Use relative path
    )

    # Verify async indexing started
    assert result["status"] == "started"
    assert "operation_id" in result

    # Poll for completion (with timeout)
    import asyncio

    session_manager = mcp_services["session_manager"]
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
                    pytest.fail(
                        f"Indexing failed: {event.get('data', {}).get('error')}"
                    )

        if completed:
            break

        # Wait before polling again
        await asyncio.sleep(0.5)

    # Verify completion
    if not completed:
        pytest.fail(f"Indexing did not complete within {timeout} seconds")

    # Verify other files continue processing
    assert final_event is not None
    # At least the valid files should be processed (empty.py may or may not be processed)
    assert final_event["data"]["items_processed"] >= 2


@pytest.mark.asyncio
async def test_add_knowledge_directory_with_gitignore(
    mcp_services, patch_indexing_pipeline, tmp_path, monkeypatch
):
    """Test that directory indexing respects .gitignore patterns.

    Requirements: 6.1, 6.2
    """
    # Change to tmp_path so relative paths work
    monkeypatch.chdir(tmp_path)

    # Create test directory
    test_dir = tmp_path / "test_project"
    test_dir.mkdir()

    # Create .gitignore
    (test_dir / ".gitignore").write_text("""# Ignore build directory
build/
*.pyc
__pycache__/
""")

    # Create files that should be indexed
    (test_dir / "main.py").write_text("def main(): pass")

    # Create files that should be ignored
    build_dir = test_dir / "build"
    build_dir.mkdir()
    (build_dir / "output.py").write_text("# Should be ignored")

    pycache_dir = test_dir / "__pycache__"
    pycache_dir.mkdir()
    (pycache_dir / "cache.pyc").write_text("# Should be ignored")

    # Get session_id from fixture
    session_id = mcp_services["test_session_id"]

    # Index directory (now async) using relative path
    result = await add_knowledge(
        services=mcp_services,
        session_id=session_id,
        content_type="directory",
        source="test_project",  # Use relative path
    )

    # Verify async indexing started
    assert result["status"] == "started"
    assert "operation_id" in result

    # Poll for completion (with timeout)
    import asyncio

    session_manager = mcp_services["session_manager"]
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
                    pytest.fail(
                        f"Indexing failed: {event.get('data', {}).get('error')}"
                    )

        if completed:
            break

        # Wait before polling again
        await asyncio.sleep(0.5)

    # Verify completion
    if not completed:
        pytest.fail(f"Indexing did not complete within {timeout} seconds")

    # Verify only non-ignored files were processed
    assert final_event is not None
    # Should only index main.py, not files in build/ or __pycache__/
    assert final_event["data"]["items_processed"] == 1


@pytest.mark.asyncio
async def test_add_knowledge_text_content(mcp_services, patch_indexing_pipeline):
    """Test indexing raw text content.

    Requirements: 5.1, 5.5
    """
    # Index text content using the session_id from fixture
    text_content = """This is raw text content for testing.
It contains multiple lines and should be indexed as a single chunk.
We can search for this content later."""

    result = await add_knowledge(
        services=mcp_services,
        session_id=mcp_services["test_session_id"],
        content_type="text",
        source=text_content,
    )

    # Verify successful indexing
    assert result["status"] == "completed"
    assert result["items_processed"] == 1
    assert result["chunks_created"] == 1
    assert result["content_type"] == "text"

    # Verify searchable
    from agentic_inquiry.search.service import SearchService

    search_service = SearchService(
        storage=mcp_services["storage"],  # Use StorageFacade for SearchService
        config=mcp_services["config"],
        event_system=mcp_services["event_system"],
        project_id="test_integration_project",
    )

    search_results = await search_service.fts_search(
        query_fts="raw text content", project_id="test_integration_project", limit=10
    )

    assert len(search_results) > 0, "Expected to find text content in search"
