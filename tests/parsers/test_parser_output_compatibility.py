"""Test that parser output is compatible with indexing/search expectations.

This test validates that UnifiedCodeParser produces ParsedDocument objects
with the correct structure expected by IndexingPipeline and SearchService.
"""

import pytest

pytestmark = pytest.mark.integration

import tempfile
from pathlib import Path

from agent_vault.parsers import ParsedDocument, ParserChunk
from agent_vault.parsers.executor import get_parser_instance

# Trigger parser auto-registration
import agent_vault.parsers.implementations  # noqa: F401


@pytest.fixture
def sample_python_file():
    """Create a sample Python file for testing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write('''
"""User management module."""
import os
from typing import List

class UserManager:
    """Manages user operations."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
    
    def add_user(self, username: str) -> bool:
        """Add a user."""
        return True
''')
        f.flush()
        yield Path(f.name)
    
    # Cleanup
    Path(f.name).unlink()


@pytest.mark.asyncio
async def test_parser_returns_parsed_document(sample_python_file):
    """Test that parser returns a ParsedDocument instance."""
    parser = get_parser_instance("unified_code")
    result = await parser.parse(str(sample_python_file))
    
    assert isinstance(result, ParsedDocument)


@pytest.mark.asyncio
async def test_parsed_document_has_required_fields(sample_python_file):
    """Test that ParsedDocument has all required fields."""
    parser = get_parser_instance("unified_code")
    doc = await parser.parse(str(sample_python_file))
    
    # Required fields
    assert hasattr(doc, 'doc_id')
    assert hasattr(doc, 'file_path')
    assert hasattr(doc, 'chunks')
    assert hasattr(doc, 'metadata')
    
    # Verify types
    assert isinstance(doc.doc_id, str)
    assert isinstance(doc.file_path, str)
    assert isinstance(doc.chunks, list)
    assert doc.metadata is None or isinstance(doc.metadata, dict)


@pytest.mark.asyncio
async def test_chunks_have_required_fields(sample_python_file):
    """Test that ParserChunk objects have required fields."""
    parser = get_parser_instance("unified_code")
    doc = await parser.parse(str(sample_python_file))
    
    assert len(doc.chunks) > 0, "Should have at least one chunk"
    
    for chunk in doc.chunks:
        assert isinstance(chunk, ParserChunk)
        
        # Required fields
        assert hasattr(chunk, 'content')
        assert hasattr(chunk, 'symbols')
        assert hasattr(chunk, 'relationships')
        assert hasattr(chunk, 'metadata')
        assert hasattr(chunk, 'ranking_signals')
        assert hasattr(chunk, 'fts_text')
        assert hasattr(chunk, 'language')
        
        # Verify types
        assert chunk.content is None or isinstance(chunk.content, str)
        assert isinstance(chunk.symbols, list)
        assert isinstance(chunk.relationships, list)
        assert chunk.metadata is None or isinstance(chunk.metadata, dict)
        assert chunk.ranking_signals is None or isinstance(chunk.ranking_signals, dict)
        assert chunk.fts_text is None or isinstance(chunk.fts_text, str)
        assert chunk.language is None or isinstance(chunk.language, str)


@pytest.mark.asyncio
async def test_code_symbols_extracted(sample_python_file):
    """Test that code symbols are extracted."""
    parser = get_parser_instance("unified_code")
    doc = await parser.parse(str(sample_python_file))
    
    # Collect all symbols
    all_symbols = []
    for chunk in doc.chunks:
        all_symbols.extend(chunk.symbols)
    
    # Should find the UserManager class
    assert "UserManager" in all_symbols, f"Should find UserManager in symbols: {all_symbols}"


@pytest.mark.asyncio
async def test_metadata_has_content_type(sample_python_file):
    """Test that metadata includes content_type field."""
    parser = get_parser_instance("unified_code")
    doc = await parser.parse(str(sample_python_file))
    
    # Check document metadata
    if doc.metadata:
        assert "content_type" in doc.metadata
        assert doc.metadata["content_type"] == "CODE"
    
    # Check chunk metadata
    for chunk in doc.chunks:
        if chunk.metadata:
            assert "content_type" in chunk.metadata
            assert chunk.metadata["content_type"] == "CODE"


@pytest.mark.asyncio
async def test_language_detected(sample_python_file):
    """Test that language is correctly detected."""
    parser = get_parser_instance("unified_code")
    doc = await parser.parse(str(sample_python_file))
    
    # Check chunks - language is a chunk-level field
    for chunk in doc.chunks:
        assert chunk.language == "python"


@pytest.mark.asyncio
async def test_fts_text_generated(sample_python_file):
    """Test that FTS text is generated for code chunks."""
    parser = get_parser_instance("unified_code")
    doc = await parser.parse(str(sample_python_file))
    
    # At least some chunks should have FTS text
    has_fts = any(chunk.fts_text for chunk in doc.chunks)
    assert has_fts, "At least one chunk should have fts_text"
    
    # FTS text should contain symbols
    for chunk in doc.chunks:
        if chunk.fts_text and chunk.symbols:
            # At least some symbols should be in FTS text
            fts_lower = chunk.fts_text.lower()
            symbol_found = any(sym.lower() in fts_lower for sym in chunk.symbols)
            assert symbol_found, f"FTS text should contain symbols: {chunk.symbols}"


@pytest.mark.asyncio
async def test_ranking_signals_present(sample_python_file):
    """Test that ranking signals are present."""
    parser = get_parser_instance("unified_code")
    doc = await parser.parse(str(sample_python_file))
    
    # At least some chunks should have ranking signals
    has_signals = any(chunk.ranking_signals for chunk in doc.chunks)
    assert has_signals, "At least one chunk should have ranking_signals"


@pytest.mark.asyncio
async def test_multiple_file_types():
    """Test that parser works with multiple file types."""
    test_files = {
        'test.py': 'def hello(): pass',
        'test.js': 'function hello() {}',
        'test.java': 'public class Test {}',
    }
    
    parser = get_parser_instance("unified_code")
    
    for filename, content in test_files.items():
        with tempfile.NamedTemporaryFile(mode='w', suffix=Path(filename).suffix, delete=False) as f:
            f.write(content)
            f.flush()
            
            try:
                doc = await parser.parse(f.name)
                assert isinstance(doc, ParsedDocument)
                assert len(doc.chunks) > 0
            finally:
                Path(f.name).unlink()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
