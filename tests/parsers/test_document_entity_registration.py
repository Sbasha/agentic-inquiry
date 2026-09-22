"""Test document entity registration in IndexingPipeline."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

pytestmark = pytest.mark.integration

from agentic_inquiry.config import Config, StorageConfig
from agentic_inquiry.embeddings.base import Embedder
from agentic_inquiry.embeddings.registry import EmbeddingRegistry
from agentic_inquiry.indexing.pipeline import IndexingPipeline
from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk, ParserRelationship
from tests.utils.in_memory_lancedb_manager import InMemoryLanceDBManager


class _DummyEmbedder(Embedder):
    def __init__(self):
        self._ndims = 1

    def generate(self, texts):
        return [[float(len(text))] for text in texts]

    def ndims(self):
        return self._ndims


def _create_mock_event_system():
    """Create a mock event system for tests."""
    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    return mock_es


def test_document_entity_registration():
    """Test that document entities (headings, sections) are registered in symbol registry."""
    async def run():
        from pathlib import Path

        # Resolve paths to handle macOS /tmp -> /private/tmp symlink
        project_root = str(Path("/tmp/project").resolve())
        outline_file = str(Path("/tmp/project/outline.md").resolve())

        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-doc-entities")
        await mock_db_manager.create_tables_and_indexes()
        await mock_db_manager.connect()

        config = Config()
        config.storage = StorageConfig(root=project_root)
        mock_event_system = _create_mock_event_system()

        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id="test_project",
            event_system=mock_event_system,
            registry=registry,
            project_root=project_root,
        )

        # Create a document with structural elements (headings, sections)
        doc = ParsedDocument(
            doc_id="doc-1",
            file_path=outline_file,
            chunks=[
                # Heading chunk
                ParserChunk(
                    content="# Introduction",
                    element_type="doc_section",
                    element_name="Introduction",
                    parent_id="",  # Top-level heading
                    language="markdown",
                    line_start=1,
                    line_end=1,
                ),
                # Section chunk under heading
                ParserChunk(
                    content="This is the introduction section.",
                    element_type="section",
                    element_name="This is the introduction section",
                    parent_id="Introduction",  # Parent is the heading
                    language="markdown",
                    line_start=2,
                    line_end=2,
                ),
                # Another heading
                ParserChunk(
                    content="## Background",
                    element_type="doc_section",
                    element_name="Background",
                    parent_id="Introduction",  # Nested under Introduction
                    language="markdown",
                    line_start=4,
                    line_end=4,
                ),
                # Table chunk
                ParserChunk(
                    content="| Column 1 | Column 2 |\n|----------|----------|",
                    element_type="table",
                    element_name="Comparison table",
                    parent_id="Background",
                    language="markdown",
                    line_start=6,
                    line_end=7,
                ),
            ],
        )

        await pipeline.process_document(doc)

        # Verify document entities were registered
        assert "Introduction" in pipeline.symbol_registry._by_name
        assert "Background" in pipeline.symbol_registry._by_name
        assert "This is the introduction section" in pipeline.symbol_registry._by_name
        assert "Comparison table" in pipeline.symbol_registry._by_name

        # Verify metadata for heading entity
        intro_metadata = pipeline.symbol_registry.lookup_by_name("Introduction")
        assert len(intro_metadata) == 1
        assert intro_metadata[0].name == "Introduction"
        assert intro_metadata[0].entity_type == "doc_section"
        assert intro_metadata[0].language == "markdown"
        assert intro_metadata[0].file_path == outline_file
        assert intro_metadata[0].is_exported is True  # Document entities are always exported
        assert intro_metadata[0].parent_scope is None  # Top-level heading has no parent

        # Verify metadata for nested heading
        background_metadata = pipeline.symbol_registry.lookup_by_name("Background")
        assert len(background_metadata) == 1
        assert background_metadata[0].name == "Background"
        assert background_metadata[0].entity_type == "doc_section"
        assert background_metadata[0].parent_scope == "Introduction"  # Nested under Introduction

        # Verify metadata for section entity
        section_metadata = pipeline.symbol_registry.lookup_by_name("This is the introduction section")
        assert len(section_metadata) == 1
        assert section_metadata[0].name == "This is the introduction section"
        assert section_metadata[0].entity_type == "section"
        assert section_metadata[0].parent_scope == "Introduction"

        # Verify metadata for table entity
        table_metadata = pipeline.symbol_registry.lookup_by_name("Comparison table")
        assert len(table_metadata) == 1
        assert table_metadata[0].name == "Comparison table"
        assert table_metadata[0].entity_type == "table"
        assert table_metadata[0].parent_scope == "Background"

        # Verify lookup by name and type works for document entities
        heading_lookup = pipeline.symbol_registry.lookup_by_name_and_type("Introduction", "doc_section")
        assert len(heading_lookup) == 1
        assert heading_lookup[0].name == "Introduction"

        # Verify stats
        stats = await pipeline.symbol_registry.get_stats()
        assert stats["total_symbols"] == 5  # 4 document entities + 1 file entity
        assert stats["total_files"] == 1
        assert stats["total_entries"] == 5

    asyncio.run(run())


def test_document_relationships_processing():
    """Test that document relationships (contains, follows) are processed correctly."""
    async def run():
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-doc-rels")
        await mock_db_manager.create_tables_and_indexes()
        await mock_db_manager.connect()

        config = Config()
        config.storage = StorageConfig(root="/tmp/project")
        mock_event_system = _create_mock_event_system()

        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id="test_project",
            event_system=mock_event_system,
            registry=registry,
            project_root="/tmp/project",
        )

        # Create a document with hierarchical relationships
        doc = ParsedDocument(
            doc_id="doc-1",
            file_path="/tmp/project/outline.md",
            chunks=[
                # Top-level heading with relationships
                ParserChunk(
                    content="# Chapter 1",
                    element_type="doc_section",
                    element_name="Chapter 1",
                    parent_id="",
                    language="markdown",
                    relationships=[
                        # Document contains this heading
                        ParserRelationship(
                            source_type="document",
                            source_name="outline.md",
                            target_type="doc_section",
                            target_name="Chapter 1",
                            type="contains",
                            metadata={"hierarchy_level": 1}
                        ),
                    ],
                ),
                # Nested heading with relationships
                ParserChunk(
                    content="## Section 1.1",
                    element_type="doc_section",
                    element_name="Section 1.1",
                    parent_id="Chapter 1",
                    language="markdown",
                    relationships=[
                        # Parent heading contains this heading
                        ParserRelationship(
                            source_type="doc_section",
                            source_name="Chapter 1",
                            target_type="doc_section",
                            target_name="Section 1.1",
                            type="contains",
                            metadata={"hierarchy_level": 2}
                        ),
                    ],
                ),
                # Another nested heading with follows relationship
                ParserChunk(
                    content="## Section 1.2",
                    element_type="doc_section",
                    element_name="Section 1.2",
                    parent_id="Chapter 1",
                    language="markdown",
                    relationships=[
                        # Parent heading contains this heading
                        ParserRelationship(
                            source_type="doc_section",
                            source_name="Chapter 1",
                            target_type="doc_section",
                            target_name="Section 1.2",
                            type="contains",
                            metadata={"hierarchy_level": 2}
                        ),
                        # This heading follows the previous one
                        ParserRelationship(
                            source_type="doc_section",
                            source_name="Section 1.1",
                            target_type="doc_section",
                            target_name="Section 1.2",
                            type="follows",
                            metadata={}
                        ),
                    ],
                ),
            ],
        )

        await pipeline.process_document(doc)

        # Verify entities were registered
        assert "Chapter 1" in pipeline.symbol_registry._by_name
        assert "Section 1.1" in pipeline.symbol_registry._by_name
        assert "Section 1.2" in pipeline.symbol_registry._by_name

        # Verify relationships were collected
        # Relationships are stored in _pending_relationships until flush
        assert len(pipeline._pending_relationships) == 4  # 3 contains + 1 follows

        # Verify relationship types
        rel_types = [rel.type for rel, _ in pipeline._pending_relationships]
        assert rel_types.count("contains") == 3
        assert rel_types.count("follows") == 1

        # Flush relationships to create graph edges
        created_count = await pipeline.flush_pending_relationships()
        assert created_count == 4  # All 4 relationships should be created

        # Verify relationships were created in database
        all_relationships = await mock_db_manager.advanced_filter("graph_relationships")
        assert len(all_relationships) == 4

        # Verify contains relationships
        contains_rels = [r for r in all_relationships if r["type"] == "contains"]
        assert len(contains_rels) == 3

        # Verify follows relationships
        follows_rels = [r for r in all_relationships if r["type"] == "follows"]
        assert len(follows_rels) == 1

    asyncio.run(run())


def test_mixed_code_and_document_entities():
    """Test that code entities and document entities can coexist in the same document."""
    async def run():
        from pathlib import Path

        # Resolve paths to handle macOS /tmp -> /private/tmp symlink
        project_root = str(Path("/tmp/project").resolve())
        module_file = str(Path("/tmp/project/module.py").resolve())

        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-mixed")
        await mock_db_manager.create_tables_and_indexes()
        await mock_db_manager.connect()

        config = Config()
        config.storage = StorageConfig(root=project_root)
        mock_event_system = _create_mock_event_system()

        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id="test_project",
            event_system=mock_event_system,
            registry=registry,
            project_root=project_root,
        )

        # Create a document with both code entities and document entities
        doc = ParsedDocument(
            doc_id="doc-1",
            file_path=module_file,
            chunks=[
                # Document heading (from docstring or comment)
                ParserChunk(
                    content="# Module Overview",
                    element_type="doc_section",
                    element_name="Module Overview",
                    parent_id="",
                    language="python",
                ),
                # Code entity (class)
                ParserChunk(
                    content="class MyClass:\n    pass",
                    language="python",
                    line_start=5,
                    line_end=6,
                    symbols=["MyClass"],
                    symbol_metadata={
                        "MyClass": {
                            "type": "class",
                            "is_exported": True
                        }
                    }
                ),
                # Code entity (function)
                ParserChunk(
                    content="def my_function():\n    pass",
                    language="python",
                    line_start=8,
                    line_end=9,
                    symbols=["my_function"],
                    symbol_metadata={
                        "my_function": {
                            "type": "function",
                            "is_exported": True
                        }
                    }
                ),
            ],
        )

        await pipeline.process_document(doc)

        # Verify both document entities and code entities were registered
        assert "Module Overview" in pipeline.symbol_registry._by_name  # Document entity
        assert "MyClass" in pipeline.symbol_registry._by_name  # Code entity
        assert "my_function" in pipeline.symbol_registry._by_name  # Code entity

        # Verify document entity metadata
        doc_entity = pipeline.symbol_registry.lookup_by_name("Module Overview")
        assert len(doc_entity) == 1
        assert doc_entity[0].entity_type == "doc_section"

        # Verify code entity metadata
        class_entity = pipeline.symbol_registry.lookup_by_name("MyClass")
        assert len(class_entity) == 1
        assert class_entity[0].entity_type == "class"

        function_entity = pipeline.symbol_registry.lookup_by_name("my_function")
        assert len(function_entity) == 1
        assert function_entity[0].entity_type == "function"

        # Verify stats
        stats = await pipeline.symbol_registry.get_stats()
        assert stats["total_symbols"] == 4  # 1 document entity + 2 code entities + 1 file entity
        assert stats["total_files"] == 1
        assert stats["total_entries"] == 4

    asyncio.run(run())


def test_document_entity_without_element_name():
    """Test that chunks without element_name are not registered as entities."""
    async def run():
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-no-name")
        await mock_db_manager.create_tables_and_indexes()
        await mock_db_manager.connect()

        config = Config()
        config.storage = StorageConfig(root="/tmp/project")
        mock_event_system = _create_mock_event_system()

        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id="test_project",
            event_system=mock_event_system,
            registry=registry,
            project_root="/tmp/project",
        )

        # Create a document with chunks that have no element_name
        doc = ParsedDocument(
            doc_id="doc-1",
            file_path="/tmp/project/plain.txt",
            chunks=[
                # Chunk with element_type but no element_name
                ParserChunk(
                    content="Some plain text content.",
                    element_type="section",
                    element_name="",  # Empty element_name
                    language="text",
                ),
                # Chunk with element_name (should be registered)
                ParserChunk(
                    content="# Important Section",
                    element_type="doc_section",
                    element_name="Important Section",
                    language="text",
                ),
            ],
        )

        await pipeline.process_document(doc)

        # Verify only the chunk with element_name was registered
        assert "Important Section" in pipeline.symbol_registry._by_name

        # Verify the chunk without element_name was not registered
        # (we can't directly check for empty string, but we can check the count)
        stats = await pipeline.symbol_registry.get_stats()
        assert stats["total_symbols"] == 2  # "Important Section" + file entity
        assert stats["total_entries"] == 2

    asyncio.run(run())
