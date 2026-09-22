"""Unit tests for HybridSearchService."""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock

from agentic_inquiry.database.adapters.lancedb_adapter import LanceDBAdapter
from agentic_inquiry.database.results import SearchResult
from agentic_inquiry.search.hybrid_search import HybridSearchService
from agentic_inquiry.search.rerankers import RRFReranker, RerankerProtocol


def _make_search_results(dicts: list, source: str = "test") -> list[SearchResult]:
    """Helper to create SearchResult objects from dict test data."""
    results = []
    for d in dicts:
        result_id = d.get("id") or d.get("doc_id") or d.get("chunk_id") or str(hash(str(d)))
        # Use score if present, else calculate from _distance
        if "score" in d:
            score = d["score"]
        elif "_distance" in d:
            score = 1.0 / (1.0 + d["_distance"])
        elif "_score" in d:
            score = d["_score"]
        else:
            score = 0.5
        results.append(SearchResult(
            id=str(result_id),
            data=d,
            score=score,
            source=source,
            distance=d.get("_distance"),
        ))
    return results


@pytest.fixture
def mock_db_manager():
    """Create a mock LanceDBAdapter for testing.

    Uses spec=LanceDBAdapter so isinstance checks pass. The adapter
    wraps a mock underlying manager accessed via _manager attribute.
    """
    mock_adapter = MagicMock(spec=LanceDBAdapter)
    mock_adapter.vector_search = AsyncMock()
    mock_adapter.fts_search = AsyncMock()
    mock_adapter._manager = MagicMock()
    mock_adapter._manager.hybrid_search = AsyncMock(return_value=[])
    return mock_adapter


@pytest.fixture
def mock_storage_facade(mock_db_manager):
    """Create a mock StorageFacade providing the adapter.

    Services that use StorageFacade access the underlying manager via
    storage.vector_provider._manager for backwards compatibility.
    """
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
    return config


@pytest.fixture
def mock_deduplicator():
    """Create a mock deduplicator."""
    dedup = MagicMock()
    dedup.deduplicate_results.return_value = []
    return dedup


@pytest.fixture
def hybrid_search_service(mock_storage_facade, mock_config, mock_deduplicator):
    """Create a HybridSearchService instance.

    HybridSearchService now accepts a StorageFacade directly instead of db_manager.
    """
    return HybridSearchService(
        storage=mock_storage_facade,
        config=mock_config,
        deduplicator=mock_deduplicator,
        project_id=mock_storage_facade.project_id,
    )


class TestHybridSearchService:
    """Tests for HybridSearchService."""

    @pytest.mark.unit
    async def test_hybrid_search_both_empty(self, hybrid_search_service):
        """Test hybrid search when both vector and FTS return empty results."""
        # Setup mock functions
        async def mock_vector_search(**kwargs):
            return []

        async def mock_fts_search(**kwargs):
            return []

        # Execute
        result = await hybrid_search_service.hybrid_search(
            query_vector=[0.1, 0.2, 0.3],
            query_fts="test query",
            sanitized_fts_query="test query",
            vector_search_fn=mock_vector_search,
            fts_search_fn=mock_fts_search,
            limit=10,
        )

        # Verify
        assert result == []

    @pytest.mark.unit
    async def test_hybrid_search_vector_only(self, hybrid_search_service, mock_deduplicator):
        """Test hybrid search when only vector search returns results."""
        # Setup mock data as SearchResult objects (what vector_search now returns)
        vector_dicts = [
            {"doc_id": "doc_1", "content": "test", "_distance": 0.1},
        ]
        vector_results = _make_search_results(vector_dicts, source="vector")
        # Deduplicator receives dicts (after SearchResult -> dict conversion)
        mock_deduplicator.deduplicate_results.return_value = vector_dicts

        # Setup mock functions returning SearchResult objects
        async def mock_vector_search(**kwargs):
            return vector_results

        async def mock_fts_search(**kwargs):
            return []

        # Execute
        result = await hybrid_search_service.hybrid_search(
            query_vector=[0.1, 0.2, 0.3],
            query_fts="test query",
            sanitized_fts_query="test query",
            vector_search_fn=mock_vector_search,
            fts_search_fn=mock_fts_search,
            limit=10,
        )

        # Verify
        assert len(result) == 1
        assert result[0]["doc_id"] == "doc_1"

    @pytest.mark.unit
    async def test_hybrid_search_fts_only(self, hybrid_search_service, mock_deduplicator):
        """Test hybrid search when only FTS returns results."""
        # Setup mock data as SearchResult objects (what fts_search now returns)
        fts_dicts = [
            {"doc_id": "doc_1", "content": "test", "_score": 0.9},
        ]
        fts_results = _make_search_results(fts_dicts, source="fts")
        # Deduplicator receives dicts (after SearchResult -> dict conversion)
        mock_deduplicator.deduplicate_results.return_value = fts_dicts

        # Setup mock functions returning SearchResult objects
        async def mock_vector_search(**kwargs):
            return []

        async def mock_fts_search(**kwargs):
            return fts_results

        # Execute
        result = await hybrid_search_service.hybrid_search(
            query_vector=[0.1, 0.2, 0.3],
            query_fts="test query",
            sanitized_fts_query="test query",
            vector_search_fn=mock_vector_search,
            fts_search_fn=mock_fts_search,
            limit=10,
        )

        # Verify
        assert len(result) == 1
        assert result[0]["doc_id"] == "doc_1"

    @pytest.mark.unit
    def test_simple_merge(self, hybrid_search_service):
        """Test simple merge of vector and FTS results."""
        # Setup mock data
        vector_results = [
            {"id": "1", "doc_id": "doc_1", "content": "vector result"},
        ]
        fts_results = [
            {"id": "2", "doc_id": "doc_2", "content": "fts result"},
        ]

        # Execute
        result = hybrid_search_service._simple_merge(vector_results, fts_results, limit=10)

        # Verify
        assert len(result) == 2
        assert result[0]["id"] == "1"
        assert result[1]["id"] == "2"

    @pytest.mark.unit
    def test_simple_merge_with_duplicates(self, hybrid_search_service):
        """Test simple merge removes duplicates."""
        # Setup mock data with duplicate doc_id
        vector_results = [
            {"id": "1", "doc_id": "doc_1", "content": "vector result"},
        ]
        fts_results = [
            {"id": "1", "doc_id": "doc_1", "content": "same result"},
        ]

        # Execute
        result = hybrid_search_service._simple_merge(vector_results, fts_results, limit=10)

        # Verify - should only have one result
        assert len(result) == 1

    @pytest.mark.unit
    def test_apply_overview_boosting(self, hybrid_search_service):
        """Test overview boosting."""
        # Setup mock data as SearchResult objects (what _apply_overview_boosting expects)
        results_dicts = [
            {"file_path": "README.md", "_distance": 0.5},
            {"file_path": "src/code.py", "_distance": 0.3},
        ]
        results = _make_search_results(results_dicts, source="vector")

        # Execute
        boosted = hybrid_search_service._apply_overview_boosting(results, boost_overview=True)

        # Verify - boosted returns SearchResult objects
        # README should be boosted, but code.py has better original score (lower distance)
        # With boost_factor 1.5, README score ~0.67 * 1.5 = ~1.0 (clamped)
        # code.py score ~0.77 (unmodified)
        # After boosting, README score becomes higher
        assert boosted[0].data["file_path"] == "README.md"  # Boosted to top
        assert boosted[1].data["file_path"] == "src/code.py"
        assert boosted[0].data.get("_overview_boosted") is True

    @pytest.mark.unit
    def test_apply_deduplication_called_with_results(self, hybrid_search_service, mock_deduplicator):
        """Test that deduplication delegates to the deduplicator.

        Note: Detailed deduplication logic is tested in test_deduplicator.py.
        This test verifies the HybridSearchService correctly invokes deduplication.
        """
        # Setup mock data with multiple results
        results = [
            {"doc_id": "doc_1", "file_path": "a.py", "relevance_score": 0.9},
            {"doc_id": "doc_2", "file_path": "a.py", "relevance_score": 0.8},
        ]
        # Mock returns only the higher-scored result (simulating dedup behavior)
        mock_deduplicator.deduplicate_results.return_value = [results[0]]

        # Execute
        deduplicated = hybrid_search_service._apply_deduplication(results)

        # Verify the deduplicator was called with correct input
        mock_deduplicator.deduplicate_results.assert_called_once_with(results)

        # Verify the deduplicated result is returned (only 1 result)
        assert len(deduplicated) == 1
        assert deduplicated[0]["doc_id"] == "doc_1"

    @pytest.mark.unit
    def test_create_reranker_returns_protocol(self, hybrid_search_service):
        """Test reranker creation always returns a RerankerProtocol."""
        # Execute
        reranker = hybrid_search_service._create_reranker()

        # Verify - always returns a valid reranker (defaults to RRF)
        assert isinstance(reranker, RerankerProtocol)
        assert isinstance(reranker, RRFReranker)


class TestRRFScoringFormula:
    """Tests that verify the RRF scoring formula is applied correctly.

    RRF formula: score = sum(weight / (k + rank + 1)) for each result across strategies.
    Default k=60, default weights: vector=0.7, fts=0.3
    """

    @pytest.mark.unit
    def test_rrf_score_calculation(self):
        """Test that RRF scores are calculated correctly per the formula."""
        from agentic_inquiry.database.results import SearchResult

        # Create test results
        vector_results = [
            SearchResult(id="doc1", data={"content": "a"}, score=0.9, source="vector"),
            SearchResult(id="doc2", data={"content": "b"}, score=0.8, source="vector"),
        ]
        fts_results = [
            SearchResult(id="doc2", data={"content": "b"}, score=0.95, source="fts"),
            SearchResult(id="doc3", data={"content": "c"}, score=0.85, source="fts"),
        ]

        # Create reranker with known parameters
        reranker = RRFReranker(k=60)
        config = {"vector_weight": 0.7, "fts_weight": 0.3}

        # Execute reranking
        results = reranker.rerank(
            query="test",
            vector_results=vector_results,
            fts_results=fts_results,
            config=config,
        )

        # Verify results are returned
        assert len(results) == 3  # doc1, doc2, doc3

        # Calculate expected raw RRF scores manually:
        # doc1: only in vector at rank 0 → 0.7 / (60 + 0 + 1) = 0.7/61 ≈ 0.01148
        # doc2: vector rank 1 + fts rank 0 → 0.7/(60+1+1) + 0.3/(60+0+1) = 0.7/62 + 0.3/61 ≈ 0.01129 + 0.00492 = 0.01621
        # doc3: only in fts at rank 1 → 0.3 / (60 + 1 + 1) = 0.3/62 ≈ 0.00484

        # doc2 should have highest score (appears in both)
        result_ids = [r.id for r in results]
        assert result_ids[0] == "doc2", "doc2 should rank first (appears in both results)"

        # doc1 should rank second (higher vector weight, rank 0 in vector)
        assert result_ids[1] == "doc1", "doc1 should rank second (vector rank 0)"

        # doc3 should rank last (only in FTS at rank 1)
        assert result_ids[2] == "doc3", "doc3 should rank last (only fts rank 1)"

    @pytest.mark.unit
    def test_rrf_respects_weight_configuration(self):
        """Test that RRF respects different weight configurations."""
        from agentic_inquiry.database.results import SearchResult

        # Same results but appearing at rank 0 in each list
        vector_results = [
            SearchResult(id="vec_doc", data={"content": "v"}, score=0.9, source="vector"),
        ]
        fts_results = [
            SearchResult(id="fts_doc", data={"content": "f"}, score=0.9, source="fts"),
        ]

        reranker = RRFReranker(k=60)

        # With vector-heavy weights (0.9, 0.1)
        results_vector_heavy = reranker.rerank(
            query="test",
            vector_results=vector_results,
            fts_results=fts_results,
            config={"vector_weight": 0.9, "fts_weight": 0.1},
        )
        # vec_doc: 0.9/(60+1) ≈ 0.01475
        # fts_doc: 0.1/(60+1) ≈ 0.00164
        assert results_vector_heavy[0].id == "vec_doc", "Vector doc should rank first with vector-heavy weights"

        # With FTS-heavy weights (0.1, 0.9)
        results_fts_heavy = reranker.rerank(
            query="test",
            vector_results=vector_results,
            fts_results=fts_results,
            config={"vector_weight": 0.1, "fts_weight": 0.9},
        )
        # vec_doc: 0.1/(60+1) ≈ 0.00164
        # fts_doc: 0.9/(60+1) ≈ 0.01475
        assert results_fts_heavy[0].id == "fts_doc", "FTS doc should rank first with FTS-heavy weights"

    @pytest.mark.unit
    def test_rrf_scores_are_normalized(self):
        """Test that final RRF scores are normalized to 0.0-1.0 range."""
        from agentic_inquiry.database.results import SearchResult

        vector_results = [
            SearchResult(id="doc1", data={"content": "a"}, score=0.9, source="vector"),
            SearchResult(id="doc2", data={"content": "b"}, score=0.8, source="vector"),
        ]
        fts_results = [
            SearchResult(id="doc3", data={"content": "c"}, score=0.9, source="fts"),
        ]

        reranker = RRFReranker(k=60)
        results = reranker.rerank(
            query="test",
            vector_results=vector_results,
            fts_results=fts_results,
            config={"vector_weight": 0.7, "fts_weight": 0.3},
        )

        # All scores should be normalized to 0.0-1.0
        for result in results:
            assert 0.0 <= result.score <= 1.0, f"Score {result.score} not in [0.0, 1.0]"

        # The highest-ranked result should have score 1.0 (max normalization)
        assert results[0].score == 1.0, "Top result should have normalized score of 1.0"

    @pytest.mark.unit
    def test_rrf_empty_inputs(self):
        """Test RRF handles empty inputs gracefully."""
        from agentic_inquiry.database.results import SearchResult

        reranker = RRFReranker(k=60)

        # Both empty
        results = reranker.rerank(
            query="test", vector_results=[], fts_results=[], config={}
        )
        assert results == [], "Empty inputs should return empty results"

        # Only vector results
        vector_results = [
            SearchResult(id="doc1", data={"content": "a"}, score=0.9, source="vector"),
        ]
        results = reranker.rerank(
            query="test", vector_results=vector_results, fts_results=[], config={}
        )
        assert len(results) == 1
        assert results[0].id == "doc1"

        # Only FTS results
        fts_results = [
            SearchResult(id="doc2", data={"content": "b"}, score=0.9, source="fts"),
        ]
        results = reranker.rerank(
            query="test", vector_results=[], fts_results=fts_results, config={}
        )
        assert len(results) == 1
        assert results[0].id == "doc2"


class TestContentPreference:
    """Tests for soft content preference boosting (SDD-001).

    Content preference replaces hard filtering with soft boosting:
    - Preferred content types get score boosted by weight factor
    - Non-preferred content types are still included (cross-content discovery)
    - Results are re-sorted by boosted scores
    """

    @pytest.mark.unit
    def test_content_preference_boosts_matching_type(self, hybrid_search_service):
        """Test that matching content types get boosted scores."""
        # Setup: code result has lower original score than doc result
        results = [
            {"doc_id": "doc_1", "content_type": "documentation", "score": 0.9},
            {"doc_id": "doc_2", "content_type": "code", "score": 0.7},
        ]

        # Execute: prefer code with 70% boost
        boosted = hybrid_search_service._apply_content_preference(
            results=results,
            content_preference="code",
            content_preference_weight=0.7,
        )

        # Verify: code result should now rank first (0.7 * 1.7 = 1.19 > 0.9)
        assert boosted[0]["content_type"] == "code"
        assert boosted[0]["score"] == pytest.approx(0.7 * 1.7, rel=1e-2)
        assert boosted[0].get("_content_preference_boosted") is True

        # Documentation result unchanged in score
        assert boosted[1]["content_type"] == "documentation"
        assert boosted[1]["score"] == 0.9
        assert boosted[1].get("_content_preference_boosted") is None

    @pytest.mark.unit
    def test_content_preference_includes_non_matching(self, hybrid_search_service):
        """Test that non-matching content types are still included (not filtered)."""
        # Setup: mix of content types
        results = [
            {"doc_id": "doc_1", "content_type": "code", "score": 0.8},
            {"doc_id": "doc_2", "content_type": "documentation", "score": 0.7},
            {"doc_id": "doc_3", "content_type": "test", "score": 0.6},
        ]

        # Execute: prefer code
        boosted = hybrid_search_service._apply_content_preference(
            results=results,
            content_preference="code",
            content_preference_weight=0.5,
        )

        # Verify: all results still present (soft preference, not hard filter)
        assert len(boosted) == 3
        content_types = {r["content_type"] for r in boosted}
        assert content_types == {"code", "documentation", "test"}

    @pytest.mark.unit
    def test_content_preference_respects_weight(self, hybrid_search_service):
        """Test that different weights produce different boost amounts."""
        results = [
            {"doc_id": "doc_1", "content_type": "code", "score": 0.5},
        ]

        # Low weight (20% boost)
        low_boost = hybrid_search_service._apply_content_preference(
            results=results.copy(),
            content_preference="code",
            content_preference_weight=0.2,
        )
        assert low_boost[0]["score"] == pytest.approx(0.5 * 1.2, rel=1e-2)

        # High weight (90% boost)
        high_boost = hybrid_search_service._apply_content_preference(
            results=results.copy(),
            content_preference="code",
            content_preference_weight=0.9,
        )
        assert high_boost[0]["score"] == pytest.approx(0.5 * 1.9, rel=1e-2)

    @pytest.mark.unit
    def test_no_preference_returns_all_types_unchanged(self, hybrid_search_service):
        """Test that None preference returns results unchanged."""
        results = [
            {"doc_id": "doc_1", "content_type": "documentation", "score": 0.9},
            {"doc_id": "doc_2", "content_type": "code", "score": 0.7},
        ]

        # Execute: no preference
        unchanged = hybrid_search_service._apply_content_preference(
            results=results,
            content_preference=None,
            content_preference_weight=0.7,
        )

        # Verify: results unchanged (same order, same scores)
        assert unchanged[0]["doc_id"] == "doc_1"
        assert unchanged[0]["score"] == 0.9
        assert unchanged[1]["doc_id"] == "doc_2"
        assert unchanged[1]["score"] == 0.7

    @pytest.mark.unit
    def test_content_preference_case_insensitive(self, hybrid_search_service):
        """Test that content type matching is case-insensitive."""
        results = [
            {"doc_id": "doc_1", "content_type": "CODE", "score": 0.5},
            {"doc_id": "doc_2", "content_type": "Code", "score": 0.4},
        ]

        # Execute: prefer "code" (lowercase)
        boosted = hybrid_search_service._apply_content_preference(
            results=results,
            content_preference="code",
            content_preference_weight=0.5,
        )

        # Verify: both CODE and Code matched
        assert all(r.get("_content_preference_boosted") for r in boosted)

    @pytest.mark.unit
    def test_content_preference_empty_results(self, hybrid_search_service):
        """Test that empty results are handled gracefully."""
        boosted = hybrid_search_service._apply_content_preference(
            results=[],
            content_preference="code",
            content_preference_weight=0.7,
        )
        assert boosted == []

    @pytest.mark.unit
    def test_content_preference_missing_content_type(self, hybrid_search_service):
        """Test that results without content_type field are not boosted."""
        results = [
            {"doc_id": "doc_1", "content_type": "code", "score": 0.5},
            {"doc_id": "doc_2", "score": 0.6},  # No content_type
        ]

        boosted = hybrid_search_service._apply_content_preference(
            results=results,
            content_preference="code",
            content_preference_weight=0.5,
        )

        # Code result boosted, missing type not boosted
        code_result = next(r for r in boosted if r["doc_id"] == "doc_1")
        no_type_result = next(r for r in boosted if r["doc_id"] == "doc_2")

        assert code_result.get("_content_preference_boosted") is True
        assert no_type_result.get("_content_preference_boosted") is None
        assert no_type_result["score"] == 0.6  # Unchanged
