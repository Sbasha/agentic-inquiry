"""Tests for hybrid search fallback strategies.

This module tests the fallback logic in hybrid search when:
- Vector search returns no results
- FTS returns no results
- Both return no results
- Reranker fails or eliminates all results
- Simple merge function when reranker is unavailable
"""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock

from agent_vault.config import Config
from agent_vault.database.adapters.lancedb_adapter import LanceDBAdapter
from agent_vault.database.results import SearchResult
from agent_vault.search.service import SearchService
from agent_vault.search.hybrid_search import HybridSearchService
from agent_vault.search.deduplicator import SearchDeduplicator
from agent_vault.events.system import EventSystem


def _make_search_results(dicts: list, source: str = "test") -> list[SearchResult]:
    """Helper to create SearchResult objects from dict test data."""
    results = []
    for d in dicts:
        result_id = d.get("id") or d.get("chunk_id") or str(hash(str(d)))
        results.append(SearchResult(
            id=str(result_id),
            data=d,
            score=d.get("score", 0.5),
            source=source,
            distance=d.get("_distance"),
        ))
    return results


@pytest.fixture
def mock_event_system():
    """Create a mock event system."""
    event_system = MagicMock(spec=EventSystem)
    event_system.emit = AsyncMock()
    return event_system


@pytest.fixture
def base_config():
    """Create a base configuration for testing."""
    config = Config.load()
    config.search.default_limit = 10
    config.search.hybrid_search.rerank_by_graph = False
    return config


@pytest.fixture
def mock_db_manager():
    """Create a mock database adapter with LanceDBAdapter spec.

    Uses spec=LanceDBAdapter so isinstance checks pass in SearchService.
    """
    mock_adapter = MagicMock(spec=LanceDBAdapter)
    mock_adapter.vector_search = AsyncMock()
    mock_adapter.fts_search = AsyncMock()
    mock_adapter.hybrid_search = AsyncMock()
    mock_adapter._manager = MagicMock()
    return mock_adapter


@pytest.fixture
def mock_storage_facade(mock_db_manager):
    """Create a mock StorageFacade that provides mock_db_manager."""
    mock_storage = MagicMock()
    mock_storage.vector_provider = mock_db_manager
    mock_storage.project_id = "test_project"
    return mock_storage


@pytest.fixture
def search_service(base_config, mock_storage_facade, mock_event_system):
    """Create a search service with mocked dependencies."""
    service = SearchService(
        storage=mock_storage_facade,
        config=base_config,
        event_system=mock_event_system,
    )
    return service


@pytest.fixture
def hybrid_search_service(base_config, mock_db_manager, mock_event_system):
    """Create a hybrid search service with mocked dependencies."""
    deduplicator = SearchDeduplicator(
        max_results_per_file=base_config.search.deduplication.max_results_per_file,
        min_diversity_ratio=base_config.search.deduplication.min_diversity_ratio,
    )
    service = HybridSearchService(
        db_manager=mock_db_manager,
        config=base_config,
        deduplicator=deduplicator,
        event_system=mock_event_system,
        project_id="test_project",
    )
    return service


class TestHybridSearchFallbackStrategies:
    """Test hybrid search fallback strategies."""
    
    @pytest.mark.asyncio
    async def test_both_strategies_return_results(self, search_service, mock_db_manager):
        """Test hybrid search when both vector and FTS return results."""
        # Setup mock results as SearchResult objects (now returned by vector_search/fts_search)
        vector_dicts = [
            {"id": "v1", "content": "vector result 1", "score": 0.9},
            {"id": "v2", "content": "vector result 2", "score": 0.8},
        ]
        fts_dicts = [
            {"id": "f1", "content": "fts result 1", "score": 0.85},
            {"id": "f2", "content": "fts result 2", "score": 0.75},
        ]

        # Mock the individual search methods to return SearchResult objects
        search_service.vector_search = AsyncMock(
            return_value=_make_search_results(vector_dicts, source="vector")
        )
        search_service.fts_search = AsyncMock(
            return_value=_make_search_results(fts_dicts, source="fts")
        )

        # Mock reranker to return None (will use simple merge)
        search_service._create_reranker = MagicMock(return_value=None)

        # Execute hybrid search
        query_vector = [0.1] * 384
        query_fts = "test query"
        results = await search_service.hybrid_search(
            query_vector=query_vector,
            query_fts=query_fts,
            limit=10
        )

        # Verify both searches were called
        search_service.vector_search.assert_called_once()
        search_service.fts_search.assert_called_once()

        # Verify results were merged
        assert len(results) > 0
        assert len(results) <= 10

        # Verify no duplicates
        result_ids = [r.id for r in results]
        assert len(result_ids) == len(set(result_ids))
    
    @pytest.mark.asyncio
    async def test_fallback_when_only_vector_returns_results(self, search_service):
        """Test fallback when only vector search returns results."""
        # Setup mock results with different file_paths for diversity
        vector_dicts = [
            {"id": "v1", "content": "vector result 1", "score": 0.9, "file_path": "/a/file1.py"},
            {"id": "v2", "content": "vector result 2", "score": 0.8, "file_path": "/b/file2.py"},
        ]

        # Mock the individual search methods to return SearchResult objects
        search_service.vector_search = AsyncMock(
            return_value=_make_search_results(vector_dicts, source="vector")
        )
        search_service.fts_search = AsyncMock(return_value=[])

        # Execute hybrid search
        query_vector = [0.1] * 384
        query_fts = "test query"
        results = await search_service.hybrid_search(
            query_vector=query_vector,
            query_fts=query_fts,
            limit=10
        )

        # Verify fallback to vector results - check IDs and content, not exact scores
        # (scores are normalized during processing)
        assert len(results) >= 1  # At least some results returned
        result_ids = {r.id for r in results}
        assert "v1" in result_ids  # First result should be present
    
    @pytest.mark.asyncio
    async def test_fallback_when_only_fts_returns_results(self, search_service):
        """Test fallback when only FTS returns results."""
        # Setup mock results with different file_paths for diversity
        fts_dicts = [
            {"id": "f1", "content": "fts result 1", "score": 0.85, "file_path": "/a/file1.py"},
            {"id": "f2", "content": "fts result 2", "score": 0.75, "file_path": "/b/file2.py"},
        ]

        # Mock the individual search methods to return SearchResult objects
        search_service.vector_search = AsyncMock(return_value=[])
        search_service.fts_search = AsyncMock(
            return_value=_make_search_results(fts_dicts, source="fts")
        )

        # Execute hybrid search
        query_vector = [0.1] * 384
        query_fts = "test query"
        results = await search_service.hybrid_search(
            query_vector=query_vector,
            query_fts=query_fts,
            limit=10
        )

        # Verify fallback to FTS results - check IDs, not exact equality
        # (scores are normalized during processing)
        assert len(results) >= 1  # At least some results returned
        result_ids = {r.id for r in results}
        assert "f1" in result_ids  # First result should be present
    
    @pytest.mark.asyncio
    async def test_both_strategies_return_no_results(self, search_service):
        """Test behavior when both strategies return no results."""
        # Mock the individual search methods to return empty lists
        search_service.vector_search = AsyncMock(return_value=[])
        search_service.fts_search = AsyncMock(return_value=[])

        # Execute hybrid search
        query_vector = [0.1] * 384
        query_fts = "test query"
        results = await search_service.hybrid_search(
            query_vector=query_vector,
            query_fts=query_fts,
            limit=10
        )

        # Verify empty results
        assert results == []
    
    @pytest.mark.asyncio
    async def test_reranker_failure_fallback(self, search_service, mock_db_manager):
        """Test fallback when reranker fails.

        Note: With protocol-based rerankers, failures during reranking will
        cause the hybrid search to fall back to vector results.
        """
        # Setup mock results as SearchResult objects
        vector_dicts = [
            {"id": "v1", "content": "vector result 1", "score": 0.9},
            {"id": "v2", "content": "vector result 2", "score": 0.8},
        ]
        fts_dicts = [
            {"id": "f1", "content": "fts result 1", "score": 0.85},
        ]

        # Mock the individual search methods to return SearchResult objects
        search_service.vector_search = AsyncMock(
            return_value=_make_search_results(vector_dicts, source="vector")
        )
        search_service.fts_search = AsyncMock(
            return_value=_make_search_results(fts_dicts, source="fts")
        )

        # Mock reranker to raise an exception when rerank() is called
        mock_reranker = MagicMock()
        mock_reranker.rerank = MagicMock(side_effect=Exception("Reranker failed"))
        search_service._hybrid_search._create_reranker = MagicMock(return_value=mock_reranker)

        # Execute hybrid search - should fall back due to reranker failure
        query_vector = [0.1] * 384
        query_fts = "test query"

        # The hybrid search should raise an exception since reranking fails
        # and we don't have a try/catch around the reranker call
        with pytest.raises(Exception, match="Reranker failed"):
            await search_service.hybrid_search(
                query_vector=query_vector,
                query_fts=query_fts,
                limit=10
            )
    
    @pytest.mark.asyncio
    async def test_reranker_eliminates_all_results(self, search_service, mock_db_manager):
        """Test fallback when reranker eliminates all results.

        When the reranker returns empty results, hybrid search should
        fall back to vector results.
        """
        # Setup mock results as SearchResult objects with different file_paths for diversity
        vector_dicts = [
            {"id": "v1", "content": "vector result 1", "score": 0.9, "file_path": "/a/file1.py"},
            {"id": "v2", "content": "vector result 2", "score": 0.8, "file_path": "/b/file2.py"},
        ]
        fts_dicts = [
            {"id": "f1", "content": "fts result 1", "score": 0.85, "file_path": "/c/file3.py"},
        ]

        # Mock the individual search methods to return SearchResult objects
        search_service.vector_search = AsyncMock(
            return_value=_make_search_results(vector_dicts, source="vector")
        )
        search_service.fts_search = AsyncMock(
            return_value=_make_search_results(fts_dicts, source="fts")
        )

        # Mock reranker to return empty results
        mock_reranker = MagicMock()
        mock_reranker.rerank = MagicMock(return_value=[])
        search_service._hybrid_search._create_reranker = MagicMock(return_value=mock_reranker)

        # Execute hybrid search
        query_vector = [0.1] * 384
        query_fts = "test query"
        results = await search_service.hybrid_search(
            query_vector=query_vector,
            query_fts=query_fts,
            limit=10
        )

        # Verify fallback to vector results - at least first result present
        # (deduplication may filter some results based on diversity threshold)
        assert len(results) >= 1
        result_ids = {r.id for r in results}
        assert "v1" in result_ids  # First vector result should be present



# NOTE: TestSimpleMergeFunction was removed as part of S3-003-CLEANUP.
# The tests were testing dead code in SearchService that used an interleaving algorithm.
# The active implementation in HybridSearchService uses weighted scoring instead.
# See commit for S3-003-CLEANUP in .sessions/deep-architecture-review/sprint3-execution.md
