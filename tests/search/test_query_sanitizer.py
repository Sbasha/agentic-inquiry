"""Unit tests for QuerySanitizer."""

import pytest

pytestmark = pytest.mark.unit

from agentic_inquiry.search.query_sanitizer import QuerySanitizer


class TestQuerySanitizer:
    """Test QuerySanitizer functionality."""

    def test_sanitize_question_mark(self):
        """Test escaping question marks."""
        sanitizer = QuerySanitizer()

        # Single question mark
        assert sanitizer.sanitize("What is this?") == "What is this\\?"

        # Multiple question marks
        assert sanitizer.sanitize("What? Why? How?") == "What\\? Why\\? How\\?"

        # Question mark in middle
        assert sanitizer.sanitize("Is this? a test") == "Is this\\? a test"

    def test_sanitize_asterisk(self):
        """Test escaping asterisks."""
        sanitizer = QuerySanitizer()

        # Single asterisk
        assert sanitizer.sanitize("file*.py") == "file\\*\\.py"

        # Multiple asterisks
        assert sanitizer.sanitize("**/*.py") == "\\*\\*/\\*\\.py"

        # Asterisk in middle
        assert sanitizer.sanitize("test*file") == "test\\*file"

    def test_sanitize_brackets(self):
        """Test escaping brackets."""
        sanitizer = QuerySanitizer()

        # Square brackets
        assert sanitizer.sanitize("test[123]") == "test\\[123\\]"

        # Curly braces
        assert sanitizer.sanitize("test{abc}") == "test\\{abc\\}"

        # Parentheses
        assert sanitizer.sanitize("test(xyz)") == "test\\(xyz\\)"

    def test_sanitize_backslash(self):
        """Test escaping backslashes."""
        sanitizer = QuerySanitizer()

        # Single backslash
        assert sanitizer.sanitize("path\\to\\file") == "path\\\\to\\\\file"

        # Backslash with other special chars
        assert sanitizer.sanitize("\\?") == "\\\\\\?"

    def test_sanitize_regex_chars(self):
        """Test escaping regex special characters."""
        sanitizer = QuerySanitizer()

        # Plus sign
        assert sanitizer.sanitize("C++") == "C\\+\\+"

        # Dot
        assert sanitizer.sanitize("file.py") == "file\\.py"

        # Caret
        assert sanitizer.sanitize("^start") == "\\^start"

        # Dollar sign
        assert sanitizer.sanitize("end$") == "end\\$"

        # Pipe
        assert sanitizer.sanitize("a|b") == "a\\|b"

    def test_sanitize_empty_query(self):
        """Test handling empty queries."""
        sanitizer = QuerySanitizer()

        assert sanitizer.sanitize("") == ""
        assert sanitizer.sanitize(None) is None

    def test_sanitize_no_special_chars(self):
        """Test queries without special characters."""
        sanitizer = QuerySanitizer()

        # Simple query
        query = "simple query"
        assert sanitizer.sanitize(query) == query

        # Query with numbers
        query = "test 123"
        assert sanitizer.sanitize(query) == query

        # Query with underscores and hyphens
        query = "test_file-name"
        assert sanitizer.sanitize(query) == query

    def test_sanitize_mixed_special_chars(self):
        """Test queries with multiple types of special characters."""
        sanitizer = QuerySanitizer()

        # Mix of question mark and asterisk
        assert sanitizer.sanitize("What is *.py?") == "What is \\*\\.py\\?"

        # Mix of brackets and parentheses
        assert sanitizer.sanitize("test[1](2)") == "test\\[1\\]\\(2\\)"

        # Complex query
        assert (
            sanitizer.sanitize("How does file*.py work?")
            == "How does file\\*\\.py work\\?"
        )

    def test_preserve_wildcards_mode(self):
        """Test wildcard preservation mode."""
        sanitizer = QuerySanitizer()

        # Asterisk preserved
        assert sanitizer.preserve_wildcards_mode("file*.py") == "file*\\.py"

        # Question mark preserved
        assert sanitizer.preserve_wildcards_mode("file?.py") == "file?\\.py"

        # Other special chars still escaped
        assert (
            sanitizer.preserve_wildcards_mode("test[123]*.py") == "test\\[123\\]*\\.py"
        )

        # Mix of wildcards and other special chars
        assert sanitizer.preserve_wildcards_mode("*.py?[abc]") == "*\\.py?\\[abc\\]"

    def test_preserve_wildcards_constructor(self):
        """Test QuerySanitizer with preserve_wildcards=True."""
        sanitizer = QuerySanitizer(preserve_wildcards=True)

        # Wildcards should not be escaped
        assert sanitizer.sanitize("file*.py") == "file*\\.py"
        assert sanitizer.sanitize("file?.py") == "file?\\.py"

        # Other special chars should still be escaped
        assert sanitizer.sanitize("test[123]") == "test\\[123\\]"

    def test_is_safe_query(self):
        """Test checking if query is safe."""
        sanitizer = QuerySanitizer()

        # Safe queries
        assert sanitizer.is_safe_query("simple query") is True
        assert sanitizer.is_safe_query("test 123") is True
        assert sanitizer.is_safe_query("") is True

        # Unsafe queries
        assert sanitizer.is_safe_query("What is this?") is False
        assert sanitizer.is_safe_query("file*.py") is False
        assert sanitizer.is_safe_query("test[123]") is False

    def test_get_sanitization_info(self):
        """Test getting detailed sanitization information."""
        sanitizer = QuerySanitizer()

        # Query with special chars
        info = sanitizer.get_sanitization_info("What is *.py?")
        assert info["original"] == "What is *.py?"
        assert info["sanitized"] == "What is \\*\\.py\\?"
        assert info["changed"] is True
        assert "?" in info["special_chars_found"]
        assert "*" in info["special_chars_found"]
        assert "." in info["special_chars_found"]
        assert info["is_safe"] is False

        # Safe query
        info = sanitizer.get_sanitization_info("simple query")
        assert info["original"] == "simple query"
        assert info["sanitized"] == "simple query"
        assert info["changed"] is False
        assert info["special_chars_found"] == []
        assert info["is_safe"] is True

        # Empty query
        info = sanitizer.get_sanitization_info("")
        assert info["original"] == ""
        assert info["sanitized"] == ""
        assert info["changed"] is False
        assert info["is_safe"] is True

    def test_real_world_queries(self):
        """Test with real-world query examples."""
        sanitizer = QuerySanitizer()

        # Natural language question
        assert sanitizer.sanitize("How do I use the API?") == "How do I use the API\\?"

        # File pattern
        assert sanitizer.sanitize("Find all *.ts files") == "Find all \\*\\.ts files"

        # Code snippet
        assert (
            sanitizer.sanitize("function test() { return true; }")
            == "function test\\(\\) \\{ return true; \\}"
        )

        # Regex pattern
        assert sanitizer.sanitize("^[a-z]+$") == "\\^\\[a-z\\]\\+\\$"

        # Path with wildcards
        assert sanitizer.sanitize("src/**/*.py") == "src/\\*\\*/\\*\\.py"

    def test_unicode_queries(self):
        """Test queries with unicode characters."""
        sanitizer = QuerySanitizer()

        # Unicode characters should not be escaped
        assert sanitizer.sanitize("测试文件") == "测试文件"
        assert sanitizer.sanitize("Тест файл") == "Тест файл"
        assert sanitizer.sanitize("テストファイル") == "テストファイル"

        # Unicode with special chars
        assert sanitizer.sanitize("测试文件?") == "测试文件\\?"

    def test_whitespace_handling(self):
        """Test handling of whitespace."""
        sanitizer = QuerySanitizer()

        # Leading/trailing whitespace preserved
        assert sanitizer.sanitize("  query  ") == "  query  "

        # Multiple spaces preserved
        assert (
            sanitizer.sanitize("query    with    spaces") == "query    with    spaces"
        )

        # Tabs and newlines preserved
        assert sanitizer.sanitize("query\twith\ttabs") == "query\twith\ttabs"
        assert sanitizer.sanitize("query\nwith\nnewlines") == "query\nwith\nnewlines"

    def test_edge_cases(self):
        """Test edge cases."""
        sanitizer = QuerySanitizer()

        # Only special characters
        assert sanitizer.sanitize("?*[]()") == "\\?\\*\\[\\]\\(\\)"

        # Repeated special characters
        assert sanitizer.sanitize("????") == "\\?\\?\\?\\?"
        assert sanitizer.sanitize("****") == "\\*\\*\\*\\*"

        # Special char at start
        assert sanitizer.sanitize("?query") == "\\?query"

        # Special char at end
        assert sanitizer.sanitize("query?") == "query\\?"

        # Adjacent special chars
        assert sanitizer.sanitize("test?*[") == "test\\?\\*\\["

    def test_performance_with_long_queries(self):
        """Test performance with long queries."""
        sanitizer = QuerySanitizer()

        # Long query without special chars (should be fast)
        long_query = "simple query " * 1000
        result = sanitizer.sanitize(long_query)
        assert result == long_query

        # Long query with special chars
        long_query_with_special = "query? " * 1000
        result = sanitizer.sanitize(long_query_with_special)
        assert result == "query\\? " * 1000


class TestQuerySanitizerIntegration:
    """Integration tests for QuerySanitizer with search scenarios."""

    def test_natural_language_questions(self):
        """Test sanitizing natural language questions."""
        sanitizer = QuerySanitizer()

        questions = [
            "What is the purpose of this function?",
            "How do I configure the database?",
            "Why does this error occur?",
            "When should I use async/await?",
            "Where is the configuration file?",
        ]

        for question in questions:
            sanitized = sanitizer.sanitize(question)
            # Should escape question marks
            assert "\\?" in sanitized
            # Should not contain unescaped question marks
            assert sanitized.count("?") == 0 or sanitized.count("\\?") > 0

    def test_code_search_patterns(self):
        """Test sanitizing code search patterns."""
        sanitizer = QuerySanitizer()

        patterns = [
            "function test()",
            "class MyClass { }",
            "import { Component } from 'react'",
            "def __init__(self):",
            "const arr = [1, 2, 3]",
        ]

        for pattern in patterns:
            sanitized = sanitizer.sanitize(pattern)
            # Should escape brackets and parentheses
            assert "(" not in sanitized or "\\(" in sanitized
            assert "[" not in sanitized or "\\[" in sanitized
            assert "{" not in sanitized or "\\{" in sanitized

    def test_file_pattern_search(self):
        """Test sanitizing file pattern searches."""
        sanitizer = QuerySanitizer()

        # With wildcard escaping (default)
        assert sanitizer.sanitize("*.py") == "\\*\\.py"
        assert sanitizer.sanitize("test_*.py") == "test_\\*\\.py"
        assert sanitizer.sanitize("**/*.ts") == "\\*\\*/\\*\\.ts"

        # With wildcard preservation
        assert sanitizer.preserve_wildcards_mode("*.py") == "*\\.py"
        assert sanitizer.preserve_wildcards_mode("test_*.py") == "test_*\\.py"
        assert sanitizer.preserve_wildcards_mode("**/*.ts") == "**/*\\.ts"
