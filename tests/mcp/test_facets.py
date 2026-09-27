"""Tests for facet generation utility."""

import pytest

pytestmark = pytest.mark.unit

from agentic_inquiry.mcp.utils.facets import (
    generate_facets,
    generate_refinement_suggestions,
)


def test_generate_facets_empty_results():
    """Test facet generation with empty results."""
    facets = generate_facets([])

    assert facets["by_type"] == {}
    assert facets["by_language"] == {}
    assert facets["by_directory"] == {}
    assert facets["common_terms"] == {}
    assert facets["total_count"] == 0


def test_generate_facets_by_type():
    """Test facet generation by type."""
    results = [
        {"type": "code", "file_path": "test.py"},
        {"type": "code", "file_path": "test2.py"},
        {"type": "doc", "file_path": "README.md"},
    ]

    facets = generate_facets(results)

    assert facets["by_type"]["code"] == 2
    assert facets["by_type"]["doc"] == 1
    assert facets["total_count"] == 3


def test_generate_facets_by_language():
    """Test facet generation by language."""
    results = [
        {
            "type": "code",
            "file_path": "test.py",
            "metadata": {"language": "python"},
        },
        {
            "type": "code",
            "file_path": "test.js",
            "metadata": {"language": "javascript"},
        },
        {
            "type": "code",
            "file_path": "test2.py",
            "metadata": {"language": "python"},
        },
    ]

    facets = generate_facets(results)

    assert facets["by_language"]["python"] == 2
    assert facets["by_language"]["javascript"] == 1


def test_generate_facets_by_directory():
    """Test facet generation by directory."""
    results = [
        {"type": "code", "file_path": "src/module1/test.py"},
        {"type": "code", "file_path": "src/module2/test.py"},
        {"type": "doc", "file_path": "docs/api.md"},
    ]

    facets = generate_facets(results)

    assert facets["by_directory"]["src"] == 2
    assert facets["by_directory"]["docs"] == 1


def test_generate_facets_common_terms():
    """Test common terms extraction."""
    results = [
        {
            "type": "code",
            "title": "Authentication Function",
            "summary": "Handles user authentication",
            "file_path": "auth.py",
        },
        {
            "type": "code",
            "title": "Authorization Check",
            "summary": "Checks user authorization",
            "file_path": "auth.py",
        },
    ]

    facets = generate_facets(results)

    # Should extract "authentication", "authorization", "user", etc.
    assert "authentication" in facets["common_terms"]
    assert "authorization" in facets["common_terms"]
    assert "user" in facets["common_terms"]

    # Should filter out stop words
    assert "the" not in facets["common_terms"]
    assert "a" not in facets["common_terms"]


def test_generate_refinement_suggestions_no_filters():
    """Test refinement suggestions with no current filters."""
    facets = {
        "by_type": {"code": 10, "doc": 5},
        "by_language": {"python": 8, "javascript": 7},
        "by_directory": {"src": 10, "tests": 5},
        "common_terms": {"function": 5, "class": 3},
        "total_count": 15,
    }

    suggestions = generate_refinement_suggestions(facets, {})

    # Should suggest filtering by type
    assert any("type" in s.lower() for s in suggestions)

    # Should suggest filtering by language
    assert any("language" in s.lower() for s in suggestions)

    # Should suggest filtering by directory
    assert any("director" in s.lower() for s in suggestions)


def test_generate_refinement_suggestions_with_filters():
    """Test refinement suggestions with existing filters."""
    facets = {
        "by_type": {"code": 10, "doc": 5},
        "by_language": {"python": 8, "javascript": 7},
        "by_directory": {"src": 10, "tests": 5},
        "common_terms": {"function": 5, "class": 3},
        "total_count": 15,
    }

    # Already filtered by type
    suggestions = generate_refinement_suggestions(facets, {"type": "code"})

    # Should not suggest filtering by type again
    type_suggestions = [s for s in suggestions if "type" in s.lower()]
    assert len(type_suggestions) == 0

    # Should still suggest other filters
    assert any("language" in s.lower() for s in suggestions)


def test_generate_facets_language_from_extension():
    """Test language detection from file extension."""
    results = [
        {"type": "code", "file_path": "test.py", "metadata": {}},
        {"type": "code", "file_path": "test.js", "metadata": {}},
        {"type": "code", "file_path": "test.ts", "metadata": {}},
    ]

    facets = generate_facets(results)

    # Should detect languages from extensions
    assert "py" in facets["by_language"]
    assert "js" in facets["by_language"]
    assert "ts" in facets["by_language"]
