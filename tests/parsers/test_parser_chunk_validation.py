"""Unit tests for ParserChunk metadata validation.

Feature: claude-review-improvements
Tests specific validation scenarios for metadata type constraints.
"""

import pytest

pytestmark = pytest.mark.unit

from agentic_inquiry.parsers.models import ParserChunk


class TestParserChunkMetadataValidation:
    """Unit tests for ParserChunk metadata validation.
    
    Requirements: 5.1
    """

    def test_accepts_string_in_metadata(self):
        """Test acceptance of string in metadata.
        
        Validates: Requirements 5.1
        """
        metadata = {"author": "John Doe"}
        chunk = ParserChunk(content="test content", metadata=metadata)
        
        assert chunk.metadata == metadata
        assert chunk.metadata["author"] == "John Doe"

    def test_accepts_int_in_metadata(self):
        """Test acceptance of int in metadata.
        
        Validates: Requirements 5.1
        """
        metadata = {"line_count": 42}
        chunk = ParserChunk(content="test content", metadata=metadata)
        
        assert chunk.metadata == metadata
        assert chunk.metadata["line_count"] == 42

    def test_accepts_float_in_metadata(self):
        """Test acceptance of float in metadata.
        
        Validates: Requirements 5.1
        """
        metadata = {"confidence": 0.95}
        chunk = ParserChunk(content="test content", metadata=metadata)
        
        assert chunk.metadata == metadata
        assert chunk.metadata["confidence"] == 0.95

    def test_accepts_bool_in_metadata(self):
        """Test acceptance of bool in metadata.
        
        Validates: Requirements 5.1
        """
        metadata = {"is_public": True}
        chunk = ParserChunk(content="test content", metadata=metadata)
        
        assert chunk.metadata == metadata
        assert chunk.metadata["is_public"] is True

    def test_accepts_none_in_metadata(self):
        """Test acceptance of None in metadata.
        
        Validates: Requirements 5.1
        """
        metadata = {"optional_field": None}
        chunk = ParserChunk(content="test content", metadata=metadata)
        
        assert chunk.metadata == metadata
        assert chunk.metadata["optional_field"] is None

    def test_accepts_mixed_simple_types(self):
        """Test acceptance of multiple simple types in metadata.
        
        Validates: Requirements 5.1
        """
        metadata = {
            "author": "Jane Doe",
            "line_count": 100,
            "confidence": 0.87,
            "is_public": False,
            "optional": None,
        }
        chunk = ParserChunk(content="test content", metadata=metadata)
        
        assert chunk.metadata == metadata

    def test_accepts_none_metadata(self):
        """Test that None metadata is accepted (optional field).
        
        Validates: Requirements 5.1
        """
        chunk = ParserChunk(content="test content", metadata=None)
        assert chunk.metadata is None

    def test_accepts_empty_metadata(self):
        """Test that empty metadata dict is accepted.
        
        Validates: Requirements 5.1
        """
        chunk = ParserChunk(content="test content", metadata={})
        assert chunk.metadata == {}

    @pytest.mark.parametrize(
        "metadata",
        [
            {"tags": ["tag1", "tag2"]},
            {"config": {"key": "value", "nested": True}},
            {"nested": [[1, 2], [3, 4]]},
            {"nested": {"inner": {"deep": "value"}}},
        ],
    )
    def test_accepts_list_and_dict_in_metadata(self, metadata):
        """List and dict values pass through; the storage layer serializes them."""
        chunk = ParserChunk(content="test content", metadata=metadata)

        assert chunk.metadata == metadata
