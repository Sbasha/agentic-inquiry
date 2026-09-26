"""
Tests for info tools (get_server_info, get_events, get_project_info).

Tests server discovery, project listing, and caching behavior.
"""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from agentic_inquiry.mcp.tools.info import get_server_info, get_events, get_project_info
from agentic_inquiry.mcp.models.session import Session, ProjectStatistics


@pytest.fixture
def mcp_services():
    """Create mock services for testing."""
    session_manager = MagicMock()
    mock_db_manager = MagicMock()
    memory_system = MagicMock()
    event_system = MagicMock()
    config = MagicMock()
    
    # Mock server configuration
    server_config = {
        "default_project_id": "agentic-inquiry",
        "server_name": "Agentic Inquiry MCP Server",
        "server_version": "1.0.0",
        "server_description": "Intelligent search and knowledge management"
    }
    
    # Mock session
    mock_session = Session(
        session_id="test-session-123",
        project_id="test-project",
        created_at=datetime.now(),
        last_active=datetime.now(),
        description="Test session",
    )
    
    # Mock database table
    mock_table = MagicMock()
    mock_db_manager.get_table.return_value = mock_table
    
    # Configure async methods properly to avoid warnings
    session_manager.get_session = AsyncMock(return_value=mock_session)
    session_manager.validate_session = AsyncMock(return_value=True)
    session_manager.get_project_statistics = AsyncMock(return_value=ProjectStatistics(
        total_chunks=0, total_memories=0, total_files=0, index_health="empty"
    ))
    
    mock_db_manager.advanced_filter = AsyncMock(return_value=[])
    mock_db_manager.count_records = AsyncMock(return_value=0)
    mock_db_manager.count_relationships_by_type = AsyncMock(return_value={})
    
    memory_system.get_stats = AsyncMock(return_value={
        "total_memories": 0,
        "working": {"count": 0},
        "episodic": {"count": 0},
        "semantic": {"count": 0}
    })
    
    return {
        "session_manager": session_manager,
        "mock_db_manager": mock_db_manager,
        "storage": mock_db_manager,  # Expose as storage for tools
        "memory_system": memory_system,
        "event_system": event_system,
        "config": config,
        "server_config": server_config,
    }


@pytest.fixture
def sample_chunks():
    """Sample chunks for testing."""
    return [
        {
            "id": "chunk1",
            "project_id": "project-a",
            "file_path": "src/auth.py",
            "language": "python",
            "created_at": datetime(2024, 1, 15, 10, 30, 0),
        },
        {
            "id": "chunk2",
            "project_id": "project-a",
            "file_path": "src/utils.py",
            "language": "python",
            "created_at": datetime(2024, 1, 16, 14, 20, 0),
        },
        {
            "id": "chunk3",
            "project_id": "project-b",
            "file_path": "docs/README.md",
            "language": "markdown",
            "created_at": datetime(2024, 1, 10, 9, 0, 0),
        },
        {
            "id": "chunk4",
            "project_id": "project-c",
            "file_path": "main.js",
            "language": "javascript",
            "created_at": datetime(2024, 1, 20, 16, 45, 0),
        },
    ]


@pytest.fixture
def sample_project_stats():
    """Sample project statistics."""
    return ProjectStatistics(
        total_chunks=10,
        total_memories=5,
        total_files=3,
        index_health="healthy",
        languages={"python": 8, "markdown": 2},
        entity_counts={"function": 5, "class": 3}
    )


class TestGetServerInfo:
    """Tests for get_server_info() function."""
    
    @pytest.mark.asyncio
    async def test_server_metadata_retrieval(self, mcp_services):
        """Test that server metadata is correctly retrieved."""
        # Setup
        mcp_services["storage"].advanced_filter.return_value = []
        
        # Execute
        result = await get_server_info(mcp_services)
        
        # Verify
        assert "server" in result
        assert result["server"]["name"] == "Agentic Inquiry MCP Server"
        assert result["server"]["version"] == "1.0.0"
        assert result["server"]["description"] == "Intelligent search and knowledge management"
    
    @pytest.mark.asyncio
    async def test_default_project_info(self, mcp_services):
        """Test that default project information is included."""
        # Setup
        mcp_services["storage"].advanced_filter.return_value = []
        
        # Execute
        result = await get_server_info(mcp_services)
        
        # Verify
        assert "default_project" in result
        assert result["default_project"]["project_id"] == "agentic-inquiry"
        assert "description" in result["default_project"]
    
    @pytest.mark.asyncio
    async def test_project_discovery_from_database(self, mcp_services, sample_chunks, sample_project_stats):
        """Test that projects are discovered from database."""
        # Setup
        # Make advanced_filter async
        async def mock_advanced_filter(*args, **kwargs):
            return sample_chunks
        
        mcp_services["storage"].advanced_filter = mock_advanced_filter
        
        # Make get_project_statistics async
        async def mock_get_stats(project_id):
            return sample_project_stats
        
        mcp_services["session_manager"].get_project_statistics = mock_get_stats
        
        # Clear cache
        if hasattr(get_server_info, "_cache"):
            get_server_info._cache.clear()
        
        # Execute
        result = await get_server_info(mcp_services, limit=50)
        
        # Verify
        assert "available_projects" in result
        projects = result["available_projects"]
        
        # Should have 3 unique projects
        assert len(projects) == 3
        project_ids = [p["project_id"] for p in projects]
        assert "project-a" in project_ids
        assert "project-b" in project_ids
        assert "project-c" in project_ids
    
    @pytest.mark.asyncio
    async def test_statistics_gathering_for_projects(self, mcp_services, sample_chunks, sample_project_stats):
        """Test that statistics are gathered for each project."""
        # Setup
        # Make advanced_filter async
        async def mock_advanced_filter(*args, **kwargs):
            return sample_chunks
        
        mcp_services["storage"].advanced_filter = mock_advanced_filter
        
        # Make get_project_statistics async
        async def mock_get_stats(project_id):
            return sample_project_stats
        
        mcp_services["session_manager"].get_project_statistics = mock_get_stats
        
        # Clear cache
        if hasattr(get_server_info, "_cache"):
            get_server_info._cache.clear()
        
        # Execute
        result = await get_server_info(mcp_services)
        
        # Verify
        projects = result["available_projects"]
        assert len(projects) > 0
        
        # Check first project has statistics
        project = projects[0]
        assert "total_chunks" in project
        assert "total_files" in project
        assert "total_entities" in project
        assert "last_indexed" in project
        assert "index_health" in project
        assert "languages" in project
        
        # Verify statistics match
        assert project["total_chunks"] == 10
        assert project["total_files"] == 3
        assert project["index_health"] == "healthy"
    
    @pytest.mark.asyncio
    async def test_response_format_and_structure(self, mcp_services):
        """Test that response has correct format and structure."""
        # Setup
        mcp_services["storage"].advanced_filter.return_value = []
        
        # Execute
        result = await get_server_info(mcp_services)
        
        # Verify all required keys
        assert "server" in result
        assert "default_project" in result
        assert "available_projects" in result
        assert "project_id_rules" in result
        assert "tools" in result
        assert "usage_guidelines" in result
        
        # Verify project_id_rules structure
        rules = result["project_id_rules"]
        assert "format" in rules
        assert "pattern" in rules
        assert "length" in rules
        assert "normalization" in rules
        assert "examples" in rules
        
        # Verify tools structure
        tools = result["tools"]
        assert "cognitive_tools" in tools
        assert "direct_access_tools" in tools
        
        # Verify usage_guidelines structure
        guidelines = result["usage_guidelines"]
        assert "getting_started" in guidelines
        assert "project_discovery" in guidelines
        assert "project_mismatch" in guidelines
    
    @pytest.mark.asyncio
    async def test_caching_behavior(self, mcp_services, sample_chunks):
        """Test that results are cached for 60 seconds."""
        # Setup
        mcp_services["storage"].advanced_filter.return_value = sample_chunks
        
        # Clear cache if exists
        if hasattr(get_server_info, "_cache"):
            get_server_info._cache.clear()
        
        # First call
        result1 = await get_server_info(mcp_services, limit=10)
        
        # Verify database was called
        assert mcp_services["storage"].advanced_filter.call_count == 1
        
        # Second call (should use cache)
        result2 = await get_server_info(mcp_services, limit=10)
        
        # Verify database was NOT called again
        assert mcp_services["storage"].advanced_filter.call_count == 1
        
        # Results should be identical
        assert result1 == result2
    
    @pytest.mark.asyncio
    async def test_limit_parameter_default(self, mcp_services, sample_chunks):
        """Test that limit parameter defaults to 50."""
        # Setup - create more than 50 projects
        many_chunks = []
        for i in range(60):
            many_chunks.append({
                "id": f"chunk{i}",
                "project_id": f"project-{i}",
                "file_path": f"file{i}.py",
                "created_at": datetime(2024, 1, 1, 0, 0, 0),
            })
        
        mcp_services["storage"].advanced_filter.return_value = many_chunks
        mcp_services["session_manager"].get_project_statistics.return_value = ProjectStatistics(
            total_chunks=1, total_memories=0, total_files=1, index_health="healthy"
        )
        
        # Clear cache
        if hasattr(get_server_info, "_cache"):
            get_server_info._cache.clear()
        
        # Execute without limit parameter
        result = await get_server_info(mcp_services)
        
        # Verify - should return max 50 projects
        assert len(result["available_projects"]) == 50
    
    @pytest.mark.asyncio
    async def test_limit_parameter_custom_value(self, mcp_services, sample_chunks):
        """Test that custom limit parameter is respected."""
        # Setup
        mcp_services["storage"].advanced_filter.return_value = sample_chunks
        mcp_services["session_manager"].get_project_statistics.return_value = ProjectStatistics(
            total_chunks=1, total_memories=0, total_files=1, index_health="healthy"
        )
        
        # Clear cache
        if hasattr(get_server_info, "_cache"):
            get_server_info._cache.clear()
        
        # Execute with limit=2
        result = await get_server_info(mcp_services, limit=2)
        
        # Verify - should return max 2 projects
        assert len(result["available_projects"]) <= 2
    
    @pytest.mark.asyncio
    async def test_sort_by_last_indexed(self, mcp_services, sample_chunks, sample_project_stats):
        """Test sorting projects by last_indexed (most recent first)."""
        # Setup
        mcp_services["storage"].advanced_filter.return_value = sample_chunks
        mcp_services["session_manager"].get_project_statistics.return_value = sample_project_stats
        
        # Clear cache
        if hasattr(get_server_info, "_cache"):
            get_server_info._cache.clear()
        
        # Execute with sort_by="last_indexed"
        result = await get_server_info(mcp_services, sort_by="last_indexed")
        
        # Verify - projects should be sorted by last_indexed (most recent first)
        projects = result["available_projects"]
        assert len(projects) == 3
        
        # project-c should be first (2024-01-20)
        # project-a should be second (2024-01-16)
        # project-b should be third (2024-01-10)
        assert projects[0]["project_id"] == "project-c"
        assert projects[1]["project_id"] == "project-a"
        assert projects[2]["project_id"] == "project-b"
    
    @pytest.mark.asyncio
    async def test_sort_by_name(self, mcp_services, sample_chunks, sample_project_stats):
        """Test sorting projects alphabetically by name."""
        # Setup
        mcp_services["storage"].advanced_filter.return_value = sample_chunks
        mcp_services["session_manager"].get_project_statistics.return_value = sample_project_stats
        
        # Clear cache
        if hasattr(get_server_info, "_cache"):
            get_server_info._cache.clear()
        
        # Execute with sort_by="name"
        result = await get_server_info(mcp_services, sort_by="name")
        
        # Verify - projects should be sorted alphabetically
        projects = result["available_projects"]
        assert len(projects) == 3
        
        # Should be in alphabetical order
        assert projects[0]["project_id"] == "project-a"
        assert projects[1]["project_id"] == "project-b"
        assert projects[2]["project_id"] == "project-c"
    
    @pytest.mark.asyncio
    async def test_empty_database(self, mcp_services):
        """Test behavior with empty database (no projects)."""
        # Setup
        mcp_services["storage"].advanced_filter.return_value = []
        
        # Clear cache
        if hasattr(get_server_info, "_cache"):
            get_server_info._cache.clear()
        
        # Execute
        result = await get_server_info(mcp_services)
        
        # Verify
        assert "available_projects" in result
        assert result["available_projects"] == []
        
        # Other fields should still be present
        assert "server" in result
        assert "default_project" in result
        assert "project_id_rules" in result
    
    @pytest.mark.asyncio
    async def test_multiple_projects(self, mcp_services, sample_chunks, sample_project_stats):
        """Test handling of multiple projects."""
        # Setup
        mcp_services["storage"].advanced_filter.return_value = sample_chunks
        mcp_services["session_manager"].get_project_statistics.return_value = sample_project_stats
        
        # Clear cache
        if hasattr(get_server_info, "_cache"):
            get_server_info._cache.clear()
        
        # Execute
        result = await get_server_info(mcp_services)
        
        # Verify
        projects = result["available_projects"]
        assert len(projects) == 3
        
        # All projects should have required fields
        for project in projects:
            assert "project_id" in project
            assert "total_chunks" in project
            assert "total_files" in project
            assert "total_entities" in project
            assert "last_indexed" in project
            assert "index_health" in project
            assert "languages" in project
    
    @pytest.mark.asyncio
    async def test_cache_key_includes_parameters(self, mcp_services, sample_chunks):
        """Test that cache key includes limit and sort_by parameters."""
        # Setup
        mcp_services["storage"].advanced_filter.return_value = sample_chunks
        
        # Clear cache
        if hasattr(get_server_info, "_cache"):
            get_server_info._cache.clear()
        
        # Call with different parameters
        await get_server_info(mcp_services, limit=10, sort_by="last_indexed")
        await get_server_info(mcp_services, limit=20, sort_by="last_indexed")
        await get_server_info(mcp_services, limit=10, sort_by="name")
        
        # Verify cache has 3 different entries
        assert len(get_server_info._cache) == 3
        
        # Verify cache keys are different
        cache_keys = list(get_server_info._cache.keys())
        assert "server_info:v1:10:last_indexed" in cache_keys
        assert "server_info:v1:20:last_indexed" in cache_keys
        assert "server_info:v1:10:name" in cache_keys
    
    @pytest.mark.asyncio
    async def test_statistics_failure_handling(self, mcp_services, sample_chunks):
        """Test graceful handling when statistics gathering fails."""
        # Setup
        mcp_services["storage"].advanced_filter.return_value = sample_chunks
        mcp_services["session_manager"].get_project_statistics.side_effect = Exception("Stats error")
        
        # Clear cache
        if hasattr(get_server_info, "_cache"):
            get_server_info._cache.clear()
        
        # Execute - should not raise exception
        result = await get_server_info(mcp_services)
        
        # Verify - projects should still be listed with basic info
        projects = result["available_projects"]
        assert len(projects) == 3
        
        # Projects should have default values
        for project in projects:
            assert project["total_chunks"] == 0
            assert project["total_files"] == 0
            assert project["total_entities"] == 0
            assert project["index_health"] == "unknown"


class TestGetEvents:
    """Tests for get_events() function."""
    
    @pytest.mark.asyncio
    async def test_get_events_basic(self, mcp_services):
        """Test basic event retrieval."""
        # Setup
        mock_session = Session(
            session_id="test-session-123",
            project_id="test-project",
            created_at=datetime.now(),
            last_active=datetime.now(),
            description="Test session",
            history=[
                {
                    "timestamp": datetime.now().isoformat(),
                    "event_type": "mcp.tool.started",
                    "tool_name": "search_knowledge",
                    "details": {"query": "test"}
                }
            ]
        )
        mcp_services["session_manager"].get_session.return_value = mock_session
        
        # Execute
        result = await get_events(mcp_services, "test-session-123")
        
        # Verify
        assert "events" in result
        assert len(result["events"]) == 1
        assert result["events"][0]["event_type"] == "mcp.tool.started"


class TestGetProjectInfo:
    """Tests for get_project_info() function."""
    
    @pytest.mark.asyncio
    async def test_get_project_info_basic(self, mcp_services):
        """Test basic project info retrieval."""
        # Setup
        mcp_services["memory_system"].get_stats.return_value = {
            "total_memories": 10,
            "working": {"count": 3},
            "episodic": {"count": 4},
            "semantic": {"count": 3}
        }
        
        # Execute
        result = await get_project_info(mcp_services, "test-session-123")
        
        # Verify
        assert "project_id" in result
        assert "statistics" in result
        assert "status" in result
        assert "guidance" in result

    @pytest.mark.asyncio
    async def test_get_project_info_statistics_accuracy(self, mcp_services):
        """Test that statistics accurately reflect indexed content."""
        # Setup - simulate indexed content (count_records used for chunks/entities)
        mcp_services["storage"].count_records = AsyncMock(side_effect=lambda table_name, **kwargs: {
            "document_chunks": 150,
            "graph_entities": 75,
        }.get(table_name, 0))

        # Mock count_relationships_by_type (returns dict with type -> count)
        mcp_services["storage"].count_relationships_by_type = AsyncMock(return_value={
            "calls": 100,
            "imports": 50,
            "defines": 50,
        })  # 200 relationships total

        # Mock must match actual API structure:
        # working_memory.size + episodic_memory.size + semantic_memory.size
        mcp_services["memory_system"].get_stats.return_value = {
            "working_memory": {"size": 10},
            "episodic_memory": {"size": 8},
            "semantic_memory": {"size": 7}
        }

        # Execute
        result = await get_project_info(mcp_services, "test-session-123")

        # Verify statistics are accurate
        assert result["statistics"]["chunks_indexed"] == 150
        assert result["statistics"]["entities_created"] == 75
        assert result["statistics"]["relationships_created"] == 200
        assert result["statistics"]["memories_stored"] == 25

        # Verify status flags
        assert result["status"]["indexed"] is True
        assert result["status"]["has_entities"] is True
        assert result["status"]["has_relationships"] is True
        assert result["status"]["has_memories"] is True

        # Verify relationships_by_type includes actual types (not "unknown")
        assert "calls" in result["statistics"]["relationships_by_type"]
        assert "imports" in result["statistics"]["relationships_by_type"]
        assert "unknown" not in result["statistics"]["relationships_by_type"]

    @pytest.mark.asyncio
    async def test_get_project_info_handles_database_errors(self, mcp_services):
        """Test that database errors are handled gracefully."""
        # Setup - simulate database error
        mcp_services["storage"].count_records = AsyncMock(
            side_effect=Exception("Database connection failed")
        )

        # Execute
        result = await get_project_info(mcp_services, "test-session-123")

        # Verify error handling - should return 0 counts instead of failing
        assert result["statistics"]["chunks_indexed"] == 0
        assert result["statistics"]["entities_created"] == 0
        assert result["statistics"]["relationships_created"] == 0

        # Verify status flags reflect empty state
        assert result["status"]["indexed"] is False
        assert result["status"]["has_entities"] is False
        assert result["status"]["has_relationships"] is False
        assert result["warnings"] == ["Could not read index statistics; counts are unknown."]
        assert not any("not yet indexed" in step for step in result["guidance"]["next_steps"])


class TestRunMaintenance:
    """Tests for run_maintenance() MCP tool."""

    @pytest.fixture
    def maintenance_services(self, mcp_services):
        """Create services with maintenance mocks."""
        # Mock run_maintenance on db_manager
        mcp_services["storage"].run_maintenance = AsyncMock(return_value={
            "compaction": {
                "document_chunks": {"status": "success", "fragments_before": 10, "fragments_after": 2},
                "graph_entities": {"status": "success", "fragments_before": 5, "fragments_after": 1},
            },
            "cleanup": {
                "document_chunks": {"status": "success", "versions_before": 5, "versions_after": 1},
                "graph_entities": {"status": "success", "versions_before": 3, "versions_after": 1},
            },
            "summary": {
                "fragments_reduced": 12,
                "versions_removed": 6,
            }
        })
        return mcp_services

    @pytest.mark.asyncio
    async def test_run_maintenance_success(self, maintenance_services):
        """Test successful maintenance run."""
        from agentic_inquiry.mcp.tools.info import run_maintenance

        result = await run_maintenance(
            maintenance_services,
            session_id="test-session-123",
            cleanup_hours=1.0
        )

        assert result["status"] == "success"
        assert "compaction" in result
        assert "cleanup" in result
        assert "summary" in result
        assert result["summary"]["fragments_reduced"] == 12
        assert result["summary"]["versions_removed"] == 6
        assert "message" in result

    @pytest.mark.asyncio
    async def test_run_maintenance_invalid_session(self, maintenance_services):
        """Test maintenance with invalid session."""
        from agentic_inquiry.mcp.tools.info import run_maintenance

        # Setup - session validation fails
        maintenance_services["session_manager"].validate_session = AsyncMock(return_value=False)

        result = await run_maintenance(
            maintenance_services,
            session_id="invalid-session",
            cleanup_hours=1.0
        )

        assert "error" in result
        assert "not found or expired" in result["error"]
        assert "suggestion" in result

    @pytest.mark.asyncio
    async def test_run_maintenance_custom_cleanup_hours(self, maintenance_services):
        """Test maintenance with custom cleanup_hours parameter."""
        from datetime import timedelta
        from agentic_inquiry.mcp.tools.info import run_maintenance

        result = await run_maintenance(
            maintenance_services,
            session_id="test-session-123",
            cleanup_hours=24.0
        )

        # Verify db_manager.run_maintenance was called with correct timedelta
        maintenance_services["storage"].run_maintenance.assert_called_once()
        call_kwargs = maintenance_services["storage"].run_maintenance.call_args[1]
        assert call_kwargs["cleanup_older_than"] == timedelta(hours=24.0)

        assert result["status"] == "success"
        assert result["cleanup_hours"] == 24.0

    @pytest.mark.asyncio
    async def test_run_maintenance_database_error(self, maintenance_services):
        """Test maintenance handles database errors gracefully."""
        from agentic_inquiry.mcp.tools.info import run_maintenance

        # Setup - database error
        maintenance_services["storage"].run_maintenance = AsyncMock(
            side_effect=Exception("Database connection failed")
        )

        result = await run_maintenance(
            maintenance_services,
            session_id="test-session-123",
            cleanup_hours=1.0
        )

        assert "error" in result
        assert "Database connection failed" in result["error"]
        assert "suggestion" in result

    @pytest.mark.asyncio
    async def test_run_maintenance_partial_success(self, maintenance_services):
        """Test maintenance with partial success (some tables failed)."""
        from agentic_inquiry.mcp.tools.info import run_maintenance

        # Setup - partial success
        maintenance_services["storage"].run_maintenance = AsyncMock(return_value={
            "compaction": {
                "document_chunks": {"status": "success", "fragments_before": 10, "fragments_after": 2},
                "graph_entities": {"status": "error", "error": "Table locked"},
            },
            "cleanup": {
                "document_chunks": {"status": "success", "versions_before": 5, "versions_after": 1},
                "graph_entities": {"status": "skipped", "reason": "compaction failed"},
            },
            "summary": {
                "fragments_reduced": 8,
                "versions_removed": 4,
            }
        })

        result = await run_maintenance(
            maintenance_services,
            session_id="test-session-123",
            cleanup_hours=1.0
        )

        # Should still return success status (partial success is still success)
        assert result["status"] == "success"
        assert result["compaction"]["graph_entities"]["status"] == "error"
        assert result["cleanup"]["graph_entities"]["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_run_maintenance_message_format(self, maintenance_services):
        """Test that message correctly summarizes results."""
        from agentic_inquiry.mcp.tools.info import run_maintenance

        result = await run_maintenance(
            maintenance_services,
            session_id="test-session-123",
            cleanup_hours=1.0
        )

        message = result["message"]
        assert "12 fragments" in message
        assert "6 old versions" in message

    @pytest.mark.asyncio
    async def test_run_maintenance_default_cleanup_hours(self, maintenance_services):
        """Test that cleanup_hours defaults to 1.0."""
        from datetime import timedelta
        from agentic_inquiry.mcp.tools.info import run_maintenance

        result = await run_maintenance(
            maintenance_services,
            session_id="test-session-123"
            # cleanup_hours not specified, should default to 1.0
        )

        # Verify db_manager.run_maintenance was called with default timedelta
        call_kwargs = maintenance_services["storage"].run_maintenance.call_args[1]
        assert call_kwargs["cleanup_older_than"] == timedelta(hours=1.0)

        assert result["status"] == "success"
        assert result["cleanup_hours"] == 1.0
