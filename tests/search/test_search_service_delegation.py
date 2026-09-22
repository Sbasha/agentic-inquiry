"""Unit tests for SearchService delegation to specialized services."""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock

from agent_vault.search.service import SearchService


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    config = MagicMock()
    config.storage.default_project_id = "test_project"
    config.search.default_limit = 10
    config.search.max_limit = 1000
    config.search.hybrid_search.rerank_by_graph = False
    config.search.hybrid_search.reranker.enabled = False
    config.search.hybrid_search.reranker_type = "rrf"
    config.search.hybrid_search.reranker_params = {}
    config.search.deduplication.enabled = True
    config.search.deduplication.max_results_per_file = 3
    config.search.deduplication.min_diversity_ratio = 0.3
    config.search.query_sanitization.preserve_wildcards = False
    config.search.graph_search.max_depth = 3
    config.mcp.relationships.max_per_node = 100
    config.mcp.query.default_limit = 50
    config.embeddings.provider = "sentence_transformers"
    config.embeddings.model_name = "all-MiniLM-L6-v2"
    return config


@pytest.fixture
def mock_event_system():
    """Create a mock event system."""
    event_system = AsyncMock()
    event_system.emit = AsyncMock()
    event_system.subscribe = MagicMock()
    return event_system


@pytest.fixture
def search_service(mock_storage_facade, mock_config, mock_event_system):
    """Create a SearchService instance."""
    return SearchService(
        storage=mock_storage_facade,
        config=mock_config,
        event_system=mock_event_system,
    )


class TestSearchServiceDelegation:
    """Tests for SearchService delegation to specialized services."""

    @pytest.mark.unit
    async def test_traverse_relationships_delegates_to_graph_search(self, search_service):
        """Test that traverse_relationships delegates to GraphSearchService."""
        # Setup mock
        search_service._graph_search.traverse_relationships = AsyncMock(
            return_value={"entity": None, "relationships": []}
        )

        # Execute
        result = await search_service.traverse_relationships(
            entity_id="test_entity",
            max_depth=2,
        )

        # Verify delegation
        search_service._graph_search.traverse_relationships.assert_called_once_with(
            entity_id="test_entity",
            relationship_types=None,
            direction="outgoing",
            max_depth=2,
            project_id="current",
            include_metadata=True,
        )
        assert result == {"entity": None, "relationships": []}

    @pytest.mark.unit
    async def test_resolve_entity_delegates_to_graph_search(self, search_service):
        """Test that resolve_entity delegates to GraphSearchService."""
        # Setup mock
        search_service._graph_search.resolve_entity = AsyncMock(
            return_value={"matches": [], "found": False}
        )

        # Execute
        result = await search_service.resolve_entity(
            entity_name="TestEntity",
        )

        # Verify delegation
        search_service._graph_search.resolve_entity.assert_called_once_with(
            entity_name="TestEntity",
            entity_type=None,
            context=None,
            project_id="current",
            similarity_threshold=0.7,
        )
        assert result == {"matches": [], "found": False}

    @pytest.mark.unit
    async def test_enrich_with_graph_context_delegates_to_graph_search(self, search_service):
        """Test that enrich_with_graph_context delegates to GraphSearchService."""
        # Setup mock
        search_results = [{"doc_id": "doc_1"}]
        search_service._graph_search.enrich_with_graph_context = AsyncMock(
            return_value=search_results
        )

        # Execute
        result = await search_service.enrich_with_graph_context(search_results)

        # Verify delegation
        search_service._graph_search.enrich_with_graph_context.assert_called_once_with(
            search_results=search_results,
            project_id="current",
        )
        assert result == search_results

    @pytest.mark.unit
    async def test_graph_filtered_search_delegates_to_graph_search(self, search_service):
        """Test that graph_filtered_search delegates to GraphSearchService."""
        # Setup mock
        search_service._graph_search.graph_filtered_search = AsyncMock(return_value=[])

        # Execute
        result = await search_service.graph_filtered_search(
            graph_filters={"type": "function"},
            limit=10,
        )

        # Verify delegation
        search_service._graph_search.graph_filtered_search.assert_called_once()
        assert result == []

    @pytest.mark.unit
    async def test_hybrid_search_delegates_to_hybrid_search_service(self, search_service):
        """Test that hybrid_search delegates to HybridSearchService."""
        # Setup mock
        search_service._hybrid_search.hybrid_search = AsyncMock(return_value=[])

        # Execute
        result = await search_service.hybrid_search(
            query_vector=[0.1, 0.2, 0.3],
            query_fts="test query",
            limit=10,
        )

        # Verify delegation
        search_service._hybrid_search.hybrid_search.assert_called_once()
        assert result == []

    @pytest.mark.unit
    async def test_rerank_by_graph_delegates_to_graph_search(self, search_service):
        """Test that _rerank_by_graph delegates to GraphSearchService."""
        # Setup mock
        search_results = [{"doc_id": "doc_1"}]
        search_service._graph_search.rerank_by_graph = AsyncMock(return_value=search_results)

        # Execute
        result = await search_service._rerank_by_graph(search_results)

        # Verify delegation
        search_service._graph_search.rerank_by_graph.assert_called_once_with(search_results)
        assert result == search_results
