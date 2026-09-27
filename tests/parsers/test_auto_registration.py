"""Tests for parser auto-registration system.

This module tests that parsers are automatically registered on import
and that the registry functions (get_parser, available_parsers) work correctly.
"""

import pytest

pytestmark = pytest.mark.unit
from agentic_inquiry.parsers.executor import (
    get_parser,
    get_parser_instance,
    available_parsers,
    ParserProtocol,
)

# Import implementations module to trigger auto-registration
from agentic_inquiry.parsers import implementations  # noqa: F401


def test_parsers_auto_registered():
    """Test that parsers are automatically registered on module import."""
    # Get list of available parsers
    parsers = available_parsers()

    # Should have at least the fallback_text parser (no dependencies)
    assert len(parsers) > 0, "No parsers were registered"
    assert "fallback_text" in parsers, (
        "Fallback text parser should always be registered (no dependencies)"
    )

    # Log what was registered for debugging
    print(f"Registered parsers: {parsers}")


def test_get_parser_retrieves_callable():
    """Test that get_parser() retrieves a callable parser."""
    # Get the fallback_text parser (should always be available)
    parser = get_parser("fallback_text")

    # Should be callable
    assert callable(parser), "Parser should be callable"


def test_get_parser_instance_retrieves_protocol():
    """Test that get_parser_instance() retrieves a ParserProtocol instance."""
    # Get the fallback_text parser instance
    parser_instance = get_parser_instance("fallback_text")

    # Should implement ParserProtocol
    assert isinstance(parser_instance, ParserProtocol), (
        "Parser instance should implement ParserProtocol"
    )

    # Should have parse method
    assert hasattr(parser_instance, "parse"), "Parser instance should have parse method"


def test_get_parser_raises_on_unknown():
    """Test that get_parser() raises KeyError for unknown parser."""
    with pytest.raises(KeyError, match="not registered"):
        get_parser("nonexistent_parser")


def test_available_parsers_returns_tuple():
    """Test that available_parsers() returns a tuple of strings."""
    parsers = available_parsers()

    # Should be a tuple
    assert isinstance(parsers, tuple), "available_parsers() should return a tuple"

    # All elements should be strings
    assert all(isinstance(p, str) for p in parsers), (
        "All parser names should be strings"
    )


def test_registered_parser_names():
    """Test that parsers are registered with correct descriptive names."""
    parsers = available_parsers()

    # Fallback text parser should always be registered (no dependencies)
    assert "fallback_text" in parsers, (
        "Fallback text parser should be registered as 'fallback_text'"
    )

    # If unified_code is registered, check the name
    if "unified_code" in parsers:
        parser = get_parser_instance("unified_code")
        assert hasattr(parser, "parse"), "unified_code should have parse method"

    # If document is registered, check the name
    if "document" in parsers:
        parser = get_parser_instance("document")
        assert hasattr(parser, "parse"), "document should have parse method"


@pytest.mark.asyncio
async def test_parser_can_parse_method():
    """Test that parsers with can_parse method are accessible."""
    parsers = available_parsers()

    for parser_name in parsers:
        parser_instance = get_parser_instance(parser_name)

        # Check if parser has can_parse method
        if hasattr(parser_instance, "can_parse"):
            # Should be callable
            assert callable(parser_instance.can_parse), (
                f"{parser_name} can_parse should be callable"
            )

            # Should accept a path argument
            # Test with a dummy path
            try:
                result = await parser_instance.can_parse("/tmp/test.txt")
                assert isinstance(result, bool), (
                    f"{parser_name} can_parse should return bool"
                )
            except Exception as e:
                pytest.fail(f"{parser_name} can_parse raised unexpected error: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
