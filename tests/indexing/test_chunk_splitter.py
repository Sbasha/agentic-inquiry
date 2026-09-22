"""Tests for chunk content size splitting."""

from __future__ import annotations

import pytest

from agentic_inquiry.indexing.chunk_splitter import (
    MIN_CHUNK_SIZE,
    _hard_split,
    _split_content,
    _split_on_separator,
    split_parser_chunks,
)
from agentic_inquiry.parsers.models import ParserChunk


def _make_chunk(content: str, **kwargs) -> ParserChunk:
    """Helper to create a ParserChunk with minimal fields."""
    defaults = {
        "content": content,
        "content_type": "code",
        "language": "python",
        "element_type": "function",
        "element_name": "test_func",
        "line_start": 1,
        "line_end": 10,
    }
    defaults.update(kwargs)
    return ParserChunk(**defaults)


class TestSplitParserChunks:
    """Tests for split_parser_chunks()."""

    def test_no_split_needed(self) -> None:
        """Chunks under max_size pass through unchanged."""
        chunks = [_make_chunk("short content")]
        result = split_parser_chunks(chunks, max_size=1000)
        assert len(result) == 1
        assert result[0].content == "short content"

    def test_exact_size_no_split(self) -> None:
        """Content exactly at max_size is not split."""
        content = "x" * 500
        chunks = [_make_chunk(content)]
        result = split_parser_chunks(chunks, max_size=500)
        assert len(result) == 1
        assert result[0].content == content

    def test_one_char_over_splits(self) -> None:
        """Content 1 char over max_size triggers split."""
        content = "x" * 501
        chunks = [_make_chunk(content)]
        result = split_parser_chunks(chunks, max_size=500)
        assert len(result) == 2
        assert all(len(c.content) <= 500 for c in result)
        # Content preserved
        assert "".join(c.content for c in result) == content

    def test_paragraph_boundary_split(self) -> None:
        """Prefers splitting on paragraph boundaries (\\n\\n)."""
        para1 = "a" * 300
        para2 = "b" * 300
        content = f"{para1}\n\n{para2}"
        chunks = [_make_chunk(content)]
        result = split_parser_chunks(chunks, max_size=400)
        assert len(result) == 2
        assert result[0].content == para1
        assert result[1].content == para2

    def test_line_boundary_fallback(self) -> None:
        """Falls back to line boundaries when paragraphs are too large."""
        # One big paragraph with lines
        lines = ["x" * 100 for _ in range(5)]
        content = "\n".join(lines)
        chunks = [_make_chunk(content)]
        result = split_parser_chunks(chunks, max_size=250)
        assert len(result) >= 2
        assert all(len(c.content) <= 250 for c in result)

    def test_hard_split_fallback(self) -> None:
        """Falls back to hard split when no line boundaries exist."""
        content = "x" * 1000  # No newlines at all
        chunks = [_make_chunk(content)]
        result = split_parser_chunks(chunks, max_size=300)
        assert len(result) == 4  # ceil(1000/300) = 4
        assert all(len(c.content) <= 300 for c in result)
        assert "".join(c.content for c in result) == content

    def test_metadata_preserved(self) -> None:
        """Sub-chunks inherit parent metadata."""
        chunk = _make_chunk(
            "a" * 600,
            content_type="documentation",
            language="markdown",
            element_type="section",
            element_name="Overview",
            line_start=10,
            line_end=50,
            page_number=3,
            metadata={"source": "readme"},
        )
        result = split_parser_chunks([chunk], max_size=400)
        assert len(result) >= 2
        for sub in result:
            assert sub.content_type == "documentation"
            assert sub.language == "markdown"
            assert sub.element_type == "section"
            assert sub.element_name == "Overview"
            assert sub.line_start == 10
            assert sub.line_end == 50
            assert sub.page_number == 3
            assert sub.metadata == {"source": "readme"}

    def test_empty_content_passthrough(self) -> None:
        """Empty content chunks pass through without splitting."""
        chunks = [_make_chunk(""), _make_chunk(None)]
        result = split_parser_chunks(chunks, max_size=500)
        assert len(result) == 2

    def test_mixed_chunks(self) -> None:
        """Mix of normal and oversized chunks."""
        chunks = [
            _make_chunk("small"),
            _make_chunk("x" * 1000),
            _make_chunk("also small"),
        ]
        result = split_parser_chunks(chunks, max_size=400)
        assert result[0].content == "small"
        assert result[-1].content == "also small"
        assert len(result) > 3  # The big one was split

    def test_min_size_validation(self) -> None:
        """Raises ValueError for max_size below minimum."""
        with pytest.raises(ValueError, match="must be >= 100"):
            split_parser_chunks([], max_size=50)

    def test_unicode_content(self) -> None:
        """Unicode multibyte content is handled correctly."""
        # Each emoji is multiple bytes but 1-2 chars
        content = "\U0001f600" * 600  # 600 emoji chars
        chunks = [_make_chunk(content)]
        result = split_parser_chunks(chunks, max_size=400)
        assert len(result) >= 2
        assert all(len(c.content) <= 400 for c in result)
        assert "".join(c.content for c in result) == content

    def test_very_large_content(self) -> None:
        """Handles very large content (500K chars) without error."""
        # Simulate the 4.2M char problem at smaller scale
        paragraphs = ["x" * 5000 for _ in range(100)]
        content = "\n\n".join(paragraphs)
        chunks = [_make_chunk(content)]
        result = split_parser_chunks(chunks, max_size=50000)
        assert all(len(c.content) <= 50000 for c in result)
        # All content accounted for (rejoin with separator should reconstruct)
        reconstructed = "\n\n".join(c.content for c in result)
        assert reconstructed == content


class TestSplitContent:
    """Tests for _split_content() internal function."""

    def test_paragraph_preferred(self) -> None:
        pieces = _split_content("aaa\n\nbbb\n\nccc", 5)
        assert pieces == ["aaa", "bbb", "ccc"]

    def test_line_fallback(self) -> None:
        pieces = _split_content("aaa\nbbb\nccc", 5)
        assert pieces == ["aaa", "bbb", "ccc"]

    def test_hard_fallback(self) -> None:
        pieces = _split_content("abcdef", 3)
        assert pieces == ["abc", "def"]


class TestSplitOnSeparator:
    """Tests for _split_on_separator() internal function."""

    def test_returns_none_for_oversized_segment(self) -> None:
        result = _split_on_separator("toolong", "\n", 3)
        assert result is None

    def test_groups_segments(self) -> None:
        result = _split_on_separator("a\nb\nc", "\n", 5)
        assert result is not None
        assert all(len(p) <= 5 for p in result)

    def test_single_segment_fits(self) -> None:
        result = _split_on_separator("hi", "\n\n", 100)
        assert result == ["hi"]


class TestHardSplit:
    """Tests for _hard_split() internal function."""

    def test_exact_division(self) -> None:
        assert _hard_split("abcdef", 3) == ["abc", "def"]

    def test_remainder(self) -> None:
        assert _hard_split("abcde", 3) == ["abc", "de"]

    def test_single_piece(self) -> None:
        assert _hard_split("ab", 5) == ["ab"]
