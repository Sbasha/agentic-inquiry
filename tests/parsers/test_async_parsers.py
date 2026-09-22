"""Tests for async parser implementations."""

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

pytestmark = pytest.mark.unit
from agentic_inquiry.parsers.implementations.fallback_text import FallbackTextParser
from agentic_inquiry.parsers.implementations.unified_code import UnifiedCodeParser
from agentic_inquiry.parsers.implementations.document import DocumentParser
from agentic_inquiry.parsers.chain import ParserChain
from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk


def _create_mock_event_system():
    """Create a mock event system for tests."""
    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    return mock_es


@pytest.mark.asyncio
async def test_fallback_text_parser_async_file_reading(tmp_path):
    """Test that FallbackTextParser reads files asynchronously."""
    # Create a test file
    test_file = tmp_path / "test.txt"
    test_content = "This is a test file.\n\nIt has multiple paragraphs.\n\nAnd some content."
    test_file.write_text(test_content)
    
    # Parse the file
    parser = FallbackTextParser()
    result = await parser.parse(str(test_file))
    
    # Verify result
    assert isinstance(result, ParsedDocument)
    assert result.file_path == str(test_file.absolute())
    assert len(result.chunks) > 0
    assert all(isinstance(chunk, ParserChunk) for chunk in result.chunks)


@pytest.mark.asyncio
async def test_fallback_text_parser_encoding_detection(tmp_path):
    """Test that FallbackTextParser handles different encodings."""
    # Create a test file with UTF-8 content
    test_file = tmp_path / "test_utf8.txt"
    test_content = "Hello, 世界! This is UTF-8 content."
    test_file.write_text(test_content, encoding='utf-8')
    
    # Parse the file
    parser = FallbackTextParser()
    result = await parser.parse(str(test_file))
    
    # Verify content was read correctly
    assert isinstance(result, ParsedDocument)
    assert len(result.chunks) > 0
    assert "世界" in result.chunks[0].content


@pytest.mark.asyncio
async def test_unified_code_parser_async_file_reading(tmp_path):
    """Test that UnifiedCodeParser reads files asynchronously."""
    # Create a test Python file
    test_file = tmp_path / "test.py"
    test_content = """
def hello_world():
    '''A simple function.'''
    print("Hello, world!")

class TestClass:
    '''A simple class.'''
    def method(self):
        pass
"""
    test_file.write_text(test_content)
    
    # Parse the file
    parser = UnifiedCodeParser()
    result = await parser.parse(str(test_file))
    
    # Verify result
    assert isinstance(result, ParsedDocument)
    assert result.file_path == str(test_file)
    assert len(result.chunks) > 0


@pytest.mark.asyncio
async def test_unified_code_parser_tree_sitter_in_executor(tmp_path):
    """Test that UnifiedCodeParser executes tree-sitter parsing in executor."""
    # Create a test Python file with complex code
    test_file = tmp_path / "complex.py"
    test_content = """
import os
import sys
from typing import List, Dict

class ComplexClass:
    def __init__(self, name: str):
        self.name = name
    
    def process(self, data: List[Dict]) -> None:
        for item in data:
            if item.get('valid'):
                self._handle_item(item)
    
    def _handle_item(self, item: Dict) -> None:
        pass

def main():
    obj = ComplexClass("test")
    obj.process([{"valid": True}])

if __name__ == "__main__":
    main()
"""
    test_file.write_text(test_content)
    
    # Parse the file
    parser = UnifiedCodeParser()
    result = await parser.parse(str(test_file))
    
    # Verify result
    assert isinstance(result, ParsedDocument)
    assert len(result.chunks) > 0
    # Should have extracted classes and functions
    assert any('ComplexClass' in chunk.content for chunk in result.chunks)


@pytest.mark.asyncio
async def test_document_parser_async_file_reading(tmp_path):
    """Test that DocumentParser reads files asynchronously."""
    # Create a test markdown file
    test_file = tmp_path / "test.md"
    test_content = """# Test Document

This is a test document with multiple sections.

## Section 1

Content for section 1.

## Section 2

Content for section 2.
"""
    test_file.write_text(test_content)
    
    # Parse the file
    parser = DocumentParser()
    result = await parser.parse(str(test_file))
    
    # Verify result
    assert isinstance(result, ParsedDocument)
    assert result.file_path == str(test_file)
    assert len(result.chunks) > 0


@pytest.mark.asyncio
async def test_document_parser_unstructured_in_executor(tmp_path):
    """Test that DocumentParser executes unstructured calls in executor."""
    # Create a test markdown file with complex structure
    test_file = tmp_path / "complex.md"
    test_content = """# Main Title

## Introduction

This is the introduction section with some content.

## Methods

### Method 1

Description of method 1.

### Method 2

Description of method 2.

## Results

The results section contains:

- Item 1
- Item 2
- Item 3

## Conclusion

Final thoughts and conclusions.
"""
    test_file.write_text(test_content)
    
    # Parse the file
    parser = DocumentParser()
    result = await parser.parse(str(test_file))
    
    # Verify result
    assert isinstance(result, ParsedDocument)
    assert len(result.chunks) > 0
    # Should have extracted headings and sections
    assert any('Main Title' in chunk.content or 'Introduction' in chunk.content for chunk in result.chunks)


@pytest.mark.asyncio
async def test_parser_chain_async_execution(tmp_path):
    """Test that ParserChain executes parsers asynchronously."""
    # Create a test file
    test_file = tmp_path / "test.txt"
    test_content = "This is a test file for parser chain."
    test_file.write_text(test_content)
    
    # Create parser chain
    chain = ParserChain(event_system=_create_mock_event_system(), parser_names=["fallback_text"])
    
    # Parse the file
    result = await chain.parse(str(test_file))
    
    # Verify result
    assert isinstance(result, ParsedDocument)
    assert result.file_path == str(test_file.absolute())


@pytest.mark.asyncio
async def test_concurrent_parsing(tmp_path):
    """Test that multiple files can be parsed concurrently."""
    # Create multiple test files
    files = []
    for i in range(5):
        test_file = tmp_path / f"test_{i}.txt"
        test_file.write_text(f"Content for file {i}")
        files.append(test_file)
    
    # Parse files concurrently
    parser = FallbackTextParser()
    tasks = [parser.parse(str(f)) for f in files]
    results = await asyncio.gather(*tasks)
    
    # Verify all files were parsed
    assert len(results) == 5
    assert all(isinstance(r, ParsedDocument) for r in results)
    assert all(len(r.chunks) > 0 for r in results)


@pytest.mark.asyncio
async def test_parser_chain_with_can_parse(tmp_path):
    """Test that ParserChain respects async can_parse method."""
    # Create a Python file
    test_file = tmp_path / "test.py"
    test_file.write_text("def hello(): pass")
    
    # Create parser chain with unified_code first
    chain = ParserChain(event_system=_create_mock_event_system(), parser_names=["unified_code", "fallback_text"])
    
    # Parse the file
    result = await chain.parse(str(test_file))
    
    # Verify result
    assert isinstance(result, ParsedDocument)
    # Should be parsed by unified_code parser
    assert result.metadata.get('language') == 'python' or 'python' in str(result.metadata)


@pytest.mark.asyncio
async def test_parser_chain_fallback_on_failure(tmp_path):
    """Test that ParserChain falls back to next parser on failure."""
    # Create a file that unified_code might fail on
    test_file = tmp_path / "test.unknown"
    test_file.write_text("Some random content")
    
    # Create parser chain
    chain = ParserChain(event_system=_create_mock_event_system(), parser_names=["unified_code", "document", "fallback_text"])
    
    # Parse the file - should fall back to fallback_text
    result = await chain.parse(str(test_file))
    
    # Verify result
    assert isinstance(result, ParsedDocument)
    assert len(result.chunks) > 0


@pytest.mark.asyncio
async def test_async_can_parse_methods(tmp_path):
    """Test that all parsers have async can_parse methods."""
    test_file = tmp_path / "test.py"
    test_file.write_text("def test(): pass")
    
    # Test FallbackTextParser
    fallback_parser = FallbackTextParser()
    can_parse = await fallback_parser.can_parse(str(test_file))
    assert isinstance(can_parse, bool)
    
    # Test UnifiedCodeParser
    unified_parser = UnifiedCodeParser()
    can_parse = await unified_parser.can_parse(str(test_file))
    assert isinstance(can_parse, bool)
    
    # Test DocumentParser
    doc_parser = DocumentParser()
    can_parse = await doc_parser.can_parse(str(test_file))
    assert isinstance(can_parse, bool)
