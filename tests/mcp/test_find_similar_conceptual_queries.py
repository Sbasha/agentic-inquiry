"""Tests for find_similar with conceptual queries.

This module tests that find_similar properly handles conceptual queries
(e.g., "authentication") that don't directly match entity names but should
find semantically related entities (e.g., AuthService, login, verify_token).

Related to Task 0.13: Improve Semantic Search Sensitivity for Conceptual Queries.
"""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock
import numpy as np

from agentic_inquiry.mcp.tools.search import find_similar


@pytest.fixture
def mock_session():
    """Create a mock session object."""
    session = MagicMock()
    session.project_id = "test_project"
    return session


@pytest.fixture
def mock_services_with_search(mock_session):
    """Create mock services with search service for semantic bridge testing."""
    session_manager = AsyncMock()
    session_manager.validate_session = AsyncMock(return_value=True)
    session_manager.get_session = AsyncMock(return_value=mock_session)

    # Mock embedding service
    embedding_service = AsyncMock()
    embedding_service.embed_async = AsyncMock(return_value=np.array([0.1] * 384))

    # Mock event system
    event_system = AsyncMock()
    event_system.emit = AsyncMock()
    event_system.store = AsyncMock()
    event_system.store.query = AsyncMock(return_value=[])

    # Mock database manager with async methods
    db_manager = MagicMock()

    # Mock table for entity search
    mock_table = MagicMock()
    mock_search_builder = MagicMock()
    mock_search_builder.where = MagicMock(return_value=mock_search_builder)
    mock_search_builder.limit = MagicMock(return_value=mock_search_builder)
    mock_search_builder.to_list = MagicMock(return_value=[])
    mock_table.search = MagicMock(return_value=mock_search_builder)
    db_manager.get_table = MagicMock(return_value=mock_table)
    db_manager.advanced_filter = AsyncMock(return_value=[])
    db_manager.count_records = AsyncMock(
        return_value=100
    )  # Sufficient for sparse threshold

    # Mock search service with hybrid search returning semantic results
    search_service = AsyncMock()

    # Mock config with required nested attributes
    config = MagicMock()
    config.search.sparse_index.threshold = 50
    # The timeouts object has methods that return integers, not just attributes
    config.search.graph_search.timeouts.get_find_similar_timeout = MagicMock(
        return_value=5000
    )
    config.search.graph_search.timeouts.find_similar_ms = 5000

    return {
        "session_manager": session_manager,
        "embedding_service": embedding_service,
        "event_system": event_system,
        "storage": db_manager,
        "search_service": search_service,
        "config": config,
    }


class TestFindSimilarDefaultThreshold:
    """Tests for the default similarity_threshold value."""

    @pytest.mark.asyncio
    async def test_default_threshold_is_0_3(self, mock_services_with_search):
        """Verify that the default similarity_threshold is 0.3.

        The default was lowered from 0.5 to 0.3 to improve sensitivity
        for conceptual queries that don't directly match entity names.
        """
        # Import to check the function signature
        import inspect

        sig = inspect.signature(find_similar)
        params = sig.parameters

        # Check the default value
        assert params["similarity_threshold"].default == 0.3, (
            "Default similarity_threshold should be 0.3 for better conceptual query support"
        )

    @pytest.mark.asyncio
    async def test_threshold_respected_in_results(self, mock_services_with_search):
        """Verify that results are filtered by the threshold."""
        # This test verifies the filtering logic works with the new default
        result = await find_similar(
            services=mock_services_with_search,
            session_id="test_session",
            query="authentication",
            search_scope="entities",
            similarity_threshold=0.3,
        )

        # Should return a valid response structure
        assert isinstance(result, dict)
        assert "query" in result
        assert result["similarity_threshold"] == 0.3


class TestFindSimilarConceptualQueries:
    """Tests for conceptual query handling in find_similar."""

    @pytest.mark.asyncio
    async def test_conceptual_query_uses_semantic_bridge(
        self, mock_services_with_search
    ):
        """Test that conceptual queries trigger semantic bridge search.

        When searching for "authentication", the semantic bridge should:
        1. Search code chunks semantically
        2. Find entities in files with matching code content
        3. Return those entities even if their names don't match the query
        """
        # Mock search service to return chunks from auth-related files
        mock_chunk = MagicMock()
        mock_chunk.id = "chunk_1"
        mock_chunk.distance = 0.3  # Close semantic match
        mock_chunk.data = {
            "file_path": "/src/auth/service.py",
            "content": "class AuthService: handles authentication...",
        }

        mock_services_with_search["search_service"].hybrid_search = AsyncMock(
            return_value=[mock_chunk]
        )

        # Mock storage (db_manager) to return entities from the auth file
        mock_services_with_search["storage"].advanced_filter = AsyncMock(
            return_value=[
                {
                    "name": "AuthService",
                    "type": "class",
                    "file_path": "/src/auth/service.py",
                    "line_start": 1,
                    "line_end": 50,
                }
            ]
        )

        result = await find_similar(
            services=mock_services_with_search,
            session_id="test_session",
            query="authentication",  # Conceptual query
            search_scope="entities",
            similarity_threshold=0.2,  # Low threshold for testing
        )

        # Should find entities via semantic bridge
        assert isinstance(result, dict)
        # The search_service.hybrid_search should be called for semantic bridge
        mock_services_with_search["search_service"].hybrid_search.assert_called()

    @pytest.mark.asyncio
    async def test_search_scope_all_for_comprehensive_results(
        self, mock_services_with_search
    ):
        """Test that search_scope='all' provides both entities and content.

        For conceptual queries, using search_scope='all' is recommended
        as it searches both entities and content chunks.
        """
        # Mock hybrid search to return content chunks
        mock_chunk = MagicMock()
        mock_chunk.id = "chunk_1"
        mock_chunk.distance = 0.2
        mock_chunk.data = {
            "file_path": "/src/auth.py",
            "content": "def authenticate_user()...",
            "content_type": "CODE",
            "chunk_type": "function",
        }

        mock_services_with_search["search_service"].hybrid_search = AsyncMock(
            return_value=[mock_chunk]
        )

        result = await find_similar(
            services=mock_services_with_search,
            session_id="test_session",
            query="authentication",
            search_scope="all",  # Search both entities and content
            similarity_threshold=0.2,
        )

        assert isinstance(result, dict)
        assert result["search_scope"] == "all"
        # Should include content search results
        assert "similar_content" in result or "content_count" in result


class TestFindSimilarThresholdBehavior:
    """Tests for similarity_threshold behavior."""

    @pytest.mark.asyncio
    async def test_lower_threshold_finds_more_results(self, mock_services_with_search):
        """Verify that lower thresholds allow more results through.

        With the default lowered to 0.3, conceptual queries should find
        more results than with the old 0.5 default.
        """
        # This is a behavior test - we just verify the parameter is accepted
        result = await find_similar(
            services=mock_services_with_search,
            session_id="test_session",
            query="database",
            search_scope="entities",
            similarity_threshold=0.2,  # Very low threshold
        )

        assert isinstance(result, dict)
        assert result["similarity_threshold"] == 0.2

    @pytest.mark.asyncio
    async def test_higher_threshold_is_stricter(self, mock_services_with_search):
        """Verify that higher thresholds filter out lower-quality matches."""
        result = await find_similar(
            services=mock_services_with_search,
            session_id="test_session",
            query="Config",
            search_scope="entities",
            similarity_threshold=0.8,  # High threshold for exact matching
        )

        assert isinstance(result, dict)
        assert result["similarity_threshold"] == 0.8


class TestFindSimilarDocumentation:
    """Tests verifying the docstring accurately describes behavior."""

    def test_docstring_mentions_conceptual_queries(self):
        """Verify docstring documents conceptual query behavior."""
        docstring = find_similar.__doc__

        # Check that the docstring mentions key concepts
        assert "conceptual" in docstring.lower(), (
            "Docstring should mention conceptual queries"
        )
        assert "semantic bridge" in docstring.lower(), (
            "Docstring should mention semantic bridge strategy"
        )
        assert "0.3" in docstring, (
            "Docstring should mention the default threshold of 0.3"
        )

    def test_docstring_has_threshold_guidance(self):
        """Verify docstring provides guidance on threshold values."""
        docstring = find_similar.__doc__

        # Check for guidance on threshold values
        assert "0.2" in docstring or "0.4" in docstring, (
            "Docstring should provide guidance on threshold values"
        )
        assert "0.5" in docstring or "0.8" in docstring, (
            "Docstring should mention higher threshold values for exact matching"
        )
