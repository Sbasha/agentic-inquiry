"""Test validation error messages (Example 6, 7).

This module tests that validation errors provide helpful messages with
invalid values, valid values, and examples.

**Validates: Requirements 9.1, 9.2**
"""

import pytest

from agentic_inquiry.exceptions import ValidationError
from agentic_inquiry.mcp.utils.validation import validate_content_type


class TestValidationErrorMessages:
    """Test validation error messages provide helpful context."""

    def test_invalid_content_type_error_message(self):
        """Test that invalid content_type raises ValidationError with helpful message.

        **Example 6: Validation error messages**
        **Validates: Requirements 9.1**

        Verifies that:
        - Error includes the invalid value
        - Error lists all valid values
        - Error provides an example
        """
        # Provide invalid content_type (use a truly invalid value, not "code" which is now an alias)
        invalid_value = "invalid_type"

        with pytest.raises(ValidationError) as exc_info:
            validate_content_type(invalid_value)

        error = exc_info.value

        # Verify error includes invalid value
        assert error.invalid_value == invalid_value
        assert invalid_value in str(error)

        # Verify error includes valid values (including the "code" alias)
        assert "file" in error.valid_values
        assert "directory" in error.valid_values
        assert "text" in error.valid_values
        assert "code" in error.valid_values  # Alias is listed as valid
        assert "file" in str(error)
        assert "directory" in str(error)
        assert "text" in str(error)

        # Verify error includes example
        assert error.example is not None
        assert "content_type=" in error.example

    def test_code_alias_for_directory(self):
        """Test that 'code' is accepted as an alias for 'directory'.

        This improves UX by using more intuitive naming for codebase indexing.
        """
        # "code" should normalize to "directory"
        result = validate_content_type("code")
        assert result == "directory"

    def test_canonical_content_types_unchanged(self):
        """Test that canonical content types remain unchanged."""
        assert validate_content_type("file") == "file"
        assert validate_content_type("directory") == "directory"
        assert validate_content_type("text") == "text"

    def test_missing_parameter_error_message(self):
        """Test that missing parameter error names parameter and shows example.

        **Example 7: Missing parameter error**
        **Validates: Requirements 9.2**

        Verifies that:
        - Error names the missing parameter
        - Error shows an example of correct usage
        """
        # Test with None (simulating missing parameter)
        with pytest.raises(ValidationError) as exc_info:
            validate_content_type(None)

        error = exc_info.value

        # Verify error names the parameter
        assert error.param_name == "content_type"
        assert "content_type" in str(error)

        # Verify error shows example
        assert error.example is not None
        assert "content_type=" in error.example

    def test_validation_error_attributes(self):
        """Test ValidationError has all required attributes."""
        error = ValidationError(
            param_name="test_param",
            invalid_value="invalid",
            valid_values=["valid1", "valid2"],
            example="test_param='valid1'",
        )

        assert error.param_name == "test_param"
        assert error.invalid_value == "invalid"
        assert error.valid_values == ["valid1", "valid2"]
        assert error.example == "test_param='valid1'"

        # Verify message format
        error_msg = str(error)
        assert "test_param" in error_msg
        assert "invalid" in error_msg
        assert "valid1" in error_msg
        assert "valid2" in error_msg
        assert "test_param='valid1'" in error_msg
