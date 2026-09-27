"""Tests for pattern analyzer service."""

import pytest

pytestmark = pytest.mark.unit

import numpy as np
from unittest.mock import AsyncMock, patch

from agentic_inquiry.mcp.services.pattern_analyzer import PatternAnalyzer


@pytest.fixture
def mock_search_service():
    """Create mock search service."""
    service = AsyncMock()
    return service


@pytest.fixture
def mock_db_manager():
    """Create mock database manager."""
    manager = AsyncMock()
    return manager


@pytest.fixture
def mock_embedding_service():
    """Create mock embedding service that returns varied embeddings for clustering."""
    service = AsyncMock()
    # Return a 384-dimensional embedding as numpy array
    service.embed_async.return_value = np.array([0.1] * 384, dtype=np.float32)

    # embed_batch_async returns varied embeddings for clustering to work
    # Each text gets a unique but clusterable embedding based on its index
    async def mock_embed_batch(texts):
        embeddings = []
        for i, text in enumerate(texts):
            # Create varied embeddings - first half cluster around [1,0,...], second around [0,1,...]
            base = np.zeros(384, dtype=np.float32)
            if i < len(texts) // 2:
                base[0] = 1.0
                base[1:10] = 0.1
            else:
                base[0] = 0.0
                base[1] = 1.0
                base[2:10] = 0.1
            base += np.random.normal(0, 0.01, 384).astype(np.float32)
            embeddings.append(base)
        return embeddings

    service.embed_batch_async = mock_embed_batch
    return service


@pytest.fixture
def pattern_analyzer(mock_search_service, mock_db_manager, mock_embedding_service):
    """Create pattern analyzer instance with embedding service."""
    return PatternAnalyzer(
        search_service=mock_search_service,
        db_manager=mock_db_manager,
        embedding_service=mock_embedding_service,
    )


@pytest.mark.asyncio
async def test_find_patterns_insufficient_results(
    pattern_analyzer, mock_search_service
):
    """Test pattern discovery with insufficient results."""
    # Mock search to return too few results
    mock_search_service.hybrid_search.return_value = [
        {"id": "1", "vector": [0.1, 0.2], "content": "test"}
    ]

    result = await pattern_analyzer.find_patterns(
        project_id="test_project", pattern_type="architectural"
    )

    # Should return empty list when insufficient results
    assert isinstance(result, list)
    assert len(result) == 0


@pytest.mark.asyncio
async def test_find_patterns_no_embeddings(pattern_analyzer, mock_search_service):
    """Test pattern discovery when results lack embeddings."""
    # Mock search to return results without vectors
    mock_search_service.hybrid_search.return_value = [
        {"id": "1", "content": "test 1"},
        {"id": "2", "content": "test 2"},
        {"id": "3", "content": "test 3"},
    ]

    result = await pattern_analyzer.find_patterns(
        project_id="test_project", pattern_type="design"
    )

    # Should return empty list when no embeddings available
    assert isinstance(result, list)
    assert len(result) == 0


@pytest.mark.asyncio
async def test_find_patterns_successful_clustering(
    pattern_analyzer, mock_search_service
):
    """Test successful pattern clustering."""
    # Create mock results with embeddings
    # Cluster 1: Similar vectors around [1, 0]
    # Cluster 2: Similar vectors around [0, 1]
    mock_results = []
    for i in range(5):
        mock_results.append(
            {
                "id": f"cluster1_{i}",
                "vector": [
                    1.0 + np.random.normal(0, 0.1),
                    0.0 + np.random.normal(0, 0.1),
                ],
                "content": "def factory_create():\n    return Instance()",
                "file_path": f"test_{i}.py",
                "line_start": i * 10,
            }
        )
    for i in range(5):
        mock_results.append(
            {
                "id": f"cluster2_{i}",
                "vector": [
                    0.0 + np.random.normal(0, 0.1),
                    1.0 + np.random.normal(0, 0.1),
                ],
                "content": "class ServiceLayer:\n    def __init__(self):\n        pass",
                "file_path": f"class_{i}.py",
                "line_start": i * 20,
            }
        )

    mock_search_service.hybrid_search.return_value = mock_results

    result = await pattern_analyzer.find_patterns(
        project_id="test_project", pattern_type="architectural", limit=10
    )

    # Should find patterns
    assert isinstance(result, list)
    assert len(result) > 0

    # Each pattern should have required fields
    for pattern in result:
        assert "name" in pattern
        assert "type" in pattern
        assert "count" in pattern
        assert "examples" in pattern
        assert "prevalence" in pattern
        assert isinstance(pattern["examples"], list)

        # Each example should have required fields
        for example in pattern["examples"]:
            assert "file_path" in example
            assert "snippet" in example
            assert "line_start" in example


@pytest.mark.asyncio
async def test_find_patterns_search_error(pattern_analyzer, mock_search_service):
    """Test pattern discovery when search fails."""
    # Mock search to raise an error
    mock_search_service.hybrid_search.side_effect = Exception("Search failed")

    result = await pattern_analyzer.find_patterns(
        project_id="test_project", pattern_type="design"
    )

    # Should handle error gracefully and return empty list
    assert isinstance(result, list)
    assert len(result) == 0


@pytest.mark.asyncio
async def test_find_patterns_clustering_error(pattern_analyzer, mock_search_service):
    """Test pattern discovery when clustering fails."""
    # Create mock results
    mock_results = [
        {
            "id": f"result_{i}",
            "vector": [float(i), float(i)],
            "content": f"test content {i}",
            "file_path": f"test_{i}.py",
            "line_start": i,
        }
        for i in range(10)
    ]
    mock_search_service.hybrid_search.return_value = mock_results

    # Mock KMeans to raise an error (it's imported inside the function from sklearn.cluster)
    with patch("sklearn.cluster.KMeans") as mock_kmeans:
        mock_kmeans.side_effect = Exception("Clustering failed")

        result = await pattern_analyzer.find_patterns(
            project_id="test_project", pattern_type="naming"
        )

        # Should handle error gracefully and return empty list
        assert isinstance(result, list)
        assert len(result) == 0


def test_infer_pattern_name_architectural(pattern_analyzer):
    """Test pattern name inference for architectural patterns."""
    examples = [{"content": "def create_factory():\n    return Factory()"}]

    pattern_name = pattern_analyzer._infer_pattern_name(examples, "architectural")
    assert "Factory" in pattern_name or "Architectural" in pattern_name


def test_infer_pattern_name_design(pattern_analyzer):
    """Test pattern name inference for design patterns."""
    examples = [{"content": "class Singleton:\n    _instance = None"}]

    pattern_name = pattern_analyzer._infer_pattern_name(examples, "design")
    assert "Singleton" in pattern_name or "Design" in pattern_name


def test_infer_pattern_name_naming(pattern_analyzer):
    """Test pattern name inference for naming conventions."""
    examples = [{"content": "def my_function_name():\n    pass"}]

    pattern_name = pattern_analyzer._infer_pattern_name(examples, "naming")
    assert "Convention" in pattern_name or "Naming" in pattern_name


def test_infer_pattern_name_antipattern(pattern_analyzer):
    """Test pattern name inference for antipatterns."""
    examples = [{"content": "class GodClass:\n    # too many responsibilities"}]

    pattern_name = pattern_analyzer._infer_pattern_name(examples, "antipattern")
    assert (
        "God" in pattern_name
        or "Smell" in pattern_name
        or "antipattern" in pattern_name.lower()
    )


@pytest.mark.asyncio
async def test_find_patterns_max_clusters_limit(pattern_analyzer, mock_search_service):
    """Test that limit parameter is respected."""
    # Create many results that could form many clusters
    mock_results = [
        {
            "id": f"result_{i}",
            "vector": [float(i % 10), float(i % 10)],
            "content": f"def factory_create_{i}():\n    return Instance()",
            "file_path": f"test_{i}.py",
            "line_start": i * 10,
        }
        for i in range(30)
    ]
    mock_search_service.hybrid_search.return_value = mock_results

    result = await pattern_analyzer.find_patterns(
        project_id="test_project", pattern_type="architectural", limit=3
    )

    # Should not exceed limit
    assert isinstance(result, list)
    assert len(result) <= 3


@pytest.mark.asyncio
async def test_find_patterns_examples_per_cluster_limit(
    pattern_analyzer, mock_search_service
):
    """Test that examples are limited per pattern."""
    # Create results
    mock_results = [
        {
            "id": f"result_{i}",
            "vector": [1.0, 0.0],
            "content": f"def singleton_instance_{i}():\n    return _instance",
            "file_path": f"test_{i}.py",
            "line_start": i * 10,
        }
        for i in range(10)
    ]
    mock_search_service.hybrid_search.return_value = mock_results

    result = await pattern_analyzer.find_patterns(
        project_id="test_project", pattern_type="design", limit=5
    )

    # Each pattern should have at most 3 examples (hardcoded in implementation)
    for pattern in result:
        assert len(pattern["examples"]) <= 3


@pytest.mark.asyncio
async def test_find_patterns_calls_embedding_service(
    pattern_analyzer, mock_search_service, mock_embedding_service
):
    """Test that find_patterns uses embedding service to generate query vectors.

    This test verifies the fix where hybrid_search is called with query_vector
    generated from embedding_service instead of the incorrect query_text parameter.
    """
    # Create mock results with embeddings
    mock_results = [
        {
            "id": f"result_{i}",
            "vector": [float(i) / 10, float(i) / 10],
            "content": f"def service_layer_{i}():\n    return handle_request()",
            "file_path": f"service_{i}.py",
            "line_start": i * 10,
        }
        for i in range(10)
    ]
    mock_search_service.hybrid_search.return_value = mock_results

    await pattern_analyzer.find_patterns(
        project_id="test_project", pattern_type="architectural", limit=5
    )

    # Verify embedding service was called (once per query)
    # The architectural pattern type has 5 queries in _get_pattern_queries
    assert mock_embedding_service.embed_async.call_count >= 1, (
        "Expected embedding service to be called at least once"
    )

    # Verify hybrid_search was called with query_vector parameter (not query_text)
    assert mock_search_service.hybrid_search.called, (
        "Expected hybrid_search to be called"
    )

    # Get the call arguments
    call_args = mock_search_service.hybrid_search.call_args

    # Verify query_vector is in the call kwargs (key fix validation)
    if call_args.kwargs:
        assert "query_vector" in call_args.kwargs, (
            "Expected hybrid_search to be called with query_vector parameter"
        )
        assert "query_fts" in call_args.kwargs, (
            "Expected hybrid_search to be called with query_fts parameter"
        )
        # Ensure the old incorrect parameter is NOT used
        assert "query_text" not in call_args.kwargs, (
            "query_text parameter should not be used - this was the bug"
        )


@pytest.mark.asyncio
async def test_find_patterns_embedding_error_handled(
    pattern_analyzer, mock_search_service, mock_embedding_service
):
    """Test that embedding service errors are handled gracefully."""
    # Make embedding service raise an error
    mock_embedding_service.embed_async.side_effect = Exception("Embedding failed")

    result = await pattern_analyzer.find_patterns(
        project_id="test_project", pattern_type="design"
    )

    # Should handle error gracefully and return empty list
    assert isinstance(result, list)
    assert len(result) == 0
