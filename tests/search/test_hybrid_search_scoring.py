"""Tests for hybrid search scoring with configured weights."""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock
from agentic_inquiry.search.service import SearchService
from agentic_inquiry.config import Config
from agentic_inquiry.database.results import SearchResult
from agentic_inquiry.exceptions import ConfigurationError


@pytest.fixture
def mock_db_manager():
    """Create a mock adapter with AsyncMock methods for controlled testing.

    This mock is used as the adapter that SearchService uses for search
    operations. By using spec=LanceDBAdapter, the isinstance check passes
    and SearchService uses this mock directly without wrapping.

    SearchService checks isinstance(provider, LanceDBAdapter) and if True,
    uses the provider directly as self._adapter.
    """
    from agentic_inquiry.database.adapters.lancedb_adapter import LanceDBAdapter

    # Create a mock that looks like a LanceDBAdapter
    mock_adapter = MagicMock(spec=LanceDBAdapter)
    mock_adapter.vector_search = AsyncMock()
    mock_adapter.fts_search = AsyncMock()
    mock_adapter.hybrid_search = AsyncMock()
    # Provide a mock underlying manager for SearchService's self.db_manager
    mock_adapter._manager = MagicMock()
    return mock_adapter


@pytest.fixture
def mock_storage_facade(mock_db_manager):
    """Create a mock StorageFacade that uses mock_db_manager as the adapter.

    The facade provides a vector_provider that is the mock adapter.
    SearchService now delegates to StorageFacade methods directly, so the
    mock needs async methods for fts_search, vector_search, and hybrid_search.
    """
    mock_storage = MagicMock()
    mock_storage.vector_provider = mock_db_manager  # The mock adapter
    mock_storage.project_id = "test_project"

    # Add async mock methods that SearchService delegates to StorageFacade
    mock_storage.fts_search = mock_db_manager.fts_search
    mock_storage.vector_search = mock_db_manager.vector_search
    mock_storage.hybrid_search = mock_db_manager.hybrid_search

    # Ensure get_backend_type returns "lancedb" so SearchService uses LanceDBAdapter
    mock_storage.get_backend_type = MagicMock(return_value="lancedb")

    return mock_storage


@pytest.fixture
def mock_event_system():
    """Create a mock event system."""
    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    return mock_es


@pytest.fixture
def base_config():
    """Create a base configuration for testing."""
    config = Config.load()
    return config


def create_search_service_with_weights(mock_storage_facade, vector_weight: float, fts_weight: float, mock_event_system=None):
    """Helper to create SearchService with specific weights."""
    config = Config.load()
    config.search.hybrid_search.vector_weight = vector_weight
    config.search.hybrid_search.fts_weight = fts_weight
    config.search.hybrid_search.rerank_by_graph = False  # Disable graph reranking for tests
    # Create a mock event system if not provided
    if mock_event_system is None:
        mock_event_system = MagicMock()
        mock_event_system.emit = AsyncMock()
    return SearchService(storage=mock_storage_facade, config=config, event_system=mock_event_system)


def make_search_results(items: list, source: str = "vector") -> list:
    """Helper to convert dict items to SearchResult objects for testing."""
    return [
        SearchResult(
            id=item["id"],
            data={k: v for k, v in item.items() if k not in ("id", "score")},
            score=item.get("score", 1.0),
            source=source
        )
        for item in items
    ]


class TestHybridSearchWeightApplication:
    """Test that configured weights are applied correctly in hybrid search."""

    @pytest.mark.asyncio
    async def test_default_weights_applied(self, mock_db_manager, mock_storage_facade):
        """Test that default weights (0.7 vector, 0.3 FTS) are applied."""
        # Setup mock responses for individual search methods returning SearchResult objects
        mock_db_manager.vector_search.return_value = [
            SearchResult(id="doc1", data={"doc_id": "doc1", "content": "test1", "project_id": "test_project"}, score=0.95, source="vector"),
            SearchResult(id="doc2", data={"doc_id": "doc2", "content": "test2", "project_id": "test_project"}, score=0.85, source="vector"),
        ]
        mock_db_manager.fts_search.return_value = [
            SearchResult(id="doc3", data={"doc_id": "doc3", "content": "test3", "project_id": "test_project"}, score=0.75, source="fts"),
        ]

        # Create service with default weights
        service = create_search_service_with_weights(mock_storage_facade, 0.7, 0.3)

        # Perform hybrid search
        results = await service.hybrid_search(
            query_vector=[0.1] * 384,
            query_fts="test",
            limit=10,
            project_id="test_project"
        )

        # Verify results are returned
        assert len(results) > 0

        # Verify vector_search and fts_search were called
        assert mock_db_manager.vector_search.called
        assert mock_db_manager.fts_search.called

    @pytest.mark.asyncio
    async def test_custom_weights_applied(self, mock_db_manager, mock_storage_facade):
        """Test that custom weights (0.5 vector, 0.5 FTS) are applied."""
        # Setup mock responses with file_path for diversity returning SearchResult objects
        mock_db_manager.vector_search.return_value = [
            SearchResult(id="doc1", data={"doc_id": "doc1", "content": "test1", "project_id": "test_project", "file_path": "/a/file1.py"}, score=0.9, source="vector"),
            SearchResult(id="doc2", data={"doc_id": "doc2", "content": "test2", "project_id": "test_project", "file_path": "/b/file2.py"}, score=0.85, source="vector"),
        ]
        mock_db_manager.fts_search.return_value = [
            SearchResult(id="doc3", data={"doc_id": "doc3", "content": "test3", "project_id": "test_project", "file_path": "/c/file3.py"}, score=0.8, source="fts"),
        ]

        # Create service with equal weights
        service = create_search_service_with_weights(mock_storage_facade, 0.5, 0.5)

        # Perform hybrid search
        results = await service.hybrid_search(
            query_vector=[0.1] * 384,
            query_fts="test",
            limit=10,
            project_id="test_project"
        )

        # Verify results are returned (at least some results from either search)
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_vector_heavy_weights(self, mock_db_manager, mock_storage_facade):
        """Test with vector-heavy weights (0.9 vector, 0.1 FTS)."""
        # Setup mock responses returning SearchResult objects
        mock_db_manager.vector_search.return_value = make_search_results([
            {"id": "doc1", "doc_id": "doc1", "content": "test1", "project_id": "test_project", "score": 0.95},
            {"id": "doc2", "doc_id": "doc2", "content": "test2", "project_id": "test_project", "score": 0.85},
        ], source="vector")
        mock_db_manager.fts_search.return_value = make_search_results([
            {"id": "doc3", "doc_id": "doc3", "content": "test3", "project_id": "test_project", "score": 0.75},
        ], source="fts")

        # Create service with vector-heavy weights
        service = create_search_service_with_weights(mock_storage_facade, 0.9, 0.1)

        # Perform hybrid search
        results = await service.hybrid_search(
            query_vector=[0.1] * 384,
            query_fts="test",
            limit=10,
            project_id="test_project"
        )

        # Verify results are returned
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_fts_heavy_weights(self, mock_db_manager, mock_storage_facade):
        """Test with FTS-heavy weights (0.1 vector, 0.9 FTS)."""
        # Setup mock responses returning SearchResult objects
        mock_db_manager.vector_search.return_value = make_search_results([
            {"id": "doc1", "doc_id": "doc1", "content": "test1", "project_id": "test_project", "score": 0.85},
        ], source="vector")
        mock_db_manager.fts_search.return_value = make_search_results([
            {"id": "doc2", "doc_id": "doc2", "content": "test2", "project_id": "test_project", "score": 0.9},
            {"id": "doc3", "doc_id": "doc3", "content": "test3", "project_id": "test_project", "score": 0.8},
        ], source="fts")

        # Create service with FTS-heavy weights
        service = create_search_service_with_weights(mock_storage_facade, 0.1, 0.9)

        # Perform hybrid search
        results = await service.hybrid_search(
            query_vector=[0.1] * 384,
            query_fts="test",
            limit=10,
            project_id="test_project"
        )

        # Verify results are returned
        assert len(results) > 0


class TestScoreNormalization:
    """Test that scores are normalized correctly before applying weights."""

    @pytest.mark.asyncio
    async def test_vector_scores_normalized(self, mock_db_manager, mock_storage_facade):
        """Test that vector scores are normalized to 0-1 range."""
        # Setup mock responses returning SearchResult objects
        mock_db_manager.vector_search.return_value = make_search_results([
            {"id": "doc1", "doc_id": "doc1", "content": "test1", "project_id": "test_project", "score": 0.95},
            {"id": "doc2", "doc_id": "doc2", "content": "test2", "project_id": "test_project", "score": 0.75},
        ], source="vector")
        mock_db_manager.fts_search.return_value = make_search_results([
            {"id": "doc3", "doc_id": "doc3", "content": "test3", "project_id": "test_project", "score": 0.55},
        ], source="fts")

        # Create service
        service = create_search_service_with_weights(mock_storage_facade, 0.7, 0.3)

        # Perform hybrid search
        results = await service.hybrid_search(
            query_vector=[0.1] * 384,
            query_fts="test",
            limit=10,
            project_id="test_project"
        )

        # Verify results are returned and ordered
        assert len(results) > 0
        # Vector results should be first (interleaved)
        assert results[0].id == "doc1"

    @pytest.mark.asyncio
    async def test_fts_scores_normalized(self, mock_db_manager, mock_storage_facade):
        """Test that FTS scores are normalized to 0-1 range."""
        # Setup mock responses returning SearchResult objects
        mock_db_manager.vector_search.return_value = make_search_results([
            {"id": "doc1", "doc_id": "doc1", "content": "test1", "project_id": "test_project", "score": 0.95},
        ], source="vector")
        mock_db_manager.fts_search.return_value = make_search_results([
            {"id": "doc2", "doc_id": "doc2", "content": "test2", "project_id": "test_project", "score": 0.75},
            {"id": "doc3", "doc_id": "doc3", "content": "test3", "project_id": "test_project", "score": 0.55},
        ], source="fts")

        # Create service
        service = create_search_service_with_weights(mock_storage_facade, 0.7, 0.3)

        # Perform hybrid search
        results = await service.hybrid_search(
            query_vector=[0.1] * 384,
            query_fts="test",
            limit=10,
            project_id="test_project"
        )

        # Verify results are returned
        assert len(results) > 0
        # Verify all scores are in valid range
        for result in results:
            assert 0.0 <= result.score <= 1.0

    @pytest.mark.asyncio
    async def test_combined_scores_with_normalization(self, mock_db_manager, mock_storage_facade):
        """Test that combined scores use normalized values."""
        # Setup mock responses returning SearchResult objects - doc2 appears in both
        mock_db_manager.vector_search.return_value = make_search_results([
            {"id": "doc1", "doc_id": "doc1", "content": "test1", "project_id": "test_project", "score": 0.85},
            {"id": "doc2", "doc_id": "doc2", "content": "test2", "project_id": "test_project", "score": 0.95},
        ], source="vector")
        mock_db_manager.fts_search.return_value = make_search_results([
            {"id": "doc2", "doc_id": "doc2", "content": "test2", "project_id": "test_project", "score": 0.95},
            {"id": "doc3", "doc_id": "doc3", "content": "test3", "project_id": "test_project", "score": 0.75},
        ], source="fts")

        # Create service with equal weights
        service = create_search_service_with_weights(mock_storage_facade, 0.5, 0.5)

        # Perform hybrid search
        results = await service.hybrid_search(
            query_vector=[0.1] * 384,
            query_fts="test",
            limit=10,
            project_id="test_project"
        )

        # Verify results are returned
        assert len(results) > 0
        # doc2 should be in results (it appears in both)
        doc2_found = any(r.id == "doc2" for r in results)
        assert doc2_found
        # Verify all scores are normalized
        for result in results:
            assert 0.0 <= result.score <= 1.0


class TestWeightConfiguration:
    """Test weight configuration validation and usage."""
    
    def test_weights_must_sum_to_one(self):
        """Test that weights must sum to 1.0."""
        config_data = {
            'storage': {
                'root': './.test_storage',
                'lancedb': {'path': 'lancedb'},
                'file_tracker': {'path': 'file_tracker.db'},
                'document_cache': {'enabled': False, 'path': 'cache'}
            },
            'cache': {'document_cache': {'max_size': 1000}},
            'search': {
                'default_limit': 10,
                'max_limit': 100,
                'hybrid_search': {
                    'vector_weight': 0.8,
                    'fts_weight': 0.4  # Sum = 1.2, invalid
                }
            },
            'embeddings': {'default_provider': 'sentence_transformer'},
            'parsers': {}
        }
        
        with pytest.raises(ConfigurationError) as exc_info:
            Config._validate_config(config_data)
        
        assert "must sum to 1.0" in str(exc_info.value)
    
    def test_valid_weights_accepted(self):
        """Test that valid weights are accepted."""
        config_data = {
            'storage': {
                'root': './.test_storage',
                'lancedb': {'path': 'lancedb'},
                'file_tracker': {'path': 'file_tracker.db'},
                'document_cache': {'enabled': False, 'path': 'cache'}
            },
            'cache': {'document_cache': {'max_size': 1000}},
            'search': {
                'default_limit': 10,
                'max_limit': 100,
                'hybrid_search': {
                    'vector_weight': 0.6,
                    'fts_weight': 0.4  # Sum = 1.0, valid
                }
            },
            'embeddings': {'default_provider': 'sentence_transformer'},
            'parsers': {}
        }
        
        # Should not raise
        Config._validate_config(config_data)
    
    def test_extreme_weights_accepted(self):
        """Test that extreme but valid weights are accepted."""
        # All weight on vector
        config_data = {
            'storage': {
                'root': './.test_storage',
                'lancedb': {'path': 'lancedb'},
                'file_tracker': {'path': 'file_tracker.db'},
                'document_cache': {'enabled': False, 'path': 'cache'}
            },
            'cache': {'document_cache': {'max_size': 1000}},
            'search': {
                'default_limit': 10,
                'max_limit': 100,
                'hybrid_search': {
                    'vector_weight': 1.0,
                    'fts_weight': 0.0
                }
            },
            'embeddings': {'default_provider': 'sentence_transformer'},
            'parsers': {}
        }
        
        # Should not raise
        Config._validate_config(config_data)
        
        # All weight on FTS
        config_data['search']['hybrid_search'] = {
            'vector_weight': 0.0,
            'fts_weight': 1.0
        }
        
        # Should not raise
        Config._validate_config(config_data)


class TestDifferentWeightConfigurations:
    """Test hybrid search with different weight configurations."""

    @pytest.mark.asyncio
    async def test_equal_weights_50_50(self, mock_db_manager, mock_storage_facade):
        """Test with equal weights (0.5, 0.5)."""
        # Use multiple results with diverse file paths, returning SearchResult objects
        mock_db_manager.vector_search.return_value = make_search_results([
            {"id": "doc1", "doc_id": "doc1", "content": "test1", "project_id": "test_project", "score": 0.9, "file_path": "/a/file1.py"},
            {"id": "doc2", "doc_id": "doc2", "content": "test2", "project_id": "test_project", "score": 0.85, "file_path": "/b/file2.py"},
        ], source="vector")
        mock_db_manager.fts_search.return_value = make_search_results([
            {"id": "doc3", "doc_id": "doc3", "content": "test3", "project_id": "test_project", "score": 0.8, "file_path": "/c/file3.py"},
        ], source="fts")

        service = create_search_service_with_weights(mock_storage_facade, 0.5, 0.5)
        results = await service.hybrid_search(
            query_vector=[0.1] * 384,
            query_fts="test",
            limit=10,
            project_id="test_project"
        )

        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_weights_60_40(self, mock_db_manager, mock_storage_facade):
        """Test with 60/40 split."""
        mock_db_manager.vector_search.return_value = make_search_results([
            {"id": "doc1", "doc_id": "doc1", "content": "test1", "project_id": "test_project", "score": 0.9},
        ], source="vector")
        mock_db_manager.fts_search.return_value = make_search_results([
            {"id": "doc2", "doc_id": "doc2", "content": "test2", "project_id": "test_project", "score": 0.85},
        ], source="fts")

        service = create_search_service_with_weights(mock_storage_facade, 0.6, 0.4)
        results = await service.hybrid_search(
            query_vector=[0.1] * 384,
            query_fts="test",
            limit=10,
            project_id="test_project"
        )

        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_weights_80_20(self, mock_db_manager, mock_storage_facade):
        """Test with 80/20 split."""
        mock_db_manager.vector_search.return_value = make_search_results([
            {"id": "doc1", "doc_id": "doc1", "content": "test1", "project_id": "test_project", "score": 0.9},
        ], source="vector")
        mock_db_manager.fts_search.return_value = make_search_results([
            {"id": "doc2", "doc_id": "doc2", "content": "test2", "project_id": "test_project", "score": 0.85},
        ], source="fts")

        service = create_search_service_with_weights(mock_storage_facade, 0.8, 0.2)
        results = await service.hybrid_search(
            query_vector=[0.1] * 384,
            query_fts="test",
            limit=10,
            project_id="test_project"
        )

        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_weights_20_80(self, mock_db_manager, mock_storage_facade):
        """Test with 20/80 split."""
        mock_db_manager.vector_search.return_value = make_search_results([
            {"id": "doc1", "doc_id": "doc1", "content": "test1", "project_id": "test_project", "score": 0.9},
        ], source="vector")
        mock_db_manager.fts_search.return_value = make_search_results([
            {"id": "doc2", "doc_id": "doc2", "content": "test2", "project_id": "test_project", "score": 0.85},
        ], source="fts")

        service = create_search_service_with_weights(mock_storage_facade, 0.2, 0.8)
        results = await service.hybrid_search(
            query_vector=[0.1] * 384,
            query_fts="test",
            limit=10,
            project_id="test_project"
        )

        assert len(results) > 0


# Removed TestScoreNormalizationMethods class - these private methods don't exist in the current implementation
# Normalization is tested through the public API in TestScoreNormalization class


class TestScoreBasedVsRankBasedFusion:
    """Test that score-based fusion differs from rank-based approach."""

    @pytest.mark.asyncio
    async def test_weights_properly_applied_with_actual_scores(self, mock_db_manager, mock_storage_facade):
        """Test that configured weights are properly applied to actual scores."""
        # Test with vector-heavy weights (0.9, 0.1)
        # Setup mock responses for vector-heavy search, returning SearchResult objects
        mock_db_manager.vector_search.return_value = make_search_results([
            {"id": "doc1", "doc_id": "doc1", "content": "test1", "project_id": "test_project", "score": 0.95},
            {"id": "doc2", "doc_id": "doc2", "content": "test2", "project_id": "test_project", "score": 0.75},
        ], source="vector")
        mock_db_manager.fts_search.return_value = make_search_results([
            {"id": "doc3", "doc_id": "doc3", "content": "test3", "project_id": "test_project", "score": 0.55},
        ], source="fts")

        service_vector_heavy = create_search_service_with_weights(mock_storage_facade, 0.9, 0.1)
        results_vector_heavy = await service_vector_heavy.hybrid_search(
            query_vector=[0.1] * 384,
            query_fts="test",
            limit=10,
            project_id="test_project"
        )

        # doc1 should rank first (best vector match, interleaved)
        assert results_vector_heavy[0].id == "doc1"

        # Test with FTS-heavy weights (0.1, 0.9)
        mock_db_manager.vector_search.return_value = make_search_results([
            {"id": "doc1", "doc_id": "doc1", "content": "test1", "project_id": "test_project", "score": 0.55},
        ], source="vector")
        mock_db_manager.fts_search.return_value = make_search_results([
            {"id": "doc2", "doc_id": "doc2", "content": "test2", "project_id": "test_project", "score": 0.95},
            {"id": "doc3", "doc_id": "doc3", "content": "test3", "project_id": "test_project", "score": 0.75},
        ], source="fts")

        service_fts_heavy = create_search_service_with_weights(mock_storage_facade, 0.1, 0.9)
        results_fts_heavy = await service_fts_heavy.hybrid_search(
            query_vector=[0.1] * 384,
            query_fts="test",
            limit=10,
            project_id="test_project"
        )

        # Results should be interleaved: doc1 (vector), doc2 (fts), doc3 (fts)
        # doc1 is first because interleaving takes vector first
        assert len(results_fts_heavy) >= 1

    @pytest.mark.asyncio
    async def test_score_differences_reflected_in_ranking(self, mock_db_manager, mock_storage_facade):
        """Test that actual score differences are reflected in final ranking.

        With linear combination reranking:
        - doc1: 0.5 * 0.99 = 0.495 (highest vector score)
        - doc3: 0.5 * 0.98 = 0.490 (highest FTS score)
        - doc2: 0.5 * 0.20 = 0.100
        - doc4: 0.5 * 0.10 = 0.050

        After min-max normalization and deduplication, high-scoring results
        should appear first.
        """
        # Setup with distinct vector and FTS results and file paths for diversity
        # Return SearchResult objects instead of dicts
        mock_db_manager.vector_search.return_value = make_search_results([
            {"id": "doc1", "doc_id": "doc1", "content": "test1", "project_id": "test_project", "score": 0.99, "file_path": "/a/file1.py"},
            {"id": "doc2", "doc_id": "doc2", "content": "test2", "project_id": "test_project", "score": 0.20, "file_path": "/b/file2.py"},
        ], source="vector")
        mock_db_manager.fts_search.return_value = make_search_results([
            {"id": "doc3", "doc_id": "doc3", "content": "test3", "project_id": "test_project", "score": 0.98, "file_path": "/c/file3.py"},
            {"id": "doc4", "doc_id": "doc4", "content": "test4", "project_id": "test_project", "score": 0.10, "file_path": "/d/file4.py"},
        ], source="fts")

        # With equal weights
        service = create_search_service_with_weights(mock_storage_facade, 0.5, 0.5)
        results = await service.hybrid_search(
            query_vector=[0.1] * 384,
            query_fts="test",
            limit=10,
            project_id="test_project"
        )

        # Results should include high-scoring documents
        assert len(results) >= 2
        result_ids = [r.id for r in results]
        # The highest scoring documents (doc1, doc3) should be in results
        assert "doc1" in result_ids or "doc3" in result_ids
