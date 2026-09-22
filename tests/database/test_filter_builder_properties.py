"""Property-based tests for FilterBuilder.

**Feature: claude-review-improvements**

These tests verify that FilterBuilder properly escapes and validates inputs
to prevent injection vulnerabilities in database queries.
"""

import pytest

pytestmark = pytest.mark.unit

from typing import List, Any
from hypothesis import given, settings, strategies as st

# FilterBuilder from consolidated filters package
try:
    from agentic_inquiry.database.filters import FilterBuilder
except ImportError:
    FilterBuilder: Any = None


# Strategy for generating potentially malicious strings
malicious_strings = st.one_of(
    # SQL injection attempts
    st.just("'; DROP TABLE documents; --"),
    st.just("' OR '1'='1"),
    st.just("'; DELETE FROM chunks WHERE '1'='1"),
    st.just("' UNION SELECT * FROM users --"),
    # Special characters that need escaping
    st.just("test'value"),
    st.just('test"value'),
    st.just("test\\value"),
    st.just("test\nvalue"),
    st.just("test\rvalue"),
    st.just("test\tvalue"),
    st.just("test\x00value"),
    # Unicode and special characters
    st.just("test\u0000value"),
    st.just("test\u2028value"),
    st.just("test\u2029value"),
    # Nested quotes
    st.just("test'\"value\"'"),
    st.just('test"\'value\'"'),
    # Backslash escaping
    st.just("test\\\\value"),
    st.just("test\\'value"),
    # Empty and whitespace
    st.just(""),
    st.just("   "),
    st.just("\n\t\r"),
)


# Strategy for generating valid doc IDs (mix of safe and potentially dangerous)
doc_id_strategy = st.one_of(
    st.text(min_size=1, max_size=100),  # Random text
    malicious_strings,  # Potentially malicious strings
    st.from_regex(r"[a-zA-Z0-9_-]{1,50}", fullmatch=True),  # Safe IDs
)


# Strategy for generating lists of doc IDs
doc_ids_list_strategy = st.lists(
    doc_id_strategy,
    min_size=1,
    max_size=20,
)


# Strategy for generating project IDs (excluding empty strings)
project_id_strategy = st.one_of(
    st.text(min_size=1, max_size=100),
    malicious_strings.filter(lambda x: len(x) > 0),  # Exclude empty strings
    st.from_regex(r"[a-zA-Z0-9_-]{1,50}", fullmatch=True),
)


# **Feature: claude-review-improvements, Property 12: Filter input validation**
# **Validates: Requirements 6.2**
@pytest.mark.unit
@pytest.mark.skipif(FilterBuilder is None, reason="FilterBuilder not yet implemented")
@settings(max_examples=100, deadline=None)
@given(doc_ids=doc_ids_list_strategy)
def test_property_filter_builder_escapes_doc_ids(doc_ids: List[str]):
    """Property: For any list of doc IDs, FilterBuilder should escape them safely.
    
    This property verifies that FilterBuilder properly escapes special characters
    in document IDs to prevent injection attacks. Single quotes should be doubled
    (SQL standard escaping).
    
    **Feature: claude-review-improvements, Property 12: Filter input validation**
    **Validates: Requirements 6.2**
    
    Args:
        doc_ids: List of document IDs (may contain malicious strings)
    """
    builder = FilterBuilder()
    builder.add_doc_id_filter(doc_ids)
    filter_expr = builder.build()
    
    # The filter expression should be a string
    assert isinstance(filter_expr, str), "Filter expression must be a string"

    # The filter should not be empty if we have doc IDs
    assert len(filter_expr) > 0, "Filter expression should not be empty"
    # Verify filter contains expected structure (field name and operator)
    assert "doc_id" in filter_expr or "IN" in filter_expr.upper(), \
        f"Filter should reference doc_id field, got: {filter_expr}"
    
    # Verify that all single quotes in doc_ids are properly escaped (doubled)
    for doc_id in doc_ids:
        if "'" in doc_id:
            # The escaped version should have doubled quotes
            escaped = doc_id.replace("'", "''")
            assert escaped in filter_expr, (
                f"Doc ID '{doc_id}' not properly escaped in filter"
            )
    
    # Verify the filter is properly quoted
    # All values should be wrapped in single quotes
    assert filter_expr.count("'") % 2 == 0, "Filter should have balanced quotes"


@pytest.mark.unit
@pytest.mark.skipif(FilterBuilder is None, reason="FilterBuilder not yet implemented")
@settings(max_examples=100, deadline=None)
@given(project_id=project_id_strategy)
def test_property_filter_builder_escapes_project_id(project_id: str):
    """Property: For any project ID, FilterBuilder should escape it safely.
    
    This property verifies that FilterBuilder properly escapes special characters
    in project IDs to prevent injection attacks. Single quotes should be doubled.
    
    **Feature: claude-review-improvements, Property 12: Filter input validation**
    **Validates: Requirements 6.2**
    
    Args:
        project_id: Project ID (may contain malicious strings)
    """
    builder = FilterBuilder()
    builder.add_project_filter(project_id)
    filter_expr = builder.build()
    
    # The filter expression should be a string
    assert isinstance(filter_expr, str), "Filter expression must be a string"

    # The filter should not be empty
    assert len(filter_expr) > 0, "Filter expression should not be empty"
    # Verify filter contains expected structure (field name and operator)
    assert "project_id" in filter_expr or "=" in filter_expr, \
        f"Filter should reference project_id field, got: {filter_expr}"

    # Verify that single quotes are properly escaped (doubled)
    if "'" in project_id:
        escaped = project_id.replace("'", "''")
        assert escaped in filter_expr, (
            f"Project ID '{project_id}' not properly escaped in filter"
        )
    
    # Verify the filter is properly quoted
    assert filter_expr.count("'") % 2 == 0, "Filter should have balanced quotes"


@pytest.mark.unit
@pytest.mark.skipif(FilterBuilder is None, reason="FilterBuilder not yet implemented")
@settings(max_examples=100, deadline=None)
@given(
    doc_ids=doc_ids_list_strategy,
    project_id=project_id_strategy,
)
def test_property_filter_builder_combines_filters_safely(
    doc_ids: List[str],
    project_id: str,
):
    """Property: For any combination of filters, FilterBuilder should combine them safely.
    
    This property verifies that when multiple filters are combined, the resulting
    expression is still safe and properly escaped.
    
    **Feature: claude-review-improvements, Property 12: Filter input validation**
    **Validates: Requirements 6.2**
    
    Args:
        doc_ids: List of document IDs
        project_id: Project ID
    """
    # Skip if project_id is empty (validation will reject it)
    if not project_id:
        return
    
    builder = FilterBuilder()
    builder.add_doc_id_filter(doc_ids)
    builder.add_project_filter(project_id)
    filter_expr = builder.build()
    
    # The filter expression should be a string
    assert isinstance(filter_expr, str), "Filter expression must be a string"

    # The filter should not be empty
    assert len(filter_expr) > 0, "Filter expression should not be empty"
    # Verify filter contains both doc_id and project_id filters
    assert "doc_id" in filter_expr or "IN" in filter_expr.upper(), \
        f"Combined filter should reference doc_id, got: {filter_expr}"
    assert "project_id" in filter_expr or "AND" in filter_expr.upper(), \
        f"Combined filter should reference project_id, got: {filter_expr}"

    # Verify all single quotes are properly escaped
    for doc_id in doc_ids:
        if "'" in doc_id:
            escaped = doc_id.replace("'", "''")
            assert escaped in filter_expr
    
    if "'" in project_id:
        escaped = project_id.replace("'", "''")
        assert escaped in filter_expr
    
    # Verify the filter has balanced quotes
    assert filter_expr.count("'") % 2 == 0, "Filter should have balanced quotes"


@pytest.mark.unit
@pytest.mark.skipif(FilterBuilder is None, reason="FilterBuilder not yet implemented")
def test_filter_builder_validates_input_types():
    """Test that FilterBuilder validates input types.
    
    This test verifies that FilterBuilder rejects invalid input types
    with clear error messages.
    
    **Feature: claude-review-improvements, Property 12: Filter input validation**
    **Validates: Requirements 6.2**
    """
    builder = FilterBuilder()
    
    # add_doc_id_filter accepts both string and list, so this should work
    builder.add_doc_id_filter("single_doc")
    assert "doc_id = 'single_doc'" in builder.build()
    
    # Reset for next test
    builder.reset()
    
    # Should reject non-string items in doc_ids list
    with pytest.raises(ValueError):
        builder.add_doc_id_filter([123, 456])  # type: ignore
    
    # Should reject non-string project_id
    with pytest.raises(ValueError):
        builder.add_project_filter(123)  # type: ignore
    
    # Should reject None for project_id
    with pytest.raises(ValueError):
        builder.add_project_filter(None)  # type: ignore


@pytest.mark.unit
@pytest.mark.skipif(FilterBuilder is None, reason="FilterBuilder not yet implemented")
def test_filter_builder_handles_empty_inputs():
    """Test that FilterBuilder handles empty inputs appropriately.
    
    This test verifies that FilterBuilder handles edge cases like empty lists
    and empty strings in a safe manner.
    
    **Feature: claude-review-improvements, Property 12: Filter input validation**
    **Validates: Requirements 6.2**
    """
    builder = FilterBuilder()
    
    # Empty doc_ids list should either raise an error or return a valid filter
    try:
        builder.add_doc_id_filter([])
        filter_expr = builder.build()
        # If it doesn't raise, it should return a valid string
        assert isinstance(filter_expr, str)
    except ValueError:
        # It's acceptable to reject empty lists
        pass
    
    # Empty string in doc_ids should be handled
    builder2 = FilterBuilder()
    try:
        builder2.add_doc_id_filter([""])
        filter_expr = builder2.build()
        assert isinstance(filter_expr, str)
    except ValueError:
        # It's acceptable to reject empty strings
        pass


@pytest.mark.unit
@pytest.mark.skipif(FilterBuilder is None, reason="FilterBuilder not yet implemented")
@settings(max_examples=100, deadline=None)
@given(doc_ids=doc_ids_list_strategy)
def test_property_filter_builder_idempotent(doc_ids: List[str]):
    """Property: Building the same filter twice should produce the same result.
    
    This property verifies that FilterBuilder is deterministic and produces
    consistent results for the same inputs.
    
    **Feature: claude-review-improvements, Property 12: Filter input validation**
    **Validates: Requirements 6.2**
    
    Args:
        doc_ids: List of document IDs
    """
    builder1 = FilterBuilder()
    builder1.add_doc_id_filter(doc_ids)
    filter1 = builder1.build()
    
    builder2 = FilterBuilder()
    builder2.add_doc_id_filter(doc_ids)
    filter2 = builder2.build()
    
    # Same inputs should produce same output
    assert filter1 == filter2, (
        "FilterBuilder should produce consistent results for same inputs"
    )


@pytest.mark.unit
@pytest.mark.skipif(FilterBuilder is None, reason="FilterBuilder not yet implemented")
def test_filter_builder_no_string_formatting():
    """Test that FilterBuilder doesn't use dangerous string formatting.
    
    This test verifies that the filter expression doesn't contain patterns
    that suggest unsafe string formatting was used.
    
    **Feature: claude-review-improvements, Property 12: Filter input validation**
    **Validates: Requirements 6.2**
    """
    # Test with a value that would break string formatting
    dangerous_value = "test%s%d%f"
    
    builder = FilterBuilder()
    builder.add_doc_id_filter([dangerous_value])
    filter_expr = builder.build()
    
    # The dangerous value should be escaped, not interpreted as format string
    # If string formatting was used, this would likely cause an error or
    # produce unexpected output
    assert isinstance(filter_expr, str)
    assert len(filter_expr) > 0
    # Verify the dangerous value appears literally in the filter (not interpreted)
    assert dangerous_value in filter_expr or dangerous_value.replace("'", "''") in filter_expr, \
        f"Filter should contain literal value '{dangerous_value}', got: {filter_expr}"
