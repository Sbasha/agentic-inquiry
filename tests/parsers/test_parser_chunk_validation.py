"""Unit tests for ParserChunk metadata validation.

Feature: claude-review-improvements
Tests specific validation scenarios for metadata type constraints.
"""

import pytest

pytestmark = pytest.mark.unit
from pydantic import ValidationError

from agentic_inquiry.parsers.models import ParserChunk


class TestParserChunkMetadataValidation:
    """Unit tests for ParserChunk metadata validation.
    
    Requirements: 5.1, 5.2, 5.4
    """

    def test_rejects_list_in_metadata(self):
        """Test rejection of list in metadata.
        
        Validates: Requirements 5.1, 5.2
        """
        metadata = {"tags": ["tag1", "tag2", "tag3"]}
        
        with pytest.raises(ValidationError) as exc_info:
            ParserChunk(content="test content", metadata=metadata)
        
        error_message = str(exc_info.value)
        assert "tags" in error_message
        assert "list" in error_message
        assert "parser-guidelines.md" in error_message

    def test_rejects_dict_in_metadata(self):
        """Test rejection of dict in metadata.
        
        Validates: Requirements 5.1, 5.2
        """
        metadata = {"config": {"key": "value", "nested": True}}
        
        with pytest.raises(ValidationError) as exc_info:
            ParserChunk(content="test content", metadata=metadata)
        
        error_message = str(exc_info.value)
        assert "config" in error_message
        assert "dict" in error_message
        assert "parser-guidelines.md" in error_message

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

    def test_error_message_references_guidelines(self):
        """Test error message content references parser-guidelines.md.

        Validates: Requirements 5.4
        """
        metadata = {"invalid": ["list", "of", "items"]}

        with pytest.raises(ValidationError) as exc_info:
            ParserChunk(content="test content", metadata=metadata)

        error_message = str(exc_info.value)
        assert "parser-guidelines.md" in error_message

    def test_error_message_includes_field_name(self):
        """Test error message includes the problematic field name.
        
        Validates: Requirements 5.4
        """
        metadata = {"problematic_field": {"nested": "dict"}}
        
        with pytest.raises(ValidationError) as exc_info:
            ParserChunk(content="test content", metadata=metadata)
        
        error_message = str(exc_info.value)
        assert "problematic_field" in error_message

    def test_error_message_includes_type_name(self):
        """Test error message includes the type name.
        
        Validates: Requirements 5.4
        """
        metadata = {"field_with_list": [1, 2, 3]}
        
        with pytest.raises(ValidationError) as exc_info:
            ParserChunk(content="test content", metadata=metadata)
        
        error_message = str(exc_info.value)
        assert "list" in error_message

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

    def test_rejects_nested_list(self):
        """Test rejection of nested list in metadata.
        
        Validates: Requirements 5.1, 5.2
        """
        metadata = {"nested": [[1, 2], [3, 4]]}
        
        with pytest.raises(ValidationError) as exc_info:
            ParserChunk(content="test content", metadata=metadata)
        
        error_message = str(exc_info.value)
        assert "nested" in error_message
        assert "list" in error_message

    def test_rejects_nested_dict(self):
        """Test rejection of nested dict in metadata.
        
        Validates: Requirements 5.1, 5.2
        """
        metadata = {"nested": {"inner": {"deep": "value"}}}
        
        with pytest.raises(ValidationError) as exc_info:
            ParserChunk(content="test content", metadata=metadata)
        
        error_message = str(exc_info.value)
        assert "nested" in error_message
        assert "dict" in error_message
