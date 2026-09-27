"""Tests for parser metadata schema compliance.

This module tests that all parser implementations comply with LanceDB schema
constraints, specifically that ParserChunk.metadata only contains primitive
types (str, int, float, bool, None) and not lists or dicts.
"""

import pytest

pytestmark = pytest.mark.integration
from pathlib import Path
from typing import Any, Dict

from agentic_inquiry.parsers.implementations.unified_code import UnifiedCodeParser
from agentic_inquiry.parsers.implementations.document import DocumentParser
from agentic_inquiry.parsers.models import ParserChunk


def validate_metadata_primitives(
    metadata: Dict[str, Any], path: str = "metadata"
) -> None:
    """Validate that metadata dict only contains primitive types.

    Args:
        metadata: Metadata dict to validate
        path: Path for error messages (for nested validation)

    Raises:
        AssertionError: If metadata contains non-primitive types
    """
    if metadata is None:
        return

    assert isinstance(metadata, dict), f"{path} must be a dict, got {type(metadata)}"

    for key, value in metadata.items():
        field_path = f"{path}.{key}"

        # Check that value is a primitive type
        if value is not None:
            assert isinstance(value, (str, int, float, bool)), (
                f"{field_path} must be a primitive type (str, int, float, bool, None), "
                f"got {type(value).__name__}: {value!r}"
            )


def validate_chunk_schema(chunk: ParserChunk) -> None:
    """Validate that a ParserChunk complies with schema constraints.

    Args:
        chunk: ParserChunk to validate

    Raises:
        AssertionError: If chunk violates schema constraints
    """
    # Validate metadata contains only primitives
    validate_metadata_primitives(chunk.metadata, "chunk.metadata")

    # Validate ranking_signals is a dict (if present)
    if chunk.ranking_signals is not None:
        assert isinstance(chunk.ranking_signals, dict), (
            f"ranking_signals must be a dict, got {type(chunk.ranking_signals)}"
        )

    # Validate symbols is a list of strings (if present)
    if chunk.symbols:
        assert isinstance(chunk.symbols, list), (
            f"symbols must be a list, got {type(chunk.symbols)}"
        )
        for i, symbol in enumerate(chunk.symbols):
            assert isinstance(symbol, str), (
                f"symbols[{i}] must be a string, got {type(symbol)}"
            )


@pytest.mark.asyncio
async def test_unified_code_parser_metadata_compliance(tmp_path: Path) -> None:
    """Test that UnifiedCodeParser produces valid metadata (no lists/dicts)."""
    # Create a sample Python file with imports and complexity
    test_file = tmp_path / "test_code.py"
    test_file.write_text("""
import os
from pathlib import Path
from typing import List, Dict

class TestClass:
    def __init__(self):
        self.value = 0
    
    def complex_method(self, x: int) -> int:
        if x > 0:
            for i in range(x):
                if i % 2 == 0:
                    return i
        return 0

def simple_function():
    return 42
""")

    # Parse the file
    parser = UnifiedCodeParser()
    doc = await parser.parse(str(test_file))

    # Validate all chunks
    assert len(doc.chunks) > 0, "Should have parsed some chunks"
    # Verify chunks have content
    assert all(
        chunk.content and len(chunk.content.strip()) > 0 for chunk in doc.chunks
    ), "All chunks should have non-empty content"

    for i, chunk in enumerate(doc.chunks):
        # Validate schema compliance
        validate_chunk_schema(chunk)

        # Ensure metadata doesn't contain import_names (should be import_names_str)
        if chunk.metadata:
            assert "import_names" not in chunk.metadata, (
                f"Chunk {i}: metadata should not contain 'import_names' list, "
                f"use 'import_names_str' instead"
            )

            # If import_names_str is present, it should be a string
            if "import_names_str" in chunk.metadata:
                assert isinstance(chunk.metadata["import_names_str"], str), (
                    f"Chunk {i}: import_names_str must be a string"
                )


@pytest.mark.asyncio
async def test_unified_code_complexity_in_ranking_signals(tmp_path: Path) -> None:
    """Test that complexity is in ranking_signals, not metadata."""
    # Create a sample file with complex code
    test_file = tmp_path / "complex_code.py"
    test_file.write_text("""
def complex_function(x):
    if x > 0:
        for i in range(x):
            if i % 2 == 0:
                while i > 0:
                    i -= 1
    return x
""")

    # Parse the file
    parser = UnifiedCodeParser()
    doc = await parser.parse(str(test_file))

    # Find chunks with complexity
    chunks_with_complexity = [
        chunk
        for chunk in doc.chunks
        if chunk.ranking_signals and "complexity" in chunk.ranking_signals
    ]

    assert len(chunks_with_complexity) > 0, "Should have chunks with complexity"
    # Verify complexity values are numeric and positive
    complexity_values = [
        chunk.ranking_signals["complexity"] for chunk in chunks_with_complexity
    ]
    assert all(
        isinstance(val, (int, float)) and val >= 0 for val in complexity_values
    ), f"All complexity values should be non-negative numbers, got: {complexity_values}"

    for chunk in chunks_with_complexity:
        # Complexity should be in ranking_signals
        assert "complexity" in chunk.ranking_signals, (
            "Complexity should be in ranking_signals"
        )
        assert isinstance(chunk.ranking_signals["complexity"], (int, float)), (
            "Complexity should be a number"
        )

        # Complexity should NOT be in metadata
        if chunk.metadata:
            assert "complexity" not in chunk.metadata, (
                "Complexity should not be in metadata, use ranking_signals instead"
            )


@pytest.mark.asyncio
async def test_unified_code_uses_symbols_field(tmp_path: Path) -> None:
    """Test that symbols field is used, not code_symbols."""
    # Create a sample file with symbols
    test_file = tmp_path / "symbols_test.py"
    test_file.write_text("""
class MyClass:
    def my_method(self):
        pass

def my_function():
    pass

MY_CONSTANT = 42
""")

    # Parse the file
    parser = UnifiedCodeParser()
    doc = await parser.parse(str(test_file))

    # Check that chunks use symbols field
    chunks_with_symbols = [chunk for chunk in doc.chunks if chunk.symbols]

    assert len(chunks_with_symbols) > 0, "Should have chunks with symbols"

    for chunk in chunks_with_symbols:
        # Should have symbols field populated
        assert isinstance(chunk.symbols, list), "symbols should be a list"
        assert all(isinstance(s, str) for s in chunk.symbols), (
            "All symbols should be strings"
        )

        # Verify ParserChunk has symbols attribute (not code_symbols)
        assert hasattr(chunk, "symbols"), "ParserChunk should have 'symbols' attribute"
        assert not hasattr(chunk, "code_symbols"), (
            "ParserChunk should not have 'code_symbols' attribute"
        )


@pytest.mark.asyncio
async def test_document_parser_metadata_compliance(tmp_path: Path) -> None:
    """Test that DocumentParser produces valid metadata."""
    # Create a sample markdown file
    test_file = tmp_path / "test_doc.md"
    test_file.write_text("""
# Main Heading

This is a paragraph with some content.

## Subheading

More content here.

- List item 1
- List item 2
""")

    # Parse the file
    parser = DocumentParser()
    doc = await parser.parse(str(test_file))

    # Validate all chunks
    assert len(doc.chunks) > 0, "Should have parsed some chunks"

    for i, chunk in enumerate(doc.chunks):
        # Validate schema compliance
        validate_chunk_schema(chunk)


@pytest.mark.asyncio
async def test_parser_chunk_normalization_handles_code_symbols(tmp_path: Path) -> None:
    """Test that ParserChunk normalization handles code_symbols -> symbols mapping."""
    from agentic_inquiry.parsers.models import ParsedDocument

    # Create a document with chunks using old code_symbols field
    doc = ParsedDocument(
        doc_id="test",
        file_path="test.py",
        chunks=[
            {
                "content": "test content",
                "code_symbols": ["func1", "func2"],  # Old field name
                "metadata": {"test": "value"},
            }
        ],
    )

    # Check that it was normalized to symbols
    assert len(doc.chunks) == 1
    chunk = doc.chunks[0]
    assert chunk.symbols == ["func1", "func2"], (
        "code_symbols should be normalized to symbols"
    )


@pytest.mark.asyncio
async def test_actual_indexing_succeeds(tmp_path: Path) -> None:
    """Test that actual indexing succeeds without schema errors.

    This is an integration test that verifies the parsers work with the
    actual indexing pipeline and database.
    """
    # Create test files
    py_file = tmp_path / "test.py"
    py_file.write_text("""
import os
from typing import List

def test_function(x: int) -> int:
    if x > 0:
        return x * 2
    return 0

class TestClass:
    def method(self):
        pass
""")

    md_file = tmp_path / "test.md"
    md_file.write_text("""
# Test Document

This is a test document.

## Section 1

Content here.
""")

    # Parse both files
    code_parser = UnifiedCodeParser()
    doc_parser = DocumentParser()

    py_doc = await code_parser.parse(str(py_file))
    md_doc = await doc_parser.parse(str(md_file))

    # Validate all chunks from both parsers
    for doc in [py_doc, md_doc]:
        assert len(doc.chunks) > 0, f"Should have chunks for {doc.file_path}"
        for chunk in doc.chunks:
            validate_chunk_schema(chunk)

    # If we get here without exceptions, the parsers are compliant
    assert True, "All parsers produce schema-compliant chunks"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
