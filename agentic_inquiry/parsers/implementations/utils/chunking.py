"""Text chunking utilities for parsers.

This module provides stateless functions for chunking text content using various
strategies, reducing duplication across parser modules.

Copied from akb_iq and adapted for the new parser registry system.
"""

import re
from typing import List


def chunk_text_by_tokens(text: str, max_tokens: int = 500, overlap: int = 50) -> List[str]:
    """Chunk text by approximate token count.

    Args:
        text: Text to chunk
        max_tokens: Maximum tokens per chunk (approximate)
        overlap: Number of tokens to overlap between chunks

    Returns:
        List of text chunks
    """
    if not text.strip():
        return []

    # Rough approximation: 1 token ≈ 4 characters
    chars_per_token = 4
    max_chars = max_tokens * chars_per_token
    overlap_chars = overlap * chars_per_token

    chunks = []
    start = 0

    while start < len(text):
        # Find chunk end
        end = start + max_chars

        if end >= len(text):
            # Last chunk
            chunks.append(text[start:])
            break

        # Try to break at word boundary
        chunk_end = _find_word_boundary(text, end, start)
        chunks.append(text[start:chunk_end])

        # Move start with overlap
        start = max(start + 1, chunk_end - overlap_chars)

    return [chunk for chunk in chunks if chunk.strip()]


def chunk_text_by_lines(text: str, max_lines: int = 50, overlap: int = 5) -> List[str]:
    """Chunk text by line count with overlap.

    Args:
        text: Text to chunk
        max_lines: Maximum lines per chunk
        overlap: Number of lines to overlap between chunks

    Returns:
        List of text chunks
    """
    if not text.strip():
        return []

    lines = text.split("\n")
    if len(lines) <= max_lines:
        return [text]

    chunks = []
    start = 0

    while start < len(lines):
        end = min(start + max_lines, len(lines))
        chunk_lines = lines[start:end]
        chunks.append("\n".join(chunk_lines))

        if end >= len(lines):
            break

        # Move start with overlap
        start = end - overlap

    return [chunk for chunk in chunks if chunk.strip()]


def merge_small_chunks(chunks: List[str], min_size: int = 100) -> List[str]:
    """Merge chunks that are smaller than minimum size.

    Args:
        chunks: List of text chunks
        min_size: Minimum character count for chunks

    Returns:
        List of merged chunks
    """
    if not chunks:
        return []

    merged = []
    current_chunk = ""

    for chunk in chunks:
        if not chunk.strip():
            continue

        # If current chunk + new chunk is still reasonable size
        combined = current_chunk + "\n\n" + chunk if current_chunk else chunk

        if len(current_chunk) < min_size or len(combined) < min_size * 2:
            current_chunk = combined
        else:
            # Save current chunk and start new one
            if current_chunk:
                merged.append(current_chunk)
            current_chunk = chunk

    # Add final chunk
    if current_chunk:
        merged.append(current_chunk)

    return merged


def _find_word_boundary(text: str, preferred_end: int, min_pos: int) -> int:
    """Find nearest word boundary before preferred_end position.

    Args:
        text: Text to search in
        preferred_end: Preferred ending position
        min_pos: Minimum position to consider

    Returns:
        Position of word boundary
    """
    if preferred_end >= len(text):
        return len(text)

    # Look backward for word boundaries
    search_start = max(min_pos, preferred_end - 100)
    search_text = text[search_start:preferred_end]

    # Try different boundary patterns in order of preference
    patterns = [
        r"\n\n",  # Paragraph breaks
        r"\.\s+",  # Sentence endings
        r"\n",  # Line breaks
        r"\s+",  # Any whitespace
    ]

    for pattern in patterns:
        matches = list(re.finditer(pattern, search_text))
        if matches:
            last_match = matches[-1]
            return search_start + last_match.end()

    # Fallback to preferred end
    return preferred_end
