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
    return FallbackTextParser(max_chunk_size=1000)


@pytest.fixture
def small_parser():
    """Create a FallbackTextParser with small chunks for testing."""
    return FallbackTextParser(max_chunk_size=200)


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
        assert chunk.metadata['chunk_type'] in ['lines', 'empty']






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


@pytest.mark.asyncio
async def test_chunks_hold_exactly_their_lines(small_parser, tmp_path):
    """Every chunk's content is its line_start..line_end lines, with no overlap."""
    lines = [f"Line {i} of a transcript with some words." for i in range(1, 41)]
    lines[10] = ""
    text_file = tmp_path / "lines.txt"
    text_file.write_text("\n".join(lines) + "\n")

    result = await small_parser.parse(str(text_file))

    seen = []
    for chunk in result.chunks:
        assert chunk.content == "\n".join(lines[chunk.line_start - 1:chunk.line_end])
        assert len(chunk.content) <= 200
        seen.extend(range(chunk.line_start, chunk.line_end + 1))
    assert seen == sorted(set(seen))
    assert set(range(1, 41)) - {11} <= set(seen)



@pytest.mark.asyncio
async def test_binary_files_are_refused(parser, tmp_path):
    """A NUL byte in the first block marks the file as binary."""
    image = tmp_path / "logo.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 64)
    assert not await parser.can_parse(str(image))
    with pytest.raises(ParsingError):
        await parser.parse(str(image))


@pytest.mark.asyncio
async def test_markdown_chunks_carry_heading_scope(tmp_path):
    """Markdown chunks record the heading path where they start."""
    doc = tmp_path / "guide.md"
    doc.write_text(
        "# Guide\n\nIntro text.\n\n## Install\n\n```\n# not a heading\n```\n\nRun pip.\n\n"
        "## Usage\n\n" + "Call the client. " * 12 + "\n"
    )
    result = await FallbackTextParser(max_chunk_size=120).parse(str(doc))
    scopes = [c.metadata.get("scope") for c in result.chunks]
    assert all("not a heading" not in (s or "") for s in scopes)
    usage = [c for c in result.chunks if (c.metadata.get("scope") or "").endswith("Usage")]
    assert usage and usage[0].element_type == "section" and usage[0].element_name == "Usage"
    assert all(c.content_type == "PROSE" for c in result.chunks)
