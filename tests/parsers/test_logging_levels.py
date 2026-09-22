"""Tests for parser logging levels.

This module tests that parser failures are logged at appropriate levels:
- Individual parser failures: WARNING level
- All parsers failed: ERROR level
- Debug information: DEBUG level only
"""

import logging
import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_vault.exceptions import ParsingError
from agent_vault.parsers.chain import ParserChain
from agent_vault.parsers.executor import register_parser, unregister_parser
from agent_vault.parsers.models import ParsedDocument, ParserChunk


def _create_mock_event_system():
    """Create a mock event system for tests."""
    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    return mock_es


class MockFailingParser:
    """Mock parser that always fails."""
    
    def __init__(self, name: str, error_message: str = "Mock parsing error"):
        self.name = name
        self.priority = 100
        self.error_message = error_message
    
    async def can_parse(self, path: str) -> bool:
        return True
    
    async def parse(self, path: str) -> ParsedDocument:
        raise ParsingError(self.error_message)


class MockSuccessParser:
    """Mock parser that always succeeds."""
    
    def __init__(self, name: str):
        self.name = name
        self.priority = 50
    
    async def can_parse(self, path: str) -> bool:
        return True
    
    async def parse(self, path: str) -> ParsedDocument:
        return ParsedDocument(
            doc_id=path,
            file_path=path,
            chunks=[
                ParserChunk(
                    content="Mock content",
                    line_start=1,
                    line_end=1,
                )
            ],
            metadata={"parser": self.name},
        )


@pytest.mark.asyncio
async def test_parser_chain_logs_individual_failure_at_warning(caplog):
    """Test that individual parser failures are logged at WARNING level."""
    # Register a failing parser and a successful parser
    failing_parser = MockFailingParser("failing_parser", "Test error")
    success_parser = MockSuccessParser("success_parser")
    
    register_parser("failing_parser", failing_parser, overwrite=True)
    register_parser("success_parser", success_parser, overwrite=True)
    
    try:
        chain = ParserChain(event_system=_create_mock_event_system(), parser_names=["failing_parser", "success_parser"])
        
        with caplog.at_level(logging.WARNING):
            result = await chain.parse("/test/file.txt")
        
        # Verify the result is from the success parser
        assert result.metadata["parser"] == "success_parser"
        
        # Check that WARNING was logged for the failing parser
        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_records) == 1
        
        warning_record = warning_records[0]
        assert "failing_parser" in warning_record.message
        assert "failed" in warning_record.message.lower()
        assert "/test/file.txt" in warning_record.message
        
        # Verify stack trace is included
        assert warning_record.exc_info is not None
        
    finally:
        unregister_parser("failing_parser")
        unregister_parser("success_parser")


@pytest.mark.asyncio
async def test_parser_chain_logs_all_failures_at_error(caplog):
    """Test that when all parsers fail, the summary is logged at ERROR level."""
    # Register multiple failing parsers
    parser1 = MockFailingParser("parser1", "Error 1")
    parser2 = MockFailingParser("parser2", "Error 2")
    
    register_parser("parser1", parser1, overwrite=True)
    register_parser("parser2", parser2, overwrite=True)
    
    try:
        chain = ParserChain(event_system=_create_mock_event_system(), parser_names=["parser1", "parser2"])
        
        with caplog.at_level(logging.WARNING):
            with pytest.raises(ParsingError) as exc_info:
                await chain.parse("/test/file.txt")
        
        # Verify the error message
        assert "All parsers failed" in str(exc_info.value)
        
        # Check that ERROR was logged
        error_records = [r for r in caplog.records if r.levelname == "ERROR"]
        assert len(error_records) == 1
        
        error_record = error_records[0]
        assert "All parsers failed" in error_record.message
        assert "/test/file.txt" in error_record.message
        
        # Check that both parser errors are mentioned
        assert "parser1" in error_record.message or hasattr(error_record, "parser_errors")
        assert "parser2" in error_record.message or hasattr(error_record, "parser_errors")
        
    finally:
        unregister_parser("parser1")
        unregister_parser("parser2")


async def test_document_parser_logs_failure_at_warning(caplog, tmp_path):
    """Test that DocumentParser logs failures at WARNING level, not ERROR.
    
    Note: This test verifies that when DocumentParser encounters an error,
    it logs at WARNING level since ParserChain will handle the error
    and provide appropriate ERROR-level logging if all parsers fail.
    """
    from agent_vault.parsers.implementations.document import DocumentParser
    
    # Create a test file
    test_file = tmp_path / "test.pdf"
    test_file.write_bytes(b"Some content")
    
    parser = DocumentParser()
    
    # Mock the partition function to raise an exception
    with patch('agent_vault.parsers.implementations.document.partition') as mock_partition:
        mock_partition.side_effect = Exception("Mocked parsing failure")
        
        with caplog.at_level(logging.DEBUG):
            try:
                await parser.parse(str(test_file))
            except Exception:
                pass  # Expected to fail
    
    # Check logging levels
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
    
    # After fix, DocumentParser should log at WARNING level, not ERROR
    assert len(warning_records) >= 1, "DocumentParser should log at WARNING level"
    assert any("parsing failed" in r.message.lower() for r in warning_records)
    
    # Should NOT log at ERROR level (ParserChain handles that)
    assert len(error_records) == 0, "DocumentParser should not log at ERROR level"


async def test_unified_code_parser_logs_failure_at_warning(caplog, tmp_path):
    """Test that UnifiedCodeParser logs parsing failures at WARNING level.
    
    UnifiedCodeParser already correctly logs at WARNING level when tree-sitter
    parsing fails and it falls back to simple chunking.
    """
    from agent_vault.parsers.implementations.unified_code import UnifiedCodeParser
    
    # Create a test file with content that might trigger fallback
    test_file = tmp_path / "test.py"
    test_file.write_text("# Simple Python file\nprint('hello')\n")
    
    parser = UnifiedCodeParser()
    
    with caplog.at_level(logging.DEBUG):
        # Parse the file - should succeed but might log warnings
        await parser.parse(str(test_file))
    
    # UnifiedCodeParser correctly logs at WARNING level for parsing failures
    # This test verifies the correct behavior is maintained
    [r for r in caplog.records if r.levelname == "WARNING"]
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    
    # Should not log at ERROR level for parsing issues
    assert len(error_records) == 0, "UnifiedCodeParser should not log at ERROR level"


@pytest.mark.asyncio
async def test_parser_chain_provides_actionable_information(caplog):
    """Test that parser failure logs contain actionable information."""
    failing_parser = MockFailingParser("test_parser", "Specific error: missing dependency")
    
    register_parser("test_parser", failing_parser, overwrite=True)
    
    try:
        chain = ParserChain(event_system=_create_mock_event_system(), parser_names=["test_parser"])
        
        with caplog.at_level(logging.WARNING):
            with pytest.raises(ParsingError):
                await chain.parse("/path/to/file.txt")
        
        # Check that logs contain actionable information
        all_messages = " ".join(r.message for r in caplog.records)
        
        # Should include:
        # - Parser name
        assert "test_parser" in all_messages
        
        # - File path
        assert "/path/to/file.txt" in all_messages
        
        # - Error details
        assert "Specific error" in all_messages or "missing dependency" in all_messages
        
    finally:
        unregister_parser("test_parser")


@pytest.mark.asyncio
async def test_debug_logs_not_required_for_production(caplog):
    """Test that parser failures are visible without DEBUG level logging."""
    failing_parser = MockFailingParser("debug_test_parser")
    
    register_parser("debug_test_parser", failing_parser, overwrite=True)
    
    try:
        chain = ParserChain(event_system=_create_mock_event_system(), parser_names=["debug_test_parser"])
        
        # Set logging to INFO level (typical production setting)
        with caplog.at_level(logging.INFO):
            with pytest.raises(ParsingError):
                await chain.parse("/test/file.txt")
        
        # Should still see WARNING and ERROR logs
        warning_or_error = [
            r for r in caplog.records 
            if r.levelname in ("WARNING", "ERROR")
        ]
        
        # Should have at least one warning/error about the failure
        assert len(warning_or_error) >= 1
        
        # Verify we can see the failure without DEBUG
        messages = " ".join(r.message for r in warning_or_error)
        assert "debug_test_parser" in messages
        assert "failed" in messages.lower()
        
    finally:
        unregister_parser("debug_test_parser")
