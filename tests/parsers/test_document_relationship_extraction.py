"""Property-based tests for document relationship extraction modularization.

Feature: code-review-dec-2024-fixes
Tests Property 13: Element type determines delegation
"""

import pytest

pytestmark = pytest.mark.unit
from pathlib import Path
from unittest.mock import Mock, patch
from hypothesis import given, settings
import hypothesis.strategies as st

from agentic_inquiry.parsers.implementations.document import DocumentParser


def create_mock_element(element_type: str, text: str = "content", page_number: int = 1):
    """Create a mock element with proper class name for _get_element_type().

    Mock().__class__.__name__ always returns 'Mock', so we need to create
    actual classes with the right names.
    """
    # Create a class with the right name
    element_class = type(element_type, (), {})
    elem = element_class()
    elem.text = text
    elem.metadata = Mock()
    elem.metadata.page_number = page_number
    return elem


# Strategy for generating mock elements with different types
@st.composite
def mock_element(draw, element_type=None):
    """Generate a mock element with specified or random type."""
    if element_type is None:
        element_type = draw(st.sampled_from([
            "Title", "NarrativeText", "ListItem", "Table", "Image"
        ]))

    text = draw(st.text(min_size=1, max_size=100))
    page_number = draw(st.integers(min_value=1, max_value=100))
    mock_elem = create_mock_element(element_type, text, page_number)
    return mock_elem


@st.composite
def element_list(draw):
    """Generate a list of mixed heading and non-heading elements."""
    num_elements = draw(st.integers(min_value=1, max_value=20))
    elements = []
    
    for _ in range(num_elements):
        # Mix of heading and non-heading types
        is_heading = draw(st.booleans())
        if is_heading:
            elem_type = "Title"
        else:
            elem_type = draw(st.sampled_from([
                "NarrativeText", "ListItem", "Table", "Image"
            ]))
        
        elem = draw(mock_element(element_type=elem_type))
        elements.append(elem)
    
    return elements


class TestElementTypeDelegation:
    """Test that element type determines which processing method is called."""
    
    # Feature: code-review-dec-2024-fixes, Property 13: Element type determines delegation
    @settings(max_examples=100)
    @given(elements=element_list())
    @pytest.mark.asyncio
    async def test_heading_elements_call_process_heading(self, elements):
        """Property: Heading elements should call _process_heading_element."""
        parser = DocumentParser()
        file_path = Path("/test/document.md")
        
        # Mock the processing methods
        with patch.object(parser, '_process_heading_element') as mock_heading, \
             patch.object(parser, '_process_non_heading_element') as mock_non_heading:
            
            # Call the method under test
            parser._extract_relationships(elements, file_path)
            
            # Count expected calls based on element types
            heading_count = sum(1 for elem in elements if elem.__class__.__name__ == "Title")
            non_heading_count = len(elements) - heading_count
            
            # Verify correct delegation
            assert mock_heading.call_count == heading_count, \
                f"Expected {heading_count} heading calls, got {mock_heading.call_count}"
            assert mock_non_heading.call_count == non_heading_count, \
                f"Expected {non_heading_count} non-heading calls, got {mock_non_heading.call_count}"
    
    # Feature: code-review-dec-2024-fixes, Property 13: Element type determines delegation
    @settings(max_examples=100)
    @given(elements=element_list())
    @pytest.mark.asyncio
    async def test_non_heading_elements_call_process_non_heading(self, elements):
        """Property: Non-heading elements should call _process_non_heading_element."""
        parser = DocumentParser()
        file_path = Path("/test/document.md")
        
        # Mock the processing methods
        with patch.object(parser, '_process_heading_element'), \
             patch.object(parser, '_process_non_heading_element') as mock_non_heading:
            
            # Call the method under test
            parser._extract_relationships(elements, file_path)
            
            # Verify that each non-heading element resulted in a call
            non_heading_types = ["NarrativeText", "ListItem", "Table", "Image"]
            for i, elem in enumerate(elements):
                if elem.__class__.__name__ in non_heading_types:
                    # Check that this element was processed as non-heading
                    # We can't check exact call args easily, but we can verify the count
                    pass
            
            # At minimum, verify the call counts match expectations
            heading_count = sum(1 for elem in elements if elem.__class__.__name__ == "Title")
            non_heading_count = len(elements) - heading_count
            
            assert mock_non_heading.call_count == non_heading_count
    
    # Feature: code-review-dec-2024-fixes, Property 13: Element type determines delegation
    @pytest.mark.asyncio
    async def test_only_headings_no_non_heading_calls(self):
        """Property: Document with only headings should not call _process_non_heading_element."""
        parser = DocumentParser()
        file_path = Path("/test/document.md")

        # Create elements that are all headings using create_mock_element
        elements = [create_mock_element("Title", f"Heading {i}") for i in range(5)]

        with patch.object(parser, '_process_heading_element') as mock_heading, \
             patch.object(parser, '_process_non_heading_element') as mock_non_heading:

            parser._extract_relationships(elements, file_path)

            assert mock_heading.call_count == 5
            assert mock_non_heading.call_count == 0

    # Feature: code-review-dec-2024-fixes, Property 13: Element type determines delegation
    @pytest.mark.asyncio
    async def test_only_non_headings_no_heading_calls(self):
        """Property: Document with no headings should not call _process_heading_element."""
        parser = DocumentParser()
        file_path = Path("/test/document.md")

        # Create elements that are all non-headings using create_mock_element
        elements = [create_mock_element("NarrativeText", f"Paragraph {i}") for i in range(5)]

        with patch.object(parser, '_process_heading_element') as mock_heading, \
             patch.object(parser, '_process_non_heading_element') as mock_non_heading:

            parser._extract_relationships(elements, file_path)

            assert mock_heading.call_count == 0
            assert mock_non_heading.call_count == 5
    
    # Feature: code-review-dec-2024-fixes, Property 13: Element type determines delegation
    @settings(max_examples=100)
    @given(
        num_headings=st.integers(min_value=0, max_value=10),
        num_non_headings=st.integers(min_value=0, max_value=10)
    )
    @pytest.mark.asyncio
    async def test_delegation_count_matches_element_types(self, num_headings, num_non_headings):
        """Property: Number of delegation calls should match number of each element type."""
        # Skip if no elements
        if num_headings == 0 and num_non_headings == 0:
            return

        parser = DocumentParser()
        file_path = Path("/test/document.md")

        # Create mixed elements using create_mock_element
        elements = []
        for i in range(num_headings):
            elements.append(create_mock_element("Title", f"Heading {i}"))
        for i in range(num_non_headings):
            elements.append(create_mock_element("NarrativeText", f"Paragraph {i}"))

        with patch.object(parser, '_process_heading_element') as mock_heading, \
             patch.object(parser, '_process_non_heading_element') as mock_non_heading:

            parser._extract_relationships(elements, file_path)

            assert mock_heading.call_count == num_headings, \
                f"Expected {num_headings} heading calls, got {mock_heading.call_count}"
            assert mock_non_heading.call_count == num_non_headings, \
                f"Expected {num_non_headings} non-heading calls, got {mock_non_heading.call_count}"
