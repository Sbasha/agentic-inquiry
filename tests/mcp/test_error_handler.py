"""Tests for MCP error handler.

This module tests:
- Error message formatting
- Suggestion generation
- Error code mapping
- Context preservation
"""

import pytest

pytestmark = pytest.mark.unit

from agentic_inquiry.mcp.utils.errors import MCPErrorHandler
from agentic_inquiry.mcp.models.errors import (
    SessionNotFoundError,
    EntityNotFoundError,
)
from agentic_inquiry.exceptions import (
    ConfigurationError,
    StorageError,
    ParsingError,
)


@pytest.fixture
def mcp_services():
    """Create mock services for error handler."""
    return {
        "session_manager": None,
        "event_system": None,
    }


@pytest.mark.asyncio
async def test_handle_session_not_found_error(mcp_services):
    """Test handling SessionNotFoundError."""
    error = SessionNotFoundError(session_id="test-session-123")
    context = {"session_id": "test-session-123"}
    
    result = await MCPErrorHandler.handle(error, context, mcp_services)
    
    assert result["error"]["code"] == "SESSION_NOT_FOUND"
    assert "test-session-123" in result["error"]["message"]
    assert len(result["suggestions"]) > 0
    assert "create_session" in result["related_tools"]


@pytest.mark.asyncio
async def test_handle_no_results_error(mcp_services):
    """Test handling no results error."""
    error = Exception("No results found for query")
    context = {"query": "test query"}
    
    result = await MCPErrorHandler.handle(error, context, mcp_services)
    
    assert result["error"]["code"] == "NO_RESULTS"
    assert len(result["suggestions"]) > 0
    # Should have suggestions about search alternatives
    assert any("broader" in s.lower() or "keyword" in s.lower() 
               for s in result["suggestions"])


@pytest.mark.asyncio
async def test_handle_entity_not_found_error(mcp_services):
    """Test handling EntityNotFoundError."""
    error = EntityNotFoundError(entity_name="MyClass")
    context = {"entity": "MyClass"}
    
    result = await MCPErrorHandler.handle(error, context, mcp_services)
    
    assert result["error"]["code"] == "ENTITY_NOT_FOUND"
    assert "MyClass" in result["error"]["message"]
    assert len(result["suggestions"]) > 0
    # Should suggest qualified names
    assert any("qualified" in s.lower() for s in result["suggestions"])


@pytest.mark.asyncio
async def test_handle_token_budget_exceeded_error(mcp_services):
    """Test handling token budget exceeded error."""
    error = Exception("Token budget exceeded")
    context = {"max_tokens": 4000}
    
    result = await MCPErrorHandler.handle(error, context, mcp_services)
    
    assert result["error"]["code"] == "TOKEN_BUDGET_EXCEEDED"
    assert "4000" in result["error"]["message"]
    # Suggestions list exists (may be empty for this error type)
    assert "suggestions" in result


@pytest.mark.asyncio
async def test_handle_storage_error(mcp_services):
    """Test handling StorageError."""
    error = StorageError("Database connection failed")
    context = {}
    
    result = await MCPErrorHandler.handle(error, context, mcp_services)
    
    assert result["error"]["code"] == "STORAGE_ERROR"
    assert "storage" in result["error"]["message"].lower()


@pytest.mark.asyncio
async def test_handle_configuration_error(mcp_services):
    """Test handling ConfigurationError."""
    error = ConfigurationError("Invalid config")
    context = {}
    
    result = await MCPErrorHandler.handle(error, context, mcp_services)
    
    assert result["error"]["code"] == "CONFIGURATION_ERROR"
    assert "configuration" in result["error"]["message"].lower()


@pytest.mark.asyncio
async def test_handle_parsing_error(mcp_services):
    """Test handling ParsingError."""
    error = ParsingError("Failed to parse file")
    context = {"source": "/path/to/file.py"}
    
    result = await MCPErrorHandler.handle(error, context, mcp_services)
    
    assert result["error"]["code"] == "INDEXING_FAILED"
    assert "/path/to/file.py" in result["error"]["message"]


@pytest.mark.asyncio
async def test_handle_generic_exception(mcp_services):
    """Test handling generic exceptions."""
    error = ValueError("Something went wrong")
    context = {"param": "value"}
    
    result = await MCPErrorHandler.handle(error, context, mcp_services)
    
    assert result["error"]["code"] == "INTERNAL_ERROR"
    assert "Something went wrong" in result["error"]["message"]
    assert result["error"]["details"]["error_type"] == "ValueError"


@pytest.mark.asyncio
async def test_error_response_structure(mcp_services):
    """Test that all error responses have correct structure."""
    error = SessionNotFoundError("Test")
    context = {"session_id": "test"}
    
    result = await MCPErrorHandler.handle(error, context, mcp_services)
    
    # Verify required fields
    assert "error" in result
    assert "code" in result["error"]
    assert "message" in result["error"]
    assert "help" in result["error"]
    assert "details" in result["error"]
    
    assert "suggestions" in result
    assert isinstance(result["suggestions"], list)
    
    assert "related_tools" in result
    assert isinstance(result["related_tools"], list)
    
    assert "context" in result
    assert isinstance(result["context"], dict)


@pytest.mark.asyncio
async def test_suggest_search_alternatives_short_query(mcp_services):
    """Test suggestions for very short queries."""
    suggestions = await MCPErrorHandler._suggest_search_alternatives(
        "x",
        mcp_services
    )
    
    assert len(suggestions) > 0
    assert any("longer" in s.lower() for s in suggestions)


@pytest.mark.asyncio
async def test_suggest_search_alternatives_long_query(mcp_services):
    """Test suggestions for very long queries."""
    long_query = "a" * 150
    suggestions = await MCPErrorHandler._suggest_search_alternatives(
        long_query,
        mcp_services
    )
    
    assert len(suggestions) > 0
    assert any("shorter" in s.lower() for s in suggestions)


@pytest.mark.asyncio
async def test_suggest_search_alternatives_normal_query(mcp_services):
    """Test suggestions for normal queries."""
    suggestions = await MCPErrorHandler._suggest_search_alternatives(
        "authentication function",
        mcp_services
    )
    
    # Normal queries may not generate additional suggestions
    # The base suggestions from ERROR_MESSAGES are always included
    assert isinstance(suggestions, list)


@pytest.mark.asyncio
async def test_suggest_similar_entities_simple_name(mcp_services):
    """Test entity suggestions for simple names."""
    suggestions = await MCPErrorHandler._suggest_similar_entities(
        "MyClass",
        mcp_services
    )
    
    assert len(suggestions) > 0
    # Should suggest qualified names
    assert any("qualified" in s.lower() for s in suggestions)


@pytest.mark.asyncio
async def test_suggest_similar_entities_qualified_name(mcp_services):
    """Test entity suggestions for qualified names."""
    suggestions = await MCPErrorHandler._suggest_similar_entities(
        "module.MyClass",
        mcp_services
    )
    
    # Qualified names may not generate additional suggestions
    # The base suggestions from ERROR_MESSAGES are always included
    assert isinstance(suggestions, list)


@pytest.mark.asyncio
async def test_create_validation_error():
    """Test creating validation error responses."""
    result = MCPErrorHandler.create_validation_error(
        field="limit",
        message="must be between 1 and 100",
        context={"limit": 200}
    )
    
    assert result["error"]["code"] == "VALIDATION_ERROR"
    assert "limit" in result["error"]["message"]
    assert "must be between 1 and 100" in result["error"]["message"]
    assert result["error"]["details"]["field"] == "limit"
    assert len(result["suggestions"]) > 0


@pytest.mark.asyncio
async def test_error_message_formatting_with_context(mcp_services):
    """Test that error messages are formatted with context."""
    error = SessionNotFoundError("Test")
    context = {"session_id": "abc-123"}
    
    result = await MCPErrorHandler.handle(error, context, mcp_services)
    
    # Session ID should be in the message
    assert "abc-123" in result["error"]["message"]


@pytest.mark.asyncio
async def test_error_message_formatting_missing_context(mcp_services):
    """Test error message formatting when context is missing."""
    error = SessionNotFoundError("Test")
    context = {}  # Missing session_id
    
    result = await MCPErrorHandler.handle(error, context, mcp_services)
    
    # Should still return valid error response
    assert result["error"]["code"] == "SESSION_NOT_FOUND"
    assert "message" in result["error"]


@pytest.mark.asyncio
async def test_context_preservation(mcp_services):
    """Test that original context is preserved in error response."""
    error = Exception("No results found")
    context = {
        "query": "test query",
        "limit": 20,
        "filters": {"type": "code"}
    }
    
    result = await MCPErrorHandler.handle(error, context, mcp_services)
    
    # Original context should be preserved
    assert result["context"] == context


@pytest.mark.asyncio
async def test_related_tools_included(mcp_services):
    """Test that related tools are included in error responses."""
    error = SessionNotFoundError("Test")
    context = {"session_id": "test"}
    
    result = await MCPErrorHandler.handle(error, context, mcp_services)
    
    assert "related_tools" in result
    assert len(result["related_tools"]) > 0
    assert "create_session" in result["related_tools"]


@pytest.mark.asyncio
async def test_help_text_included(mcp_services):
    """Test that help text is included in error responses."""
    error = EntityNotFoundError("Test")
    context = {"entity": "MyClass"}
    
    result = await MCPErrorHandler.handle(error, context, mcp_services)
    
    assert "help" in result["error"]
    assert len(result["error"]["help"]) > 0
    # Help text should be present and non-empty
    assert isinstance(result["error"]["help"], str)
