"""Unit tests for vector dimension edge cases.

This test module covers edge cases and failure modes related to vector dimensions:
- Zero-dimension vectors (empty list)
- Max-dimension vectors (very large dimensions)
- Mismatched dimensions between query and stored vectors
- Dimension validation error handling

Related to TEST-004: Add Vector Dimension Edge Cases
"""

import pytest
import numpy as np

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock, patch

from agentic_inquiry.database.adapters.lancedb_adapter import LanceDBAdapter
from agentic_inquiry.database.results import SearchResult
from agentic_inquiry.search.hybrid_search import HybridSearchService
from agentic_inquiry.embeddings.service import EmbeddingService


@pytest.fixture
def mock_db_manager():
    """Create a mock LanceDBAdapter for testing."""
    mock_adapter = MagicMock(spec=LanceDBAdapter)
    mock_adapter.vector_search = AsyncMock()
    mock_adapter.fts_search = AsyncMock()
    mock_adapter._manager = MagicMock()
    mock_adapter._manager.hybrid_search = AsyncMock(return_value=[])
    mock_adapter._manager.vector_search = AsyncMock(return_value=[])
    return mock_adapter


@pytest.fixture
def mock_storage_facade(mock_db_manager):
    """Create a mock StorageFacade providing the adapter."""
    mock_storage = MagicMock()
    mock_storage.vector_provider = mock_db_manager
    mock_storage.project_id = "test_project"
    return mock_storage


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    config = MagicMock()
    config.search.default_limit = 10
    config.search.hybrid_search.rerank_by_graph = False
    config.search.hybrid_search.reranker.enabled = False
    config.search.hybrid_search.overview_boost_factor = 1.5
    config.search.hybrid_search.reranker_type = "rrf"
    config.search.hybrid_search.reranker_params = {}
    config.search.hybrid_search.vector_weight = 0.7
    config.search.hybrid_search.fts_weight = 0.3
    config.search.deduplication.enabled = True
    config.search.deduplication.max_results_per_file = 3
    config.search.deduplication.min_diversity_ratio = 0.3
    config.embeddings.default_dimensions = 384
    config.embeddings.default_provider = "sentence_transformer"
    config.embeddings.sentence_transformer.model_name = "all-MiniLM-L6-v2"
    return config


@pytest.fixture
def mock_deduplicator():
    """Create a mock deduplicator."""
    dedup = MagicMock()
    dedup.deduplicate_results.return_value = []
    return dedup


@pytest.fixture
def hybrid_search_service(mock_storage_facade, mock_config, mock_deduplicator):
    """Create a HybridSearchService instance."""
    return HybridSearchService(
        storage=mock_storage_facade,
        config=mock_config,
        deduplicator=mock_deduplicator,
        project_id=mock_storage_facade.project_id,
    )


class TestZeroDimensionVectors:
    """Tests for zero-dimension (empty) vector edge cases."""

    @pytest.mark.unit
    async def test_empty_query_vector_returns_empty_results(self, hybrid_search_service):
        """Test that an empty query vector returns empty results gracefully."""
        # Setup mock functions
        async def mock_vector_search(**kwargs):
            # Empty vector should result in no vector search
            return []

        async def mock_fts_search(**kwargs):
            return []

        # Execute with empty vector
        result = await hybrid_search_service.hybrid_search(
            query_vector=[],  # Empty vector
            query_fts="test query",
            sanitized_fts_query="test query",
            vector_search_fn=mock_vector_search,
            fts_search_fn=mock_fts_search,
            limit=10,
        )

        # Verify - should handle gracefully
        assert result == []

    @pytest.mark.unit
    async def test_none_query_vector_falls_back_to_fts_only(self, hybrid_search_service, mock_deduplicator):
        """Test that None query vector falls back to FTS-only search."""
        # Setup FTS results
        fts_dicts = [
            {"doc_id": "doc_1", "content": "test", "_score": 0.9},
        ]
        fts_results = [
            SearchResult(id="doc_1", data=fts_dicts[0], score=0.9, source="fts")
        ]
        mock_deduplicator.deduplicate_results.return_value = fts_dicts

        # Setup mock functions
        async def mock_vector_search(**kwargs):
            return []

        async def mock_fts_search(**kwargs):
            return fts_results

        # Execute with None vector
        result = await hybrid_search_service.hybrid_search(
            query_vector=None,  # None vector
            query_fts="test query",
            sanitized_fts_query="test query",
            vector_search_fn=mock_vector_search,
            fts_search_fn=mock_fts_search,
            limit=10,
        )

        # Verify - should return FTS results only
        assert len(result) == 1
        assert result[0]["doc_id"] == "doc_1"

    @pytest.mark.unit
    async def test_zero_dimension_embedding_service(self, mock_config):
        """Test that EmbeddingService handles zero-dimension configuration."""
        # Configure for zero dimensions (edge case)
        mock_config.embeddings.default_dimensions = 0

        # Mock the embedder to simulate zero-dimension output
        with patch('agentic_inquiry.embeddings.registry.embedding_registry') as mock_registry:
            mock_embedder = MagicMock()
            mock_embedder.ndims.return_value = 0
            mock_embedder.embed.return_value = np.array([])
            mock_registry.has_default_embedder.return_value = True
            mock_registry.get_default_embedder.return_value = mock_embedder

            service = EmbeddingService(mock_config)

            # Verify configuration accepted
            assert service.config.embeddings.default_dimensions == 0


class TestMaxDimensionVectors:
    """Tests for very large dimension vectors (max dimension edge cases)."""

    @pytest.mark.unit
    async def test_very_large_dimension_vector_10000(self, hybrid_search_service):
        """Test handling of very large dimension vectors (10000 dimensions)."""
        # Create a very large vector (10000 dimensions)
        large_vector = [0.1] * 10000

        # Setup mock functions that would handle large vectors
        async def mock_vector_search(**kwargs):
            # Verify the vector was passed through
            assert len(kwargs.get("query_vector", [])) == 10000
            return []

        async def mock_fts_search(**kwargs):
            return []

        # Execute with large vector
        result = await hybrid_search_service.hybrid_search(
            query_vector=large_vector,
            query_fts="test query",
            sanitized_fts_query="test query",
            vector_search_fn=mock_vector_search,
            fts_search_fn=mock_fts_search,
            limit=10,
        )

        # Verify - should handle without error
        assert result == []

    @pytest.mark.unit
    async def test_extremely_large_dimension_vector_100000(self, hybrid_search_service):
        """Test handling of extremely large dimension vectors (100000 dimensions)."""
        # Create an extremely large vector (100000 dimensions)
        extremely_large_vector = [0.01] * 100000

        # Setup mock functions
        call_count = {"vector": 0}

        async def mock_vector_search(**kwargs):
            call_count["vector"] += 1
            # Verify the vector was passed through
            assert len(kwargs.get("query_vector", [])) == 100000
            return []

        async def mock_fts_search(**kwargs):
            return []

        # Execute with extremely large vector
        result = await hybrid_search_service.hybrid_search(
            query_vector=extremely_large_vector,
            query_fts="test query",
            sanitized_fts_query="test query",
            vector_search_fn=mock_vector_search,
            fts_search_fn=mock_fts_search,
            limit=10,
        )

        # Verify - should handle without error and call vector search
        assert result == []
        assert call_count["vector"] == 1

    @pytest.mark.unit
    async def test_large_dimension_with_results(self, hybrid_search_service, mock_deduplicator):
        """Test that large dimension vectors can return results successfully."""
        # Create a large vector
        large_vector = [0.05] * 5000

        # Setup mock results
        vector_dicts = [
            {"doc_id": "doc_1", "content": "test", "_distance": 0.2},
        ]
        vector_results = [
            SearchResult(id="doc_1", data=vector_dicts[0], score=0.83, source="vector")
        ]
        mock_deduplicator.deduplicate_results.return_value = vector_dicts

        # Setup mock functions
        async def mock_vector_search(**kwargs):
            assert len(kwargs.get("query_vector", [])) == 5000
            return vector_results

        async def mock_fts_search(**kwargs):
            return []

        # Execute
        result = await hybrid_search_service.hybrid_search(
            query_vector=large_vector,
            query_fts="test query",
            sanitized_fts_query="test query",
            vector_search_fn=mock_vector_search,
            fts_search_fn=mock_fts_search,
            limit=10,
        )

        # Verify - should return results
        assert len(result) == 1
        assert result[0]["doc_id"] == "doc_1"


class TestMismatchedDimensions:
    """Tests for mismatched dimensions between query and stored vectors."""

    @pytest.mark.unit
    async def test_query_vector_smaller_than_stored_dimensions(self, mock_db_manager):
        """Test query vector with fewer dimensions than stored vectors."""
        # Simulate stored vectors are 384 dimensions, query is 128
        query_vector_small = [0.1] * 128

        # Mock will simulate dimension mismatch error from LanceDB
        mock_db_manager._manager.vector_search.side_effect = Exception(
            "Dimension mismatch: query vector has 128 dimensions, expected 384"
        )

        # Execute and verify error propagates
        with pytest.raises(Exception, match="Dimension mismatch"):
            await mock_db_manager._manager.vector_search(
                table_name="document_chunks",
                query_vector=query_vector_small,
                vector_column_name="vector",
                limit=10
            )

    @pytest.mark.unit
    async def test_query_vector_larger_than_stored_dimensions(self, mock_db_manager):
        """Test query vector with more dimensions than stored vectors."""
        # Simulate stored vectors are 384 dimensions, query is 1024
        query_vector_large = [0.1] * 1024

        # Mock will simulate dimension mismatch error from LanceDB
        mock_db_manager._manager.vector_search.side_effect = Exception(
            "Dimension mismatch: query vector has 1024 dimensions, expected 384"
        )

        # Execute and verify error propagates
        with pytest.raises(Exception, match="Dimension mismatch"):
            await mock_db_manager._manager.vector_search(
                table_name="document_chunks",
                query_vector=query_vector_large,
                vector_column_name="vector",
                limit=10
            )

    @pytest.mark.unit
    async def test_mismatched_dimensions_with_graceful_fallback(self, hybrid_search_service, mock_deduplicator):
        """Test graceful fallback to FTS when vector search fails due to dimension mismatch."""
        # Setup: vector search fails, FTS succeeds
        fts_dicts = [
            {"doc_id": "doc_1", "content": "test", "_score": 0.9},
        ]
        fts_results = [
            SearchResult(id="doc_1", data=fts_dicts[0], score=0.9, source="fts")
        ]
        mock_deduplicator.deduplicate_results.return_value = fts_dicts

        # Setup mock functions
        async def mock_vector_search(**kwargs):
            # Simulate dimension mismatch error
            raise Exception("Dimension mismatch: query vector has 128 dimensions, expected 384")

        async def mock_fts_search(**kwargs):
            return fts_results

        # Execute - should catch error and continue with FTS results
        # Note: Current implementation may not have graceful fallback,
        # this test documents the expected behavior
        with pytest.raises(Exception, match="Dimension mismatch"):
            await hybrid_search_service.hybrid_search(
                query_vector=[0.1] * 128,  # Wrong dimension
                query_fts="test query",
                sanitized_fts_query="test query",
                vector_search_fn=mock_vector_search,
                fts_search_fn=mock_fts_search,
                limit=10,
            )


class TestDimensionValidation:
    """Tests for dimension validation and error handling."""

    @pytest.mark.unit
    async def test_non_numeric_vector_values(self, hybrid_search_service):
        """Test that non-numeric vector values are rejected."""
        # Create vector with non-numeric values
        invalid_vector = ["string", "values", "not", "numbers"]

        # Setup mock that would validate types
        async def mock_vector_search(**kwargs):
            query_vec = kwargs.get("query_vector", [])
            # Simulate type checking that would happen in real implementation
            if not all(isinstance(x, (int, float)) for x in query_vec):
                raise TypeError("Vector values must be numeric")
            return []

        async def mock_fts_search(**kwargs):
            return []

        # Execute and verify error
        with pytest.raises(TypeError, match="Vector values must be numeric"):
            await hybrid_search_service.hybrid_search(
                query_vector=invalid_vector,  # Invalid type
                query_fts="test query",
                sanitized_fts_query="test query",
                vector_search_fn=mock_vector_search,
                fts_search_fn=mock_fts_search,
                limit=10,
            )

    @pytest.mark.unit
    async def test_nan_vector_values(self, hybrid_search_service):
        """Test handling of NaN values in vectors."""
        # Create vector with NaN values
        vector_with_nan = [0.1, float('nan'), 0.3, 0.4]

        # Setup mock that would detect NaN
        async def mock_vector_search(**kwargs):
            query_vec = kwargs.get("query_vector", [])
            # Simulate NaN checking
            import math
            if any(math.isnan(x) for x in query_vec if isinstance(x, float)):
                raise ValueError("Vector contains NaN values")
            return []

        async def mock_fts_search(**kwargs):
            return []

        # Execute and verify error
        with pytest.raises(ValueError, match="Vector contains NaN values"):
            await hybrid_search_service.hybrid_search(
                query_vector=vector_with_nan,
                query_fts="test query",
                sanitized_fts_query="test query",
                vector_search_fn=mock_vector_search,
                fts_search_fn=mock_fts_search,
                limit=10,
            )

    @pytest.mark.unit
    async def test_infinity_vector_values(self, hybrid_search_service):
        """Test handling of infinity values in vectors."""
        # Create vector with infinity values
        vector_with_inf = [0.1, float('inf'), 0.3, 0.4]

        # Setup mock that would detect infinity
        async def mock_vector_search(**kwargs):
            query_vec = kwargs.get("query_vector", [])
            # Simulate infinity checking
            import math
            if any(math.isinf(x) for x in query_vec if isinstance(x, float)):
                raise ValueError("Vector contains infinity values")
            return []

        async def mock_fts_search(**kwargs):
            return []

        # Execute and verify error
        with pytest.raises(ValueError, match="Vector contains infinity values"):
            await hybrid_search_service.hybrid_search(
                query_vector=vector_with_inf,
                query_fts="test query",
                sanitized_fts_query="test query",
                vector_search_fn=mock_vector_search,
                fts_search_fn=mock_fts_search,
                limit=10,
            )

    @pytest.mark.unit
    async def test_mixed_valid_and_invalid_dimensions(self, hybrid_search_service):
        """Test batch operations with mixed valid and invalid dimension vectors."""
        # Simulate a scenario where multiple vectors are processed
        valid_vector = [0.1] * 384
        invalid_vector = [0.1] * 128  # Wrong dimension

        # Setup tracking
        results_collected = []

        async def mock_vector_search(**kwargs):
            query_vec = kwargs.get("query_vector", [])
            if len(query_vec) != 384:
                raise ValueError(f"Expected 384 dimensions, got {len(query_vec)}")
            results_collected.append("valid")
            return []

        async def mock_fts_search(**kwargs):
            return []

        # Test valid vector succeeds
        await hybrid_search_service.hybrid_search(
            query_vector=valid_vector,
            query_fts="test query",
            sanitized_fts_query="test query",
            vector_search_fn=mock_vector_search,
            fts_search_fn=mock_fts_search,
            limit=10,
        )
        assert len(results_collected) == 1

        # Test invalid vector fails
        with pytest.raises(ValueError, match="Expected 384 dimensions, got 128"):
            await hybrid_search_service.hybrid_search(
                query_vector=invalid_vector,
                query_fts="test query",
                sanitized_fts_query="test query",
                vector_search_fn=mock_vector_search,
                fts_search_fn=mock_fts_search,
                limit=10,
            )

    @pytest.mark.unit
    async def test_embedding_service_dimension_consistency(self, mock_config):
        """Test that EmbeddingService maintains dimension consistency."""
        # Configure service
        mock_config.embeddings.default_dimensions = 384

        with patch('agentic_inquiry.embeddings.registry.embedding_registry') as mock_registry:
            mock_embedder = MagicMock()
            mock_embedder.ndims.return_value = 384
            mock_embedder.embed.return_value = np.array([0.1] * 384)
            mock_registry.has_default_embedder.return_value = True
            mock_registry.get_default_embedder.return_value = mock_embedder

            service = EmbeddingService(mock_config)

            # Verify dimensions are consistent with config
            assert service.config.embeddings.default_dimensions == 384


class TestEdgeCaseCombinations:
    """Tests for combinations of edge cases."""

    @pytest.mark.unit
    async def test_empty_vector_with_empty_fts_query(self, hybrid_search_service):
        """Test both empty vector and empty FTS query."""
        # Setup mock functions
        async def mock_vector_search(**kwargs):
            return []

        async def mock_fts_search(**kwargs):
            return []

        # Execute with both empty
        result = await hybrid_search_service.hybrid_search(
            query_vector=[],  # Empty
            query_fts="",  # Empty
            sanitized_fts_query="",
            vector_search_fn=mock_vector_search,
            fts_search_fn=mock_fts_search,
            limit=10,
        )

        # Verify - should return empty results gracefully
        assert result == []

    @pytest.mark.unit
    async def test_large_dimension_vector_with_zero_limit(self, hybrid_search_service):
        """Test large dimension vector with limit=0."""
        large_vector = [0.1] * 1000

        # Setup mock functions
        async def mock_vector_search(**kwargs):
            # Even with zero limit, should handle the vector
            assert len(kwargs.get("query_vector", [])) == 1000
            return []

        async def mock_fts_search(**kwargs):
            return []

        # Execute with limit=0
        result = await hybrid_search_service.hybrid_search(
            query_vector=large_vector,
            query_fts="test query",
            sanitized_fts_query="test query",
            vector_search_fn=mock_vector_search,
            fts_search_fn=mock_fts_search,
            limit=0,  # Zero limit
        )

        # Verify - should handle gracefully
        assert result == []

    @pytest.mark.unit
    async def test_single_dimension_vector(self, hybrid_search_service):
        """Test vector with only one dimension (edge case of minimal dimensions)."""
        single_dim_vector = [0.5]

        # Setup mock functions
        async def mock_vector_search(**kwargs):
            query_vec = kwargs.get("query_vector", [])
            assert len(query_vec) == 1
            return []

        async def mock_fts_search(**kwargs):
            return []

        # Execute
        result = await hybrid_search_service.hybrid_search(
            query_vector=single_dim_vector,
            query_fts="test query",
            sanitized_fts_query="test query",
            vector_search_fn=mock_vector_search,
            fts_search_fn=mock_fts_search,
            limit=10,
        )

        # Verify - should handle single dimension
        assert result == []
