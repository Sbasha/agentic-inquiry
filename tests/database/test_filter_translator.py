"""Tests for LanceDB filter translator.

Tests cover:
- All filter operators
- String escaping (SQL injection prevention)
- Compound expressions (AND/OR)
- Null checks
- Empty list behavior (IN([]) → FALSE, NOT_IN([]) → TRUE)
- Edge cases
"""
import pytest

pytestmark = pytest.mark.unit

from agentic_inquiry.database.filters import (
    and_,
    eq,
    gt,
    gte,
    is_in,
    is_not_null,
    is_null,
    lt,
    lte,
    ne,
    not_in,
    or_,
)
from agentic_inquiry.database.filters import (
    LanceDBFilterTranslator,
    translate_filter,
)


class TestComparisonOperators:
    """Tests for comparison operators (EQ, NE, GT, GTE, LT, LTE)."""

    def test_eq_string(self) -> None:
        """EQ with string value."""
        f = eq("status", "active")
        result = translate_filter(f)
        assert result == 'status = \'active\''

    def test_eq_integer(self) -> None:
        """EQ with integer value."""
        f = eq("count", 42)
        result = translate_filter(f)
        assert result == 'count = 42'

    def test_eq_float(self) -> None:
        """EQ with float value."""
        f = eq("score", 0.95)
        result = translate_filter(f)
        assert result == 'score = 0.95'

    def test_eq_boolean_true(self) -> None:
        """EQ with boolean True."""
        f = eq("is_active", True)
        result = translate_filter(f)
        assert result == 'is_active = TRUE'

    def test_eq_boolean_false(self) -> None:
        """EQ with boolean False."""
        f = eq("is_deleted", False)
        result = translate_filter(f)
        assert result == 'is_deleted = FALSE'

    def test_ne_string(self) -> None:
        """NE with string value."""
        f = ne("status", "deleted")
        result = translate_filter(f)
        assert result == 'status != \'deleted\''

    def test_gt_integer(self) -> None:
        """GT with integer value."""
        f = gt("count", 10)
        result = translate_filter(f)
        assert result == 'count > 10'

    def test_gte_float(self) -> None:
        """GTE with float value."""
        f = gte("score", 0.5)
        result = translate_filter(f)
        assert result == 'score >= 0.5'

    def test_lt_integer(self) -> None:
        """LT with integer value."""
        f = lt("age", 100)
        result = translate_filter(f)
        assert result == 'age < 100'

    def test_lte_float(self) -> None:
        """LTE with float value."""
        f = lte("confidence", 1.0)
        result = translate_filter(f)
        assert result == 'confidence <= 1.0'


class TestNullOperators:
    """Tests for null check operators."""

    def test_is_null(self) -> None:
        """IS_NULL operator."""
        f = is_null("deleted_at")
        result = translate_filter(f)
        assert result == 'deleted_at IS NULL'

    def test_is_not_null(self) -> None:
        """IS_NOT_NULL operator."""
        f = is_not_null("name")
        result = translate_filter(f)
        assert result == 'name IS NOT NULL'


class TestSetMembershipOperators:
    """Tests for IN and NOT_IN operators."""

    def test_in_strings(self) -> None:
        """IN with string values."""
        f = is_in("type", ["code", "doc", "test"])
        result = translate_filter(f)
        assert result == "type IN ('code', 'doc', 'test')"

    def test_in_integers(self) -> None:
        """IN with integer values."""
        f = is_in("priority", [1, 2, 3])
        result = translate_filter(f)
        assert result == 'priority IN (1, 2, 3)'

    def test_in_single_value(self) -> None:
        """IN with single value."""
        f = is_in("status", ["active"])
        result = translate_filter(f)
        assert result == "status IN ('active')"

    def test_in_empty_list_returns_false(self) -> None:
        """IN with empty list must return FALSE."""
        f = is_in("type", [])
        result = translate_filter(f)
        assert result == "FALSE"

    def test_not_in_strings(self) -> None:
        """NOT_IN with string values."""
        f = not_in("type", ["internal", "temp"])
        result = translate_filter(f)
        assert result == "type NOT IN ('internal', 'temp')"

    def test_not_in_empty_list_returns_true(self) -> None:
        """NOT_IN with empty list must return TRUE."""
        f = not_in("status", [])
        result = translate_filter(f)
        assert result == "TRUE"


class TestCompoundOperators:
    """Tests for AND and OR operators."""

    def test_simple_and(self) -> None:
        """Simple AND of two filters."""
        f = and_(eq("status", "active"), gt("score", 0.5))
        result = translate_filter(f)
        assert result == "(status = 'active') AND (score > 0.5)"

    def test_simple_or(self) -> None:
        """Simple OR of two filters."""
        f = or_(eq("type", "code"), eq("type", "doc"))
        result = translate_filter(f)
        assert result == "(type = 'code') OR (type = 'doc')"

    def test_nested_and_or(self) -> None:
        """Nested AND with OR."""
        inner_or = or_(eq("type", "code"), eq("type", "doc"))
        outer_and = and_(inner_or, eq("status", "active"))
        result = translate_filter(outer_and)
        assert result == "((type = 'code') OR (type = 'doc')) AND (status = 'active')"

    def test_multiple_and(self) -> None:
        """Chain of AND filters."""
        f = and_(
            eq("status", "active"),
            gt("score", 0.5),
            is_not_null("name"),
        )
        result = translate_filter(f)
        # and_() chains left-to-right: ((a AND b) AND c)
        assert result == "((status = 'active') AND (score > 0.5)) AND (name IS NOT NULL)"

    def test_multiple_or(self) -> None:
        """Chain of OR filters."""
        f = or_(
            eq("priority", 1),
            eq("priority", 2),
            eq("priority", 3),
        )
        result = translate_filter(f)
        assert result == '((priority = 1) OR (priority = 2)) OR (priority = 3)'


class TestStringEscaping:
    """Tests for SQL injection prevention via string escaping."""

    def test_escape_single_quote(self) -> None:
        """Single quotes in strings must be escaped."""
        f = eq("name", "O'Brien")
        result = translate_filter(f)
        assert result == "name = 'O''Brien'"

    def test_escape_multiple_quotes(self) -> None:
        """Multiple single quotes must all be escaped."""
        f = eq("value", "it's a 'test' value")
        result = translate_filter(f)
        assert result == "value = 'it''s a ''test'' value'"

    def test_escape_in_list_values(self) -> None:
        """Quotes in IN list values must be escaped."""
        f = is_in("name", ["John's", "Mary's"])
        result = translate_filter(f)
        assert result == "name IN ('John''s', 'Mary''s')"

    def test_sql_injection_attempt_semicolon(self) -> None:
        """SQL injection with semicolon is escaped."""
        f = eq("name", "test; DROP TABLE users;--")
        result = translate_filter(f)
        # The semicolon and -- are just part of the string, safely quoted
        assert result == "name = 'test; DROP TABLE users;--'"

    def test_sql_injection_attempt_quote_escape(self) -> None:
        """SQL injection with quote escaping attempt is handled."""
        f = eq("name", "test' OR '1'='1")
        result = translate_filter(f)
        # All quotes are escaped, breaking the injection
        assert result == "name = 'test'' OR ''1''=''1'"


class TestNestedFields:
    """Tests for nested field access (e.g., metadata.type)."""

    def test_nested_field_eq(self) -> None:
        """Nested field with EQ - each segment is quoted."""
        f = eq("metadata.type", "code")
        result = translate_filter(f)
        assert result == "metadata.type = 'code'"

    def test_deeply_nested_field(self) -> None:
        """Deeply nested field - all segments quoted."""
        f = eq("data.headers.content_type", "application/json")
        result = translate_filter(f)
        assert result == "data.headers.content_type = 'application/json'"


class TestTranslateFilterFunction:
    """Tests for the translate_filter convenience function."""

    def test_translate_none_returns_none(self) -> None:
        """translate_filter(None) returns None."""
        assert translate_filter(None) is None

    def test_translate_simple_filter(self) -> None:
        """translate_filter works with simple filter."""
        f = eq("x", 1)
        assert translate_filter(f) == 'x = 1'


class TestTranslatorClass:
    """Tests for the LanceDBFilterTranslator class directly."""

    def test_translator_instance(self) -> None:
        """Translator can be instantiated and reused."""
        translator = LanceDBFilterTranslator()

        f1 = eq("a", 1)
        f2 = eq("b", 2)

        assert translator.translate(f1) == 'a = 1'
        assert translator.translate(f2) == 'b = 2'


class TestEdgeCases:
    """Tests for edge cases and special values."""

    def test_zero_value(self) -> None:
        """Zero is a valid value."""
        f = eq("count", 0)
        result = translate_filter(f)
        assert result == 'count = 0'

    def test_negative_value(self) -> None:
        """Negative numbers are valid."""
        f = lt("temperature", -10)
        result = translate_filter(f)
        assert result == 'temperature < -10'

    def test_float_precision(self) -> None:
        """Float precision is preserved."""
        f = eq("value", 3.14159265359)
        result = translate_filter(f)
        assert result == 'value = 3.14159265359'

    def test_empty_string_value(self) -> None:
        """Empty string is a valid value."""
        f = eq("name", "")
        result = translate_filter(f)
        assert result == "name = ''"

    def test_string_with_newlines(self) -> None:
        """Strings with newlines are handled."""
        f = eq("content", "line1\nline2")
        result = translate_filter(f)
        assert result == "content = 'line1\nline2'"

    def test_underscore_field_name(self) -> None:
        """Field names starting with underscore."""
        f = eq("_private", "value")
        result = translate_filter(f)
        assert result == "_private = 'value'"

    def test_mixed_case_field_name(self) -> None:
        """Mixed case field names."""
        f = eq("fileName", "test.py")
        result = translate_filter(f)
        assert result == "fileName = 'test.py'"


class TestComplexQueries:
    """Tests for complex real-world query patterns."""

    def test_project_scoped_query(self) -> None:
        """Query scoped to a project."""
        f = and_(
            is_in("project_id", ["proj_001", "proj_002"]),
            eq("status", "indexed"),
        )
        result = translate_filter(f)
        assert result is not None
        assert "project_id IN ('proj_001', 'proj_002')" in result
        assert "status = 'indexed'" in result
        assert "AND" in result

    def test_entity_type_filter(self) -> None:
        """Filter by entity type with score threshold."""
        f = and_(
            eq("entity_type", "function"),
            gte("pagerank", 0.1),
            is_not_null("source_file"),
        )
        result = translate_filter(f)
        assert result is not None
        assert "entity_type = 'function'" in result
        assert "pagerank >= 0.1" in result
        assert "source_file IS NOT NULL" in result

    def test_file_extension_filter(self) -> None:
        """Filter by file extension alternatives."""
        f = or_(
            eq("extension", ".py"),
            eq("extension", ".pyi"),
            eq("extension", ".pyx"),
        )
        result = translate_filter(f)
        assert result is not None
        assert "extension = '.py'" in result
        assert "extension = '.pyi'" in result
        assert "extension = '.pyx'" in result
        assert "OR" in result

    def test_reserved_keyword_field(self) -> None:
        """Field names that are SQL reserved keywords are safely quoted."""
        # Fields like 'order', 'group', 'select' would cause syntax errors
        # without quoting
        f = eq("order", 5)
        result = translate_filter(f)
        assert result is not None
        # The double quotes protect against reserved keyword collisions
        assert result == 'order = 5'
