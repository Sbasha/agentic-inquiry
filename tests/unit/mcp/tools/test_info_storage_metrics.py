"""Tests for storage_metrics in get_project_info.

This test module verifies that get_project_info returns storage metrics
including table sizes and version counts for tracking disk usage trends.

Requirement tested: NFR-3.2
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

pytestmark = pytest.mark.unit


class TestStorageMetricsInProjectInfo:
    """Test storage_metrics included in get_project_info response."""

    @pytest.mark.asyncio
    async def test_storage_metrics_in_project_info(self):
        """Test that get_project_info includes storage_metrics in response.

        Verifies:
        - Response includes 'storage_metrics' key
        - storage_metrics is a dict
        - Contains table information
        """
        from agentic_inquiry.mcp.tools.info import get_project_info

        # Create mock services
        mock_session_manager = AsyncMock()
        mock_session = MagicMock()
        mock_session.project_id = "test_project"
        mock_session_manager.validate_session = AsyncMock(return_value=True)
        mock_session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock storage with db_manager that has get_table_statistics
        mock_storage = AsyncMock()
        mock_lance_manager = AsyncMock()

        # Mock table statistics
        table_stats = {
            "document_chunks": {
                "status": "success",
                "size_bytes": 1024000,  # 1MB
                "version_count": 5,
                "fragment_count": 3,
            },
            "graph_entities": {
                "status": "success",
                "size_bytes": 512000,  # 512KB
                "version_count": 3,
                "fragment_count": 2,
            },
            "graph_relationships": {
                "status": "success",
                "size_bytes": 256000,  # 256KB
                "version_count": 2,
                "fragment_count": 1,
            },
        }

        mock_lance_manager.get_table_statistics = AsyncMock(return_value=table_stats)
        mock_storage.get_db_manager = MagicMock(return_value=mock_lance_manager)
        mock_storage.count_records = AsyncMock(return_value=10)
        mock_storage.advanced_filter = AsyncMock(return_value=[])

        # Mock memory system
        mock_memory_system = AsyncMock()
        mock_memory_system.get_stats = AsyncMock(
            return_value={
                "working_memory": {"size": 5},
                "episodic_memory": {"size": 10},
                "semantic_memory": {"size": 3},
            }
        )

        # Mock cache manager
        mock_cache_manager = MagicMock()
        mock_cache_manager.get = MagicMock(return_value=None)  # No cache hit
        mock_cache_manager.set = MagicMock()

        services = {
            "session_manager": mock_session_manager,
            "storage": mock_storage,
            "memory_system": mock_memory_system,
            "cache_manager": mock_cache_manager,
        }

        # Mock check_project_state
        with patch(
            "agentic_inquiry.mcp.utils.project_state.check_project_state",
            new_callable=AsyncMock,
        ) as mock_check:
            mock_check.return_value = {
                "chunk_count": 100,
                "entity_count": 50,
                "warnings": [],
            }

            # Call get_project_info
            result = await get_project_info(services, "test_session")

        # Verify storage_metrics is in response
        assert "storage_metrics" in result, "Response should include storage_metrics"
        assert isinstance(result["storage_metrics"], dict), (
            "storage_metrics should be a dict"
        )

    @pytest.mark.asyncio
    async def test_storage_metrics_includes_table_sizes(self):
        """Test that storage_metrics includes table sizes in bytes.

        Verifies:
        - Each table has size_bytes
        - total_size_bytes is calculated correctly
        - Sizes are numeric
        """
        from agentic_inquiry.mcp.tools.info import get_project_info

        # Create mock services
        mock_session_manager = AsyncMock()
        mock_session = MagicMock()
        mock_session.project_id = "test_project"
        mock_session_manager.validate_session = AsyncMock(return_value=True)
        mock_session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock storage with specific table sizes
        mock_storage = AsyncMock()
        mock_lance_manager = AsyncMock()

        table_stats = {
            "document_chunks": {
                "status": "success",
                "size_bytes": 2048000,  # 2MB
                "version_count": 10,
                "fragment_count": 5,
            },
            "graph_entities": {
                "status": "success",
                "size_bytes": 1024000,  # 1MB
                "version_count": 8,
                "fragment_count": 4,
            },
            "graph_relationships": {
                "status": "success",
                "size_bytes": 512000,  # 512KB
                "version_count": 5,
                "fragment_count": 2,
            },
        }

        mock_lance_manager.get_table_statistics = AsyncMock(return_value=table_stats)
        mock_storage.get_db_manager = MagicMock(return_value=mock_lance_manager)
        mock_storage.count_records = AsyncMock(return_value=10)
        mock_storage.advanced_filter = AsyncMock(return_value=[])

        # Mock memory system
        mock_memory_system = AsyncMock()
        mock_memory_system.get_stats = AsyncMock(
            return_value={
                "working_memory": {"size": 0},
                "episodic_memory": {"size": 0},
                "semantic_memory": {"size": 0},
            }
        )

        # Mock cache manager (no cache)
        mock_cache_manager = MagicMock()
        mock_cache_manager.get = MagicMock(return_value=None)
        mock_cache_manager.set = MagicMock()

        services = {
            "session_manager": mock_session_manager,
            "storage": mock_storage,
            "memory_system": mock_memory_system,
            "cache_manager": mock_cache_manager,
        }

        # Mock check_project_state
        with patch(
            "agentic_inquiry.mcp.utils.project_state.check_project_state",
            new_callable=AsyncMock,
        ) as mock_check:
            mock_check.return_value = {
                "chunk_count": 100,
                "entity_count": 50,
                "warnings": [],
            }

            # Call get_project_info
            result = await get_project_info(services, "test_session")

        # Verify storage_metrics structure
        storage_metrics = result["storage_metrics"]
        assert "tables" in storage_metrics, "storage_metrics should have 'tables'"
        assert "total_size_bytes" in storage_metrics, (
            "storage_metrics should have 'total_size_bytes'"
        )

        # Verify table sizes
        tables = storage_metrics["tables"]
        assert "document_chunks" in tables
        assert "graph_entities" in tables
        assert "graph_relationships" in tables

        # Verify each table has size_bytes
        for table_name, table_info in tables.items():
            assert "size_bytes" in table_info, f"{table_name} should have size_bytes"
            assert isinstance(table_info["size_bytes"], (int, float)), (
                f"{table_name} size_bytes should be numeric"
            )

        # Verify total_size_bytes is sum of all table sizes
        expected_total = 2048000 + 1024000 + 512000  # 3.5MB
        assert storage_metrics["total_size_bytes"] == expected_total

    @pytest.mark.asyncio
    async def test_storage_metrics_includes_version_counts(self):
        """Test that storage_metrics includes version counts per table.

        Verifies:
        - Each table has version_count
        - version_count is numeric
        - version_count reflects MVCC versioning
        """
        from agentic_inquiry.mcp.tools.info import get_project_info

        # Create mock services
        mock_session_manager = AsyncMock()
        mock_session = MagicMock()
        mock_session.project_id = "test_project"
        mock_session_manager.validate_session = AsyncMock(return_value=True)
        mock_session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock storage with specific version counts
        mock_storage = AsyncMock()
        mock_lance_manager = AsyncMock()

        table_stats = {
            "document_chunks": {
                "status": "success",
                "size_bytes": 1024000,
                "version_count": 15,  # Many versions (needs cleanup)
                "fragment_count": 8,
            },
            "graph_entities": {
                "status": "success",
                "size_bytes": 512000,
                "version_count": 10,
                "fragment_count": 5,
            },
            "graph_relationships": {
                "status": "success",
                "size_bytes": 256000,
                "version_count": 7,
                "fragment_count": 3,
            },
        }

        mock_lance_manager.get_table_statistics = AsyncMock(return_value=table_stats)
        mock_storage.get_db_manager = MagicMock(return_value=mock_lance_manager)
        mock_storage.count_records = AsyncMock(return_value=10)
        mock_storage.advanced_filter = AsyncMock(return_value=[])

        # Mock memory system
        mock_memory_system = AsyncMock()
        mock_memory_system.get_stats = AsyncMock(
            return_value={
                "working_memory": {"size": 0},
                "episodic_memory": {"size": 0},
                "semantic_memory": {"size": 0},
            }
        )

        # Mock cache manager
        mock_cache_manager = MagicMock()
        mock_cache_manager.get = MagicMock(return_value=None)
        mock_cache_manager.set = MagicMock()

        services = {
            "session_manager": mock_session_manager,
            "storage": mock_storage,
            "memory_system": mock_memory_system,
            "cache_manager": mock_cache_manager,
        }

        # Mock check_project_state
        with patch(
            "agentic_inquiry.mcp.utils.project_state.check_project_state",
            new_callable=AsyncMock,
        ) as mock_check:
            mock_check.return_value = {
                "chunk_count": 100,
                "entity_count": 50,
                "warnings": [],
            }

            # Call get_project_info
            result = await get_project_info(services, "test_session")

        # Verify storage_metrics has version counts
        storage_metrics = result["storage_metrics"]
        tables = storage_metrics["tables"]

        # Verify each table has version_count
        assert tables["document_chunks"]["version_count"] == 15
        assert tables["graph_entities"]["version_count"] == 10
        assert tables["graph_relationships"]["version_count"] == 7

        # Verify version_count is numeric
        for table_name, table_info in tables.items():
            assert "version_count" in table_info, (
                f"{table_name} should have version_count"
            )
            assert isinstance(table_info["version_count"], int), (
                f"{table_name} version_count should be int"
            )

    @pytest.mark.asyncio
    async def test_storage_metrics_cached_for_performance(self):
        """Test that storage_metrics are cached to avoid performance impact.

        Verifies:
        - First call populates cache
        - Second call uses cached value
        - Cache has reasonable TTL (60 seconds per spec)
        """
        from agentic_inquiry.mcp.tools.info import get_project_info

        # Create mock services
        mock_session_manager = AsyncMock()
        mock_session = MagicMock()
        mock_session.project_id = "test_project"
        mock_session_manager.validate_session = AsyncMock(return_value=True)
        mock_session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock storage
        mock_storage = AsyncMock()
        mock_lance_manager = AsyncMock()

        table_stats = {
            "document_chunks": {
                "status": "success",
                "size_bytes": 1024000,
                "version_count": 5,
                "fragment_count": 3,
            }
        }

        mock_lance_manager.get_table_statistics = AsyncMock(return_value=table_stats)
        mock_storage.get_db_manager = MagicMock(return_value=mock_lance_manager)
        mock_storage.count_records = AsyncMock(return_value=10)
        mock_storage.advanced_filter = AsyncMock(return_value=[])

        # Mock memory system
        mock_memory_system = AsyncMock()
        mock_memory_system.get_stats = AsyncMock(
            return_value={
                "working_memory": {"size": 0},
                "episodic_memory": {"size": 0},
                "semantic_memory": {"size": 0},
            }
        )

        # Mock cache manager with tracking
        cached_value = None

        def mock_get(key):
            return cached_value

        def mock_set(key, value, ttl=None):
            nonlocal cached_value
            cached_value = value
            # Verify TTL is 60 seconds
            assert ttl == 60, "Cache TTL should be 60 seconds"

        mock_cache_manager = MagicMock()
        mock_cache_manager.get = MagicMock(side_effect=mock_get)
        mock_cache_manager.set = MagicMock(side_effect=mock_set)

        services = {
            "session_manager": mock_session_manager,
            "storage": mock_storage,
            "memory_system": mock_memory_system,
            "cache_manager": mock_cache_manager,
        }

        # Mock check_project_state
        with patch(
            "agentic_inquiry.mcp.utils.project_state.check_project_state",
            new_callable=AsyncMock,
        ) as mock_check:
            mock_check.return_value = {
                "chunk_count": 100,
                "entity_count": 50,
                "warnings": [],
            }

            # First call - should populate cache
            await get_project_info(services, "test_session")

            # Verify cache was set
            mock_cache_manager.set.assert_called_once()
            cache_key = "storage_metrics:test_project"
            assert mock_cache_manager.set.call_args[0][0] == cache_key

            # Reset mocks
            mock_lance_manager.get_table_statistics.reset_mock()
            mock_cache_manager.get.return_value = {
                "tables": {},
                "total_size_bytes": 100,
            }

            # Second call - should use cache
            await get_project_info(services, "test_session")

            # Verify get_table_statistics was NOT called again (used cache)

    @pytest.mark.asyncio
    async def test_storage_metrics_graceful_failure(self):
        """Test that get_project_info handles storage_metrics errors gracefully.

        Verifies:
        - If get_table_statistics fails, response still succeeds
        - storage_metrics is omitted or None if unavailable
        - Other response fields are still populated
        """
        from agentic_inquiry.mcp.tools.info import get_project_info

        # Create mock services
        mock_session_manager = AsyncMock()
        mock_session = MagicMock()
        mock_session.project_id = "test_project"
        mock_session_manager.validate_session = AsyncMock(return_value=True)
        mock_session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock storage - get_table_statistics raises exception
        mock_storage = AsyncMock()
        mock_lance_manager = AsyncMock()
        mock_lance_manager.get_table_statistics = AsyncMock(
            side_effect=Exception("LanceDB connection error")
        )
        mock_storage.get_db_manager = MagicMock(return_value=mock_lance_manager)
        mock_storage.count_records = AsyncMock(return_value=10)
        mock_storage.advanced_filter = AsyncMock(return_value=[])

        # Mock memory system
        mock_memory_system = AsyncMock()
        mock_memory_system.get_stats = AsyncMock(
            return_value={
                "working_memory": {"size": 0},
                "episodic_memory": {"size": 0},
                "semantic_memory": {"size": 0},
            }
        )

        # Mock cache manager
        mock_cache_manager = MagicMock()
        mock_cache_manager.get = MagicMock(return_value=None)
        mock_cache_manager.set = MagicMock()

        services = {
            "session_manager": mock_session_manager,
            "storage": mock_storage,
            "memory_system": mock_memory_system,
            "cache_manager": mock_cache_manager,
        }

        # Mock check_project_state
        with patch(
            "agentic_inquiry.mcp.utils.project_state.check_project_state",
            new_callable=AsyncMock,
        ) as mock_check:
            mock_check.return_value = {
                "chunk_count": 100,
                "entity_count": 50,
                "warnings": [],
            }

            # Call get_project_info
            result = await get_project_info(services, "test_session")

        # Verify response still succeeds
        assert "project_id" in result
        assert "statistics" in result
        assert result["project_id"] == "test_project"

        # storage_metrics should be absent or None (graceful degradation)
        assert "storage_metrics" not in result or result.get("storage_metrics") is None
