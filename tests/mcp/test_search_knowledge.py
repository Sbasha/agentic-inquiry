"""Tests for enhanced search_knowledge() with debug info."""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, patch
from datetime import datetime

from agentic_inquiry.mcp.tools.search import search_knowledge
from agentic_inquiry.mcp.models.session import Session


@pytest.fixture
def mcp_services():
    """Create mock services for testing.

    Note: This fixture patches should_use_fallback to return False,
    preventing fallback search from being triggered during tests.
    The fallback search feature is tested separately in test_fallback_search.py.
    """
    import numpy as np
    from unittest.mock import MagicMock

    session_manager = AsyncMock()
    search_service = AsyncMock()
    event_system = AsyncMock()
    mock_db_manager = AsyncMock()
    embedding_service = AsyncMock()

    # Mock event_system.store for detect_index_state
    mock_event_store = AsyncMock()
    mock_event_store.get_events_by_type = AsyncMock(return_value=[])
    mock_event_store.get_operation_status = AsyncMock(return_value={})
    event_system.store = mock_event_store

    # Mock config with sparse_index settings
    mock_config = MagicMock()
    mock_config.search.sparse_index.threshold = 50

    # Mock session
    session = Session(
        session_id="test_session",
        project_id="test_project",
        created_at=datetime.now(),
        last_active=datetime.now(),
        description="Test session",
    )
    session_manager.get_session.return_value = session
    session_manager.validate_session.return_value = True

    # Mock embedding service - return numpy array
    embedding_service.embed_async.return_value = np.array([0.1] * 384)

    return {
        "session_manager": session_manager,
        "search_service": search_service,
        "event_system": event_system,
        "mock_db_manager": mock_db_manager,
        "storage": mock_db_manager,  # Expose as storage for tools
        "embedding_service": embedding_service,
        "config": mock_config,
    }


@pytest.fixture
def mock_fallback_search_empty():
    """Mock execute_fallback_search to return empty results.

    For tests that need to verify empty result handling logic without
    triggering real filesystem operations, this fixture mocks the fallback
    to return an empty result set with proper structure.
    """
    empty_fallback_response = {
        "results": [],
        "source": "python_glob",
        "source_note": "Results from basic file search (semantic index still building)",
    }
    with patch(
        "agentic_inquiry.mcp.tools.search.execute_fallback_search",
        new_callable=AsyncMock,
        return_value=empty_fallback_response
    ):
        yield


@pytest.fixture
def mock_structural_search_empty():
    """Mock structural_search to return empty results.

    For structural queries (e.g., containing 'class', 'def'), this fixture
    ensures the structural search path also returns empty results.
    """
    empty_structural_response = {
        "results": [],
        "source": "python_glob",
        "source_note": "Results from pattern-based search (ast-grep not available)",
    }
    with patch(
        "agentic_inquiry.mcp.tools.search.structural_search",
        new_callable=AsyncMock,
        return_value=empty_structural_response
    ):
        yield


@pytest.mark.asyncio
async def test_empty_results_with_no_indexed_content(mcp_services, mock_fallback_search_empty):
    """Test empty result handling when project has no indexed content.

    This test verifies the empty result handling logic when fallback search
    also returns no results. The mock_fallback_search_empty fixture mocks
    execute_fallback_search to return an empty result set, simulating the
    scenario where neither semantic nor fallback search finds matches.
    """
    # Mock empty search results
    mcp_services["search_service"].hybrid_search.return_value = []

    # Mock no indexed chunks
    mcp_services["storage"].count_records.return_value = 0

    # Execute search
    result = await search_knowledge(
        services=mcp_services,
        session_id="test_session",
        query="test query",
        limit=10,
        search_type="hybrid"
    )
    
    # Verify response structure
    assert "results" in result
    assert len(result["results"]) == 0
    assert result["total"] == 0
    assert result["query"] == "test query"
    assert result["search_type"] == "hybrid"
    
    # Verify debug_info is present
    assert "debug_info" in result
    debug_info = result["debug_info"]
    assert debug_info["query"] == "test query"
    assert debug_info["project_id"] == "test_project"
    assert debug_info["indexed_chunks"] == 0
    assert debug_info["search_type"] == "hybrid"
    
    # Verify message for empty project
    assert "message" in result
    assert "No indexed content found" in result["message"]
    assert "test_project" in result["message"]
    
    # Verify suggestions for empty project
    assert "suggestions" in result
    assert len(result["suggestions"]) > 0
    assert any("add_knowledge()" in s for s in result["suggestions"])
    assert any("get_server_info()" in s for s in result["suggestions"])
    assert any("correct project_id" in s for s in result["suggestions"])
    
    # Verify count_records was called with document_chunks (may be called multiple times)
    mcp_services["storage"].count_records.assert_any_call(
        table_name="document_chunks",
        project_id="test_project"
    )


@pytest.mark.asyncio
async def test_empty_results_with_indexed_content_but_no_matches(mcp_services):
    """Test empty result handling when content exists but no matches found."""
    # Mock empty search results
    mcp_services["search_service"].hybrid_search.return_value = []
    
    # Mock indexed chunks exist
    mcp_services["storage"].count_records.return_value = 150
    
    # Execute search
    result = await search_knowledge(
        services=mcp_services,
        session_id="test_session",
        query="nonexistent query",
        limit=10,
        search_type="hybrid"
    )
    
    # Verify response structure
    assert "results" in result
    assert len(result["results"]) == 0
    assert result["total"] == 0
    
    # Verify debug_info is present
    assert "debug_info" in result
    debug_info = result["debug_info"]
    assert debug_info["query"] == "nonexistent query"
    assert debug_info["project_id"] == "test_project"
    assert debug_info["indexed_chunks"] == 150
    assert debug_info["search_type"] == "hybrid"
    
    # Verify message for no matches
    assert "message" in result
    assert "No results found" in result["message"]
    assert "nonexistent query" in result["message"]
    assert "150 indexed chunks" in result["message"]
    
    # Verify suggestions for no matches
    assert "suggestions" in result
    assert len(result["suggestions"]) > 0
    assert any("broader search terms" in s for s in result["suggestions"])
    assert any("different keywords" in s for s in result["suggestions"])
    assert any("search_type='fts'" in s for s in result["suggestions"])
    assert any("content you're looking for is indexed" in s for s in result["suggestions"])


@pytest.mark.asyncio
async def test_debug_info_generation_with_vector_search(mcp_services):
    """Test debug_info generation with vector search type."""
    # Mock empty search results
    mcp_services["search_service"].vector_search.return_value = []
    
    # Mock indexed chunks
    mcp_services["storage"].count_records.return_value = 50
    
    # Execute search with vector search type
    result = await search_knowledge(
        services=mcp_services,
        session_id="test_session",
        query="test query",
        limit=10,
        search_type="vector"
    )
    
    # Verify debug_info has correct search_type
    assert result["debug_info"]["search_type"] == "vector"
    
    # Verify vector_search was called
    mcp_services["search_service"].vector_search.assert_called_once()


@pytest.mark.asyncio
async def test_debug_info_generation_with_fts_search(mcp_services):
    """Test debug_info generation with FTS search type."""
    # Mock empty search results
    mcp_services["search_service"].fts_search.return_value = []
    
    # Mock indexed chunks
    mcp_services["storage"].count_records.return_value = 75
    
    # Execute search with FTS search type
    result = await search_knowledge(
        services=mcp_services,
        session_id="test_session",
        query="exact keyword",
        limit=10,
        search_type="fts"
    )
    
    # Verify debug_info has correct search_type
    assert result["debug_info"]["search_type"] == "fts"
    
    # Verify fts_search was called
    mcp_services["search_service"].fts_search.assert_called_once()


@pytest.mark.asyncio
async def test_suggestion_quality_for_empty_project(mcp_services, mock_fallback_search_empty):
    """Test that suggestions are helpful and actionable for empty project.

    This test verifies suggestion generation for empty projects when
    fallback search also returns no results.
    """
    # Mock empty search results and no indexed content
    mcp_services["search_service"].hybrid_search.return_value = []
    mcp_services["storage"].count_records.return_value = 0

    # Execute search
    result = await search_knowledge(
        services=mcp_services,
        session_id="test_session",
        query="test",
        limit=10
    )
    
    # Verify suggestions are actionable
    suggestions = result["suggestions"]
    assert len(suggestions) >= 3
    
    # Check for specific actionable suggestions
    suggestions_text = " ".join(suggestions)
    assert "add_knowledge()" in suggestions_text
    assert "get_server_info()" in suggestions_text
    assert "project_id" in suggestions_text


@pytest.mark.asyncio
async def test_suggestion_quality_for_no_matches(mcp_services):
    """Test that suggestions are helpful for no matches scenario."""
    # Mock empty search results but indexed content exists
    mcp_services["search_service"].hybrid_search.return_value = []
    mcp_services["storage"].count_records.return_value = 100
    
    # Execute search
    result = await search_knowledge(
        services=mcp_services,
        session_id="test_session",
        query="specific term",
        limit=10
    )
    
    # Verify suggestions are helpful
    suggestions = result["suggestions"]
    assert len(suggestions) >= 4
    
    # Check for specific helpful suggestions
    suggestions_text = " ".join(suggestions)
    assert "broader" in suggestions_text.lower()
    assert "different" in suggestions_text.lower() or "synonyms" in suggestions_text.lower()
    assert "fts" in suggestions_text.lower()


@pytest.mark.asyncio
async def test_project_checking_logic(mcp_services, mock_fallback_search_empty):
    """Test that project checking logic works correctly.

    This test verifies that count_records is called and the result is
    included in debug_info. Uses mock_fallback_search_empty since count=42
    is below the sparse threshold, which would trigger fallback search.
    """
    # Mock empty search results
    mcp_services["search_service"].hybrid_search.return_value = []

    # Mock count_records to return different values
    mcp_services["storage"].count_records.return_value = 42

    # Execute search
    result = await search_knowledge(
        services=mcp_services,
        session_id="test_session",
        query="test",
        limit=10
    )
    
    # Verify count_records was called with correct parameters (may be called multiple times)
    mcp_services["storage"].count_records.assert_any_call(
        table_name="document_chunks",
        project_id="test_project"
    )
    
    # Verify debug_info reflects the count
    assert result["debug_info"]["indexed_chunks"] == 42


@pytest.mark.asyncio
async def test_successful_search_with_results(mcp_services):
    """Test that successful search with results doesn't include debug_info."""
    from unittest.mock import MagicMock

    # Mock successful search results using MagicMock for result objects
    mock_result = MagicMock()
    mock_result.data = {
        "file_path": "test.py",
        "content": "def test(): pass",
        "line_start": 1,
        "line_end": 1,
        "language": "python",
        "entity_type": "function",
        "entity_name": "test",
        "symbols": [],
        "element_name": "test",
        "metadata": {}
    }
    mock_result.score = 0.95
    mock_results = [mock_result]
    mcp_services["search_service"].hybrid_search.return_value = mock_results

    # Mock count_records to return a high count (index is READY, not SPARSE)
    mcp_services["storage"].count_records.return_value = 200

    # Execute search
    result = await search_knowledge(
        services=mcp_services,
        session_id="test_session",
        query="test function",
        limit=10
    )

    # Verify results are returned
    assert "results" in result
    assert len(result["results"]) == 1
    assert result["total"] == 1
    assert result["results"][0]["file_path"] == "test.py"

    # Verify debug_info is NOT present for successful searches
    assert "debug_info" not in result
    assert "message" not in result
    assert "suggestions" not in result

    # Verify index_state is NOT present when index is READY (count >= threshold)
    assert "index_state" not in result


@pytest.mark.asyncio
async def test_empty_results_with_filters(mcp_services):
    """Test empty results handling with filters applied."""
    # Mock empty search results
    mcp_services["search_service"].hybrid_search.return_value = []
    mcp_services["storage"].count_records.return_value = 50
    
    # Execute search with filters
    result = await search_knowledge(
        services=mcp_services,
        session_id="test_session",
        query="test",
        limit=10,
        filters={"language": "python"}
    )
    
    # Verify debug_info is present
    assert "debug_info" in result
    assert result["debug_info"]["indexed_chunks"] == 50
    
    # Verify suggestions are provided
    assert "suggestions" in result
    assert len(result["suggestions"]) > 0


@pytest.mark.asyncio
async def test_session_not_found_error(mcp_services):
    """Test error handling when session is not found."""
    # Mock session validation failure
    mcp_services["session_manager"].validate_session.return_value = False
    
    # Execute search
    result = await search_knowledge(
        services=mcp_services,
        session_id="invalid_session",
        query="test",
        limit=10
    )
    
    # Verify error response
    assert "error" in result
    assert result["error"]["code"] == "SESSION_NOT_FOUND"
    assert "invalid_session" in result["error"]["message"]
    assert "suggestions" in result
    
    # Verify search was not performed
    mcp_services["search_service"].hybrid_search.assert_not_called()
    mcp_services["storage"].count_records.assert_not_called()


@pytest.mark.asyncio
async def test_events_emitted_for_empty_results(mcp_services):
    """Test that events are properly emitted even for empty results."""
    # Mock empty search results
    mcp_services["search_service"].hybrid_search.return_value = []
    mcp_services["storage"].count_records.return_value = 0
    
    # Execute search
    await search_knowledge(
        services=mcp_services,
        session_id="test_session",
        query="test",
        limit=10
    )
    
    # Verify events were emitted
    event_system = mcp_services["event_system"]
    assert event_system.emit.call_count >= 1
    
    # Check for started event
    call_args_list = event_system.emit.call_args_list
    event_types = [call.args[0] if call.args else call.kwargs.get("event_type") for call in call_args_list]
    assert "mcp.tool.started" in event_types
    
    # Note: When returning early with empty results, we don't emit completed event
    # This is expected behavior as we return before the normal completion path


@pytest.mark.asyncio
async def test_index_state_included_when_sparse(mcp_services):
    """Test that index_state is included when index is sparse (below threshold)."""
    from unittest.mock import MagicMock

    # Mock search results
    mock_result = MagicMock()
    mock_result.data = {
        "file_path": "test.py",
        "content": "def test(): pass",
        "line_start": 1,
        "line_end": 1,
        "language": "python",
        "entity_type": "function",
        "entity_name": "test",
        "symbols": [],
        "element_name": "test",
        "metadata": {}
    }
    mock_result.score = 0.95
    mcp_services["search_service"].hybrid_search.return_value = [mock_result]

    # Mock count_records to return below threshold (sparse index)
    mcp_services["storage"].count_records.return_value = 10  # Below 50 threshold

    # Execute search
    result = await search_knowledge(
        services=mcp_services,
        session_id="test_session",
        query="test",
        limit=10
    )

    # Verify index_state is present when index is sparse
    assert "index_state" in result
    assert result["index_state"]["status"] == "sparse"
    assert "indexed_so_far" in result["index_state"]
    assert "message" in result["index_state"]


@pytest.mark.asyncio
async def test_index_state_not_included_when_ready(mcp_services):
    """Test that index_state is NOT included when index is ready (above threshold)."""
    from unittest.mock import MagicMock

    # Mock search results
    mock_result = MagicMock()
    mock_result.data = {
        "file_path": "test.py",
        "content": "def test(): pass",
        "line_start": 1,
        "line_end": 1,
        "language": "python",
        "entity_type": "function",
        "entity_name": "test",
        "symbols": [],
        "element_name": "test",
        "metadata": {}
    }
    mock_result.score = 0.95
    mcp_services["search_service"].hybrid_search.return_value = [mock_result]

    # Mock count_records to return above threshold (index is ready)
    mcp_services["storage"].count_records.return_value = 100  # Above 50 threshold

    # Execute search
    result = await search_knowledge(
        services=mcp_services,
        session_id="test_session",
        query="test",
        limit=10
    )

    # Verify index_state is NOT present when index is ready
    assert "index_state" not in result


@pytest.mark.asyncio
async def test_empty_results_includes_index_state_when_sparse(mcp_services, mock_fallback_search_empty):
    """Test that index_state is included in empty results when index is sparse.

    This test verifies that index_state metadata is correctly added when
    the index is sparse and fallback search also returns no results.
    Uses mock_fallback_search_empty to simulate fallback returning empty.
    """
    # Mock empty search results
    mcp_services["search_service"].hybrid_search.return_value = []

    # Mock count_records to return below threshold (sparse index)
    mcp_services["storage"].count_records.return_value = 25  # Below 50 threshold

    # Execute search
    result = await search_knowledge(
        services=mcp_services,
        session_id="test_session",
        query="test",
        limit=10
    )

    # Verify index_state is present when index is sparse
    assert "index_state" in result
    assert result["index_state"]["status"] == "sparse"



# ============================================================================
# Fallback Search Integration Tests
# ============================================================================


@pytest.fixture
def mock_fallback_with_results():
    """Create mock fallback search that returns results.

    This fixture provides a configured mock for execute_fallback_search
    that returns actual results, allowing us to verify the fallback
    integration path works correctly.
    """
    from agentic_inquiry.mcp.utils.fallback_search import FallbackResult

    # Create mock fallback results
    fallback_results = [
        FallbackResult(
            file_path="/project/src/auth.py",
            line_number=42,
            content="def authenticate_user(username, password):",
            score=1.0,
            match_type="text",
            language="python",
            context_before="# Authentication module",
            context_after="    '''Authenticate a user with credentials.'''",
            metadata={"source": "ripgrep"}
        ),
        FallbackResult(
            file_path="/project/src/auth.py",
            line_number=58,
            content="    if not verify_password(password, user.password_hash):",
            score=0.9,
            match_type="text",
            language="python",
            metadata={"source": "ripgrep"}
        ),
    ]

    fallback_response = {
        "results": fallback_results,
        "source": "ripgrep",
        "source_note": "Results from static text search (ripgrep)",
    }

    with patch(
        "agentic_inquiry.mcp.tools.search.execute_fallback_search",
        new_callable=AsyncMock,
        return_value=fallback_response
    ):
        yield fallback_response


@pytest.mark.asyncio
async def test_fallback_triggered_when_index_sparse_and_returns_results(
    mcp_services, mock_fallback_with_results
):
    """Test that fallback search is triggered when index is sparse and returns results.

    This test verifies the complete fallback integration:
    1. Semantic search returns empty (simulating no indexed content matching)
    2. Index is detected as sparse (below threshold)
    3. Fallback search is triggered and returns results
    4. Response includes fallback results with correct source field
    """
    # Mock empty semantic search results
    mcp_services["search_service"].hybrid_search.return_value = []

    # Mock sparse index (count < threshold)
    mcp_services["storage"].count_records.return_value = 10  # Below 50 threshold

    # Execute search
    result = await search_knowledge(
        services=mcp_services,
        session_id="test_session",
        query="authenticate user",
        limit=10,
        search_type="hybrid"
    )

    # Verify fallback was used
    assert "source" in result
    assert result["source"] == "ripgrep"
    assert result["source_note"] == "Results from static text search (ripgrep)"

    # Verify results are present
    assert "results" in result
    assert len(result["results"]) == 2

    # Verify result structure from fallback
    first_result = result["results"][0]
    assert first_result["file_path"] == "/project/src/auth.py"
    assert first_result["line_start"] == 42
    assert "authenticate_user" in first_result["content"]

    # Verify index_state is included (since index is sparse)
    assert "index_state" in result
    assert result["index_state"]["status"] == "sparse"


@pytest.mark.asyncio
async def test_fallback_not_triggered_when_index_ready(mcp_services):
    """Test that fallback search is NOT triggered when index is ready.

    When the index is above the sparse threshold (ready), fallback should
    not be triggered even if semantic search returns empty results.
    """
    # Mock empty semantic search results
    mcp_services["search_service"].hybrid_search.return_value = []

    # Mock ready index (count >= threshold)
    mcp_services["storage"].count_records.return_value = 100  # Above 50 threshold

    # Mock execute_fallback_search to verify it's NOT called
    with patch(
        "agentic_inquiry.mcp.tools.search.execute_fallback_search",
        new_callable=AsyncMock
    ) as mock_fallback:
        result = await search_knowledge(
            services=mcp_services,
            session_id="test_session",
            query="nonexistent query",
            limit=10,
            search_type="hybrid"
        )

        # Fallback should NOT be called when index is ready
        mock_fallback.assert_not_called()

    # Verify result shows semantic source (not fallback)
    assert result["source"] == "semantic"

    # Verify index_state is NOT included (since index is ready)
    assert "index_state" not in result


@pytest.mark.asyncio
async def test_fallback_results_properly_formatted(mcp_services, mock_fallback_with_results):
    """Test that fallback results are correctly formatted in the response.

    Verifies that FallbackResult objects are properly converted to the
    standard search result format with all expected fields.
    """
    # Mock empty semantic search results and sparse index
    mcp_services["search_service"].hybrid_search.return_value = []
    mcp_services["storage"].count_records.return_value = 5  # Very sparse

    result = await search_knowledge(
        services=mcp_services,
        session_id="test_session",
        query="authenticate",
        limit=10
    )

    # Verify all required fields are present in formatted results
    assert len(result["results"]) == 2

    for r in result["results"]:
        assert "file_path" in r
        assert "content" in r
        assert "score" in r
        assert "line_start" in r
        assert "line_end" in r
        assert "language" in r
        assert "metadata" in r


@pytest.fixture
def mock_structural_fallback_with_results():
    """Create mock structural search that returns results.

    This fixture provides a configured mock for structural_search
    that returns results for structural queries (containing 'class', 'def', etc).
    """
    from agentic_inquiry.mcp.utils.fallback_search import FallbackResult

    structural_results = [
        FallbackResult(
            file_path="/project/src/models.py",
            line_number=15,
            content="class UserModel:",
            score=1.0,
            match_type="structural",
            language="python",
            metadata={"pattern": "class $NAME: $$$BODY"}
        ),
    ]

    structural_response = {
        "results": structural_results,
        "source": "ast_grep",
        "source_note": "Results from AST-based structural search (ast-grep)",
    }

    with patch(
        "agentic_inquiry.mcp.tools.search.structural_search",
        new_callable=AsyncMock,
        return_value=structural_response
    ):
        yield structural_response


@pytest.mark.asyncio
async def test_structural_fallback_for_class_query(
    mcp_services, mock_structural_fallback_with_results
):
    """Test that structural queries use structural_search fallback.

    Queries containing keywords like 'class', 'def', 'function' should
    trigger the structural search path via ast-grep when index is sparse.
    """
    # Mock empty semantic search results and sparse index
    mcp_services["search_service"].hybrid_search.return_value = []
    mcp_services["storage"].count_records.return_value = 10

    result = await search_knowledge(
        services=mcp_services,
        session_id="test_session",
        query="find all classes",  # Contains 'class' - triggers structural search
        limit=10
    )

    # Verify structural search was used
    assert "source" in result
    assert result["source"] == "ast_grep"
    assert "AST-based" in result["source_note"]

    # Verify results
    assert len(result["results"]) == 1
    assert "UserModel" in result["results"][0]["content"]


@pytest.mark.asyncio
async def test_fallback_verify_was_called_with_correct_params(mcp_services):
    """Test that fallback search is called with correct parameters.

    Verifies that execute_fallback_search is invoked with the expected
    arguments when fallback is triggered.
    """
    from pathlib import Path

    # Mock empty semantic search results and sparse index
    mcp_services["search_service"].hybrid_search.return_value = []
    mcp_services["storage"].count_records.return_value = 10

    with patch(
        "agentic_inquiry.mcp.tools.search.execute_fallback_search",
        new_callable=AsyncMock,
        return_value={"results": [], "source": "python_glob", "source_note": "test"}
    ) as mock_fallback:
        await search_knowledge(
            services=mcp_services,
            session_id="test_session",
            query="test query",
            limit=15
        )

        # Verify fallback was called
        mock_fallback.assert_called_once()

        # Verify call arguments
        call_kwargs = mock_fallback.call_args.kwargs
        assert call_kwargs["query"] == "test query"
        assert call_kwargs["limit"] == 15
        assert isinstance(call_kwargs["project_root"], Path)
