"""Tests for canonical database types (SearchResult, Filter, QuerySpec).

These tests verify the core data structures used across all database operations.
"""
import pytest

pytestmark = pytest.mark.unit

from agentic_inquiry.database.results import (
    SearchResult,
    normalize_distance_to_score,
    normalize_similarity_to_score,
)
from agentic_inquiry.database.filters import (
    Filter,
    FilterOperator,
    validate_field_name,
    validate_filter_value,
    eq,
    ne,
    gt,
    gte,
    lt,
    lte,
    is_in,
    not_in,
    is_null,
    is_not_null,
    and_,
    or_,
)
from agentic_inquiry.database.query_spec import QuerySpec


class TestSearchResult:
    """Tests for SearchResult dataclass."""

    def test_basic_creation(self):
        """Test basic SearchResult creation."""
        result = SearchResult(
            id="doc_1",
            data={"content": "Hello world"},
            score=0.95,
            source="vector",
        )
        assert result.id == "doc_1"
        assert result.data == {"content": "Hello world"}
        assert result.score == 0.95
        assert result.source == "vector"
        assert result.distance is None

    def test_with_distance(self):
        """Test SearchResult with distance field."""
        result = SearchResult(
            id="doc_1",
            data={},
            score=0.95,
            source="vector",
            distance=0.052,
        )
        assert result.distance == 0.052

    def test_score_validation_too_high(self):
        """Test that score > 1.0 raises ValueError."""
        with pytest.raises(ValueError, match="must be normalized to 0.0-1.0"):
            SearchResult(id="1", data={}, score=1.5)

    def test_score_validation_too_low(self):
        """Test that score < 0.0 raises ValueError."""
        with pytest.raises(ValueError, match="must be normalized to 0.0-1.0"):
            SearchResult(id="1", data={}, score=-0.1)

    def test_score_boundary_values(self):
        """Test score at boundary values (0.0 and 1.0)."""
        result_zero = SearchResult(id="1", data={}, score=0.0)
        result_one = SearchResult(id="2", data={}, score=1.0)
        assert result_zero.score == 0.0
        assert result_one.score == 1.0

    def test_with_score(self):
        """Test creating new result with updated score."""
        original = SearchResult(id="1", data={"x": 1}, score=0.5, source="vector")
        updated = original.with_score(0.8, source="hybrid_rrf")

        assert updated.id == "1"
        assert updated.data == {"x": 1}
        assert updated.score == 0.8
        assert updated.source == "hybrid_rrf"
        # Original unchanged
        assert original.score == 0.5

    def test_with_score_preserves_source(self):
        """Test that with_score preserves source if not specified."""
        original = SearchResult(id="1", data={}, score=0.5, source="vector")
        updated = original.with_score(0.8)
        assert updated.source == "vector"

    def test_with_data(self):
        """Test creating new result with updated data."""
        original = SearchResult(id="1", data={"old": 1}, score=0.5)
        updated = original.with_data({"new": 2})

        assert updated.data == {"new": 2}
        assert original.data == {"old": 1}

    def test_frozen(self):
        """Test that SearchResult is immutable."""
        result = SearchResult(id="1", data={}, score=0.5)
        with pytest.raises(AttributeError):
            result.score = 0.8  # type: ignore


class TestNormalizationFunctions:
    """Tests for score normalization functions."""

    def test_normalize_distance_zero(self):
        """Test distance=0 gives score=1.0."""
        assert normalize_distance_to_score(0.0) == 1.0

    def test_normalize_distance_one(self):
        """Test distance=1 gives score=0.5."""
        assert normalize_distance_to_score(1.0) == 0.5

    def test_normalize_distance_large(self):
        """Test large distance gives low score."""
        score = normalize_distance_to_score(100.0)
        assert score < 0.01

    def test_normalize_distance_negative_raises(self):
        """Test negative distance raises ValueError."""
        with pytest.raises(ValueError, match="must be >= 0"):
            normalize_distance_to_score(-1.0)

    def test_normalize_similarity_clamps_high(self):
        """Test similarity > 1.0 is clamped to 1.0."""
        assert normalize_similarity_to_score(1.1) == 1.0

    def test_normalize_similarity_clamps_low(self):
        """Test similarity < 0.0 is clamped to 0.0."""
        assert normalize_similarity_to_score(-0.1) == 0.0

    def test_normalize_similarity_passthrough(self):
        """Test valid similarity passes through."""
        assert normalize_similarity_to_score(0.75) == 0.75


class TestFieldValidation:
    """Tests for field name validation."""

    def test_valid_field_names(self):
        """Test valid field names pass validation."""
        valid_names = ["field", "Field", "_field", "field_name", "field123", "_123"]
        for name in valid_names:
            validate_field_name(name)  # Should not raise

    def test_valid_nested_field_names(self):
        """Test nested field names with dots pass validation."""
        valid_nested = [
            "metadata.type",
            "headers.content_type",
            "a.b.c",
            "_private.nested",
            "data.sub_field.value123",
        ]
        for name in valid_nested:
            validate_field_name(name)  # Should not raise

    def test_invalid_field_empty(self):
        """Test empty field name raises."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_field_name("")

    def test_invalid_field_starts_with_number(self):
        """Test field starting with number raises."""
        with pytest.raises(ValueError, match="must match pattern"):
            validate_field_name("123field")

    def test_invalid_field_with_spaces(self):
        """Test field with spaces raises."""
        with pytest.raises(ValueError, match="must match pattern"):
            validate_field_name("field name")

    def test_invalid_field_with_special_chars(self):
        """Test field with special characters (not dots) raises."""
        with pytest.raises(ValueError, match="must match pattern"):
            validate_field_name("field-name")
        with pytest.raises(ValueError, match="must match pattern"):
            validate_field_name("field@name")

    def test_invalid_field_dot_at_start(self):
        """Test field starting with dot raises."""
        with pytest.raises(ValueError, match="cannot start/end with"):
            validate_field_name(".field")

    def test_invalid_field_dot_at_end(self):
        """Test field ending with dot raises."""
        with pytest.raises(ValueError, match="cannot start/end with"):
            validate_field_name("field.")

    def test_invalid_field_consecutive_dots(self):
        """Test field with consecutive dots raises."""
        with pytest.raises(ValueError, match="consecutive dots"):
            validate_field_name("field..name")

    def test_invalid_nested_segment(self):
        """Test nested field with invalid segment raises."""
        with pytest.raises(ValueError, match="must match pattern"):
            validate_field_name("valid.123invalid")


class TestFilterValueValidation:
    """Tests for filter value validation."""

    def test_valid_values(self):
        """Test valid filter values pass."""
        valid = ["string", 123, 45.6, True, False, None]
        for v in valid:
            validate_filter_value(v)  # Should not raise

    def test_invalid_dict(self):
        """Test dict value raises."""
        with pytest.raises(TypeError, match="must be str, int, float, bool"):
            validate_filter_value({"key": "value"})

    def test_invalid_list(self):
        """Test list value raises."""
        with pytest.raises(TypeError, match="must be str, int, float, bool"):
            validate_filter_value([1, 2, 3])


class TestFilter:
    """Tests for Filter dataclass."""

    def test_simple_eq_filter(self):
        """Test simple equality filter."""
        f = Filter(operator=FilterOperator.EQ, field="status", value="active")
        assert f.operator == FilterOperator.EQ
        assert f.field == "status"
        assert f.value == "active"

    def test_in_filter(self):
        """Test IN filter with values list."""
        f = Filter(operator=FilterOperator.IN, field="type", values=["a", "b", "c"])
        assert f.values == ["a", "b", "c"]

    def test_is_null_filter(self):
        """Test IS NULL filter."""
        f = Filter(operator=FilterOperator.IS_NULL, field="deleted_at")
        assert f.field == "deleted_at"
        assert f.value is None

    def test_compound_and_filter(self):
        """Test compound AND filter."""
        left = Filter(operator=FilterOperator.EQ, field="a", value=1)
        right = Filter(operator=FilterOperator.GT, field="b", value=2)
        compound = Filter(operator=FilterOperator.AND, left=left, right=right)

        assert compound.is_compound()
        assert compound.left == left
        assert compound.right == right

    def test_eq_with_none_forbidden(self):
        """Test EQ with None is forbidden."""
        with pytest.raises(ValueError, match="Use IS_NULL"):
            Filter(operator=FilterOperator.EQ, field="x", value=None)

    def test_ne_with_none_forbidden(self):
        """Test NE with None is forbidden."""
        with pytest.raises(ValueError, match="Use IS_NOT_NULL"):
            Filter(operator=FilterOperator.NE, field="x", value=None)

    def test_and_requires_both_operands(self):
        """Test AND requires left and right."""
        left = Filter(operator=FilterOperator.EQ, field="a", value=1)
        with pytest.raises(ValueError, match="requires both"):
            Filter(operator=FilterOperator.AND, left=left)

    def test_comparison_requires_field(self):
        """Test comparison operators require field."""
        with pytest.raises(ValueError, match="requires 'field'"):
            Filter(operator=FilterOperator.EQ, value="x")

    def test_in_requires_values(self):
        """Test IN requires values list."""
        with pytest.raises(ValueError, match="requires 'values'"):
            Filter(operator=FilterOperator.IN, field="x")

    def test_is_compound(self):
        """Test is_compound method."""
        simple = Filter(operator=FilterOperator.EQ, field="x", value=1)
        compound = Filter(
            operator=FilterOperator.AND,
            left=simple,
            right=simple
        )
        assert not simple.is_compound()
        assert compound.is_compound()


class TestFilterConvenienceFunctions:
    """Tests for filter convenience constructors."""

    def test_eq(self):
        """Test eq() convenience function."""
        f = eq("field", "value")
        assert f.operator == FilterOperator.EQ
        assert f.field == "field"
        assert f.value == "value"

    def test_ne(self):
        """Test ne() convenience function."""
        f = ne("field", "value")
        assert f.operator == FilterOperator.NE

    def test_gt_gte_lt_lte(self):
        """Test comparison convenience functions."""
        assert gt("x", 1).operator == FilterOperator.GT
        assert gte("x", 1).operator == FilterOperator.GTE
        assert lt("x", 1).operator == FilterOperator.LT
        assert lte("x", 1).operator == FilterOperator.LTE

    def test_is_in(self):
        """Test is_in() convenience function."""
        f = is_in("type", ["a", "b"])
        assert f.operator == FilterOperator.IN
        assert f.values == ["a", "b"]

    def test_not_in(self):
        """Test not_in() convenience function."""
        f = not_in("type", ["a", "b"])
        assert f.operator == FilterOperator.NOT_IN

    def test_is_null_is_not_null(self):
        """Test null check convenience functions."""
        assert is_null("x").operator == FilterOperator.IS_NULL
        assert is_not_null("x").operator == FilterOperator.IS_NOT_NULL

    def test_and_combines_filters(self):
        """Test and_() combines multiple filters."""
        combined = and_(eq("a", 1), eq("b", 2), eq("c", 3))
        assert combined.operator == FilterOperator.AND
        # Should be nested: AND(AND(a=1, b=2), c=3)
        assert combined.right.field == "c"

    def test_or_combines_filters(self):
        """Test or_() combines multiple filters."""
        combined = or_(eq("a", 1), eq("b", 2))
        assert combined.operator == FilterOperator.OR

    def test_and_requires_at_least_two(self):
        """Test and_() requires at least 2 filters."""
        with pytest.raises(ValueError, match="at least 2"):
            and_(eq("a", 1))

    def test_or_requires_at_least_two(self):
        """Test or_() requires at least 2 filters."""
        with pytest.raises(ValueError, match="at least 2"):
            or_(eq("a", 1))


class TestQuerySpec:
    """Tests for QuerySpec dataclass."""

    def test_basic_creation(self):
        """Test basic QuerySpec creation."""
        spec = QuerySpec(table="document_chunks")
        assert spec.table == "document_chunks"
        assert spec.limit == 100
        assert spec.offset == 0

    def test_full_creation(self):
        """Test QuerySpec with all fields."""
        spec = QuerySpec(
            table="document_chunks",
            filters=eq("type", "code"),
            limit=20,
            offset=10,
            vector=[0.1] * 384,
            vector_column="embedding",
            fts_query="search term",
            fts_columns=["content", "title"],
            project_ids=["project_1"],
            order_by="score",
            order_desc=True,
            select_columns=["id", "content"],
        )
        assert spec.table == "document_chunks"
        assert spec.filters is not None
        assert len(spec.vector) == 384

    def test_table_required(self):
        """Test table is required."""
        with pytest.raises(ValueError, match="requires 'table'"):
            QuerySpec(table="")

    def test_limit_must_be_positive(self):
        """Test limit must be positive."""
        with pytest.raises(ValueError, match="must be positive"):
            QuerySpec(table="t", limit=0)

    def test_offset_must_be_non_negative(self):
        """Test offset must be non-negative."""
        with pytest.raises(ValueError, match="must be non-negative"):
            QuerySpec(table="t", offset=-1)

    def test_select_columns_must_include_id(self):
        """Test select_columns must include 'id'."""
        with pytest.raises(ValueError, match="must include 'id'"):
            QuerySpec(table="t", select_columns=["content"])

    def test_select_columns_with_id_ok(self):
        """Test select_columns with 'id' is valid."""
        spec = QuerySpec(table="t", select_columns=["id", "content"])
        assert "id" in spec.select_columns

    def test_is_vector_search(self):
        """Test is_vector_search method."""
        no_vector = QuerySpec(table="t")
        with_vector = QuerySpec(table="t", vector=[0.1] * 384)

        assert not no_vector.is_vector_search()
        assert with_vector.is_vector_search()

    def test_is_fts_search(self):
        """Test is_fts_search method."""
        no_fts = QuerySpec(table="t")
        with_fts = QuerySpec(table="t", fts_query="search")

        assert not no_fts.is_fts_search()
        assert with_fts.is_fts_search()

    def test_is_hybrid_search(self):
        """Test is_hybrid_search method."""
        vector_only = QuerySpec(table="t", vector=[0.1] * 384)
        fts_only = QuerySpec(table="t", fts_query="search")
        hybrid = QuerySpec(table="t", vector=[0.1] * 384, fts_query="search")

        assert not vector_only.is_hybrid_search()
        assert not fts_only.is_hybrid_search()
        assert hybrid.is_hybrid_search()

    def test_is_filter_only(self):
        """Test is_filter_only method."""
        filter_only = QuerySpec(table="t", filters=eq("x", 1))
        with_search = QuerySpec(table="t", vector=[0.1] * 384)

        assert filter_only.is_filter_only()
        assert not with_search.is_filter_only()

    def test_is_cross_project(self):
        """Test is_cross_project method."""
        no_projects = QuerySpec(table="t")
        single_project = QuerySpec(table="t", project_ids=["p1"])
        multi_project = QuerySpec(table="t", project_ids=["p1", "p2"])

        assert not no_projects.is_cross_project()
        assert not single_project.is_cross_project()
        assert multi_project.is_cross_project()

    def test_with_filters(self):
        """Test with_filters method."""
        original = QuerySpec(table="t", limit=50)
        updated = original.with_filters(eq("x", 1))

        assert updated.filters is not None
        assert updated.limit == 50
        assert original.filters is None

    def test_with_pagination(self):
        """Test with_pagination method."""
        original = QuerySpec(table="t")
        updated = original.with_pagination(limit=20, offset=10)

        assert updated.limit == 20
        assert updated.offset == 10
        assert original.limit == 100

    def test_with_project_scope(self):
        """Test with_project_scope method."""
        original = QuerySpec(table="t")
        updated = original.with_project_scope(["p1", "p2"])

        assert updated.project_ids == ["p1", "p2"]
        assert original.project_ids is None
