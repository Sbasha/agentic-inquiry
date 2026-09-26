"""Unit tests for SearchDeduplicator."""

import pytest

pytestmark = pytest.mark.unit

from agentic_inquiry.search.deduplicator import SearchDeduplicator


class TestSearchDeduplicator:
    """Test suite for SearchDeduplicator."""

    def test_deduplicate_with_duplicate_files(self):
        """Test deduplication removes duplicate files keeping highest scores."""
        deduplicator = SearchDeduplicator(max_results_per_file=1)

        results = [
            {"file_path": "a.py", "relevance_score": 0.9, "chunk_id": "1"},
            {"file_path": "b.py", "relevance_score": 0.8, "chunk_id": "2"},
            {"file_path": "a.py", "relevance_score": 0.7, "chunk_id": "3"},
            {"file_path": "c.py", "relevance_score": 0.6, "chunk_id": "4"},
            {"file_path": "b.py", "relevance_score": 0.5, "chunk_id": "5"},
        ]

        deduplicated = deduplicator.deduplicate_results(results)

        # Should keep only 3 results (one per file)
        assert len(deduplicated) == 3

        # Should keep highest-scoring chunks
        file_paths = [r["file_path"] for r in deduplicated]
        assert "a.py" in file_paths
        assert "b.py" in file_paths
        assert "c.py" in file_paths

        # Verify highest scores were kept
        for result in deduplicated:
            if result["file_path"] == "a.py":
                assert result["relevance_score"] == 0.9
            elif result["file_path"] == "b.py":
                assert result["relevance_score"] == 0.8
            elif result["file_path"] == "c.py":
                assert result["relevance_score"] == 0.6

    def test_deduplicate_with_distance_scoring(self):
        """Test deduplication works with _distance field (lower is better)."""
        deduplicator = SearchDeduplicator(max_results_per_file=1)

        results = [
            {"file_path": "a.py", "_distance": 0.1, "chunk_id": "1"},
            {"file_path": "b.py", "_distance": 0.2, "chunk_id": "2"},
            {"file_path": "a.py", "_distance": 0.3, "chunk_id": "3"},
        ]

        deduplicated = deduplicator.deduplicate_results(results)

        # Should keep only 2 results
        assert len(deduplicated) == 2

        # Should keep lowest distance for a.py
        for result in deduplicated:
            if result["file_path"] == "a.py":
                assert result["_distance"] == 0.1

    def test_deduplicate_preserves_order(self):
        """Test that deduplication preserves original relevance ordering."""
        deduplicator = SearchDeduplicator(max_results_per_file=1)

        results = [
            {"file_path": "a.py", "relevance_score": 0.9, "chunk_id": "1"},
            {"file_path": "b.py", "relevance_score": 0.8, "chunk_id": "2"},
            {"file_path": "a.py", "relevance_score": 0.7, "chunk_id": "3"},
            {"file_path": "c.py", "relevance_score": 0.6, "chunk_id": "4"},
        ]

        deduplicated = deduplicator.deduplicate_results(results, preserve_order=True)

        # Should maintain order: a.py (0.9), b.py (0.8), c.py (0.6)
        assert deduplicated[0]["file_path"] == "a.py"
        assert deduplicated[1]["file_path"] == "b.py"
        assert deduplicated[2]["file_path"] == "c.py"

    def test_deduplicate_max_results_per_file(self):
        """Test max_results_per_file parameter."""
        deduplicator = SearchDeduplicator(max_results_per_file=2)

        results = [
            {"file_path": "a.py", "relevance_score": 0.9, "chunk_id": "1"},
            {"file_path": "a.py", "relevance_score": 0.8, "chunk_id": "2"},
            {"file_path": "a.py", "relevance_score": 0.7, "chunk_id": "3"},
            {"file_path": "b.py", "relevance_score": 0.6, "chunk_id": "4"},
        ]

        deduplicated = deduplicator.deduplicate_results(results)

        # Should keep 2 results from a.py and 1 from b.py
        assert len(deduplicated) == 3

        # Count results per file
        a_count = sum(1 for r in deduplicated if r["file_path"] == "a.py")
        b_count = sum(1 for r in deduplicated if r["file_path"] == "b.py")

        assert a_count == 2
        assert b_count == 1

    def test_deduplicate_empty_results(self):
        """Test deduplication with empty results."""
        deduplicator = SearchDeduplicator(max_results_per_file=1)

        deduplicated = deduplicator.deduplicate_results([])

        assert deduplicated == []

    def test_deduplicate_no_duplicates(self):
        """Test deduplication when there are no duplicates."""
        deduplicator = SearchDeduplicator(max_results_per_file=1)

        results = [
            {"file_path": "a.py", "relevance_score": 0.9, "chunk_id": "1"},
            {"file_path": "b.py", "relevance_score": 0.8, "chunk_id": "2"},
            {"file_path": "c.py", "relevance_score": 0.7, "chunk_id": "3"},
        ]

        deduplicated = deduplicator.deduplicate_results(results)

        # Should keep all results
        assert len(deduplicated) == 3

    def test_calculate_diversity_score(self):
        """Test diversity score calculation."""
        deduplicator = SearchDeduplicator()

        # All unique files - maximum diversity
        results = [
            {"file_path": "a.py"},
            {"file_path": "b.py"},
            {"file_path": "c.py"},
        ]
        diversity = deduplicator.calculate_diversity_score(results)
        assert diversity == 1.0

        # All same file - no diversity
        results = [
            {"file_path": "a.py"},
            {"file_path": "a.py"},
            {"file_path": "a.py"},
        ]
        diversity = deduplicator.calculate_diversity_score(results)
        assert diversity == pytest.approx(0.333, abs=0.01)

        # Mixed - 2 unique files out of 3 results
        results = [
            {"file_path": "a.py"},
            {"file_path": "b.py"},
            {"file_path": "a.py"},
        ]
        diversity = deduplicator.calculate_diversity_score(results)
        assert diversity == pytest.approx(0.666, abs=0.01)

        # Empty results - considered maximally diverse
        diversity = deduplicator.calculate_diversity_score([])
        assert diversity == 1.0

    def test_diversity_warning_threshold(self, caplog):
        """Test that low diversity triggers a warning."""
        import logging

        # Set log level for the specific logger
        caplog.set_level(logging.WARNING, logger="agentic_inquiry.search.deduplicator")

        # Use max_results_per_file=3 to keep multiple results from same file
        deduplicator = SearchDeduplicator(
            max_results_per_file=3, min_diversity_ratio=0.7
        )

        # Create results with low diversity (mostly from same file)
        # After deduplication: 3 from a.py, 1 from b.py = 4 total, 2 unique = 0.5 diversity
        results = [
            {"file_path": "a.py", "relevance_score": 0.9, "chunk_id": "1"},
            {"file_path": "a.py", "relevance_score": 0.8, "chunk_id": "2"},
            {"file_path": "a.py", "relevance_score": 0.7, "chunk_id": "3"},
            {"file_path": "b.py", "relevance_score": 0.6, "chunk_id": "4"},
        ]

        deduplicator.deduplicate_results(results)

        # Should have warning about low diversity (0.5 < 0.7)
        assert any("diversity" in record.message.lower() for record in caplog.records)

    def test_deduplicate_missing_file_path(self):
        """Test deduplication handles results without file_path."""
        deduplicator = SearchDeduplicator(max_results_per_file=1)

        results = [
            {"relevance_score": 0.9, "chunk_id": "1"},  # No file_path
            {"file_path": "a.py", "relevance_score": 0.8, "chunk_id": "2"},
        ]

        # Should not crash
        deduplicated = deduplicator.deduplicate_results(results)

        # Should keep both (treated as different files)
        assert len(deduplicated) == 2

    def test_deduplicate_with_id_field(self):
        """Test deduplication uses 'id' field for tracking."""
        deduplicator = SearchDeduplicator(max_results_per_file=1)

        results = [
            {"file_path": "a.py", "relevance_score": 0.9, "id": "1"},
            {"file_path": "b.py", "relevance_score": 0.8, "id": "2"},
            {"file_path": "a.py", "relevance_score": 0.7, "id": "3"},
        ]

        deduplicated = deduplicator.deduplicate_results(results, preserve_order=True)

        # Should preserve order using 'id' field
        assert deduplicated[0]["id"] == "1"
        assert deduplicated[1]["id"] == "2"
