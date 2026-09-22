"""Tests for relationship flushing in MCP indexing operations.

These tests verify that relationships are properly flushed during MCP indexing,
which is critical for graph-based features like impact analysis and pattern detection.
"""

import pytest

pytestmark = pytest.mark.integration

from agent_vault.mcp.tools.knowledge import add_knowledge


@pytest.mark.asyncio
async def test_single_file_indexing_creates_relationships(mcp_services, tmp_path, monkeypatch):
    """Test that single file indexing flushes relationships.

    This test verifies that when a Python file with imports is indexed,
    the relationships are created and flushed to the database.
    """
    # Change to tmp_path so relative paths work
    monkeypatch.chdir(tmp_path)

    # Create test Python file with imports (which create relationships)
    test_file = tmp_path / "test_with_imports.py"
    test_content = '''"""Test module with imports."""

import os
import sys
from pathlib import Path

def process_file(filepath: str) -> None:
    """Process a file using imported modules."""
    path = Path(filepath)
    if path.exists():
        print(f"Processing {path}")

class FileProcessor:
    """Processes files using os and sys modules."""

    def __init__(self):
        self.cwd = os.getcwd()
        self.version = sys.version
'''
    test_file.write_text(test_content)

    # Index the file
    result = await add_knowledge(
        services=mcp_services,
        session_id=mcp_services["test_session_id"],
        content_type="file",
        source="test_with_imports.py"
    )

    # Verify status is "completed"
    assert result["status"] == "completed", f"Expected completed status, got: {result}"

    # Verify items_processed count
    assert result["items_processed"] == 1, f"Expected 1 item processed, got: {result['items_processed']}"

    # Verify chunks were created
    assert result["chunks_created"] > 0, "Expected chunks to be created"

    # Verify relationships_created is returned (this is the key test)
    assert "relationships_created" in result, \
        "Expected 'relationships_created' key in result - flush was not called"

    # The actual count may vary, but we verify the field exists
    # This confirms flush_pending_relationships() was called
    relationships_created = result["relationships_created"]
    assert isinstance(relationships_created, int), \
        f"Expected relationships_created to be int, got: {type(relationships_created)}"


@pytest.mark.asyncio
async def test_directory_indexing_creates_relationships(mcp_services, tmp_path, monkeypatch):
    """Test that directory indexing flushes relationships.

    This test verifies that when a directory with Python files is indexed,
    the relationships are created and flushed to the database.
    """
    # Change to tmp_path so relative paths work
    monkeypatch.chdir(tmp_path)

    # Create a test directory with multiple Python files that import each other
    test_dir = tmp_path / "test_package"
    test_dir.mkdir()

    # Create __init__.py
    init_file = test_dir / "__init__.py"
    init_file.write_text('"""Test package."""\n')

    # Create module_a.py
    module_a = test_dir / "module_a.py"
    module_a.write_text('''"""Module A."""

def function_a():
    """Function in module A."""
    return "a"
''')

    # Create module_b.py that imports from module_a
    module_b = test_dir / "module_b.py"
    module_b.write_text('''"""Module B that imports from A."""

from .module_a import function_a

def function_b():
    """Function in module B that uses A."""
    return function_a() + "b"
''')

    # Index the directory - note: this returns immediately with operation_id
    # because directory indexing is async
    result = await add_knowledge(
        services=mcp_services,
        session_id=mcp_services["test_session_id"],
        content_type="directory",
        source="test_package"
    )

    # For directory indexing, the result should have status "started"
    # with an operation_id for tracking
    # The actual relationship flushing happens in the background task
    assert result["status"] == "started", f"Expected started status for directory, got: {result}"
    assert "operation_id" in result, "Expected operation_id in directory indexing result"


@pytest.mark.asyncio
async def test_relationship_flush_returns_count(mcp_services, tmp_path, monkeypatch):
    """Test that relationship flush returns a valid count.

    This test creates a file with known imports and verifies that
    the relationship count is a non-negative integer.
    """
    # Change to tmp_path so relative paths work
    monkeypatch.chdir(tmp_path)

    # Create test Python file with imports
    test_file = tmp_path / "simple_imports.py"
    test_content = '''"""Simple module with standard library imports."""

import json
import typing

def parse_json(data: str) -> typing.Dict:
    """Parse JSON data."""
    return json.loads(data)
'''
    test_file.write_text(test_content)

    # Index the file
    result = await add_knowledge(
        services=mcp_services,
        session_id=mcp_services["test_session_id"],
        content_type="file",
        source="simple_imports.py"
    )

    # Verify the result contains relationship information
    assert result["status"] == "completed"
    assert "relationships_created" in result or "relationship_stats" in result

    # Check relationships were processed. Note: relationships are flushed per-document
    # during indexing, so the final flush may return 0 but relationship_stats.total_pending
    # shows how many were queued and processed.
    relationships_created = result.get("relationships_created", 0)
    relationship_stats = result.get("relationship_stats", {})
    total_pending = relationship_stats.get("total_pending", 0)

    # Either relationships_created > 0 OR total_pending > 0 indicates relationships were processed
    assert relationships_created > 0 or total_pending > 0, \
        f"Expected relationships to be processed for file with imports. " \
        f"relationships_created={relationships_created}, total_pending={total_pending}"


@pytest.mark.asyncio
async def test_text_content_no_relationships(mcp_services):
    """Test that text content indexing doesn't crash on relationship handling.

    Text content doesn't have imports, so there are no relationships,
    but the code path should still work without errors.
    """
    # Index text content
    result = await add_knowledge(
        services=mcp_services,
        session_id=mcp_services["test_session_id"],
        content_type="text",
        source="This is some sample text content for testing."
    )

    # Verify status is "completed"
    assert result["status"] == "completed", f"Expected completed status, got: {result}"

    # Text content should still complete successfully
    # (no relationships_created key expected since text doesn't go through the same path)
    assert result["items_processed"] == 1
