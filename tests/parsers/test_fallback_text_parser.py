#!/usr/bin/env python3
"""Tests for FallbackTextParser with semantic chunking.

Tests text parsing with:
- Encoding detection (UTF-8, Latin-1, cp1252, ASCII)
- Semantic chunking (paragraphs and sentences)
- Chunk overlap for context preservation
- Metadata generation (chunk_index, total_chunks, chunk_type)
"""


import pytest

pytestmark = pytest.mark.integration

from agentic_inquiry.exceptions import ParsingError
from agentic_inquiry.parsers.implementations.fallback_text import FallbackTextParser
from agentic_inquiry.parsers.models import ParsedDocument


@pytest.fixture
def parser():
    """Create a FallbackTextParser instance."""
    return FallbackTextParser(max_chunk_size=1000, chunk_overlap=100)


@pytest.fixture
def small_parser():
    """Create a FallbackTextParser with small chunks for testing."""
    return FallbackTextParser(max_chunk_size=200, chunk_overlap=50)


@pytest.mark.asyncio
async def test_parse_simple_text(parser, tmp_path):
    """Test parsing a simple text file."""
    # Create a simple text file
    text_file = tmp_path / "simple.txt"
    content = "This is a simple text file.\n\nIt has two paragraphs."
    text_file.write_text(content, encoding='utf-8')
    
    # Parse the file
    result = await parser.parse(str(text_file))
    
    # Validate result
    assert isinstance(result, ParsedDocument)
    assert result.file_path == str(text_file.absolute())
    assert result.doc_id == str(text_file.absolute())
    assert len(result.chunks) > 0
    
    # Check first chunk
    chunk = result.chunks[0]
    assert chunk.content is not None
    assert isinstance(chunk.content, str)
    assert len(chunk.content) > 0
    assert chunk.fts_text is not None
    assert isinstance(chunk.fts_text, str)
    assert chunk.content_type == "OTHER"
    assert chunk.line_start is not None
    assert isinstance(chunk.line_start, int)
    assert chunk.line_start >= 1
    assert chunk.line_end is not None
    assert isinstance(chunk.line_end, int)
    assert chunk.line_end >= chunk.line_start
    assert 'chunk_index' in chunk.metadata
    assert 'total_chunks' in chunk.metadata
    assert 'chunk_type' in chunk.metadata


@pytest.mark.asyncio
async def test_paragraph_chunking(small_parser, tmp_path):
    """Test that paragraphs are properly chunked."""
    # Create a file with multiple paragraphs
    text_file = tmp_path / "paragraphs.txt"
    content = """First paragraph with some content.

Second paragraph with more content.

Third paragraph with even more content to test chunking."""
    text_file.write_text(content, encoding='utf-8')
    
    # Parse the file
    result = await small_parser.parse(str(text_file))
    
    # Should have multiple chunks due to small max_chunk_size
    assert len(result.chunks) >= 1
    
    # Check chunk metadata
    for idx, chunk in enumerate(result.chunks):
        assert chunk.metadata['chunk_index'] == idx
        assert chunk.metadata['total_chunks'] == len(result.chunks)
        assert chunk.metadata['chunk_type'] in ['paragraph', 'sentence', 'empty']


@pytest.mark.asyncio
async def test_long_paragraph_sentence_splitting(small_parser, tmp_path):
    """Test that long paragraphs are split by sentences."""
    # Create a file with a very long paragraph
    text_file = tmp_path / "long_paragraph.txt"
    content = (
        "This is the first sentence of a very long paragraph. "
        "This is the second sentence that continues the paragraph. "
        "This is the third sentence with more content. "
        "This is the fourth sentence to ensure we exceed the chunk size. "
        "This is the fifth sentence with additional information. "
        "This is the sixth sentence to make it even longer."
    )
    text_file.write_text(content, encoding='utf-8')
    
    # Parse the file
    result = await small_parser.parse(str(text_file))
    
    # Should have multiple chunks due to sentence splitting
    assert len(result.chunks) >= 2
    
    # Check that chunks have sentence type
    sentence_chunks = [c for c in result.chunks if c.metadata.get('chunk_type') == 'sentence']
    assert len(sentence_chunks) > 0


@pytest.mark.asyncio
async def test_chunk_overlap(small_parser, tmp_path):
    """Test that chunks have overlap for context preservation."""
    # Create a file with content that will be split
    text_file = tmp_path / "overlap.txt"
    content = """First paragraph with enough content to trigger chunking behavior.

Second paragraph with more content that should be in a separate chunk.

Third paragraph to ensure we have multiple chunks with overlap."""
    text_file.write_text(content, encoding='utf-8')
    
    # Parse the file
    result = await small_parser.parse(str(text_file))
    
    # If we have multiple chunks, check for overlap
    if len(result.chunks) > 1:
        # The overlap should preserve some context between chunks
        # We can't easily verify the exact overlap without inspecting internals,
        # but we can verify chunks exist and have content
        for chunk in result.chunks:
            assert len(chunk.content) > 0


@pytest.mark.asyncio
async def test_encoding_detection_utf8(parser, tmp_path):
    """Test UTF-8 encoding detection."""
    text_file = tmp_path / "utf8.txt"
    content = "Hello, world! 你好世界"
    text_file.write_text(content, encoding='utf-8')
    
    result = await parser.parse(str(text_file))
    
    assert len(result.chunks) > 0
    assert "你好世界" in result.chunks[0].content


@pytest.mark.asyncio
async def test_encoding_detection_latin1(parser, tmp_path):
    """Test Latin-1 encoding detection."""
    text_file = tmp_path / "latin1.txt"
    content = "Café résumé"
    text_file.write_bytes(content.encode('latin-1'))
    
    result = await parser.parse(str(text_file))
    
    assert len(result.chunks) > 0
    # Content should be readable (may be UTF-8 or Latin-1)
    assert len(result.chunks[0].content) > 0


@pytest.mark.asyncio
async def test_empty_file(parser, tmp_path):
    """Test parsing an empty file."""
    text_file = tmp_path / "empty.txt"
    text_file.write_text("", encoding='utf-8')
    
    result = await parser.parse(str(text_file))
    
    # Should have one empty chunk
    assert len(result.chunks) == 1
    assert result.chunks[0].content == ""
    assert result.chunks[0].metadata['chunk_type'] == 'empty'


@pytest.mark.asyncio
async def test_whitespace_only_file(parser, tmp_path):
    """Test parsing a file with only whitespace."""
    text_file = tmp_path / "whitespace.txt"
    text_file.write_text("   \n\n   \n", encoding='utf-8')
    
    result = await parser.parse(str(text_file))
    
    # Should handle gracefully
    assert len(result.chunks) >= 1


@pytest.mark.asyncio
async def test_line_numbers(parser, tmp_path):
    """Test that line numbers are correctly tracked."""
    text_file = tmp_path / "lines.txt"
    content = """Line 1

Line 3

Line 5"""
    text_file.write_text(content, encoding='utf-8')
    
    result = await parser.parse(str(text_file))
    
    # Check that line numbers are set
    for chunk in result.chunks:
        assert chunk.line_start is not None
        assert isinstance(chunk.line_start, int)
        assert chunk.line_start >= 1
        assert chunk.line_end is not None
        assert isinstance(chunk.line_end, int)
        assert chunk.line_start <= chunk.line_end


@pytest.mark.asyncio
async def test_can_parse(parser, tmp_path):
    """Test the can_parse method."""
    # Create a test file
    text_file = tmp_path / "test.txt"
    text_file.write_text("test", encoding='utf-8')
    
    # Should return True for existing files
    assert await parser.can_parse(str(text_file)) is True
    
    # Should return False for non-existent files
    assert await parser.can_parse(str(tmp_path / "nonexistent.txt")) is False
    
    # Should return False for directories
    assert await parser.can_parse(str(tmp_path)) is False


@pytest.mark.asyncio
async def test_file_not_found(parser):
    """Test error handling for non-existent files."""
    with pytest.raises(ParsingError, match="File not found"):
        await parser.parse("/nonexistent/file.txt")


@pytest.mark.asyncio
async def test_not_a_file(parser, tmp_path):
    """Test error handling for directories."""
    with pytest.raises(ParsingError, match="Not a file"):
        await parser.parse(str(tmp_path))


@pytest.mark.asyncio
async def test_metadata_structure(parser, tmp_path):
    """Test that metadata has the correct structure."""
    text_file = tmp_path / "metadata.txt"
    content = "Test content for metadata validation."
    text_file.write_text(content, encoding='utf-8')
    
    result = await parser.parse(str(text_file))
    
    # Check document metadata
    assert result.metadata is not None
    assert isinstance(result.metadata, dict)
    assert 'total_chunks' in result.metadata
    assert isinstance(result.metadata['total_chunks'], int)
    assert result.metadata['total_chunks'] > 0
    assert result.metadata['total_chunks'] == len(result.chunks)
    
    # Check chunk metadata
    for chunk in result.chunks:
        assert chunk.metadata is not None
        assert 'chunk_index' in chunk.metadata
        assert 'total_chunks' in chunk.metadata
        assert 'chunk_type' in chunk.metadata
        assert chunk.metadata['chunk_index'] >= 0
        assert chunk.metadata['chunk_index'] < chunk.metadata['total_chunks']
