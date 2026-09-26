"""Tests for ParserChain implementation."""

from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit
from agentic_inquiry.parsers import (
    ParserChain,
    ParsingError,
    create_parser_chain,
    register_parser,
    unregister_parser,
    ParsedDocument,
    ParserChunk,
)


def _create_mock_event_system():
    """Create a mock event system for tests."""
    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    return mock_es


class MockParser:
    """Mock parser for testing."""
    
    def __init__(self, name: str, can_handle: bool = True, should_fail: bool = False):
        self.name = name
        self._can_handle = can_handle
        self._should_fail = should_fail
    
    async def can_parse(self, path: str) -> bool:
        """Check if parser can handle the file."""
        return self._can_handle
    
    async def parse(self, path: str):
        """Parse the file."""
        if self._should_fail:
            raise ValueError(f"{self.name} failed to parse")
        
        return ParsedDocument(
            doc_id=path,
            file_path=path,
            chunks=[ParserChunk(content=f"Parsed by {self.name}")],
            metadata={"parser": self.name}
        )


@pytest.mark.asyncio
async def test_parser_chain_uses_first_successful_parser():
    """Test that ParserChain uses the first parser that succeeds."""
    # Register mock parsers
    parser1 = MockParser("parser1", should_fail=True)
    parser2 = MockParser("parser2", should_fail=False)
    parser3 = MockParser("parser3", should_fail=False)
    
    register_parser("parser1", parser1, overwrite=True)
    register_parser("parser2", parser2, overwrite=True)
    register_parser("parser3", parser3, overwrite=True)
    
    try:
        # Create chain
        chain = ParserChain(event_system=_create_mock_event_system(), parser_names=["parser1", "parser2", "parser3"])
        
        # Parse should succeed with parser2
        result = await chain.parse("/test/file.txt")
        
        assert result.metadata["parser"] == "parser2"
        assert result.chunks[0].content == "Parsed by parser2"
    finally:
        # Cleanup
        unregister_parser("parser1")
        unregister_parser("parser2")
        unregister_parser("parser3")


@pytest.mark.asyncio
async def test_parser_chain_skips_parsers_that_cannot_handle():
    """Test that ParserChain skips parsers where can_parse returns False."""
    # Register mock parsers
    parser1 = MockParser("parser1", can_handle=False)
    parser2 = MockParser("parser2", can_handle=True)
    
    register_parser("parser1", parser1, overwrite=True)
    register_parser("parser2", parser2, overwrite=True)
    
    try:
        # Create chain
        chain = ParserChain(event_system=_create_mock_event_system(), parser_names=["parser1", "parser2"])
        
        # Parse should skip parser1 and use parser2
        result = await chain.parse("/test/file.txt")
        
        assert result.metadata["parser"] == "parser2"
    finally:
        # Cleanup
        unregister_parser("parser1")
        unregister_parser("parser2")


@pytest.mark.asyncio
async def test_parser_chain_raises_when_all_parsers_fail():
    """Test that ParserChain raises ParsingError when all parsers fail."""
    # Register mock parsers that all fail
    parser1 = MockParser("parser1", should_fail=True)
    parser2 = MockParser("parser2", should_fail=True)
    
    register_parser("parser1", parser1, overwrite=True)
    register_parser("parser2", parser2, overwrite=True)
    
    try:
        # Create chain
        chain = ParserChain(event_system=_create_mock_event_system(), parser_names=["parser1", "parser2"])
        
        # Parse should raise ParsingError
        with pytest.raises(ParsingError) as exc_info:
            await chain.parse("/test/file.txt")
        
        assert "All parsers failed" in str(exc_info.value)
    finally:
        # Cleanup
        unregister_parser("parser1")
        unregister_parser("parser2")


@pytest.mark.asyncio
async def test_parser_chain_handles_unregistered_parsers():
    """Test that ParserChain handles unregistered parsers gracefully."""
    # Register only one parser
    parser2 = MockParser("parser2")
    register_parser("parser2", parser2, overwrite=True)
    
    try:
        # Create chain with unregistered parser
        chain = ParserChain(event_system=_create_mock_event_system(), parser_names=["nonexistent_parser", "parser2"])
        
        # Parse should skip nonexistent and use parser2
        result = await chain.parse("/test/file.txt")
        
        assert result.metadata["parser"] == "parser2"
    finally:
        # Cleanup
        unregister_parser("parser2")


def test_create_parser_chain_factory():
    """Test the create_parser_chain factory function."""
    # Test with default priority
    chain1 = create_parser_chain()
    assert chain1.parser_names == [
        "unified_code",
        "salesforce_metadata",
        "document",
        "fallback_text",
    ]
    
    # Test with custom priority
    chain2 = create_parser_chain(["parser1", "parser2"])
    assert chain2.parser_names == ["parser1", "parser2"]


@pytest.mark.asyncio
async def test_parser_chain_with_parser_without_can_parse():
    """Test that ParserChain works with parsers that don't implement can_parse."""
    
    class SimpleParser:
        """Parser without can_parse method."""
        
        async def parse(self, path: str):
            return ParsedDocument(
                doc_id=path,
                file_path=path,
                chunks=[ParserChunk(content="Simple parser")],
            )
    
    parser = SimpleParser()
    register_parser("simple", parser, overwrite=True)
    
    try:
        chain = ParserChain(event_system=_create_mock_event_system(), parser_names=["simple"])
        result = await chain.parse("/test/file.txt")
        
        assert result.chunks[0].content == "Simple parser"
    finally:
        unregister_parser("simple")


@pytest.mark.asyncio
async def test_parser_chain_logs_failures_at_warning_level(caplog):
    """Test that parser failures are logged at WARNING level with stack traces."""
    import logging
    
    # Register a parser that will fail
    parser = MockParser("failing_parser", should_fail=True)
    register_parser("failing_parser", parser, overwrite=True)
    
    # Register a successful parser to prevent ParsingError
    success_parser = MockParser("success_parser", should_fail=False)
    register_parser("success_parser", success_parser, overwrite=True)
    
    try:
        chain = ParserChain(event_system=_create_mock_event_system(), parser_names=["failing_parser", "success_parser"])
        
        with caplog.at_level(logging.WARNING):
            await chain.parse("/test/file.txt")
        
        # Check that warning was logged
        warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_records) == 1
        
        warning_record = warning_records[0]
        assert "failing_parser" in warning_record.message
        assert "failed to parse" in warning_record.message
        assert "/test/file.txt" in warning_record.message
        
        # Check that exc_info was included (stack trace)
        assert warning_record.exc_info is not None
        
        # Check structured logging extras
        assert warning_record.file_path == "/test/file.txt"
        assert warning_record.parser_name == "failing_parser"
        
    finally:
        unregister_parser("failing_parser")
        unregister_parser("success_parser")


@pytest.mark.asyncio
async def test_parser_chain_logs_all_failures_at_error_level(caplog):
    """Test that when all parsers fail, final error is logged at ERROR level."""
    import logging
    
    # Register parsers that all fail
    parser1 = MockParser("parser1", should_fail=True)
    parser2 = MockParser("parser2", should_fail=True)
    
    register_parser("parser1", parser1, overwrite=True)
    register_parser("parser2", parser2, overwrite=True)
    
    try:
        chain = ParserChain(event_system=_create_mock_event_system(), parser_names=["parser1", "parser2"])
        
        with caplog.at_level(logging.WARNING):
            with pytest.raises(ParsingError):
                await chain.parse("/test/file.txt")
        
        # Check that ERROR was logged for final failure
        error_records = [r for r in caplog.records if r.levelname == "ERROR"]
        assert len(error_records) == 1
        
        error_record = error_records[0]
        assert "All parsers failed" in error_record.message
        assert "/test/file.txt" in error_record.message
        
        # Check structured logging extras
        assert error_record.file_path == "/test/file.txt"
        assert error_record.parser_errors == ["parser1: parser1 failed to parse", "parser2: parser2 failed to parse"]
        
    finally:
        unregister_parser("parser1")
        unregister_parser("parser2")


@pytest.mark.asyncio
async def test_parser_chain_does_not_catch_keyboard_interrupt():
    """Test that KeyboardInterrupt is not caught and propagates."""
    
    class InterruptingParser:
        """Parser that raises KeyboardInterrupt."""
        
        async def can_parse(self, path: str) -> bool:
            return True
        
        async def parse(self, path: str):
            raise KeyboardInterrupt("User interrupted")
    
    parser = InterruptingParser()
    register_parser("interrupting", parser, overwrite=True)
    
    try:
        chain = ParserChain(event_system=_create_mock_event_system(), parser_names=["interrupting"])
        
        # KeyboardInterrupt should propagate, not be caught
        with pytest.raises(KeyboardInterrupt):
            await chain.parse("/test/file.txt")
    finally:
        unregister_parser("interrupting")


@pytest.mark.asyncio
async def test_parser_chain_does_not_catch_system_exit():
    """Test that SystemExit is not caught and propagates."""
    
    class ExitingParser:
        """Parser that raises SystemExit."""
        
        async def can_parse(self, path: str) -> bool:
            return True
        
        async def parse(self, path: str):
            raise SystemExit(1)
    
    parser = ExitingParser()
    register_parser("exiting", parser, overwrite=True)
    
    try:
        chain = ParserChain(event_system=_create_mock_event_system(), parser_names=["exiting"])
        
        # SystemExit should propagate, not be caught
        with pytest.raises(SystemExit):
            await chain.parse("/test/file.txt")
    finally:
        unregister_parser("exiting")


@pytest.mark.asyncio
async def test_parser_chain_tries_all_parsers_before_failing():
    """Test that all parsers in the chain are tried before raising ParsingError."""
    
    # Track which parsers were attempted
    attempted = []
    
    class TrackingParser:
        """Parser that tracks attempts."""
        
        def __init__(self, name: str):
            self.name = name
        
        async def can_parse(self, path: str) -> bool:
            return True
        
        async def parse(self, path: str):
            attempted.append(self.name)
            raise ValueError(f"{self.name} failed")
    
    parser1 = TrackingParser("parser1")
    parser2 = TrackingParser("parser2")
    parser3 = TrackingParser("parser3")
    
    register_parser("parser1", parser1, overwrite=True)
    register_parser("parser2", parser2, overwrite=True)
    register_parser("parser3", parser3, overwrite=True)
    
    try:
        chain = ParserChain(event_system=_create_mock_event_system(), parser_names=["parser1", "parser2", "parser3"])
        
        with pytest.raises(ParsingError):
            await chain.parse("/test/file.txt")
        
        # All three parsers should have been attempted
        assert attempted == ["parser1", "parser2", "parser3"]
    finally:
        unregister_parser("parser1")
        unregister_parser("parser2")
        unregister_parser("parser3")


@pytest.mark.asyncio
async def test_parser_chain_honors_fallback_text_config(tmp_path):
    """ParserChain uses fallback_text chunk settings from the supplied Config."""
    from agentic_inquiry.config import Config
    from agentic_inquiry.parsers.executor import get_parser_instance
    from agentic_inquiry.parsers.implementations.fallback_text import FallbackTextParser

    config = Config()
    config.parsers.fallback_text.max_chunk_size = 80
    config.parsers.fallback_text.chunk_overlap = 0
    config.parsers.fallback_text.whole_file_max_chars = 80
    text_file = tmp_path / "forced-split.txt"
    text_file.write_text("Paragraph one is long enough. " * 12, encoding="utf-8")

    chain = ParserChain(
        parser_names=["fallback_text"],
        config=config,
        event_system=_create_mock_event_system(),
    )
    result = await chain.parse(str(text_file))

    assert len(result.chunks) >= 2
    registered = get_parser_instance("fallback_text")
    assert isinstance(registered, FallbackTextParser)
    assert registered.max_chunk_size == 1000
    assert registered.whole_file_max_chars == 8192
