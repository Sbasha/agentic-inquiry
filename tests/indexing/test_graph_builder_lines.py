"""Tests for GraphBuilder symbol line number handling.

These tests verify that GraphBuilder correctly uses symbol-level line numbers
from symbol_metadata when available, falling back to chunk-level line_start/line_end
when symbol_metadata does not contain line information.
"""

import pytest

pytestmark = pytest.mark.integration

from pathlib import Path

from agentic_inquiry.config import Config
from agentic_inquiry.embeddings.base import Embedder
from agentic_inquiry.embeddings.registry import EmbeddingRegistry
from agentic_inquiry.indexing.document_processor import DocumentProcessor
from agentic_inquiry.indexing.embedding_service import EmbeddingService
from agentic_inquiry.indexing.graph_builder import GraphBuilder
from agentic_inquiry.indexing.relationship_resolver import RelationshipResolver
from agentic_inquiry.indexing.symbol_registry import SymbolRegistry
from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk
from tests.utils.in_memory_lancedb_manager import InMemoryLanceDBManager


class _DummyEmbedder(Embedder):
    """Dummy embedder for testing."""

    def __init__(self):
        self._ndims = 1
        self.generated_texts = []

    def generate(self, texts):
        self.generated_texts.extend(texts)
        return [[float(len(text))] for text in texts]

    def ndims(self):
        return self._ndims


@pytest.fixture
async def graph_builder_setup():
    """Set up GraphBuilder with dependencies."""
    import uuid

    Config.load()
    registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
    mock_db_manager = InMemoryLanceDBManager(uri="memory://test-graph-builder-lines")
    await mock_db_manager.create_tables_and_indexes()
    await mock_db_manager.connect()

    project_id = f"test_{uuid.uuid4().hex[:8]}"
    project_hash = project_id
    project_root = str(Path.cwd())

    symbol_registry = SymbolRegistry(project_root, project_hash)
    relationship_resolver = RelationshipResolver(
        symbol_registry=symbol_registry,
        project_root=project_root,
        db_manager=mock_db_manager,
    )
    embedding_service = EmbeddingService(registry=registry)
    document_processor = DocumentProcessor(
        project_hash=project_hash, project_id=project_id
    )

    graph_builder = GraphBuilder(
        db_manager=mock_db_manager,
        symbol_registry=symbol_registry,
        relationship_resolver=relationship_resolver,
        embedding_service=embedding_service,
        project_id=project_id,
        project_hash=project_hash,
        project_root=project_root,
    )

    yield {
        "graph_builder": graph_builder,
        "mock_db_manager": mock_db_manager,
        "document_processor": document_processor,
        "project_id": project_id,
        "project_hash": project_hash,
    }


@pytest.mark.asyncio
async def test_symbol_line_numbers_from_metadata(graph_builder_setup):
    """Graph builder uses symbol_metadata line numbers when available.

    When a chunk has line_start=-1 (full-file fallback scenario), but
    symbol_metadata contains start_line and end_line for a symbol,
    the resulting GraphEntity should use the symbol-level line numbers.
    """
    setup = graph_builder_setup
    graph_builder = setup["graph_builder"]
    document_processor = setup["document_processor"]

    # Create a parsed document with line_start=-1 (full-file fallback)
    # but symbol_metadata with specific line numbers
    parsed_document = ParsedDocument(
        doc_id="doc-lines-1",
        file_path="test_lines.py",
        chunks=[
            ParserChunk(
                content="class MyClass:\n    def method(self):\n        pass",
                line_start=-1,  # Full-file fallback scenario
                line_end=-1,
                symbols=["MyClass"],
                symbol_metadata={
                    "MyClass": {
                        "type": "class",
                        "start_line": 10,  # Symbol-level line number
                        "end_line": 50,
                    }
                },
            ),
        ],
    )

    # Create graph entities
    entities, stats = await graph_builder.create_graph_entities(
        parsed_document=parsed_document,
        chunks=parsed_document.chunks,
        document_processor=document_processor,
    )

    # Should have 2 entities: 1 file entity + 1 code entity
    assert len(entities) == 2
    assert stats["code_entities"] == 1

    # Find the MyClass entity (second entity after file entity)
    myclass_entity = entities[1]
    assert myclass_entity.name == "MyClass"
    assert myclass_entity.type == "class"

    # Verify line numbers come from symbol_metadata, not chunk level
    assert myclass_entity.line_start == 10, (
        f"Expected line_start=10 from symbol_metadata, got {myclass_entity.line_start}"
    )
    assert myclass_entity.line_end == 50, (
        f"Expected line_end=50 from symbol_metadata, got {myclass_entity.line_end}"
    )


@pytest.mark.asyncio
async def test_symbol_line_numbers_fallback_to_chunk(graph_builder_setup):
    """Graph builder falls back to chunk line numbers when metadata missing.

    When symbol_metadata does not contain line information for a symbol,
    the resulting GraphEntity should use the chunk-level line_start/line_end.
    """
    setup = graph_builder_setup
    graph_builder = setup["graph_builder"]
    document_processor = setup["document_processor"]

    # Create a parsed document with chunk-level line numbers
    # but no line numbers in symbol_metadata
    parsed_document = ParsedDocument(
        doc_id="doc-lines-2",
        file_path="test_fallback.py",
        chunks=[
            ParserChunk(
                content="def my_function():\n    return 42",
                line_start=50,  # Chunk-level line number
                line_end=75,
                symbols=["my_function"],
                symbol_metadata={
                    "my_function": {
                        "type": "function",
                        # No start_line or end_line here
                    }
                },
            ),
        ],
    )

    # Create graph entities
    entities, stats = await graph_builder.create_graph_entities(
        parsed_document=parsed_document,
        chunks=parsed_document.chunks,
        document_processor=document_processor,
    )

    # Should have 2 entities: 1 file entity + 1 code entity
    assert len(entities) == 2
    assert stats["code_entities"] == 1

    # Find the my_function entity (second entity after file entity)
    func_entity = entities[1]
    assert func_entity.name == "my_function"
    assert func_entity.type == "function"

    # Verify line numbers fall back to chunk-level values
    assert func_entity.line_start == 50, (
        f"Expected line_start=50 from chunk, got {func_entity.line_start}"
    )
    assert func_entity.line_end == 75, (
        f"Expected line_end=75 from chunk, got {func_entity.line_end}"
    )


@pytest.mark.asyncio
async def test_symbol_line_numbers_empty_symbol_metadata(graph_builder_setup):
    """Graph builder falls back to chunk line numbers when symbol_metadata empty.

    When symbol_metadata is completely empty (no entry for the symbol),
    the resulting GraphEntity should use the chunk-level line_start/line_end.
    """
    setup = graph_builder_setup
    graph_builder = setup["graph_builder"]
    document_processor = setup["document_processor"]

    # Create a parsed document with chunk-level line numbers
    # and completely empty symbol_metadata
    parsed_document = ParsedDocument(
        doc_id="doc-lines-3",
        file_path="test_empty_metadata.py",
        chunks=[
            ParserChunk(
                content="def another_function():\n    pass",
                line_start=100,
                line_end=125,
                symbols=["another_function"],
                symbol_metadata={},  # Empty - no entry for the symbol
            ),
        ],
    )

    # Create graph entities
    entities, stats = await graph_builder.create_graph_entities(
        parsed_document=parsed_document,
        chunks=parsed_document.chunks,
        document_processor=document_processor,
    )

    # Should have 2 entities: 1 file entity + 1 code entity
    assert len(entities) == 2
    assert stats["code_entities"] == 1

    # Find the another_function entity
    func_entity = entities[1]
    assert func_entity.name == "another_function"

    # Verify line numbers fall back to chunk-level values
    assert func_entity.line_start == 100, (
        f"Expected line_start=100 from chunk, got {func_entity.line_start}"
    )
    assert func_entity.line_end == 125, (
        f"Expected line_end=125 from chunk, got {func_entity.line_end}"
    )


@pytest.mark.asyncio
async def test_symbol_line_numbers_mixed_metadata(graph_builder_setup):
    """Graph builder handles mixed line number sources correctly.

    When a chunk has multiple symbols, some with symbol_metadata line numbers
    and some without, each entity should use the appropriate source.
    """
    setup = graph_builder_setup
    graph_builder = setup["graph_builder"]
    document_processor = setup["document_processor"]

    # Create a parsed document with multiple symbols
    # One has symbol_metadata line numbers, one does not
    parsed_document = ParsedDocument(
        doc_id="doc-lines-4",
        file_path="test_mixed.py",
        chunks=[
            ParserChunk(
                content="class First:\n    pass\n\nclass Second:\n    pass",
                line_start=1,  # Chunk-level fallback
                line_end=5,
                symbols=["First", "Second"],
                symbol_metadata={
                    "First": {
                        "type": "class",
                        "start_line": 10,  # Has symbol-level lines
                        "end_line": 20,
                    },
                    "Second": {
                        "type": "class",
                        # No line numbers - should fallback to chunk
                    },
                },
            ),
        ],
    )

    # Create graph entities
    entities, stats = await graph_builder.create_graph_entities(
        parsed_document=parsed_document,
        chunks=parsed_document.chunks,
        document_processor=document_processor,
    )

    # Should have 3 entities: 1 file entity + 2 code entities
    assert len(entities) == 3
    assert stats["code_entities"] == 2

    # Find entities by name
    first_entity = next(e for e in entities if e.name == "First")
    second_entity = next(e for e in entities if e.name == "Second")

    # First entity should use symbol_metadata line numbers
    assert first_entity.line_start == 10, (
        f"First: Expected line_start=10 from symbol_metadata, got {first_entity.line_start}"
    )
    assert first_entity.line_end == 20, (
        f"First: Expected line_end=20 from symbol_metadata, got {first_entity.line_end}"
    )

    # Second entity should fallback to chunk-level line numbers
    assert second_entity.line_start == 1, (
        f"Second: Expected line_start=1 from chunk fallback, got {second_entity.line_start}"
    )
    assert second_entity.line_end == 5, (
        f"Second: Expected line_end=5 from chunk fallback, got {second_entity.line_end}"
    )
