"""Integration tests for consistent error handling across MCP tools.

This module tests:
- Error format consistency across different tools
- Context-aware suggestions are included
- Related tool recommendations
- Debugging information is present
- Error responses follow MCPErrorHandler format
"""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock
from typing import Dict, Any

from agent_vault.mcp.tools.memory import save_memory, recall_memories
from agent_vault.mcp.tools.analysis import understand_entity, analyze_impact, find_patterns
from agent_vault.mcp.tools.context import build_context
from agent_vault.mcp.tools.knowledge import add_knowledge


@pytest.fixture
def mcp_services():
    """Create mock services for testing."""
    session_manager = MagicMock()
    session_manager.validate_session = AsyncMock(return_value=False)
    
    return {
        "session_manager": session_manager,
        "memory_system": MagicMock(),
        "search_service": MagicMock(),
        "event_system": MagicMock(),
        "context_builder": MagicMock(),
        "pattern_analyzer": MagicMock(),
        "entity_resolver": MagicMock(),
        "impact_analyzer": MagicMock(),
        "config": MagicMock(),
        "storage": MagicMock(),
    }


def verify_error_response_structure(result: Dict[str, Any]) -> None:
    """Verify that error response follows MCPErrorHandler format.
    
    Args:
        result: Error response dictionary to verify
    """
    # Verify required top-level fields
    assert "error" in result, "Error response must have 'error' field"
    assert "suggestions" in result, "Error response must have 'suggestions' field"
    assert "related_tools" in result, "Error response must have 'related_tools' field"
    assert "context" in result, "Error response must have 'context' field"
    
    # Verify error object structure
    error = result["error"]
    assert "code" in error, "Error must have 'code' field"
    assert "message" in error, "Error must have 'message' field"
    assert "help" in error, "Error must have 'help' field"
    assert "details" in error, "Error must have 'details' field"
    
    # Verify types
    assert isinstance(result["suggestions"], list), "Suggestions must be a list"
    assert isinstance(result["related_tools"], list), "Related tools must be a list"
    assert isinstance(result["context"], dict), "Context must be a dict"
    assert isinstance(error["code"], str), "Error code must be a string"
    assert isinstance(error["message"], str), "Error message must be a string"
    assert isinstance(error["help"], str), "Error help must be a string"


@pytest.mark.asyncio
async def test_memory_save_error_format(mcp_services):
    """Test that save_memory returns consistent error format."""
    result = await save_memory(
        services=mcp_services,
        session_id="invalid-session",
        summary="Test summary",
        content="Test content"
    )
    
    verify_error_response_structure(result)
    assert result["error"]["code"] == "SESSION_NOT_FOUND"
    assert "invalid-session" in result["error"]["message"]
    assert len(result["suggestions"]) > 0


@pytest.mark.asyncio
async def test_memory_recall_error_format(mcp_services):
    """Test that recall_memories returns consistent error format."""
    result = await recall_memories(
        services=mcp_services,
        session_id="invalid-session",
        query="test query"
    )
    
    verify_error_response_structure(result)
    assert result["error"]["code"] == "SESSION_NOT_FOUND"
    assert "invalid-session" in result["error"]["message"]
    assert len(result["suggestions"]) > 0


@pytest.mark.asyncio
async def test_analysis_understand_entity_error_format(mcp_services):
    """Test that understand_entity returns consistent error format."""
    result = await understand_entity(
        services=mcp_services,
        session_id="invalid-session",
        entity="TestEntity"
    )
    
    verify_error_response_structure(result)
    assert result["error"]["code"] == "SESSION_NOT_FOUND"
    assert "invalid-session" in result["error"]["message"]
    assert len(result["suggestions"]) > 0


@pytest.mark.asyncio
async def test_analysis_analyze_impact_error_format(mcp_services):
    """Test that analyze_impact returns consistent error format."""
    result = await analyze_impact(
        services=mcp_services,
        session_id="invalid-session",
        entity="TestEntity"
    )
    
    verify_error_response_structure(result)
    assert result["error"]["code"] == "SESSION_NOT_FOUND"
    assert "invalid-session" in result["error"]["message"]
    assert len(result["suggestions"]) > 0


@pytest.mark.asyncio
async def test_analysis_find_patterns_error_format(mcp_services):
    """Test that find_patterns returns consistent error format."""
    result = await find_patterns(
        services=mcp_services,
        session_id="invalid-session",
        pattern_type="auto"
    )
    
    verify_error_response_structure(result)
    assert result["error"]["code"] == "SESSION_NOT_FOUND"
    assert "invalid-session" in result["error"]["message"]
    assert len(result["suggestions"]) > 0


@pytest.mark.asyncio
async def test_context_build_error_format(mcp_services):
    """Test that build_context returns consistent error format."""
    result = await build_context(
        services=mcp_services,
        session_id="invalid-session",
        query="test query"
    )
    
    verify_error_response_structure(result)
    assert result["error"]["code"] == "SESSION_NOT_FOUND"
    assert "invalid-session" in result["error"]["message"]
    assert len(result["suggestions"]) > 0


@pytest.mark.asyncio
async def test_knowledge_add_error_format(mcp_services):
    """Test that add_knowledge returns consistent error format."""
    result = await add_knowledge(
        services=mcp_services,
        session_id="invalid-session",
        content_type="file",
        source="test.py"
    )
    
    verify_error_response_structure(result)
    assert result["error"]["code"] == "SESSION_NOT_FOUND"
    assert "invalid-session" in result["error"]["message"]
    assert len(result["suggestions"]) > 0


@pytest.mark.asyncio
async def test_error_context_preservation():
    """Test that original context is preserved in error responses."""
    mcp_services = {
        "session_manager": MagicMock(),
        "memory_system": MagicMock(),
        "event_system": MagicMock(),
    }
    mcp_services["session_manager"].validate_session = AsyncMock(return_value=False)
    
    result = await save_memory(
        services=mcp_services,
        session_id="test-session",
        summary="Test summary",
        content="Test content",
        importance="high",
        tags=["test", "example"]
    )
    
    # Context should include original parameters
    assert "session_id" in result["context"]
    assert result["context"]["session_id"] == "test-session"


@pytest.mark.asyncio
async def test_error_suggestions_are_actionable():
    """Test that error suggestions are actionable and helpful."""
    mcp_services = {
        "session_manager": MagicMock(),
        "search_service": MagicMock(),
        "event_system": MagicMock(),
        "entity_resolver": MagicMock(),
        "impact_analyzer": MagicMock(),
    }
    mcp_services["session_manager"].validate_session = AsyncMock(return_value=False)
    
    result = await understand_entity(
        services=mcp_services,
        session_id="invalid-session",
        entity="MyClass"
    )
    
    # Suggestions should be present and non-empty
    assert len(result["suggestions"]) > 0
    
    # Suggestions should be strings
    for suggestion in result["suggestions"]:
        assert isinstance(suggestion, str)
        assert len(suggestion) > 0
    
    # At least one suggestion should mention creating a session
    assert any("create" in s.lower() and "session" in s.lower() 
               for s in result["suggestions"])


@pytest.mark.asyncio
async def test_error_related_tools_included():
    """Test that related tools are included in error responses."""
    mcp_services = {
        "session_manager": MagicMock(),
        "memory_system": MagicMock(),
        "event_system": MagicMock(),
    }
    mcp_services["session_manager"].validate_session = AsyncMock(return_value=False)
    
    result = await recall_memories(
        services=mcp_services,
        session_id="invalid-session",
        query="test query"
    )
    
    # Related tools should be present
    assert "related_tools" in result
    assert isinstance(result["related_tools"], list)
    
    # For session not found, should suggest create_session
    assert "create_session" in result["related_tools"]


@pytest.mark.asyncio
async def test_error_debugging_information():
    """Test that debugging information is present in error responses."""
    mcp_services = {
        "session_manager": MagicMock(),
        "context_builder": MagicMock(),
        "event_system": MagicMock(),
    }
    mcp_services["session_manager"].validate_session = AsyncMock(return_value=False)
    
    result = await build_context(
        services=mcp_services,
        session_id="test-session-123",
        query="test query",
        max_tokens=2000
    )
    
    # Error details should include debugging information
    assert "details" in result["error"]
    assert isinstance(result["error"]["details"], dict)
    
    # Context should preserve original parameters for debugging
    assert "session_id" in result["context"]
    assert "query" in result["context"]


@pytest.mark.asyncio
async def test_all_tools_use_same_error_format():
    """Test that all tools return errors in the same format."""
    mcp_services = {
        "session_manager": MagicMock(),
        "memory_system": MagicMock(),
        "search_service": MagicMock(),
        "event_system": MagicMock(),
        "context_builder": MagicMock(),
        "pattern_analyzer": MagicMock(),
        "entity_resolver": MagicMock(),
        "impact_analyzer": MagicMock(),
        "config": MagicMock(),
        "storage": MagicMock(),
    }
    mcp_services["session_manager"].validate_session = AsyncMock(return_value=False)
    
    # Test all tools
    tools_to_test = [
        (save_memory, {"session_id": "test", "summary": "test", "content": "test"}),
        (recall_memories, {"session_id": "test", "query": "test"}),
        (understand_entity, {"session_id": "test", "entity": "test"}),
        (analyze_impact, {"session_id": "test", "entity": "test"}),
        (find_patterns, {"session_id": "test"}),
        (build_context, {"session_id": "test", "query": "test"}),
        (add_knowledge, {"session_id": "test", "content_type": "file", "source": "test.py"}),
    ]
    
    error_structures = []
    
    for tool_func, params in tools_to_test:
        result = await tool_func(services=mcp_services, **params)
        
        # Verify structure
        verify_error_response_structure(result)
        
        # Collect structure for comparison
        error_structures.append({
            "has_error": "error" in result,
            "has_suggestions": "suggestions" in result,
            "has_related_tools": "related_tools" in result,
            "has_context": "context" in result,
            "error_has_code": "code" in result.get("error", {}),
            "error_has_message": "message" in result.get("error", {}),
            "error_has_help": "help" in result.get("error", {}),
            "error_has_details": "details" in result.get("error", {}),
        })
    
    # All tools should have identical structure
    first_structure = error_structures[0]
    for structure in error_structures[1:]:
        assert structure == first_structure, "All tools must return errors in the same format"


@pytest.mark.asyncio
async def test_error_help_text_is_meaningful():
    """Test that error help text provides meaningful guidance."""
    mcp_services = {
        "session_manager": MagicMock(),
        "memory_system": MagicMock(),
        "event_system": MagicMock(),
    }
    mcp_services["session_manager"].validate_session = AsyncMock(return_value=False)
    
    result = await save_memory(
        services=mcp_services,
        session_id="invalid-session",
        summary="Test",
        content="Test"
    )
    
    # Help text should be present and meaningful
    help_text = result["error"]["help"]
    assert isinstance(help_text, str)
    assert len(help_text) > 10  # Should be more than just a few words
    
    # Help text should provide guidance
    assert any(keyword in help_text.lower() 
               for keyword in ["create", "session", "use", "try"])


@pytest.mark.asyncio
async def test_error_code_consistency():
    """Test that error codes are consistent across tools."""
    mcp_services = {
        "session_manager": MagicMock(),
        "memory_system": MagicMock(),
        "search_service": MagicMock(),
        "event_system": MagicMock(),
        "context_builder": MagicMock(),
        "pattern_analyzer": MagicMock(),
        "entity_resolver": MagicMock(),
        "impact_analyzer": MagicMock(),
        "config": MagicMock(),
        "storage": MagicMock(),
    }
    mcp_services["session_manager"].validate_session = AsyncMock(return_value=False)
    
    # All tools should return the same error code for session not found
    tools = [
        save_memory,
        recall_memories,
        understand_entity,
        analyze_impact,
        find_patterns,
        build_context,
        add_knowledge,
    ]
    
    error_codes = []
    for tool in tools:
        if tool == save_memory:
            result = await tool(mcp_services, "test", "summary", "content")
        elif tool == recall_memories:
            result = await tool(mcp_services, "test", "query")
        elif tool in [understand_entity, analyze_impact]:
            result = await tool(mcp_services, "test", "entity")
        elif tool == find_patterns:
            result = await tool(mcp_services, "test")
        elif tool == build_context:
            result = await tool(mcp_services, "test", "query")
        elif tool == add_knowledge:
            result = await tool(mcp_services, "test", "file", "test.py")
        
        error_codes.append(result["error"]["code"])
    
    # All should return SESSION_NOT_FOUND
    assert all(code == "SESSION_NOT_FOUND" for code in error_codes), \
        "All tools should return the same error code for session not found"


@pytest.mark.asyncio
async def test_error_message_includes_context_values():
    """Test that error messages include relevant context values."""
    mcp_services = {
        "session_manager": MagicMock(),
        "memory_system": MagicMock(),
        "event_system": MagicMock(),
    }
    mcp_services["session_manager"].validate_session = AsyncMock(return_value=False)
    
    session_id = "my-test-session-123"
    result = await recall_memories(
        services=mcp_services,
        session_id=session_id,
        query="test query"
    )
    
    # Error message should include the session_id
    assert session_id in result["error"]["message"], \
        "Error message should include the session_id for better debugging"
