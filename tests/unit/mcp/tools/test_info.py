"""Unit tests for info.py tools.

Tests the get_project_info, get_events, and other info retrieval functions
from agentic_inquiry/mcp/tools/info.py.
"""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock, patch

from agentic_inquiry.mcp.tools.info import get_project_info


class TestRelationshipVisibility:
    """Tests for relationship count visibility and accuracy."""

    @pytest.fixture
    def mock_services(self):
        """Create mock services for testing."""
        # Mock session manager
        session_manager = MagicMock()
        session_manager.validate_session = AsyncMock(return_value=True)

        # Mock session with project_id
        mock_session = MagicMock()
        mock_session.project_id = "test_project"
        session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock storage/db_manager
        db_manager = MagicMock()
        db_manager.count_records = AsyncMock(return_value=0)
        db_manager.count_relationships_by_type = AsyncMock(return_value={})
        db_manager.advanced_filter = AsyncMock(return_value=[])

        # Mock memory system
        memory_system = MagicMock()
        memory_system.get_stats = AsyncMock(
            return_value={
                "working_memory": {"size": 0},
                "episodic_memory": {"size": 0},
                "semantic_memory": {"size": 0},
            }
        )

        return {
            "session_manager": session_manager,
            "storage": db_manager,
            "memory_system": memory_system,
            "cache_manager": None,  # No cache for unit tests
        }

    @pytest.mark.asyncio
    async def test_relationship_count_uses_count_relationships_by_type(
        self, mock_services
    ):
        """Verify count_relationships_by_type() is called for relationship count, not advanced_filter().

        AC-1.3: Relationship count uses count_relationships_by_type() not advanced_filter().
        This ensures we don't hit the 100-item limit bug that affects advanced_filter.
        """
        # Mock check_project_state to avoid dependency
        with patch(
            "agentic_inquiry.mcp.utils.project_state.check_project_state"
        ) as mock_check:
            mock_check.return_value = {
                "chunk_count": 100,
                "entity_count": 50,
                "warnings": [],
            }

            # Set up count_relationships_by_type to return counts by type (sums to 881)
            mock_services["storage"].count_relationships_by_type = AsyncMock(
                return_value={"calls": 400, "imports": 300, "references": 181}
            )

            # Call get_project_info
            result = await get_project_info(
                services=mock_services, session_id="test_session"
            )

            # Verify count_relationships_by_type was called
            mock_services[
                "storage"
            ].count_relationships_by_type.assert_called_once_with(
                project_id="test_project"
            )

            # Verify advanced_filter was NOT called for relationships
            # (It may be called for other purposes like keywords, but not for relationship count)
            for call in mock_services["storage"].advanced_filter.call_args_list:
                args, kwargs = call
                # Ensure no call was made to graph_relationships table
                if kwargs.get("table_name") == "graph_relationships":
                    pytest.fail(
                        "advanced_filter should not be called for graph_relationships"
                    )

            # Verify the count is in the result (sum of all types)
            assert result["statistics"]["relationships_created"] == 881

    @pytest.mark.asyncio
    async def test_relationship_count_no_truncation(self, mock_services):
        """Verify 500+ relationships returns full count without truncation.

        AC-1.2: Project with 500+ relationships returns full count (no truncation).
        Previously, advanced_filter() would truncate at 100 items due to MCP context limits.
        Using count_relationships_by_type() ensures we get the actual count regardless of size.
        """
        # Mock check_project_state
        with patch(
            "agentic_inquiry.mcp.utils.project_state.check_project_state"
        ) as mock_check:
            mock_check.return_value = {
                "chunk_count": 1000,
                "entity_count": 200,
                "warnings": [],
            }

            # Set up count_relationships_by_type to return 500+ relationships (654 total)
            mock_services["storage"].count_relationships_by_type = AsyncMock(
                return_value={"calls": 300, "imports": 200, "references": 154}
            )

            # Call get_project_info
            result = await get_project_info(
                services=mock_services, session_id="test_session"
            )

            # Verify full count is returned (no truncation at 100)
            assert result["statistics"]["relationships_created"] == 654
            assert result["statistics"]["relationships_created"] > 500

            # Verify status reflects relationships exist
            assert result["status"]["has_relationships"] is True

    @pytest.mark.asyncio
    async def test_graph_relationship_counting(self, mock_services):
        """Verify graph relationships are counted using count_relationships_by_type.

        This test ensures that the graph relationships are queried using
        count_relationships_by_type(), which should route to the correct provider
        (graph_provider) through StorageFacade. While we can't fully test the
        routing in a unit test (that's better for integration tests), we can
        verify the correct method is used.

        Related to INV-6.4: StorageFacade routing fix for graph tables.
        """
        # Mock check_project_state
        with patch(
            "agentic_inquiry.mcp.utils.project_state.check_project_state"
        ) as mock_check:
            mock_check.return_value = {
                "chunk_count": 100,
                "entity_count": 50,
                "warnings": [],
            }

            # Set up count_relationships_by_type
            mock_services["storage"].count_relationships_by_type = AsyncMock(
                return_value={"calls": 100, "imports": 23}
            )

            # Call get_project_info
            result = await get_project_info(
                services=mock_services, session_id="test_session"
            )

            # Verify count_relationships_by_type was called with correct project_id
            mock_services["storage"].count_relationships_by_type.assert_called_once()
            call_args = mock_services["storage"].count_relationships_by_type.call_args

            assert call_args.kwargs["project_id"] == "test_project"

            # Verify result contains the count (sum: 100 + 23 = 123)
            assert result["statistics"]["relationships_created"] == 123


class TestProjectInfoCaching:
    """Tests for storage metrics caching in get_project_info."""

    @pytest.fixture
    def mock_services_with_cache(self):
        """Create mock services with a cache manager."""
        # Mock session manager
        session_manager = MagicMock()
        session_manager.validate_session = AsyncMock(return_value=True)

        mock_session = MagicMock()
        mock_session.project_id = "test_project"
        session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock storage
        db_manager = MagicMock()
        db_manager.count_records = AsyncMock(return_value=0)
        db_manager.count_relationships_by_type = AsyncMock(return_value={})
        db_manager.advanced_filter = AsyncMock(return_value=[])

        # Mock memory system
        memory_system = MagicMock()
        memory_system.get_stats = AsyncMock(
            return_value={
                "working_memory": {"size": 0},
                "episodic_memory": {"size": 0},
                "semantic_memory": {"size": 0},
            }
        )

        # Mock cache manager
        cache_manager = MagicMock()
        cache_manager.get = MagicMock(return_value=None)
        cache_manager.set = MagicMock()

        return {
            "session_manager": session_manager,
            "storage": db_manager,
            "memory_system": memory_system,
            "cache_manager": cache_manager,
        }

    @pytest.mark.asyncio
    async def test_storage_metrics_caching(self, mock_services_with_cache):
        """Verify storage metrics are cached with 60s TTL.

        Storage metrics are expensive to compute, so they should be cached
        to avoid performance impact on frequent get_project_info calls.
        """
        # Mock check_project_state
        with patch(
            "agentic_inquiry.mcp.utils.project_state.check_project_state"
        ) as mock_check:
            mock_check.return_value = {
                "chunk_count": 100,
                "entity_count": 50,
                "warnings": [],
            }

            # Mock storage with get_db_manager that has table statistics
            mock_lance_manager = MagicMock()
            mock_lance_manager.get_table_statistics = AsyncMock(
                return_value={
                    "document_chunks": {
                        "status": "success",
                        "size_bytes": 1000000,
                        "version_count": 5,
                    }
                }
            )
            mock_services_with_cache["storage"].get_db_manager = MagicMock(
                return_value=mock_lance_manager
            )

            # Call get_project_info
            result = await get_project_info(
                services=mock_services_with_cache, session_id="test_session"
            )

            # Verify cache was checked for storage_metrics
            cache_key = "storage_metrics:test_project"
            mock_services_with_cache["cache_manager"].get.assert_any_call(cache_key)

            # Verify cache was set with 60s TTL for storage_metrics
            # Need to find the specific call with storage_metrics key
            storage_metrics_call = None
            for call in mock_services_with_cache["cache_manager"].set.call_args_list:
                if call.args and cache_key in str(call.args[0]):
                    storage_metrics_call = call
                    break

            assert storage_metrics_call is not None, (
                "storage_metrics cache set not found"
            )
            assert storage_metrics_call.kwargs.get("ttl") == 60

            # Verify storage_metrics in result
            assert "storage_metrics" in result
            assert "tables" in result["storage_metrics"]
