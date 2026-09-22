"""Property tests for relationship counting optimization.

Feature: code-review-dec-2024-fixes, Property 12: Chunk relationships called once
Validates: Requirements 7.2
"""

import pytest

pytestmark = pytest.mark.integration

from unittest.mock import patch
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

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

    def generate(self, texts):
        return [[float(len(text))] for text in texts]

    def ndims(self):
        return self._ndims


async def create_graph_builder_setup():
    """Create GraphBuilder with dependencies for testing."""
    import uuid
    
    config = Config.load()
    registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
    mock_db_manager = InMemoryLanceDBManager(uri=f"memory://test-property-{uuid.uuid4().hex[:8]}")
    await mock_db_manager.create_tables_and_indexes()
    await mock_db_manager.connect()
    
    project_id = f"test_{uuid.uuid4().hex[:8]}"
    project_hash = project_id
    project_root = config.storage.root
    
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
    
    return {
        "graph_builder": graph_builder,
        "document_processor": document_processor,
    }


# Strategy for generating ParserChunks with relationships
@st.composite
def parser_chunk_with_relationships(draw):
    """Generate a ParserChunk with random relationships."""
    # Generate 0-5 relationships per chunk
    num_relationships = draw(st.integers(min_value=0, max_value=5))
    
    relationships = []
    for i in range(num_relationships):
        rel = ParserRelationship(
            source_name=f"source_{i}",
            source_type="function",
            target_name=f"target_{i}",
            target_type="function",
            type="imports",
        )
        relationships.append(rel)
    
    # Create chunk with or without symbols
    has_symbols = draw(st.booleans())
    
    if has_symbols:
        chunk = ParserChunk(
            content="def func():\n    pass",
            symbols=["func"],
            symbol_metadata={"func": {"type": "function"}},
            relationships=relationships if relationships else None,
        )
    else:
        chunk = ParserChunk(
            content="# Heading",
            element_name="Heading",
            element_type="heading",
            symbols=[],
            relationships=relationships if relationships else None,
        )
    
    return chunk


# Feature: code-review-dec-2024-fixes, Property 12: Chunk relationships called once
@pytest.mark.asyncio
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
@given(
    chunks=st.lists(parser_chunk_with_relationships(), min_size=1, max_size=10)
)
async def test_chunk_relationships_called_once_per_chunk(chunks):
    """Property: _chunk_relationships should be called exactly once per chunk.
    
    For any list of chunks with relationships, when processing them through
    create_graph_entities, the _chunk_relationships method should be called
    exactly once per chunk (not twice for counting and processing).
    
    Validates: Requirements 7.2
    """
    setup = await create_graph_builder_setup()
    graph_builder = setup["graph_builder"]
    document_processor = setup["document_processor"]
    
    # Create a parsed document with the generated chunks
    parsed_document = ParsedDocument(
        doc_id="test-doc",
        file_path="test.py",
        chunks=chunks,
    )
    
    # Mock _chunk_relationships to track calls
    original_chunk_relationships = graph_builder._chunk_relationships
    call_count = {}
    
    def tracked_chunk_relationships(chunk):
        """Track calls to _chunk_relationships."""
        chunk_id = id(chunk)
        call_count[chunk_id] = call_count.get(chunk_id, 0) + 1
        return original_chunk_relationships(chunk)
    
    # Patch the method
    with patch.object(graph_builder, '_chunk_relationships', side_effect=tracked_chunk_relationships):
        # Process the chunks
        await graph_builder.create_graph_entities(
            parsed_document=parsed_document,
            chunks=chunks,
            document_processor=document_processor,
        )
    
    # Verify: Each chunk should have _chunk_relationships called exactly once
    for chunk in chunks:
        chunk_id = id(chunk)
        if chunk.relationships:
            # Chunks with relationships should have the method called exactly once
            assert call_count.get(chunk_id, 0) == 1, (
                f"Chunk with {len(chunk.relationships)} relationships had "
                f"_chunk_relationships called {call_count.get(chunk_id, 0)} times, expected 1"
            )
        else:
            # Chunks without relationships might not have the method called at all
            # or called once (depending on implementation), but never more than once
            assert call_count.get(chunk_id, 0) <= 1, (
                f"Chunk without relationships had _chunk_relationships called "
                f"{call_count.get(chunk_id, 0)} times, expected 0 or 1"
            )


@pytest.mark.asyncio
async def test_relationship_count_matches_pending_queue():
    """Test that the logged count matches the actual pending queue size.
    
    This is a unit test to verify that the tracked count during processing
    matches the actual number of relationships added to the pending queue.
    
    Validates: Requirements 7.1, 7.3, 7.4
    """
    setup = await create_graph_builder_setup()
    graph_builder = setup["graph_builder"]
    document_processor = setup["document_processor"]
    
    # Create chunks with known number of relationships
    chunks = [
        ParserChunk(
            content="def foo():\n    pass",
            symbols=["foo"],
            symbol_metadata={"foo": {"type": "function"}},
            relationships=[
                ParserRelationship(
                    source_name="foo",
                    source_type="function",
                    target_name="bar",
                    target_type="function",
                    type="imports",
                ),
                ParserRelationship(
                    source_name="foo",
                    source_type="function",
                    target_name="baz",
                    target_type="function",
                    type="calls",
                ),
            ],
        ),
        ParserChunk(
            content="class Bar:\n    pass",
            symbols=["Bar"],
            symbol_metadata={"Bar": {"type": "class"}},
            relationships=[
                ParserRelationship(
                    source_name="Bar",
                    source_type="class",
                    target_name="Base",
                    target_type="class",
                    type="inherits",
                ),
            ],
        ),
    ]
    
    parsed_document = ParsedDocument(
        doc_id="test-doc",
        file_path="test.py",
        chunks=chunks,
    )
    
    # Clear any existing pending relationships
    graph_builder.clear_pending_relationships()
    
    # Process the chunks
    entities, stats = await graph_builder.create_graph_entities(
        parsed_document=parsed_document,
        chunks=chunks,
        document_processor=document_processor,
    )
    
    # Verify: The pending queue should have exactly 3 relationships (2 + 1)
    assert len(graph_builder._pending_relationships) == 3, (
        f"Expected 3 relationships in pending queue, got {len(graph_builder._pending_relationships)}"
    )
    
    # Verify: The logged count should match (we can't directly test the log,
    # but we can verify the count is correct by checking the pending queue)
    expected_count = sum(len(chunk.relationships) for chunk in chunks if chunk.relationships)
    assert len(graph_builder._pending_relationships) == expected_count, (
        f"Expected {expected_count} relationships, got {len(graph_builder._pending_relationships)}"
    )
