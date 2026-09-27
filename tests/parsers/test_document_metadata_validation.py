"""
Property-based tests for DocumentParser metadata type validation.

Tests that metadata validation correctly filters out complex types
and only allows simple types (str, int, float, bool, None) as required
by LanceDB schema constraints.
"""

import pytest

pytestmark = pytest.mark.unit

from hypothesis import given, settings
import hypothesis.strategies as st
from typing import Any, Dict

from agentic_inquiry.parsers.implementations.document import (
    DocumentParser,
    ALLOWED_METADATA_TYPES,
)


# Strategy for generating simple types (allowed)
simple_values = st.one_of(
    st.text(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
    st.none(),
)

# Strategy for generating complex types (not allowed)
complex_values = st.one_of(
    st.lists(st.integers()),
    st.dictionaries(st.text(), st.integers()),
    st.builds(lambda: object()),  # Custom objects
)

# Strategy for generating mixed metadata
mixed_metadata = st.dictionaries(
    keys=st.text(min_size=1),
    values=st.one_of(simple_values, complex_values),
    min_size=1,
)


# Feature: code-review-dec-2024-fixes, Property 3: Metadata contains only simple types
@settings(max_examples=100)
@given(metadata=mixed_metadata)
def test_metadata_contains_only_simple_types(metadata: Dict[str, Any]):
    """
    Property: For any metadata dictionary, after validation, all values
    should be instances of allowed types (str, int, float, bool, None).

    **Validates: Requirements 2.1**
    """
    # Create parser instance
    parser = DocumentParser()

    # Validate the metadata
    validated = parser._validate_metadata_types(metadata)

    # Check that all values in validated metadata are simple types
    for field, value in validated.items():
        assert isinstance(value, ALLOWED_METADATA_TYPES), (
            f"Field '{field}' has disallowed type {type(value).__name__}"
        )


# Feature: code-review-dec-2024-fixes, Property 3: Metadata contains only simple types
@settings(max_examples=100)
@given(metadata=mixed_metadata)
def test_complex_types_are_filtered_out(metadata: Dict[str, Any]):
    """
    Property: For any metadata dictionary containing complex types,
    those complex types should be filtered out from the result.

    **Validates: Requirements 2.1**
    """
    # Create parser instance
    parser = DocumentParser()

    # Validate the metadata
    validated = parser._validate_metadata_types(metadata)

    # Count how many fields had complex types in the original
    complex_fields = {
        field
        for field, value in metadata.items()
        if not isinstance(value, ALLOWED_METADATA_TYPES)
    }

    # Verify that none of the complex fields appear in validated metadata
    for field in complex_fields:
        assert field not in validated, (
            f"Complex field '{field}' should have been filtered out"
        )


# Feature: code-review-dec-2024-fixes, Property 3: Metadata contains only simple types
@settings(max_examples=100)
@given(metadata=st.dictionaries(st.text(min_size=1), simple_values, min_size=1))
def test_simple_types_pass_through(metadata: Dict[str, Any]):
    """
    Property: For any metadata dictionary containing only simple types,
    all fields should pass through validation unchanged.

    **Validates: Requirements 2.1**
    """
    # Create parser instance
    parser = DocumentParser()

    # Validate the metadata
    validated = parser._validate_metadata_types(metadata)

    # All simple-type fields should be present
    assert validated == metadata, "Simple-type metadata should pass through unchanged"
