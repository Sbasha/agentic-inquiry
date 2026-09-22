"""Tests for SearchResult serialization and conversion helpers.

Tests cover:
- to_dict and from_dict serialization
- dict_to_search_result conversion from DB rows
- dicts_to_search_results batch conversion

Note: Basic SearchResult construction, validation, immutability,
and normalization functions are tested in test_canonical_types.py.
"""

import pytest

pytestmark = pytest.mark.unit

from agentic_inquiry.database.results import (
    SearchResult,
    dict_to_search_result,
    dicts_to_search_results,
)


class TestToDict:
    """Tests for to_dict serialization."""

    def test_to_dict_all_fields(self) -> None:
        """to_dict includes all SearchResult fields."""
        result = SearchResult(
            id="doc_123",
            data={"content": "Hello", "file_path": "/main.py"},
            score=0.95,
            source="vector",
            distance=0.052,
        )
        d = result.to_dict()
        assert d == {
            "id": "doc_123",
            "data": {"content": "Hello", "file_path": "/main.py"},
            "score": 0.95,
            "source": "vector",
            "distance": 0.052,
        }

    def test_to_dict_default_values(self) -> None:
        """to_dict includes default values for source and distance."""
        result = SearchResult(id="1", data={}, score=0.5)
        d = result.to_dict()
        assert d["source"] == "unknown"
        assert d["distance"] is None

    def test_to_dict_is_json_serializable(self) -> None:
        """to_dict output can be serialized to JSON."""
        import json

        result = SearchResult(
            id="1",
            data={"nested": {"key": "value"}, "list": [1, 2, 3]},
            score=0.5,
        )
        d = result.to_dict()
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        assert parsed == d


class TestFromDict:
    """Tests for from_dict deserialization."""

    def test_from_dict_all_fields(self) -> None:
        """from_dict creates SearchResult from complete dict."""
        d = {
            "id": "doc_123",
            "data": {"content": "Hello"},
            "score": 0.95,
            "source": "vector",
            "distance": 0.052,
        }
        result = SearchResult.from_dict(d)
        assert result.id == "doc_123"
        assert result.data == {"content": "Hello"}
        assert result.score == 0.95
        assert result.source == "vector"
        assert result.distance == 0.052

    def test_from_dict_minimal(self) -> None:
        """from_dict works with minimal required fields."""
        d = {"id": "1", "score": 0.5}
        result = SearchResult.from_dict(d)
        assert result.id == "1"
        assert result.data == {}
        assert result.score == 0.5
        assert result.source == "unknown"
        assert result.distance is None

    def test_roundtrip(self) -> None:
        """to_dict and from_dict are inverses."""
        original = SearchResult(
            id="doc_123",
            data={"content": "Hello", "metadata": {"type": "code"}},
            score=0.95,
            source="hybrid",
            distance=0.05,
        )
        d = original.to_dict()
        restored = SearchResult.from_dict(d)
        assert restored == original

    def test_from_dict_missing_id_raises(self) -> None:
        """from_dict raises KeyError if id is missing."""
        with pytest.raises(KeyError):
            SearchResult.from_dict({"score": 0.5})

    def test_from_dict_missing_score_raises(self) -> None:
        """from_dict raises KeyError if score is missing."""
        with pytest.raises(KeyError):
            SearchResult.from_dict({"id": "1"})


class TestDictToSearchResult:
    """Tests for dict_to_search_result conversion helper."""

    def test_with_distance(self) -> None:
        """Distance is converted to normalized score."""
        row = {"doc_id": "123", "content": "Hello", "_distance": 0.0}
        result = dict_to_search_result(row, source="vector")
        assert result.id == "123"
        assert result.score == 1.0  # distance 0 = perfect score
        assert result.source == "vector"
        assert result.distance == 0.0

    def test_with_larger_distance(self) -> None:
        """Larger distance gives lower score."""
        row = {"doc_id": "123", "_distance": 1.0}
        result = dict_to_search_result(row, source="vector")
        assert result.score == 0.5  # 1 / (1 + 1) = 0.5

    def test_with_existing_score(self) -> None:
        """Existing score is used when no distance."""
        row = {"id": "456", "content": "World", "score": 0.75}
        result = dict_to_search_result(row, source="fts")
        assert result.id == "456"
        assert result.score == 0.75
        assert result.source == "fts"
        assert result.distance is None

    def test_score_clamping(self) -> None:
        """Scores outside 0-1 are clamped."""
        row = {"id": "1", "score": 1.5}
        result = dict_to_search_result(row, source="fts")
        assert result.score == 1.0

        row2 = {"id": "2", "score": -0.5}
        result2 = dict_to_search_result(row2, source="fts")
        assert result2.score == 0.0

    def test_no_score_no_distance(self) -> None:
        """Filter-only queries default to score 1.0."""
        row = {"id": "789", "content": "Filter result"}
        result = dict_to_search_result(row, source="filter")
        assert result.score == 1.0

    def test_id_field_priority(self) -> None:
        """ID is extracted from fields in priority order."""
        # doc_id takes priority
        row1 = {"doc_id": "doc", "id": "id", "chunk_id": "chunk"}
        assert dict_to_search_result(row1).id == "doc"

        # id is second priority
        row2 = {"id": "id", "chunk_id": "chunk"}
        assert dict_to_search_result(row2).id == "id"

        # chunk_id is third priority
        row3 = {"chunk_id": "chunk", "content": "test"}
        assert dict_to_search_result(row3).id == "chunk"

    def test_custom_id_fields(self) -> None:
        """Custom ID fields can be specified."""
        row = {"entity_id": "ent_123", "name": "Test"}
        result = dict_to_search_result(row, id_fields=("entity_id", "id"))
        assert result.id == "ent_123"

    def test_fallback_to_hash(self) -> None:
        """Falls back to hash if no ID field found."""
        row = {"content": "No ID here", "type": "test"}
        result = dict_to_search_result(row)
        assert result.id is not None
        # Verify it's a valid hash (non-empty, alphanumeric)
        assert len(result.id) > 0
        assert result.id.replace("_", "").replace("-", "").isalnum(), \
            f"Generated ID should be alphanumeric, got: {result.id}"

    def test_data_contains_original_row(self) -> None:
        """Data field contains the original row dict."""
        row = {"doc_id": "123", "content": "Hello", "metadata": {"type": "code"}}
        result = dict_to_search_result(row)
        assert result.data is row  # Same reference
        assert result.data["content"] == "Hello"
        assert result.data["metadata"]["type"] == "code"

    def test_data_access_works(self) -> None:
        """Data dict access works correctly."""
        row = {"doc_id": "123", "content": "Hello", "_distance": 0.1}
        result = dict_to_search_result(row, source="vector")
        # Access via .data attribute
        assert result.data["content"] == "Hello"
        assert result.data.get("missing", "default") == "default"
        assert "content" in result.data


class TestDictsToSearchResults:
    """Tests for dicts_to_search_results batch conversion."""

    def test_empty_list(self) -> None:
        """Empty list returns empty list."""
        assert dicts_to_search_results([]) == []

    def test_multiple_rows(self) -> None:
        """Multiple rows are converted correctly."""
        rows = [
            {"doc_id": "1", "_distance": 0.0},
            {"doc_id": "2", "_distance": 1.0},
            {"doc_id": "3", "score": 0.8},
        ]
        results = dicts_to_search_results(rows, source="vector")
        assert len(results) == 3
        assert results[0].id == "1"
        assert results[0].score == 1.0
        assert results[1].id == "2"
        assert results[1].score == 0.5
        assert results[2].id == "3"
        assert results[2].score == 0.8
        # All have same source
        assert all(r.source == "vector" for r in results)

    def test_preserves_order(self) -> None:
        """Result order matches input order."""
        rows = [{"id": str(i)} for i in range(10)]
        results = dicts_to_search_results(rows)
        assert [r.id for r in results] == [str(i) for i in range(10)]
