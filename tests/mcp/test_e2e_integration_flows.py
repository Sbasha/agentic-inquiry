"""End-to-end integration tests for smart error messages and server info feature.

Tests the complete user flows:
1. Discovery flow: get_server_info() → create_session() with discovered project
2. Error recovery flow: invalid project_id → validation error → get_server_info() → retry
3. Empty search flow: search in empty project → helpful error → add_knowledge → retry
4. Project mismatch flow: create session with non-default project → warning
5. Limit parameter: get_server_info() with different limits
"""

import pytest

pytestmark = pytest.mark.unit
from pathlib import Path
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from agentic_inquiry.mcp.tools.info import get_server_info
from agentic_inquiry.mcp.tools.session import create_session
from agentic_inquiry.mcp.tools.search import search_knowledge
from agentic_inquiry.mcp.models.session import Session
from agentic_inquiry.database.results import SearchResult


@pytest.fixture
def mock_fallback_search_empty():
    """Fixture to mock fallback search to return empty results.

    This prevents the fallback search from finding actual files on disk,
    allowing tests to exercise the 'empty project' code path.
    """

    async def empty_fallback(*args, **kwargs):
        return {"results": [], "source": "fallback", "source_note": "Mock fallback"}

    with (
        patch(
            "agentic_inquiry.mcp.tools.search.execute_fallback_search",
            side_effect=empty_fallback,
        ),
        patch(
            "agentic_inquiry.mcp.tools.search.structural_search",
            side_effect=empty_fallback,
        ),
    ):
        yield


@pytest.fixture
async def integration_services():
    """Create realistic mock services for integration testing."""
    import numpy as np

    # Create mock services
    session_manager = AsyncMock()
    search_service = AsyncMock()
    event_system = AsyncMock()
    mock_db_manager = AsyncMock()
    embedding_service = AsyncMock()
    mock_indexing_pipeline = AsyncMock()

    # Mock embedding service
    embedding_service.embed_async.return_value = np.array([0.1] * 384)

    # Mock event store for detect_index_state
    # Return empty list for get_events_by_type so no active indexing is detected
    # This allows detect_index_state to fall through to chunk count check
    event_system.store = AsyncMock()
    event_system.store.get_events_by_type = AsyncMock(return_value=[])
    event_system.store.get_operation_status = AsyncMock(return_value={})

    # Mock server config
    server_config = {
        "default_project_id": "agentic-inquiry",
        "server_name": "Agentic Inquiry MCP Server",
        "server_version": "1.0.0",
        "server_description": "Intelligent search and knowledge management",
    }

    # Mock project discovery - simulate chunks from multiple projects
    mock_chunks = [
        {
            "project_id": "agentic-inquiry",
            "created_at": datetime(2024, 1, 15, 10, 30, 0),
        },
        {
            "project_id": "agentic-inquiry",
            "created_at": datetime(2024, 1, 15, 11, 0, 0),
        },
        {"project_id": "test_project", "created_at": datetime(2024, 1, 14, 9, 0, 0)},
        {"project_id": "test_project", "created_at": datetime(2024, 1, 14, 10, 0, 0)},
        {"project_id": "another_project", "created_at": datetime(2024, 1, 13, 8, 0, 0)},
    ]

    async def mock_advanced_filter(table_name, filters, limit=None):
        if table_name == "document_chunks":
            return mock_chunks
        return []

    mock_db_manager.advanced_filter = mock_advanced_filter
    mock_db_manager.get_table = MagicMock(return_value=MagicMock())

    # Mock project statistics
    async def mock_get_project_statistics(project_id):
        stats_map = {
            "agentic-inquiry": {
                "total_chunks": 1234,
                "total_files": 56,
                "total_entities": 789,
                "last_indexed": datetime.now().isoformat(),
                "index_health": "healthy",
            },
            "test_project": {
                "total_chunks": 500,
                "total_files": 25,
                "total_entities": 300,
                "last_indexed": datetime.now().isoformat(),
                "index_health": "healthy",
            },
            "another_project": {
                "total_chunks": 100,
                "total_files": 10,
                "total_entities": 50,
                "last_indexed": datetime.now().isoformat(),
                "index_health": "healthy",
            },
        }
        return stats_map.get(project_id, {})

    session_manager.get_project_statistics = mock_get_project_statistics

    # Mock session creation
    async def mock_create_session(project_id, description=None):
        session = Session(
            session_id=f"session_{project_id}",
            project_id=project_id,
            created_at=datetime.now(),
            last_active=datetime.now(),
            description=description or f"Session for {project_id}",
        )
        return {
            "session_id": session.session_id,
            "project_id": session.project_id,
            "created_at": session.created_at.isoformat(),
            "description": session.description,
        }

    session_manager.create_session = mock_create_session

    # Mock session retrieval
    async def mock_get_session(session_id, include_history=False):
        project_id = session_id.replace("session_", "")
        return Session(
            session_id=session_id,
            project_id=project_id,
            created_at=datetime.now(),
            last_active=datetime.now(),
            description=f"Session for {project_id}",
        )

    session_manager.get_session = mock_get_session
    session_manager.validate_session.return_value = True

    # Mock count_records for project checking
    async def mock_count_records(table_name, project_id=None):
        # Simulate different states for different projects
        if project_id == "empty_project":
            return 0
        elif project_id == "agentic-inquiry":
            return 1234
        elif project_id == "test_project":
            return 500
        else:
            return 0

    mock_db_manager.count_records = mock_count_records
    # Add get_db_manager for StorageFacade compatibility
    mock_db_manager.get_db_manager = MagicMock(return_value=mock_db_manager)

    # Mock search results
    search_service.hybrid_search.return_value = []
    search_service.vector_search.return_value = []
    search_service.fts_search.return_value = []

    # Mock indexing - add_knowledge doesn't use mock_indexing_pipeline directly
    # It uses process_document which we need to mock
    mock_indexing_pipeline.process_document = AsyncMock(return_value=None)

    # Mock config with required nested attributes
    config = MagicMock()
    config.project.root = Path.cwd()
    config.search.sparse_index.threshold = 50

    return {
        "session_manager": session_manager,
        "search_service": search_service,
        "event_system": event_system,
        "mock_db_manager": mock_db_manager,
        "storage": mock_db_manager,  # Expose as storage for tools
        "embedding_service": embedding_service,
        "mock_indexing_pipeline": mock_indexing_pipeline,
        "server_config": server_config,
        "config": config,
    }


@pytest.mark.asyncio
async def test_discovery_flow_complete(integration_services):
    """Test complete discovery flow: get_server_info() → create_session() with discovered project.

    Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
    """
    # Step 1: Agent calls get_server_info() to discover available projects
    server_info = await get_server_info(
        services=integration_services, limit=50, sort_by="last_indexed"
    )

    # Verify server info response structure
    assert "server" in server_info
    assert server_info["server"]["name"] == "Agentic Inquiry MCP Server"
    assert server_info["server"]["version"] == "1.0.0"

    assert "default_project" in server_info
    assert server_info["default_project"]["project_id"] == "agentic-inquiry"

    assert "available_projects" in server_info
    assert len(server_info["available_projects"]) == 3

    # Verify project_id_rules are present
    assert "project_id_rules" in server_info
    assert "format" in server_info["project_id_rules"]
    assert "examples" in server_info["project_id_rules"]

    # Verify usage guidelines
    assert "usage_guidelines" in server_info
    assert "getting_started" in server_info["usage_guidelines"]

    # Step 2: Agent discovers a project from the list
    discovered_project = server_info["available_projects"][1]["project_id"]
    assert discovered_project == "test_project"

    # Step 3: Agent creates session with discovered project
    session_result = await create_session(
        services=integration_services,
        project_id=discovered_project,
        description="Session from discovery",
    )

    # Verify session creation succeeded
    assert "session_id" in session_result
    assert session_result["project_id"] == "test_project"
    assert "error" not in session_result

    # Verify warning about non-default project
    assert "warning" in session_result
    assert "server default is 'agentic-inquiry'" in session_result["warning"]["message"]
    assert "get_server_info()" in session_result["warning"]["suggestion"]


@pytest.mark.asyncio
async def test_error_recovery_flow_complete(integration_services):
    """Test error recovery flow: invalid project_id → validation error → get_server_info() → retry.

    Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 3.5
    """
    # Step 1: Agent attempts to create session with invalid project_id
    invalid_result = await create_session(
        services=integration_services,
        project_id="invalid project!",  # Contains space and special char
        description="Test session",
    )

    # Verify validation error is returned
    assert "error" in invalid_result
    assert "error_code" in invalid_result
    assert invalid_result["error_code"] == "INVALID_PROJECT_ID"

    # Verify error message is helpful
    assert "suggestion" in invalid_result
    assert "get_server_info()" in invalid_result["suggestion"]

    # Verify examples are provided
    assert "examples" in invalid_result
    assert len(invalid_result["examples"]) > 0
    assert "my-project" in invalid_result["examples"]

    # Step 2: Agent calls get_server_info() to discover valid projects
    server_info = await get_server_info(services=integration_services, limit=50)

    # Verify project_id format rules are clear
    assert "project_id_rules" in server_info
    rules = server_info["project_id_rules"]
    assert "pattern" in rules
    assert "length" in rules
    assert "examples" in rules

    # Step 3: Agent retries with valid project_id from discovery
    valid_project = server_info["available_projects"][0]["project_id"]
    retry_result = await create_session(
        services=integration_services,
        project_id=valid_project,
        description="Retry after validation error",
    )

    # Verify session creation succeeded
    assert "session_id" in retry_result
    assert retry_result["project_id"] == valid_project
    assert "error" not in retry_result


@pytest.mark.asyncio
async def test_error_recovery_with_normalization(integration_services):
    """Test error recovery with project_id normalization (uppercase to lowercase).

    Requirements: 2.3, 3.1
    """
    # Agent provides uppercase project_id
    result = await create_session(
        services=integration_services,
        project_id="TEST_PROJECT",  # Will be normalized to lowercase
        description="Test normalization",
    )

    # Verify session creation succeeded with normalized project_id
    assert "session_id" in result
    assert result["project_id"] == "test_project"  # Normalized
    assert "error" not in result

    # Note: Normalization warning is logged but not returned in response
    # This is expected behavior - normalization is automatic


@pytest.mark.asyncio
async def test_empty_search_flow_complete(integration_services, tmp_path):
    """Test empty search flow: search in empty project → helpful error → add_knowledge → retry.

    Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
    """
    # Step 1: Create session for empty project
    session_result = await create_session(
        services=integration_services,
        project_id="empty_project",
        description="Empty project test",
    )

    session_id = session_result["session_id"]

    # Step 2: Agent searches in empty project
    search_result = await search_knowledge(
        services=integration_services,
        session_id=session_id,
        query="test query",
        limit=10,
    )

    # Verify search response structure (now includes fallback results)
    assert "results" in search_result
    # Note: Results may come from fallback glob search when index is empty

    # Verify index_state indicates sparse/empty index
    assert "index_state" in search_result
    index_state = search_result["index_state"]
    assert index_state["status"] == "sparse"
    assert (
        "0 chunks" in index_state["message"]
        or "no indexed content" in index_state["message"].lower()
    )

    # Verify warnings about empty index
    assert "warnings" in search_result
    warnings_text = " ".join(search_result["warnings"])
    assert "add_knowledge()" in warnings_text or "index" in warnings_text.lower()

    # Verify query is tracked
    assert search_result["query"] == "test query"

    # Verify result_quality indicates limited coverage
    assert "result_quality" in search_result
    assert search_result["result_quality"]["level"] in ("limited", "low", "fallback")

    # Step 3: Simulate that agent adds knowledge (mock the result)
    # Note: We're testing the flow, not the actual indexing implementation
    # In reality, agent would call add_knowledge() here

    # Step 4: Mock that project now has indexed content after adding knowledge
    async def mock_count_after_indexing(table_name, project_id=None):
        if project_id == "empty_project":
            return 10  # Now has content
        elif project_id == "agentic-inquiry":
            return 1234
        elif project_id == "test_project":
            return 500
        else:
            return 0

    integration_services["mock_db_manager"].count_records = mock_count_after_indexing

    # Mock successful search results (must be SearchResult objects)
    integration_services["search_service"].hybrid_search.return_value = [
        SearchResult(
            id="test_result_1",
            data={
                "file_path": "test.py",
                "content": "def hello(): pass",
                "line_start": 1,
                "line_end": 1,
            },
            score=0.95,
            source="hybrid",
        )
    ]

    # Step 5: Agent retries search
    retry_search_result = await search_knowledge(
        services=integration_services,
        session_id=session_id,
        query="hello function",
        limit=10,
    )

    # Verify search now returns results
    assert "results" in retry_search_result
    assert len(retry_search_result["results"]) == 1
    assert retry_search_result["total"] == 1

    # Verify debug_info is NOT present for successful searches
    assert "debug_info" not in retry_search_result
    assert "message" not in retry_search_result


@pytest.mark.asyncio
async def test_empty_search_with_indexed_content_no_matches(integration_services):
    """Test empty search when content exists but no matches found.

    Requirements: 4.1, 4.2, 4.3, 4.4, 4.5
    """
    # Create session for project with content
    session_result = await create_session(
        services=integration_services,
        project_id="test_project",
        description="Project with content",
    )

    session_id = session_result["session_id"]

    # Search with query that has no matches
    search_result = await search_knowledge(
        services=integration_services,
        session_id=session_id,
        query="nonexistent term",
        limit=10,
    )

    # Verify empty results
    assert len(search_result["results"]) == 0

    # Verify debug_info shows indexed content exists
    assert "debug_info" in search_result
    assert search_result["debug_info"]["indexed_chunks"] == 500

    # Verify message indicates no matches (not empty project)
    assert "message" in search_result
    assert "No results found" in search_result["message"]
    assert "500 indexed chunks" in search_result["message"]

    # Verify different suggestions for no matches vs empty project
    suggestions_text = " ".join(search_result["suggestions"])
    assert "broader search terms" in suggestions_text
    assert "different keywords" in suggestions_text
    assert "search_type='fts'" in suggestions_text


@pytest.mark.asyncio
async def test_project_mismatch_flow_complete(integration_services):
    """Test project mismatch flow: create session with non-default project → warning.

    Requirements: 3.1, 3.3, 3.4, 3.5
    """
    # Get default project from server config
    default_project = integration_services["server_config"]["default_project_id"]
    assert default_project == "agentic-inquiry"

    # Create session with different project
    non_default_project = "test_project"
    result = await create_session(
        services=integration_services,
        project_id=non_default_project,
        description="Non-default project",
    )

    # Verify session creation succeeded
    assert "session_id" in result
    assert result["project_id"] == non_default_project
    assert "error" not in result

    # Verify warning about mismatch
    assert "warning" in result
    warning = result["warning"]
    assert "message" in warning
    assert non_default_project in warning["message"]
    assert default_project in warning["message"]

    # Verify suggestion to use get_server_info()
    assert "suggestion" in warning
    assert "get_server_info()" in warning["suggestion"]
    assert "available projects" in warning["suggestion"]


@pytest.mark.asyncio
async def test_project_mismatch_with_default_project(integration_services):
    """Test no warning when using default project.

    Requirements: 3.1, 3.3
    """
    # Create session with default project
    default_project = integration_services["server_config"]["default_project_id"]
    result = await create_session(
        services=integration_services,
        project_id=default_project,
        description="Default project",
    )

    # Verify session creation succeeded
    assert "session_id" in result
    assert result["project_id"] == default_project
    assert "error" not in result

    # Verify NO warning for default project
    assert "warning" not in result


@pytest.mark.asyncio
async def test_limit_parameter_variations(integration_services):
    """Test get_server_info() with different limit parameters.

    Requirements: 1.1, 1.2, 1.3, 7.1, 7.2, 7.3
    """
    # Test with default limit (50)
    result_default = await get_server_info(services=integration_services)

    assert "available_projects" in result_default
    # Should return all 3 projects (less than default limit of 50)
    assert len(result_default["available_projects"]) == 3

    # Test with custom limit (2)
    result_limited = await get_server_info(services=integration_services, limit=2)

    assert "available_projects" in result_limited
    # Should return only 2 projects
    assert len(result_limited["available_projects"]) == 2

    # Test with large limit (100)
    result_large = await get_server_info(services=integration_services, limit=100)

    assert "available_projects" in result_large
    # Should still return all 3 projects (limited by actual count)
    assert len(result_large["available_projects"]) == 3

    # Test with limit of 1
    result_one = await get_server_info(services=integration_services, limit=1)

    assert "available_projects" in result_one
    assert len(result_one["available_projects"]) == 1


@pytest.mark.asyncio
async def test_sort_by_parameter_variations(integration_services):
    """Test get_server_info() with different sort_by parameters.

    Requirements: 1.1, 1.2, 1.3
    """
    # Test with sort_by="last_indexed" (default)
    result_time = await get_server_info(
        services=integration_services, sort_by="last_indexed"
    )

    assert "available_projects" in result_time
    projects_time = result_time["available_projects"]
    assert len(projects_time) == 3

    # Test with sort_by="name"
    result_name = await get_server_info(services=integration_services, sort_by="name")

    assert "available_projects" in result_name
    projects_name = result_name["available_projects"]
    assert len(projects_name) == 3

    # Verify projects are sorted alphabetically by name
    project_names = [p["project_id"] for p in projects_name]
    assert project_names == sorted(project_names)


@pytest.mark.asyncio
async def test_all_error_messages_include_actionable_suggestions(
    integration_services, mock_fallback_search_empty
):
    """Verify all error messages include actionable suggestions.

    Requirements: 2.4, 3.3, 4.4, 4.5
    """
    # Test 1: Invalid project_id validation error
    invalid_result = await create_session(
        services=integration_services, project_id="invalid!@#", description="Test"
    )

    assert "error" in invalid_result
    assert "suggestion" in invalid_result
    assert "get_server_info()" in invalid_result["suggestion"]
    assert "examples" in invalid_result

    # Test 2: Empty project search error
    session_result = await create_session(
        services=integration_services, project_id="empty_project", description="Empty"
    )

    search_result = await search_knowledge(
        services=integration_services,
        session_id=session_result["session_id"],
        query="test",
        limit=10,
    )

    assert "suggestions" in search_result
    assert len(search_result["suggestions"]) >= 3
    suggestions_text = " ".join(search_result["suggestions"])
    assert "add_knowledge()" in suggestions_text
    assert "get_server_info()" in suggestions_text

    # Test 3: No matches search error
    session_result2 = await create_session(
        services=integration_services, project_id="test_project", description="Test"
    )

    search_result2 = await search_knowledge(
        services=integration_services,
        session_id=session_result2["session_id"],
        query="nonexistent",
        limit=10,
    )

    assert "suggestions" in search_result2
    assert len(search_result2["suggestions"]) >= 4
    suggestions_text2 = " ".join(search_result2["suggestions"])
    assert "broader" in suggestions_text2.lower()
    assert (
        "different" in suggestions_text2.lower()
        or "synonyms" in suggestions_text2.lower()
    )


@pytest.mark.asyncio
async def test_complete_user_journey_success_path(integration_services, tmp_path):
    """Test complete successful user journey from discovery to search.

    Requirements: All requirements (1.1-1.5, 2.1-2.5, 3.1-3.5, 4.1-4.5)
    """
    # Step 1: Discover server and projects
    server_info = await get_server_info(services=integration_services, limit=50)

    assert "server" in server_info
    assert "available_projects" in server_info
    assert len(server_info["available_projects"]) > 0

    # Step 2: Create session with discovered project
    project_id = server_info["available_projects"][0]["project_id"]
    session_result = await create_session(
        services=integration_services,
        project_id=project_id,
        description="Complete journey test",
    )

    assert "session_id" in session_result
    session_id = session_result["session_id"]

    # Step 3: Simulate adding knowledge to project
    # Note: We're testing the flow, not the actual indexing implementation
    # In reality, agent would call add_knowledge() here

    # Step 4: Mock successful search (must be SearchResult objects)
    integration_services["search_service"].hybrid_search.return_value = [
        SearchResult(
            id="test_result_1",
            data={
                "file_path": "example.py",
                "content": "def example(): return 'hello'",
                "line_start": 1,
                "line_end": 1,
            },
            score=0.95,
            source="hybrid",
        )
    ]

    # Step 5: Search successfully
    search_result = await search_knowledge(
        services=integration_services,
        session_id=session_id,
        query="example function",
        limit=10,
    )

    assert "results" in search_result
    assert len(search_result["results"]) == 1
    assert search_result["total"] == 1
    assert "error" not in search_result
    assert "debug_info" not in search_result


@pytest.mark.asyncio
async def test_complete_user_journey_error_recovery_path(
    integration_services, mock_fallback_search_empty
):
    """Test complete user journey with error recovery.

    Requirements: All requirements (1.1-1.5, 2.1-2.5, 3.1-3.5, 4.1-4.5)
    """
    # Step 1: Attempt invalid project_id
    invalid_result = await create_session(
        services=integration_services,
        project_id="Invalid Project Name!",
        description="Test",
    )

    assert "error" in invalid_result
    assert "INVALID_PROJECT_ID" in invalid_result["error_code"]

    # Step 2: Discover valid projects
    server_info = await get_server_info(services=integration_services)

    assert "available_projects" in server_info
    assert "project_id_rules" in server_info

    # Step 3: Retry with valid project
    valid_project = server_info["available_projects"][0]["project_id"]
    retry_result = await create_session(
        services=integration_services,
        project_id=valid_project,
        description="Retry after error",
    )

    assert "session_id" in retry_result
    assert "error" not in retry_result

    # Step 4: Create session with empty project to test search error
    empty_session_result = await create_session(
        services=integration_services,
        project_id="empty_project",
        description="Empty project for testing",
    )

    search_result = await search_knowledge(
        services=integration_services,
        session_id=empty_session_result["session_id"],
        query="test",
        limit=10,
    )

    # Verify helpful error for empty project
    assert "debug_info" in search_result
    assert "suggestions" in search_result
    assert any("add_knowledge()" in s for s in search_result["suggestions"])


@pytest.mark.asyncio
async def test_caching_behavior_with_different_parameters(integration_services):
    """Test that caching works correctly with different limit and sort_by parameters.

    Requirements: 7.4, 7.5
    """
    # First call with limit=50, sort_by="last_indexed"
    result1 = await get_server_info(
        services=integration_services, limit=50, sort_by="last_indexed"
    )

    # Second call with same parameters (should use cache)
    result2 = await get_server_info(
        services=integration_services, limit=50, sort_by="last_indexed"
    )

    # Results should be identical
    assert result1 == result2

    # Third call with different limit (should NOT use cache)
    result3 = await get_server_info(
        services=integration_services, limit=10, sort_by="last_indexed"
    )

    # Should have different number of projects
    assert len(result3["available_projects"]) <= len(result1["available_projects"])

    # Fourth call with different sort_by (should NOT use cache)
    result4 = await get_server_info(
        services=integration_services, limit=50, sort_by="name"
    )

    # Should have same projects but potentially different order
    assert len(result4["available_projects"]) == len(result1["available_projects"])
