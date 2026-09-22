"""Tests for build_context tool with ContextBuilder integration."""

import pytest

pytestmark = pytest.mark.unit

from unittest.mock import AsyncMock, MagicMock, patch

from agentic_inquiry.mcp.tools.context import build_context, _generate_empty_context_suggestions


@pytest.fixture
def mcp_services():
    """Create mock services for testing."""
    services = {
        "session_manager": AsyncMock(),
        "context_builder": AsyncMock(),
        "event_system": AsyncMock(),
        "search_service": AsyncMock(),
    }
    
    # Configure session manager
    services["session_manager"].validate_session = AsyncMock(return_value=True)
    services["session_manager"].get_session = AsyncMock(return_value=MagicMock(
        project_id="test_project"
    ))
    
    # Configure event system
    services["event_system"].emit = AsyncMock()
    
    return services


@pytest.mark.asyncio
async def test_build_context_with_results(mcp_services):
    """Test build_context when ContextBuilder returns results."""
    # Configure context builder to return results
    mcp_services["context_builder"].build_context = AsyncMock(return_value={
        "context": {
            "code": [
                {
                    "id": "code1",
                    "name": "test_function",
                    "summary": "A test function",
                    "relevance_score": 0.9,
                    "location": "test.py",
                    "snippet": "def test_function():",
                    "metadata": {}
                }
            ],
            "documentation": [
                {
                    "id": "doc1",
                    "name": "README",
                    "summary": "Project documentation",
                    "relevance_score": 0.8,
                    "location": "README.md",
                    "snippet": "# Project",
                    "metadata": {}
                }
            ],
            "memories": []
        },
        "summary": "Found 2 items",
        "suggestions": ["Try depth='comprehensive' for more results"],
        "token_usage": {
            "estimated_tokens": 500,
            "max_tokens": 4000,
            "remaining_tokens": 3500
        }
    })
    
    # Call build_context
    result = await build_context(
        services=mcp_services,
        session_id="test_session",
        query="test query",
        focus="balanced",
        depth="focused",
        max_tokens=4000
    )
    
    # Verify result structure
    assert "context" in result
    assert "code" in result["context"]
    assert "documentation" in result["context"]
    assert "memories" in result["context"]
    assert "summary" in result
    assert "token_usage" in result
    assert "suggestions" in result
    
    # Verify content
    assert len(result["context"]["code"]) == 1
    assert len(result["context"]["documentation"]) == 1
    assert result["context"]["code"][0]["name"] == "test_function"
    assert result["context"]["documentation"][0]["name"] == "README"
    
    # Verify token usage
    assert result["token_usage"]["used"] == 500
    assert result["token_usage"]["budget"] == 4000
    assert result["token_usage"]["remaining"] == 3500
    
    # Verify events were emitted
    assert mcp_services["event_system"].emit.call_count == 2  # started + completed


@pytest.mark.asyncio
async def test_build_context_empty_with_fallback(mcp_services):
    """Test build_context fallback when ContextBuilder returns empty results."""
    # Configure context builder to return empty results
    mcp_services["context_builder"].build_context = AsyncMock(return_value={
        "context": {
            "code": [],
            "documentation": [],
            "memories": []
        },
        "summary": "No results found",
        "suggestions": [],
        "token_usage": {
            "estimated_tokens": 0,
            "max_tokens": 4000,
            "remaining_tokens": 4000
        }
    })
    
    # Configure search service for fallback
    mcp_services["search_service"].embedder = AsyncMock()
    mcp_services["search_service"].embedder.embed_query = AsyncMock(
        return_value=[0.1] * 128
    )
    mcp_services["search_service"].hybrid_search = AsyncMock(return_value=[
        {
            "id": "fallback1",
            "name": "fallback_function",
            "content": "def fallback_function(): pass",
            "chunk_type": "function",
            "file_path": "fallback.py",
            "_distance": 0.3,
            "language": "python",
            "start_line": 1,
            "end_line": 2
        }
    ])
    
    # Call build_context
    result = await build_context(
        services=mcp_services,
        session_id="test_session",
        query="test query",
        focus="balanced",
        depth="focused",
        max_tokens=4000
    )
    
    # Verify fallback was triggered
    assert mcp_services["search_service"].hybrid_search.called
    
    # Verify result has fallback content
    assert len(result["context"]["code"]) == 1
    assert result["context"]["code"][0]["name"] == "fallback_function"
    
    # When fallback succeeds, we don't add empty context suggestions
    # because the context is no longer empty


@pytest.mark.asyncio
async def test_build_context_empty_with_failed_fallback(mcp_services):
    """Test build_context when both ContextBuilder and fallback return empty results."""
    # Configure context builder to return empty results
    mcp_services["context_builder"].build_context = AsyncMock(return_value={
        "context": {
            "code": [],
            "documentation": [],
            "memories": []
        },
        "summary": "No results found",
        "suggestions": [],
        "token_usage": {
            "estimated_tokens": 0,
            "max_tokens": 4000,
            "remaining_tokens": 4000
        }
    })
    
    # Configure search service for fallback - returns empty
    mcp_services["search_service"].embedder = AsyncMock()
    mcp_services["search_service"].embedder.embed_query = AsyncMock(
        return_value=[0.1] * 128
    )
    mcp_services["search_service"].hybrid_search = AsyncMock(return_value=[])
    
    # Call build_context
    result = await build_context(
        services=mcp_services,
        session_id="test_session",
        query="test query",
        focus="balanced",
        depth="focused",
        max_tokens=4000
    )
    
    # Verify fallback was triggered
    assert mcp_services["search_service"].hybrid_search.called
    
    # Verify context is still empty
    assert len(result["context"]["code"]) == 0
    assert len(result["context"]["documentation"]) == 0
    
    # Verify suggestions for empty context were added
    assert len(result["suggestions"]) > 0
    assert any("indexed" in s.lower() for s in result["suggestions"])


@pytest.mark.asyncio
async def test_build_context_invalid_session(mcp_services):
    """Test build_context with invalid session."""
    # Configure session manager to return invalid session
    mcp_services["session_manager"].validate_session = AsyncMock(return_value=False)
    
    # Call build_context - MCPErrorHandler is imported inside the function
    with patch("agentic_inquiry.mcp.utils.errors.MCPErrorHandler") as mock_error_handler:
        mock_error_handler.handle = AsyncMock(return_value={"error": "Session not found"})
        
        result = await build_context(
            services=mcp_services,
            session_id="invalid_session",
            query="test query",
            focus="balanced",
            depth="focused",
            max_tokens=4000
        )
        
        # Verify error handler was called
        assert mock_error_handler.handle.called
        assert "error" in result


@pytest.mark.asyncio
async def test_build_context_exception_handling(mcp_services):
    """Test build_context exception handling."""
    # Configure context builder to raise exception
    mcp_services["context_builder"].build_context = AsyncMock(
        side_effect=Exception("Test error")
    )
    
    # Call build_context - MCPErrorHandler is imported inside the function
    with patch("agentic_inquiry.mcp.utils.errors.MCPErrorHandler") as mock_error_handler:
        mock_error_handler.handle = AsyncMock(return_value={"error": "Test error"})
        
        result = await build_context(
            services=mcp_services,
            session_id="test_session",
            query="test query",
            focus="balanced",
            depth="focused",
            max_tokens=4000
        )
        
        # Verify error handler was called
        assert mock_error_handler.handle.called
        assert "error" in result
        
        # Verify failure event was emitted
        assert any(
            call[0][0] == "mcp.tool.failed"
            for call in mcp_services["event_system"].emit.call_args_list
        )


def test_generate_empty_context_suggestions_no_memories():
    """Test suggestion generation when no memories exist."""
    suggestions = _generate_empty_context_suggestions(
        query="test query",
        has_memories=False
    )
    
    assert len(suggestions) > 0
    assert any("indexed" in s.lower() for s in suggestions)
    assert any("memories" in s.lower() or "memory" in s.lower() for s in suggestions)
    assert any("broader" in s.lower() for s in suggestions)
    assert any("project" in s.lower() for s in suggestions)


def test_generate_empty_context_suggestions_with_memories():
    """Test suggestion generation when memories exist."""
    suggestions = _generate_empty_context_suggestions(
        query="test query",
        has_memories=True
    )
    
    assert len(suggestions) > 0
    assert any("indexed" in s.lower() for s in suggestions)
    assert any("broader" in s.lower() for s in suggestions)
    # Should not suggest saving memories if they already exist
    memory_suggestions = [s for s in suggestions if "save" in s.lower() and "memory" in s.lower()]
    assert len(memory_suggestions) == 0


@pytest.mark.asyncio
async def test_build_context_focus_parameter_mapping(mcp_services):
    """Test that focus parameter is correctly mapped to ContextBuilder."""
    mcp_services["context_builder"].build_context = AsyncMock(return_value={
        "context": {"code": [], "documentation": [], "memories": []},
        "summary": "No results",
        "suggestions": [],
        "token_usage": {"estimated_tokens": 0, "max_tokens": 4000, "remaining_tokens": 4000}
    })
    
    # Test with "balanced" focus (should map to "all")
    await build_context(
        services=mcp_services,
        session_id="test_session",
        query="test query",
        focus="balanced",
        depth="focused",
        max_tokens=4000
    )
    
    # Verify ContextBuilder was called with focus="all"
    call_args = mcp_services["context_builder"].build_context.call_args
    assert call_args[1]["focus"] == "all"
    
    # Test with "code" focus (should pass through)
    await build_context(
        services=mcp_services,
        session_id="test_session",
        query="test query",
        focus="code",
        depth="focused",
        max_tokens=4000
    )
    
    # Verify ContextBuilder was called with focus="code"
    call_args = mcp_services["context_builder"].build_context.call_args
    assert call_args[1]["focus"] == "code"
