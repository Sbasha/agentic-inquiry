"""Test IndexingPipeline compatibility with migrated parsers.

This test suite verifies that:
1. ParsedDocument has all required fields
2. ParserChunk maps correctly to DocumentChunk
3. ParserRelationship maps correctly to GraphRelationship
4. process_document works with all migrated parsers
5. Data is correctly stored in LanceDB
"""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

pytestmark = pytest.mark.integration

from agentic_inquiry.embeddings.registry import EmbeddingRegistry
from agentic_inquiry.indexing.pipeline import IndexingPipeline
from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk, ParserRelationship
from agentic_inquiry.parsers.executor import execute_parser
from tests.utils.in_memory_lancedb_manager import InMemoryLanceDBManager

# Trigger parser auto-registration
import agentic_inquiry.parsers.implementations  # noqa: F401


class _DummyEmbedder:
    """Dummy embedder for testing."""
    
    def generate(self, texts):
        """Generate dummy embeddings."""
        return [[0.1] * 384 for _ in texts]
    
    def ndims(self):
        """Return embedding dimensions."""
        return 384


@pytest.fixture
def temp_project_root(tmp_path):
    """Create a temporary project root directory."""
    project_root = tmp_path / "test_project"
    project_root.mkdir()
    return str(project_root)


@pytest_asyncio.fixture
async def mock_embedding_registry():
    """Create an embedding registry with dummy embedder."""
    return EmbeddingRegistry(default_embedder=_DummyEmbedder())


@pytest_asyncio.fixture
async def mock_db_manager(mock_embedding_registry):
    """Create a temporary in-memory LanceDB manager."""
    manager = InMemoryLanceDBManager(uri="memory://test-compatibility")
    await manager.create_tables_and_indexes()
    await manager.connect()
    yield manager
    # Cleanup is automatic with in-memory database


@pytest_asyncio.fixture
async def pipeline(mock_db_manager, temp_project_root, mock_embedding_registry):
    """Create an IndexingPipeline instance."""
    import uuid
    from agentic_inquiry.config import Config, StorageConfig

    config = Config()
    config.storage = StorageConfig(root=temp_project_root)
    project_id = f"test_{uuid.uuid4().hex[:8]}"

    # Create mock event system
    mock_event_system = MagicMock()
    mock_event_system.emit = AsyncMock()

    return IndexingPipeline(mock_db_manager, config, project_id=project_id, event_system=mock_event_system, registry=mock_embedding_registry, project_root=temp_project_root)


class TestParsedDocumentCompatibility:
    """Test that ParsedDocument has all required fields."""
    
    def test_parsed_document_required_fields(self):
        """Verify ParsedDocument has doc_id, file_path, and chunks fields."""
        # Create a minimal ParsedDocument
        doc = ParsedDocument(
            doc_id="test_doc_123",
            file_path="/path/to/file.py",
            chunks=[]
        )
        
        # Verify required fields exist
        assert hasattr(doc, "doc_id")
        assert hasattr(doc, "file_path")
        assert hasattr(doc, "chunks")
        
        # Verify field values
        assert doc.doc_id == "test_doc_123"
        assert doc.file_path == "/path/to/file.py"
        assert doc.chunks == []
    
    def test_parsed_document_with_metadata(self):
        """Verify ParsedDocument supports optional metadata field."""
        doc = ParsedDocument(
            doc_id="test_doc_123",
            file_path="/path/to/file.py",
            chunks=[],
            metadata={"language": "python", "version": "3.10"}
        )
        
        assert hasattr(doc, "metadata")
        assert doc.metadata == {"language": "python", "version": "3.10"}
    
    def test_parsed_document_validation(self):
        """Verify ParsedDocument validates required fields."""
        # Empty doc_id should raise ValueError
        with pytest.raises(ValueError, match="doc_id must be a non-empty string"):
            ParsedDocument(doc_id="", file_path="/path/to/file.py")
        
        # Empty file_path should raise ValueError
        with pytest.raises(ValueError, match="file_path must be a non-empty string"):
            ParsedDocument(doc_id="test_doc", file_path="")


class TestParserChunkToDocumentChunkMapping:
    """Test that ParserChunk maps correctly to DocumentChunk."""
    
    @pytest.mark.asyncio
    async def test_basic_chunk_mapping(self, pipeline):
        """Verify basic ParserChunk fields map to DocumentChunk."""
        # Create a ParsedDocument with a simple chunk
        chunk = ParserChunk(
            content="def hello():\n    print('Hello, world!')",
            fts_text="hello print Hello world",
            content_type="CODE",
            language="python",
            line_start=1,
            line_end=2,
        )
        
        doc = ParsedDocument(
            doc_id="test_doc",
            file_path="test.py",
            chunks=[chunk]
        )
        
        # Process the document
        await pipeline.process_document(doc)
        
        # Retrieve the stored chunk
        chunks = await pipeline.db_manager.advanced_filter(
            "document_chunks",
            filters={"doc_id": "test_doc"}
        )
        
        assert len(chunks) == 1
        stored_chunk = chunks[0]
        
        # Verify field mapping
        assert stored_chunk["content"] == chunk.content
        assert stored_chunk["fts_text"] == chunk.fts_text
        assert stored_chunk["content_type"] == chunk.content_type
        assert stored_chunk["language"] == chunk.language
        assert stored_chunk["line_start"] == chunk.line_start
        assert stored_chunk["line_end"] == chunk.line_end
    
    @pytest.mark.asyncio
    async def test_code_symbols_mapping(self, pipeline):
        """Verify code_symbols field maps correctly."""
        # Create a chunk with code symbols
        chunk = ParserChunk(
            content="class MyClass:\n    def my_method(self):\n        pass",
            fts_text="MyClass my_method",
            content_type="CODE",
            language="python",
            symbols=["MyClass", "my_method"],
            symbol_metadata={
                "MyClass": {"type": "class"},
                "my_method": {"type": "method"}
            }
        )
        
        doc = ParsedDocument(
            doc_id="test_doc",
            file_path="test.py",
            chunks=[chunk]
        )
        
        # Process the document
        await pipeline.process_document(doc)
        
        # Retrieve the stored chunk
        chunks = await pipeline.db_manager.advanced_filter(
            "document_chunks",
            filters={"doc_id": "test_doc"}
        )
        
        assert len(chunks) == 1
        stored_chunk = chunks[0]
        
        # Verify symbols field
        assert "symbols" in stored_chunk
        assert stored_chunk["symbols"] == ["MyClass", "my_method"]
        
        # Verify graph entities were created
        entities = await pipeline.db_manager.advanced_filter(
            "graph_entities",
            filters={"doc_id": "test_doc"}
        )

        # Expect: 1 file entity + 2 code entities (class, method)
        assert len(entities) >= 2
        # Verify code entities specifically
        code_entity_names = {e["name"] for e in entities if e.get("type") not in ("file", "code_module")}
        assert "MyClass" in code_entity_names
        assert "my_method" in code_entity_names
    
    @pytest.mark.asyncio
    async def test_relationships_mapping(self, pipeline):
        """Verify relationships field maps correctly."""
        # Create chunks with relationships
        chunk1 = ParserChunk(
            content="from module import function",
            fts_text="from module import function",
            content_type="CODE",
            language="python",
            symbols=["function"],
            relationships=[
                ParserRelationship(
                    source_type="module",
                    source_name="current_module",
                    target_type="function",
                    target_name="function",
                    type="imports",
                    target_path="module.py"
                )
            ]
        )
        
        doc = ParsedDocument(
            doc_id="test_doc",
            file_path="test.py",
            chunks=[chunk1]
        )
        
        # Process the document (disable auto-flush to test manual flush)
        await pipeline.process_document(doc, flush_relationships=False)

        # Manually flush pending relationships
        rel_count = await pipeline.flush_pending_relationships()

        # Verify relationships were created
        assert rel_count > 0

        relationships = await pipeline.db_manager.advanced_filter(
            "graph_relationships"
        )

        assert len(relationships) > 0
        # Verify relationship type and structure
        assert any(rel["type"] == "imports" for rel in relationships)
        # Verify relationships have required fields
        assert all("source_id" in rel and "target_id" in rel for rel in relationships), \
            "All relationships should have source_id and target_id fields"
    
    @pytest.mark.asyncio
    async def test_metadata_mapping(self, pipeline):
        """Verify metadata fields map correctly."""
        # Create a chunk with metadata
        chunk = ParserChunk(
            content="# Heading\n\nSome content",
            fts_text="Heading Some content",
            content_type="PROSE",
            page_number=1,
            element_type="heading",
            element_name="Heading",
            metadata={"level": 1, "section": "intro"},
            ranking_signals={"importance": 0.9}
        )
        
        doc = ParsedDocument(
            doc_id="test_doc",
            file_path="test.md",
            chunks=[chunk]
        )
        
        # Process the document
        await pipeline.process_document(doc)
        
        # Retrieve the stored chunk
        chunks = await pipeline.db_manager.advanced_filter(
            "document_chunks",
            filters={"doc_id": "test_doc"}
        )
        
        assert len(chunks) == 1
        stored_chunk = chunks[0]
        
        # Verify metadata fields
        assert stored_chunk["page_number"] == 1
        assert stored_chunk["element_type"] == "heading"
        assert stored_chunk["element_name"] == "Heading"
        
        # Verify metadata dict is stored
        assert "metadata" in stored_chunk
        # Metadata is serialized as JSON in the "data" key
        import json
        metadata_data = json.loads(stored_chunk["metadata"]["data"])
        assert metadata_data["level"] == 1
        assert metadata_data["section"] == "intro"
    
    @pytest.mark.asyncio
    async def test_sentinel_values(self, pipeline):
        """Verify sentinel values are used for optional fields."""
        # Create a chunk without optional fields
        chunk = ParserChunk(
            content="Some text content",
            fts_text="Some text content"
        )
        
        doc = ParsedDocument(
            doc_id="test_doc",
            file_path="test.txt",
            chunks=[chunk]
        )
        
        # Process the document
        await pipeline.process_document(doc)
        
        # Retrieve the stored chunk
        chunks = await pipeline.db_manager.advanced_filter(
            "document_chunks",
            filters={"doc_id": "test_doc"}
        )
        
        assert len(chunks) == 1
        stored_chunk = chunks[0]
        
        # Verify sentinel values are used
        assert stored_chunk["page_number"] == -1  # Sentinel for "not applicable"
        assert stored_chunk["line_start"] == -1
        assert stored_chunk["line_end"] == -1
        assert stored_chunk["language"] == ""  # Empty string sentinel
        assert stored_chunk["element_type"] == ""
        assert stored_chunk["element_name"] == ""


class TestProcessDocumentWithParsers:
    """Test process_document with actual parser output."""
    
    @pytest.mark.asyncio
    async def test_unified_code_parser_integration(self, pipeline, temp_project_root):
        """Test processing a document parsed by UnifiedCodeParser."""
        # Create a Python file
        test_file = Path(temp_project_root) / "test.py"
        test_file.write_text("""
def hello():
    '''Say hello'''
    print('Hello, world!')

class Greeter:
    def greet(self, name):
        return f'Hello, {name}!'
""")
        
        # Parse the file
        try:
            from agentic_inquiry.parsers.executor import get_parser_instance
            parser = get_parser_instance("unified_code")
            parsed_doc = await execute_parser(parser, str(test_file))
            
            # Verify ParsedDocument structure
            assert isinstance(parsed_doc, ParsedDocument)
            assert parsed_doc.doc_id
            assert parsed_doc.file_path == str(test_file)
            assert len(parsed_doc.chunks) > 0
            # Verify chunks have content
            assert all(chunk.content and len(chunk.content.strip()) > 0 for chunk in parsed_doc.chunks), \
                "All chunks should have non-empty content"
            
            # Process through pipeline
            await pipeline.process_document(parsed_doc)
            
            # Verify data was stored
            chunks = await pipeline.db_manager.advanced_filter(
                "document_chunks",
                filters={"file_path": str(test_file)}
            )
            assert len(chunks) > 0
            # Verify chunks have required fields (note: stored chunks use 'id' not 'chunk_id')
            assert all("content" in chunk and "id" in chunk for chunk in chunks), \
                "All stored chunks should have content and id fields"
            
            # Verify code symbols were extracted
            has_symbols = any(chunk.get("symbols") for chunk in chunks)
            assert has_symbols, "Expected at least one chunk with symbols"
            
            # Verify graph entities were created
            entities = await pipeline.db_manager.advanced_filter(
                "graph_entities",
                filters={"file_path": str(test_file)}
            )
            assert len(entities) > 0
            # Verify entities have required fields (name and type)
            assert all("name" in ent and "type" in ent for ent in entities), \
                "All entities should have name and type fields"
            
        except KeyError:
            pytest.skip("UnifiedCodeParser not registered")
    
    @pytest.mark.asyncio
    async def test_document_parser_integration(self, pipeline, temp_project_root):
        """Test processing a document parsed by DocumentParser."""
        # Create a Markdown file
        test_file = Path(temp_project_root) / "test.md"
        test_file.write_text("""
# Main Heading

This is some content.

## Subheading

More content here.
""")
        
        # Parse the file
        try:
            from agentic_inquiry.parsers.executor import get_parser_instance
            parser = get_parser_instance("document")
            parsed_doc = await execute_parser(parser, str(test_file))
            
            # Verify ParsedDocument structure
            assert isinstance(parsed_doc, ParsedDocument)
            assert parsed_doc.doc_id
            assert parsed_doc.file_path == str(test_file)
            assert len(parsed_doc.chunks) > 0
            # Verify chunks have content
            assert all(chunk.content and len(chunk.content.strip()) > 0 for chunk in parsed_doc.chunks), \
                "All chunks should have non-empty content"
            
            # Process through pipeline
            await pipeline.process_document(parsed_doc)
            
            # Verify data was stored
            chunks = await pipeline.db_manager.advanced_filter(
                "document_chunks",
                filters={"file_path": str(test_file)}
            )
            assert len(chunks) > 0
            # Verify chunks have required fields (note: stored chunks use 'id' not 'chunk_id')
            assert all("content" in chunk and "id" in chunk for chunk in chunks), \
                "All stored chunks should have content and id fields"
            
            # Verify content type is PROSE
            assert any(chunk.get("content_type") == "PROSE" for chunk in chunks)
            
        except KeyError:
            pytest.skip("DocumentParser not registered")
    
    @pytest.mark.asyncio
    async def test_fallback_text_parser_integration(self, pipeline, temp_project_root):
        """Test processing a document parsed by FallbackTextParser."""
        # Create a plain text file
        test_file = Path(temp_project_root) / "test.txt"
        test_file.write_text("""
This is a plain text file.
It has multiple lines.
And should be parsed by the fallback text parser.
""")
        
        # Parse the file
        try:
            from agentic_inquiry.parsers.executor import get_parser_instance
            parser = get_parser_instance("fallback_text")  # Fixed: use correct parser name
            parsed_doc = await execute_parser(parser, str(test_file))
            
            # Verify ParsedDocument structure
            assert isinstance(parsed_doc, ParsedDocument)
            assert parsed_doc.doc_id
            assert parsed_doc.file_path == str(test_file)
            assert len(parsed_doc.chunks) > 0
            # Verify chunks have content
            assert all(chunk.content and len(chunk.content.strip()) > 0 for chunk in parsed_doc.chunks), \
                "All chunks should have non-empty content"
            
            # Process through pipeline
            await pipeline.process_document(parsed_doc)
            
            # Verify data was stored
            chunks = await pipeline.db_manager.advanced_filter(
                "document_chunks",
                filters={"file_path": str(test_file)}
            )
            assert len(chunks) > 0
            # Verify chunks have required fields (note: stored chunks use 'id' not 'chunk_id')
            assert all("content" in chunk and "id" in chunk for chunk in chunks), \
                "All stored chunks should have content and id fields"
            
            # Verify fts_text is populated
            assert all(chunk.get("fts_text") for chunk in chunks)
            
        except KeyError:
            pytest.skip("FallbackTextParser not registered")


class TestLanceDBStorage:
    """Test that data is correctly stored in LanceDB."""
    
    @pytest.mark.asyncio
    async def test_document_chunks_table(self, pipeline):
        """Verify document chunks are stored in the correct table."""
        chunk = ParserChunk(
            content="Test content",
            fts_text="Test content"
        )
        
        doc = ParsedDocument(
            doc_id="test_doc",
            file_path="test.txt",
            chunks=[chunk]
        )
        
        await pipeline.process_document(doc)
        
        # Verify table exists and has data
        chunks = await pipeline.db_manager.advanced_filter(
            "document_chunks",
            filters={"doc_id": "test_doc"}
        )
        
        assert len(chunks) == 1
        assert chunks[0]["doc_id"] == "test_doc"
        assert chunks[0]["file_path"] == "test.txt"
    
    @pytest.mark.asyncio
    async def test_graph_entities_table(self, pipeline):
        """Verify graph entities are stored in the correct table."""
        chunk = ParserChunk(
            content="def test_function():\n    pass",
            fts_text="test_function",
            symbols=["test_function"],
            symbol_metadata={"test_function": {"type": "function"}}
        )
        
        doc = ParsedDocument(
            doc_id="test_doc",
            file_path="test.py",
            chunks=[chunk]
        )
        
        await pipeline.process_document(doc)
        
        # Verify entities were created
        entities = await pipeline.db_manager.advanced_filter(
            "graph_entities",
            filters={"doc_id": "test_doc"}
        )

        # Expect: 1 file entity + 1 code entity (function)
        assert len(entities) >= 1
        # Find the function entity specifically
        function_entities = [e for e in entities if e.get("type") == "function"]
        assert len(function_entities) == 1
        assert function_entities[0]["name"] == "test_function"

    @pytest.mark.asyncio
    async def test_graph_entities_for_document_sections(self, pipeline):
        """Verify document sections create graph entities (not just code symbols)."""
        # Create chunks with element_name but no symbols (document entities)
        chunk1 = ParserChunk(
            content="# Introduction\n\nThis is the introduction.",
            fts_text="Introduction This is the introduction.",
            element_type="doc_section",
            element_name="Introduction",
            symbols=[],  # Empty - document entity, not code
        )
        chunk2 = ParserChunk(
            content="## Background\n\nSome background info.",
            fts_text="Background Some background info.",
            element_type="doc_section",
            element_name="Background",
            symbols=[],  # Empty - document entity, not code
        )

        doc = ParsedDocument(
            doc_id="test_md_doc",
            file_path="test.md",
            chunks=[chunk1, chunk2]
        )

        await pipeline.process_document(doc)

        # Verify graph entities were created for document sections
        entities = await pipeline.db_manager.advanced_filter(
            "graph_entities",
            filters={"doc_id": "test_md_doc"}
        )

        # Expect: 1 file entity + 2 document entities
        # Find doc_section entities specifically
        doc_section_entities = [e for e in entities if e.get("type") == "doc_section"]
        assert len(doc_section_entities) == 2, f"Expected 2 doc_section entities, got {len(doc_section_entities)}: {[e.get('name') for e in doc_section_entities]}"

        # Verify entity names match element_name
        entity_names = {e["name"] for e in doc_section_entities}
        assert "Introduction" in entity_names
        assert "Background" in entity_names

    @pytest.mark.asyncio
    async def test_markdown_file_creates_graph_entities(self, pipeline, temp_project_root):
        """Verify actual markdown file parsing creates doc_section graph entities."""
        # Create a markdown file with headings
        test_file = Path(temp_project_root) / "test_headings.md"
        test_file.write_text("""# Main Title

This is an introduction paragraph.

## Section One

Content for section one.

## Section Two

Content for section two.
""")

        # Parse the markdown file
        from agentic_inquiry.parsers.executor import get_parser_instance
        parser = get_parser_instance("document")
        parsed_doc = await execute_parser(parser, str(test_file))

        # Verify parser created doc_section chunks
        doc_section_chunks = [c for c in parsed_doc.chunks if c.element_type == "doc_section"]
        assert len(doc_section_chunks) >= 2, f"Parser should create doc_section chunks: {[c.element_type for c in parsed_doc.chunks]}"

        # Process through pipeline
        await pipeline.process_document(parsed_doc)

        # Verify graph entities were created
        entities = await pipeline.db_manager.advanced_filter(
            "graph_entities",
            filters={"doc_id": parsed_doc.doc_id}
        )

        # Find doc_section entities
        doc_section_entities = [e for e in entities if e.get("type") == "doc_section"]
        assert len(doc_section_entities) >= 2, (
            f"Expected at least 2 doc_section entities from markdown file, "
            f"got {len(doc_section_entities)}: {[e.get('name') for e in doc_section_entities]}"
        )

        # Verify we got the expected headings
        entity_names = {e["name"] for e in doc_section_entities}
        assert "Main Title" in entity_names or any("Main" in n for n in entity_names), f"Missing Main Title in {entity_names}"

    @pytest.mark.asyncio
    async def test_graph_relationships_table(self, pipeline):
        """Verify graph relationships are stored in the correct table."""
        chunk = ParserChunk(
            content="from module import function",
            fts_text="from module import function",
            symbols=["function"],
            relationships=[
                ParserRelationship(
                    source_type="module",
                    source_name="current_module",
                    target_type="function",
                    target_name="function",
                    type="imports",
                    target_path="module.py"
                )
            ]
        )
        
        doc = ParsedDocument(
            doc_id="test_doc",
            file_path="test.py",
            chunks=[chunk]
        )
        
        await pipeline.process_document(doc)
        await pipeline.flush_pending_relationships()
        
        # Verify relationships were created
        relationships = await pipeline.db_manager.advanced_filter(
            "graph_relationships"
        )

        assert len(relationships) > 0
        assert any(rel["type"] == "imports" for rel in relationships)
        # Verify relationships have required fields
        import_rels = [r for r in relationships if r["type"] == "imports"]
        assert all("source_id" in rel and "target_id" in rel for rel in import_rels), \
            "All import relationships should have source_id and target_id"

    @pytest.mark.asyncio
    async def test_document_relationships_contains_follows(self, pipeline, temp_project_root):
        """Verify contains and follows relationships are created for document sections."""
        # Create a markdown file with nested headings
        test_file = Path(temp_project_root) / "nested_headings.md"
        test_file.write_text("""# Main Title

Intro paragraph.

## Section One

Content here.

### Subsection A

More content.

## Section Two

More content.
""")

        # Parse the markdown file
        from agentic_inquiry.parsers.executor import get_parser_instance
        parser = get_parser_instance("document")
        parsed_doc = await execute_parser(parser, str(test_file))

        # Process through pipeline
        await pipeline.process_document(parsed_doc)
        await pipeline.flush_pending_relationships()

        # Verify relationships were created
        relationships = await pipeline.db_manager.advanced_filter(
            "graph_relationships"
        )

        # Filter to only document relationships for this doc
        doc_relationships = [
            r for r in relationships
            if r.get("type") in ("contains", "follows")
        ]

        # Should have contains relationships (parent-child)
        contains_rels = [r for r in doc_relationships if r.get("type") == "contains"]
        assert len(contains_rels) >= 1, f"Expected contains relationships, got {len(contains_rels)}"

        # Should have follows relationships (sibling)
        follows_rels = [r for r in doc_relationships if r.get("type") == "follows"]
        assert len(follows_rels) >= 1, f"Expected follows relationships, got {len(follows_rels)}"

        # Verify relationship structure (uses source_id/target_id, not source_name/target_name)
        for rel in contains_rels:
            assert rel.get("source_id"), "Contains relationship should have source_id"
            assert rel.get("target_id"), "Contains relationship should have target_id"
            # Entity names are encoded in the IDs like "doc_section::project::file::name"
            assert "::" in rel["source_id"], f"source_id should be a qualified entity ID: {rel['source_id']}"

    @pytest.mark.asyncio
    async def test_vector_embeddings(self, pipeline):
        """Verify vector embeddings are generated and stored."""
        chunk = ParserChunk(
            content="Test content for embedding",
            fts_text="Test content for embedding"
        )
        
        doc = ParsedDocument(
            doc_id="test_doc",
            file_path="test.txt",
            chunks=[chunk]
        )
        
        await pipeline.process_document(doc)
        
        # Retrieve the stored chunk
        chunks = await pipeline.db_manager.advanced_filter(
            "document_chunks",
            filters={"doc_id": "test_doc"}
        )
        
        assert len(chunks) == 1
        stored_chunk = chunks[0]
        
        # Verify vector field exists and is a list of floats
        assert "vector" in stored_chunk
        assert isinstance(stored_chunk["vector"], list)
        assert len(stored_chunk["vector"]) > 0
        assert all(isinstance(v, (int, float)) for v in stored_chunk["vector"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
