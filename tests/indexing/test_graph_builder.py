"""Tests for GraphBuilder component."""

import pytest

pytestmark = pytest.mark.integration

import logging

from agentic_inquiry.config import Config
from agentic_inquiry.embeddings.base import Embedder
from agentic_inquiry.embeddings.registry import EmbeddingRegistry
from agentic_inquiry.indexing.document_processor import DocumentProcessor
from agentic_inquiry.indexing.embedding_service import EmbeddingService
from agentic_inquiry.indexing.graph_builder import GraphBuilder
from agentic_inquiry.indexing.relationship_resolver import RelationshipResolver
from agentic_inquiry.indexing.symbol_registry import SymbolRegistry
from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk, ParserRelationship
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
    
    from pathlib import Path

    Config.load()
    registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
    mock_db_manager = InMemoryLanceDBManager(uri="memory://test-graph-builder")
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
    document_processor = DocumentProcessor(project_hash=project_hash, project_id=project_id)
    
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
async def test_create_graph_entities_with_document_entities(graph_builder_setup):
    """Test creating graph entities from document entities."""
    setup = graph_builder_setup
    graph_builder = setup["graph_builder"]
    document_processor = setup["document_processor"]
    project_id = setup["project_id"]
    
    # Create a parsed document with document entities
    parsed_document = ParsedDocument(
        doc_id="doc-1",
        file_path="test.md",
        chunks=[
            ParserChunk(
                content="# Introduction",
                element_name="Introduction",
                element_type="heading",
                symbols=[],
            ),
            ParserChunk(
                content="## Background",
                element_name="Background",
                element_type="heading",
                symbols=[],
            ),
        ],
    )
    
    # Create graph entities
    entities, stats = await graph_builder.create_graph_entities(
        parsed_document=parsed_document,
        chunks=parsed_document.chunks,
        document_processor=document_processor,
    )
    
    # Verify entities were created (1 file entity + 2 document entities)
    assert len(entities) == 3
    assert stats["file_entities"] == 1
    assert stats["document_entities"] == 2
    assert stats["code_entities"] == 0

    # Verify file entity properties (first entity)
    assert entities[0].name.endswith("test.md")
    assert entities[0].type == "file"
    assert entities[0].file_path.endswith("test.md")
    assert entities[0].project_id == project_id

    # Verify document entity properties (after file entity)
    assert entities[1].name == "Introduction"
    assert entities[1].type == "heading"
    assert entities[1].file_path.endswith("test.md")
    assert entities[1].project_id == project_id
    assert entities[1].pagerank == 0.0

    assert entities[2].name == "Background"
    assert entities[2].type == "heading"


@pytest.mark.asyncio
async def test_create_graph_entities_with_code_entities(graph_builder_setup):
    """Test creating graph entities from code symbols."""
    setup = graph_builder_setup
    graph_builder = setup["graph_builder"]
    document_processor = setup["document_processor"]
    setup["project_id"]
    
    # Create a parsed document with code entities
    parsed_document = ParsedDocument(
        doc_id="doc-2",
        file_path="test.py",
        chunks=[
            ParserChunk(
                content="def foo():\n    pass",
                symbols=["foo"],
                symbol_metadata={"foo": {"type": "function"}},
                symbol_rankings={"foo": {"pagerank": 0.5}},
            ),
            ParserChunk(
                content="class Bar:\n    pass",
                symbols=["Bar"],
                symbol_metadata={"Bar": {"type": "class"}},
                symbol_rankings={"Bar": {"pagerank": 0.8}},
            ),
        ],
    )
    
    # Create graph entities
    entities, stats = await graph_builder.create_graph_entities(
        parsed_document=parsed_document,
        chunks=parsed_document.chunks,
        document_processor=document_processor,
    )
    
    # Verify entities were created (1 file entity + 2 code entities)
    assert len(entities) == 3
    assert stats["file_entities"] == 1
    assert stats["document_entities"] == 0
    assert stats["code_entities"] == 2

    # Verify file entity properties (first entity)
    assert entities[0].name.endswith("test.py")
    assert entities[0].type == "file"

    # Verify code entity properties (after file entity)
    assert entities[1].name == "foo"
    assert entities[1].type == "function"
    assert entities[1].pagerank == 0.5

    assert entities[2].name == "Bar"
    assert entities[2].type == "class"
    assert entities[2].pagerank == 0.8



@pytest.mark.asyncio
async def test_add_and_clear_pending_relationships(graph_builder_setup):
    """Test adding and clearing pending relationships."""
    setup = graph_builder_setup
    graph_builder = setup["graph_builder"]
    
    # Create test relationships
    rel1 = ParserRelationship(
        source_name="foo",
        source_type="function",
        target_name="bar",
        target_type="function",
        type="imports",
    )
    rel2 = ParserRelationship(
        source_name="baz",
        source_type="class",
        target_name="qux",
        target_type="class",
        type="imports",
    )
    
    # Add relationships
    graph_builder.add_pending_relationship(rel1, "test1.py")
    graph_builder.add_pending_relationship(rel2, "test2.py")
    
    # Verify relationships were added
    assert len(graph_builder._pending_relationships) == 2
    
    # Clear relationships
    graph_builder.clear_pending_relationships()
    
    # Verify relationships were cleared
    assert len(graph_builder._pending_relationships) == 0


@pytest.mark.asyncio
async def test_flush_pending_relationships_empty(graph_builder_setup, caplog):
    """Test flushing when there are no pending relationships."""
    setup = graph_builder_setup
    graph_builder = setup["graph_builder"]
    document_processor = setup["document_processor"]
    
    caplog.set_level(logging.INFO)
    
    # Flush with no pending relationships
    count = await graph_builder.flush_pending_relationships(
        document_processor=document_processor,
        use_two_pass=False,
    )
    
    # Verify no relationships were created
    assert count == 0
    assert any("No pending relationships" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_get_resolution_stats(graph_builder_setup):
    """Test getting resolution statistics."""
    setup = graph_builder_setup
    graph_builder = setup["graph_builder"]
    
    # Initially, stats should be None (no resolution performed yet)
    stats = graph_builder.get_resolution_stats()
    assert stats is None
    
    # Add a pending relationship
    rel = ParserRelationship(
        source_name="foo",
        source_type="function",
        target_name="bar",
        target_type="function",
        type="imports",
    )
    graph_builder.add_pending_relationship(rel, "test.py")
    
    # After flushing, stats should be populated
    document_processor = setup["document_processor"]
    await graph_builder.flush_pending_relationships(
        document_processor=document_processor,
        use_two_pass=False,
    )
    
    stats = graph_builder.get_resolution_stats()
    assert "total" in stats
    assert "resolved_cross_file" in stats
    assert "unresolved_external" in stats
    assert stats["total"] == 1


@pytest.mark.asyncio
async def test_create_graph_entities_with_relationships(graph_builder_setup):
    """Test that relationships are added to pending queue."""
    setup = graph_builder_setup
    graph_builder = setup["graph_builder"]
    document_processor = setup["document_processor"]
    
    # Create a parsed document with relationships
    parsed_document = ParsedDocument(
        doc_id="doc-3",
        file_path="test.py",
        chunks=[
            ParserChunk(
                content="import foo",
                symbols=["main"],
                symbol_metadata={"main": {"type": "function"}},
                relationships=[
                    ParserRelationship(
                        source_name="main",
                        source_type="function",
                        target_name="foo",
                        target_type="module",
                        type="imports",
                    )
                ],
            ),
        ],
    )
    
    # Create graph entities
    entities, stats = await graph_builder.create_graph_entities(
        parsed_document=parsed_document,
        chunks=parsed_document.chunks,
        document_processor=document_processor,
    )
    
    # Verify relationship was added to pending queue
    assert len(graph_builder._pending_relationships) == 1
    assert stats["code_entities"] == 1
