"""Unit tests for backend-agnostic filter translator adapters.

Covers the contract in :mod:`agentic_inquiry.database.filters.protocol` and
the concrete adapters. The parametrized-SQL output for the Postgres
adapter is the main new surface — these tests pin the shape (fragment,
params, next_index) and guarantee injection-safe field handling.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from agentic_inquiry.database.filters import (
    LanceDBFilterAdapter,
    MemoryFilterAdapter,
    and_,
    eq,
    gt,
    is_in,
    is_not_null,
    is_null,
    lt,
    ne,
    normalize_to_ast,
    not_in,
    or_,
)


# ---------------------------------------------------------------------------
# normalize_to_ast
# ---------------------------------------------------------------------------


class TestNormalizeToAST:
    def test_none_returns_none(self):
        assert normalize_to_ast(None) is None

    def test_empty_dict_returns_none(self):
        assert normalize_to_ast({}) is None

    def test_filter_passthrough(self):
        f = eq("x", 1)
        assert normalize_to_ast(f) is f

    def test_simple_equality(self):
        ast = normalize_to_ast({"status": "active"})
        assert ast == eq("status", "active")

    def test_multi_field_becomes_and(self):
        ast = normalize_to_ast({"status": "active", "type": "code"})
        assert ast == and_(eq("status", "active"), eq("type", "code"))

    def test_tuple_operator(self):
        assert normalize_to_ast({"score": (">", 0.5)}) == gt("score", 0.5)
        assert normalize_to_ast({"score": (">=", 0.5)}) == (
            __import__(
                "agentic_inquiry.database.filters",
                fromlist=["gte"],
            ).gte("score", 0.5)
        )

    def test_list_value_becomes_in(self):
        assert normalize_to_ast({"type": ["a", "b"]}) == is_in("type", ["a", "b"])

    def test_explicit_in_tuple(self):
        ast = normalize_to_ast({"type": ("IN", ["a", "b"])})
        assert ast == is_in("type", ["a", "b"])

    def test_not_in_tuple(self):
        ast = normalize_to_ast({"type": ("NOT IN", ["a"])})
        assert ast == not_in("type", ["a"])

    def test_none_value_becomes_is_null(self):
        assert normalize_to_ast({"deleted_at": None}) == is_null("deleted_at")

    def test_or_compound(self):
        ast = normalize_to_ast({"OR": [{"a": 1}, {"b": 2}]})
        assert ast == or_(eq("a", 1), eq("b", 2))

    def test_not_wraps_via_demorgan(self):
        # NOT(a=1 AND b=2) → a!=1 OR b!=2
        ast = normalize_to_ast({"NOT": {"a": 1, "b": 2}})
        assert ast == or_(ne("a", 1), ne("b", 2))

    def test_invalid_field_rejected(self):
        # Guards against injection via dict field names.
        with pytest.raises(ValueError):
            normalize_to_ast({"a; DROP TABLE users--": 1})

    def test_invalid_operator_rejected(self):
        with pytest.raises(ValueError):
            normalize_to_ast({"x": ("REGEX", "^foo$")})


# ---------------------------------------------------------------------------
# LanceDBFilterAdapter
# ---------------------------------------------------------------------------


class TestLanceDBFilterAdapter:
    def test_none_passthrough(self):
        assert LanceDBFilterAdapter().translate(None) is None

    def test_empty_dict_passthrough(self):
        assert LanceDBFilterAdapter().translate({}) is None

    def test_dict_to_sql(self):
        expr = LanceDBFilterAdapter().translate({"status": "active"})
        assert expr is not None
        assert "status = 'active'" in expr

    def test_ast_to_sql(self):
        expr = LanceDBFilterAdapter().translate(and_(eq("a", 1), gt("b", 2)))
        assert expr is not None
        # Existing translator uses parentheses for compound expressions.
        assert "a = 1" in expr
        assert "b > 2" in expr

    def test_crafted_tuple_operator_rejected(self):
        """Dict translation routes through the AST so operators come from
        the whitelisted :class:`FilterOperator` enum. Before this fix, a
        crafted tuple operator was interpolated verbatim into SQL.
        """
        with pytest.raises(ValueError):
            LanceDBFilterAdapter().translate(
                {"status": ("= 1) OR TRUE --", "active")}
            )



# ---------------------------------------------------------------------------
# MemoryFilterAdapter
# ---------------------------------------------------------------------------


class TestMemoryFilterAdapter:
    def test_none_returns_none(self):
        assert MemoryFilterAdapter().translate(None) is None

    def test_equality(self):
        pred = MemoryFilterAdapter().translate({"status": "active"})
        assert pred is not None
        assert pred({"status": "active"}) is True
        assert pred({"status": "inactive"}) is False
        assert pred({}) is False

    def test_in_and_not_in(self):
        in_pred = MemoryFilterAdapter().translate({"type": ("IN", ["a", "b"])})
        not_pred = MemoryFilterAdapter().translate({"type": ("NOT IN", ["a"])})
        assert in_pred is not None and not_pred is not None
        assert in_pred({"type": "a"}) is True
        assert in_pred({"type": "c"}) is False
        assert not_pred({"type": "a"}) is False
        assert not_pred({"type": "c"}) is True

    def test_in_empty_never_matches(self):
        pred = MemoryFilterAdapter().translate({"type": ("IN", [])})
        assert pred is not None
        assert pred({"type": "anything"}) is False

    def test_comparison(self):
        pred = MemoryFilterAdapter().translate({"score": (">=", 0.5)})
        assert pred is not None
        assert pred({"score": 0.9}) is True
        assert pred({"score": 0.5}) is True
        assert pred({"score": 0.1}) is False

    def test_is_null(self):
        pred = MemoryFilterAdapter().translate({"deleted_at": None})
        assert pred is not None
        assert pred({"deleted_at": None}) is True
        assert pred({}) is True  # missing field == None
        assert pred({"deleted_at": "2026-01-01"}) is False

    def test_or(self):
        pred = MemoryFilterAdapter().translate(
            or_(eq("x", 1), eq("x", 2))
        )
        assert pred is not None
        assert pred({"x": 1}) is True
        assert pred({"x": 2}) is True
        assert pred({"x": 3}) is False

    def test_nested_field(self):
        pred = MemoryFilterAdapter().translate({"metadata.type": "code"})
        assert pred is not None
        assert pred({"metadata": {"type": "code"}}) is True
        assert pred({"metadata": {"type": "doc"}}) is False
        assert pred({"metadata": None}) is False

    def test_comparison_with_incomparable_types_is_false(self):
        # String vs int — falls back to False rather than raising.
        pred = MemoryFilterAdapter().translate(lt("x", 5))
        assert pred is not None
        assert pred({"x": "not-a-number"}) is False

    def test_like_pattern(self):
        pred = MemoryFilterAdapter().translate({"name": ("LIKE", "foo%")})
        assert pred is not None
        assert pred({"name": "foobar"}) is True
        assert pred({"name": "barfoo"}) is False

    def test_ilike_is_case_insensitive(self):
        pred = MemoryFilterAdapter().translate({"name": ("ILIKE", "%SEARCH%")})
        assert pred is not None
        assert pred({"name": "my search term"}) is True
        assert pred({"name": "SEARCH"}) is True
        assert pred({"name": "nomatch"}) is False

    def test_like_underscore_single_char(self):
        pred = MemoryFilterAdapter().translate({"code": ("LIKE", "A_C")})
        assert pred is not None
        assert pred({"code": "ABC"}) is True
        assert pred({"code": "AxC"}) is True
        assert pred({"code": "ABBC"}) is False


class TestMemoryIncomparableLogging:
    """``_lt`` / ``_le`` swallow ``TypeError`` to keep filter evaluation
    running on schema-mismatched rows, but they should emit a debug log so
    the mismatch is diagnosable."""

    def test_lt_logs_on_type_mismatch(self, caplog):
        import logging

        caplog.set_level(logging.DEBUG, logger="agentic_inquiry.database.filters.memory_adapter")
        pred = MemoryFilterAdapter().translate(lt("x", 5))
        assert pred is not None
        assert pred({"x": "not-a-number"}) is False
        assert any(
            "Incomparable operand types" in record.message
            for record in caplog.records
        )


class TestLanceDBProjectIDEscaping:
    """Regression: LanceDB ``count_records`` used to hand-interpolate
    ``project_id = '{project_id}'`` into the WHERE expression. A value
    containing a single quote would break the query (or be injectable).
    After the fix it routes through ``and_(eq("project_id", ...), ...)``
    which the LanceDB AST translator escapes single quotes on.
    """

    def test_single_quote_in_project_id_is_escaped(self):
        from agentic_inquiry.database.filters import and_ as _and_
        from agentic_inquiry.database.filters import eq as _eq
        from agentic_inquiry.database.filters import translate_filter

        combined = _and_(_eq("project_id", "alice's-proj"), _eq("x", 1))
        expr = translate_filter(combined)
        # Escaped (doubled) single quote; no unescaped apostrophe breaking
        # the quoted literal.
        assert "'alice''s-proj'" in expr


class TestPostgresLikeILike:
    def test_like_emits_parameterized_sql(self):
        result = PostgresFilterAdapter().translate({"name": ("LIKE", "foo%")})
        assert result is not None
        assert result.where_sql == "AND name LIKE $1"
        assert result.params == ["foo%"]

    def test_ilike_emits_parameterized_sql(self):
        result = PostgresFilterAdapter().translate({"name": ("ILIKE", "%bar%")})
        assert result is not None
        assert result.where_sql == "AND name ILIKE $1"
        assert result.params == ["%bar%"]
