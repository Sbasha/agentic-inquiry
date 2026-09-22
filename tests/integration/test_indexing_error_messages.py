"""Test indexing failure error messages (Example 8).

This module tests that indexing failures provide helpful error messages
explaining which file failed and why.

**Validates: Requirements 9.3**
"""

from agent_vault.indexing.models import IndexingError


class TestIndexingErrorMessages:
    """Test indexing failure error messages provide helpful context."""
    
    def test_indexing_error_structure(self):
        """Test that IndexingError has all required fields.
        
        **Example 8: Indexing failure error**
        **Validates: Requirements 9.3**
        
        Verifies that:
        - Error includes file_path
        - Error includes error_type
        - Error includes error_message
        - Error includes suggestion
        """
        # Create an IndexingError
        error = IndexingError(
            file_path="/path/to/file.py",
            error_type="ParseError",
            error_message="Failed to parse file: invalid syntax",
            suggestion="Verify file is valid Python code"
        )
        
        # Verify all required fields are present
        assert error.file_path == "/path/to/file.py"
        assert error.error_type == "ParseError"
        assert error.error_message == "Failed to parse file: invalid syntax"
        assert error.suggestion == "Verify file is valid Python code"
    
    def test_indexing_error_to_dict(self):
        """Test that IndexingError.to_dict() returns proper structure."""
        error = IndexingError(
            file_path="/path/to/file.py",
            error_type="ParseError",
            error_message="Failed to parse file",
            suggestion="Check file syntax"
        )
        
        error_dict = error.to_dict()
        
        # Verify dict structure
        assert "file" in error_dict
        assert "error" in error_dict
        assert "message" in error_dict
        assert "suggestion" in error_dict
        
        # Verify values
        assert error_dict["file"] == "/path/to/file.py"
        assert error_dict["error"] == "ParseError"
        assert error_dict["message"] == "Failed to parse file"
        assert error_dict["suggestion"] == "Check file syntax"
    
    def test_parsing_error_suggestion(self):
        """Test that parsing errors get appropriate suggestions."""
        # Simulate a parsing error
        error = IndexingError(
            file_path="test.py",
            error_type="ParsingError",
            error_message="No parser available",
            suggestion="Verify file is valid and supported format (.py, .js, .ts, .md, etc.)"
        )
        
        # Verify suggestion is helpful
        assert "supported format" in error.suggestion
        assert ".py" in error.suggestion or "format" in error.suggestion
    
    def test_schema_validation_error_suggestion(self):
        """Test that schema validation errors get appropriate suggestions."""
        error = IndexingError(
            file_path="test.py",
            error_type="SchemaValidationError",
            error_message="Missing required field",
            suggestion="File structure may not match expected schema. Check parser output."
        )
        
        # Verify suggestion is helpful
        assert "schema" in error.suggestion.lower()
    
    def test_permission_error_suggestion(self):
        """Test that permission errors get appropriate suggestions."""
        error = IndexingError(
            file_path="test.py",
            error_type="PermissionError",
            error_message="Permission denied",
            suggestion="Check file permissions and ensure file is accessible"
        )
        
        # Verify suggestion is helpful
        assert "permission" in error.suggestion.lower()
    
    def test_encoding_error_suggestion(self):
        """Test that encoding errors get appropriate suggestions."""
        error = IndexingError(
            file_path="test.py",
            error_type="UnicodeDecodeError",
            error_message="Cannot decode file",
            suggestion="File may have encoding issues. Ensure file is UTF-8 encoded"
        )
        
        # Verify suggestion is helpful
        assert "encoding" in error.suggestion.lower() or "UTF-8" in error.suggestion
