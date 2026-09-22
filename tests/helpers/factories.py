"""Test data factories.

Provides factory functions for creating test data objects.
"""

from typing import Dict, List, Optional
from agentic_inquiry.models.document_chunk import DocumentChunk
from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk


def create_test_chunk(
    content: str = "test content",
    doc_id: str = "test_doc",
    chunk_id: str = "chunk_0",
    metadata: Optional[Dict] = None,
    embedding: Optional[List[float]] = None,
) -> DocumentChunk:
    """Create a test DocumentChunk.

    Args:
        content: Chunk content
        doc_id: Document ID
        chunk_id: Chunk ID
        metadata: Chunk metadata
        embedding: Embedding vector

    Returns:
        DocumentChunk instance
    """
    return DocumentChunk(
        id=chunk_id,
        doc_id=doc_id,
        file_path="test_path",
        project_id="test_project",
        content=content,
        fts_text=content,
        vector=embedding or [0.0] * 384,
        metadata=metadata or {},
    )


def create_test_parsed_document(
    file_path: str = "test.py",
    content: str = "def test(): pass",
    language: str = "python",
    chunks: Optional[List[ParserChunk]] = None,
) -> ParsedDocument:
    """Create a test ParsedDocument.

    Args:
        file_path: File path
        content: File content
        language: Programming language
        chunks: List of parser chunks

    Returns:
        ParsedDocument instance
    """
    if chunks is None:
        chunks = [
            ParserChunk(
                content=content,
                content_type="code",
                language=language,
                line_start=1,
                line_end=1,
            )
        ]
    
    return ParsedDocument(
        doc_id="test_doc",
        file_path=file_path,
        chunks=chunks,
    )
