#!/usr/bin/env python3
"""Unit tests for DocumentParser exception handling.

Tests the exception handling improvements including:
- DocumentParsingError custom exception type
- Exception chain preservation
- Exception attribute population
"""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import patch

from agentic_inquiry.parsers.implementations.document import DocumentParser
from agentic_inquiry.exceptions import DocumentParsingError, ParsingError


@pytest.fixture
def parser():
    """Provides a DocumentParser instance."""
    return DocumentParser()


class TestDocumentParsingError:
    """Test DocumentParsingError custom exception type.

    Feature: code-review-dec-2024-fixes, Property 5: Custom exceptions preserve type information
    Validates: Requirements 3.2, 3.3
    """

    @pytest.mark.asyncio
    async def test_parsing_error_raises_document_parsing_error(self, parser, tmp_path):
        """Verify DocumentParsingError is raised (not generic Exception)."""
        # Create a file that will cause parsing to fail
        invalid_file = tmp_path / "invalid.pdf"
        invalid_file.write_bytes(b"Not a valid PDF file")

        # Mock the partition function to raise an exception
        with patch(
            "agentic_inquiry.parsers.implementations.document.partition"
        ) as mock_partition:
            mock_partition.side_effect = ValueError("Invalid PDF format")

            # Should raise DocumentParsingError, not generic Exception
            with pytest.raises(DocumentParsingError) as exc_info:
                await parser.parse(str(invalid_file))

            # Verify it's the correct exception type
            assert isinstance(exc_info.value, DocumentParsingError)
            assert isinstance(exc_info.value, ParsingError)
            assert type(exc_info.value) is not Exception

    @pytest.mark.asyncio
    async def test_exception_chain_preserved(self, parser, tmp_path):
        """Verify exception chain is preserved (__cause__ is set)."""
        # Create a file that will cause parsing to fail
        invalid_file = tmp_path / "invalid.docx"
        invalid_file.write_bytes(b"Not a valid DOCX file")

        # Mock the partition function to raise a specific exception
        original_error = IOError("Cannot read file")
        with patch(
            "agentic_inquiry.parsers.implementations.document.partition"
        ) as mock_partition:
            mock_partition.side_effect = original_error

            # Catch the exception
            with pytest.raises(DocumentParsingError) as exc_info:
                await parser.parse(str(invalid_file))

            # Verify exception chain is preserved
            assert exc_info.value.__cause__ is not None
            assert exc_info.value.__cause__ == original_error
            assert isinstance(exc_info.value.__cause__, IOError)

    @pytest.mark.asyncio
    async def test_exception_attributes_populated(self, parser, tmp_path):
        """Verify exception attributes are populated (file_path, parser_type, original_error)."""
        # Create a file that will cause parsing to fail
        invalid_file = tmp_path / "test_document.md"
        invalid_file.write_text("# Test")

        # Mock the partition function to raise an exception
        original_error = RuntimeError("Parsing failed")
        with patch(
            "agentic_inquiry.parsers.implementations.document.partition"
        ) as mock_partition:
            mock_partition.side_effect = original_error

            # Catch the exception
            with pytest.raises(DocumentParsingError) as exc_info:
                await parser.parse(str(invalid_file))

            # Verify attributes are populated
            exception = exc_info.value

            # file_path should be set
            assert exception.file_path is not None
            assert str(invalid_file) in exception.file_path

            # parser_type should be set
            assert exception.parser_type == "document"

            # original_error should be set
            assert exception.original_error is not None
            assert exception.original_error == original_error
            assert isinstance(exception.original_error, RuntimeError)

    @pytest.mark.asyncio
    async def test_exception_message_includes_context(self, parser, tmp_path):
        """Verify exception message includes helpful context."""
        # Create a markdown file that will cause parsing to fail when we mock partition
        invalid_file = tmp_path / "problematic.md"
        invalid_file.write_text("# Test content")

        # Mock the partition function to raise an exception
        with patch(
            "agentic_inquiry.parsers.implementations.document.partition"
        ) as mock_partition:
            mock_partition.side_effect = ValueError("Unsupported format")

            # Catch the exception
            with pytest.raises(DocumentParsingError) as exc_info:
                await parser.parse(str(invalid_file))

            # Verify message includes file path and error details
            message = str(exc_info.value)
            assert "problematic.md" in message
            assert "Unsupported format" in message or "ValueError" in message

    @pytest.mark.asyncio
    async def test_different_error_types_preserved(self, parser, tmp_path):
        """Verify different underlying error types are preserved in chain."""
        test_file = tmp_path / "test.md"
        test_file.write_text("# Test")

        # Test with different exception types
        error_types = [
            IOError("File read error"),
            ValueError("Invalid value"),
            RuntimeError("Runtime error"),
            MemoryError("Out of memory"),
        ]

        for original_error in error_types:
            with patch(
                "agentic_inquiry.parsers.implementations.document.partition"
            ) as mock_partition:
                mock_partition.side_effect = original_error

                with pytest.raises(DocumentParsingError) as exc_info:
                    await parser.parse(str(test_file))

                # Verify the original error type is preserved
                assert exc_info.value.__cause__ == original_error
                assert type(exc_info.value.__cause__) is type(original_error)


class TestExceptionLogging:
    """Test that exception logging uses lazy logging and exc_info."""

    @pytest.mark.asyncio
    async def test_exception_logged_with_exc_info(self, parser, tmp_path, caplog):
        """Verify exceptions are logged with exc_info=True."""
        import logging

        caplog.set_level(logging.WARNING)

        invalid_file = tmp_path / "invalid.pdf"
        invalid_file.write_bytes(b"Not valid")

        with patch(
            "agentic_inquiry.parsers.implementations.document.partition"
        ) as mock_partition:
            mock_partition.side_effect = ValueError("Parse error")

            with pytest.raises(DocumentParsingError):
                await parser.parse(str(invalid_file))

            # Check that warning was logged
            assert len(caplog.records) > 0

            # Find the warning record
            warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
            assert len(warning_records) > 0

            # Verify exc_info was included (traceback should be present)
            warning_record = warning_records[0]
            assert warning_record.exc_info is not None


class TestSuccessfulParsing:
    """Test that successful parsing still works correctly."""

    @pytest.mark.asyncio
    async def test_successful_parse_no_exception(self, parser, tmp_path):
        """Verify successful parsing doesn't raise exceptions."""
        # Create a valid markdown file
        valid_file = tmp_path / "valid.md"
        valid_file.write_text("""
# Main Title

This is a test document.

## Section 1

Content for section 1.

## Section 2

Content for section 2.
""")

        # Should parse successfully without raising exceptions
        result = await parser.parse(str(valid_file))

        # Verify result is valid
        assert result is not None
        assert len(result.chunks) > 0
        assert result.file_path == str(valid_file)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
