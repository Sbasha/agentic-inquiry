"""Test incremental update support in IndexingPipeline."""

import pytest

pytestmark = pytest.mark.integration

import asyncio
from unittest.mock import AsyncMock, MagicMock

from agent_vault.embeddings.base import Embedder
from agent_vault.embeddings.registry import EmbeddingRegistry
from agent_vault.indexing.pipeline import IndexingPipeline
from agent_vault.parsers.models import ParsedDocument, ParserChunk, ParserRelationship
from tests.utils.in_memory_lancedb_manager import InMemoryLanceDBManager


def _create_mock_event_system():
    """Create a mock event system for tests."""
    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    return mock_es


class _DummyEmbedder(Embedder):
    """Dummy embedder for testing."""
    
    def generate(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 128 for _ in texts]
    
    def ndims(self) -> int:
        return 128


def test_remove_file_data():
    """Test that remove_file_data removes all data for a file."""

    async def run():
        from pathlib import Path
        from agent_vault.config import Config, StorageConfig

        # Resolve paths to handle macOS /tmp -> /private/tmp symlink
        project_root = str(Path("/tmp/project").resolve())
        test_file = str(Path("/tmp/project/test.py").resolve())

        config = Config()
        config.storage = StorageConfig(root=project_root)

        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test")
        await mock_db_manager.connect()

        mock_event_system = _create_mock_event_system()
        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id="test_project",
            event_system=mock_event_system,
            registry=registry,
            project_root=project_root,
        )

        # Index a document
        doc = ParsedDocument(
            doc_id="test_doc",
            file_path=test_file,
            chunks=[
                ParserChunk(
                    content="class TestClass:\n    pass",
                    fts_text="class TestClass:\n    pass",
                    language="python",
                    symbols=["TestClass"],
                    symbol_metadata={"TestClass": {"type": "class"}},
                    relationships=[
                        ParserRelationship(
                            source_type="class",
                            source_name="TestClass",
                            target_type="class",
                            target_name="BaseClass",
                            type="imports"
                        )
                    ]
                ),
            ],
        )
        
        await pipeline.process_document(doc)
        await pipeline.flush_pending_relationships()
        
        # Verify data exists
        chunks = await mock_db_manager.advanced_filter(
            "document_chunks",
            filters={"file_path": test_file}
        )
        assert len(chunks) == 1

        entities = await mock_db_manager.advanced_filter(
            "graph_entities",
            filters={"file_path": test_file}
        )
        # Expect: 1 file entity + 1 code entity
        assert len(entities) >= 1

        # Verify symbol is registered
        symbols = pipeline.symbol_registry.lookup_by_name("TestClass")
        assert len(symbols) == 1

        # Remove file data
        await pipeline.remove_file_data(test_file)

        # Verify data is removed
        chunks = await mock_db_manager.advanced_filter(
            "document_chunks",
            filters={"file_path": test_file}
        )
        assert len(chunks) == 0

        entities = await mock_db_manager.advanced_filter(
            "graph_entities",
            filters={"file_path": test_file}
        )
        assert len(entities) == 0
        
        # Verify symbol is removed from registry
        symbols = pipeline.symbol_registry.lookup_by_name("TestClass")
        assert len(symbols) == 0
        
        # Verify cache was cleared
        cache_info = pipeline.symbol_registry.get_cache_info()
        assert cache_info["size"] == 0
    
    asyncio.run(run())


def test_reindex_document():
    """Test that reindex_document removes old data and indexes new data."""

    async def run():
        from pathlib import Path
        from agent_vault.config import Config, StorageConfig

        # Resolve paths to handle macOS /tmp -> /private/tmp symlink
        project_root = str(Path("/tmp/project").resolve())
        test_file = str(Path("/tmp/project/test.py").resolve())

        config = Config()
        config.storage = StorageConfig(root=project_root)

        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test")
        await mock_db_manager.connect()

        mock_event_system = _create_mock_event_system()
        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id="test_project",
            event_system=mock_event_system,
            registry=registry,
            project_root=project_root,
        )

        # Index original version
        doc_v1 = ParsedDocument(
            doc_id="test_doc",
            file_path=test_file,
            chunks=[
                ParserChunk(
                    content="class OldClass:\n    pass",
                    fts_text="class OldClass:\n    pass",
                    language="python",
                    symbols=["OldClass"],
                    symbol_metadata={"OldClass": {"type": "class"}}
                ),
            ],
        )
        
        await pipeline.process_document(doc_v1)
        
        # Verify old data exists
        symbols = pipeline.symbol_registry.lookup_by_name("OldClass")
        assert len(symbols) == 1
        
        # Re-index with new version
        doc_v2 = ParsedDocument(
            doc_id="test_doc",
            file_path=test_file,
            chunks=[
                ParserChunk(
                    content="class NewClass:\n    pass",
                    fts_text="class NewClass:\n    pass",
                    language="python",
                    symbols=["NewClass"],
                    symbol_metadata={"NewClass": {"type": "class"}}
                ),
            ],
        )

        await pipeline.reindex_document(doc_v2)

        # Verify old symbol is removed
        old_symbols = pipeline.symbol_registry.lookup_by_name("OldClass")
        assert len(old_symbols) == 0

        # Verify new symbol is registered
        new_symbols = pipeline.symbol_registry.lookup_by_name("NewClass")
        assert len(new_symbols) == 1
        assert new_symbols[0].name == "NewClass"
        assert new_symbols[0].file_path == test_file

        # Verify new chunks exist
        chunks = await mock_db_manager.advanced_filter(
            "document_chunks",
            filters={"file_path": test_file}
        )
        assert len(chunks) == 1
        assert "NewClass" in chunks[0]["symbols"]
        assert "OldClass" not in chunks[0]["symbols"]

    asyncio.run(run())


def test_incremental_update_with_relationships():
    """Test that relationships are updated correctly during incremental updates."""

    async def run():
        from pathlib import Path
        from agent_vault.config import Config, StorageConfig

        # Resolve paths to handle macOS /tmp -> /private/tmp symlink
        project_root = str(Path("/tmp/project").resolve())
        base_file = str(Path("/tmp/project/base.py").resolve())
        test_file = str(Path("/tmp/project/test.py").resolve())

        config = Config()
        config.storage = StorageConfig(root=project_root)

        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test")
        await mock_db_manager.connect()

        mock_event_system = _create_mock_event_system()
        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id="test_project",
            event_system=mock_event_system,
            registry=registry,
            project_root=project_root,
        )

        # Index base file
        base_doc = ParsedDocument(
            doc_id="base_doc",
            file_path=base_file,
            chunks=[
                ParserChunk(
                    content="class BaseClass:\n    pass",
                    fts_text="class BaseClass:\n    pass",
                    language="python",
                    symbols=["BaseClass"],
                    symbol_metadata={"BaseClass": {"type": "class"}}
                ),
            ],
        )
        
        await pipeline.process_document(base_doc)
        
        # Index file that imports from base (version 1)
        doc_v1 = ParsedDocument(
            doc_id="test_doc",
            file_path=test_file,
            chunks=[
                ParserChunk(
                    content="from base import BaseClass\n\nclass TestClass(BaseClass):\n    pass",
                    fts_text="from base import BaseClass\n\nclass TestClass(BaseClass):\n    pass",
                    language="python",
                    symbols=["TestClass"],
                    symbol_metadata={"TestClass": {"type": "class"}},
                    relationships=[
                        ParserRelationship(
                            source_type="class",
                            source_name="TestClass",
                            target_type="class",
                            target_name="BaseClass",
                            type="imports"
                        )
                    ]
                ),
            ],
        )
        
        await pipeline.process_document(doc_v1)
        await pipeline.flush_pending_relationships()
        
        # Verify relationship exists
        relationships = await mock_db_manager.advanced_filter("graph_relationships")
        initial_rel_count = len(relationships)
        assert initial_rel_count > 0
        
        # Find relationship from TestClass to BaseClass
        test_to_base = [
            rel for rel in relationships
            if "TestClass" in rel["source_id"] and "BaseClass" in rel["target_id"]
        ]
        assert len(test_to_base) == 1
        
        # Re-index with new version that imports something different
        doc_v2 = ParsedDocument(
            doc_id="test_doc",
            file_path=test_file,
            chunks=[
                ParserChunk(
                    content="class TestClass:\n    pass",
                    fts_text="class TestClass:\n    pass",
                    language="python",
                    symbols=["TestClass"],
                    symbol_metadata={"TestClass": {"type": "class"}},
                    relationships=[]  # No relationships in new version
                ),
            ],
        )
        
        await pipeline.reindex_document(doc_v2)
        await pipeline.flush_pending_relationships()
        
        # Verify old relationship is removed
        relationships = await mock_db_manager.advanced_filter("graph_relationships")
        test_to_base = [
            rel for rel in relationships
            if "TestClass" in rel["source_id"] and "BaseClass" in rel["target_id"]
        ]
        assert len(test_to_base) == 0
        
        # Verify TestClass symbol still exists
        symbols = pipeline.symbol_registry.lookup_by_name("TestClass")
        assert len(symbols) == 1
    
    asyncio.run(run())


def test_remove_pending_relationships():
    """Test that pending relationships are removed when file data is removed."""

    async def run():
        from pathlib import Path
        from agent_vault.config import Config, StorageConfig

        # Resolve paths to handle macOS /tmp -> /private/tmp symlink
        project_root = str(Path("/tmp/project").resolve())
        test_file = str(Path("/tmp/project/test.py").resolve())

        config = Config()
        config.storage = StorageConfig(root=project_root)

        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test")
        await mock_db_manager.connect()

        mock_event_system = _create_mock_event_system()
        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id="test_project",
            event_system=mock_event_system,
            registry=registry,
            project_root=project_root,
        )

        # Index a document with relationships
        doc = ParsedDocument(
            doc_id="test_doc",
            file_path=test_file,
            chunks=[
                ParserChunk(
                    content="class TestClass:\n    pass",
                    fts_text="class TestClass:\n    pass",
                    language="python",
                    symbols=["TestClass"],
                    symbol_metadata={"TestClass": {"type": "class"}},
                    relationships=[
                        ParserRelationship(
                            source_type="class",
                            source_name="TestClass",
                            target_type="class",
                            target_name="BaseClass",
                            type="imports"
                        )
                    ]
                ),
            ],
        )

        # Process document with auto-flush disabled to test pending relationship cleanup
        await pipeline.process_document(doc, flush_relationships=False)

        # Verify pending relationships exist (now managed by GraphBuilder)
        assert len(pipeline.graph_builder._pending_relationships) == 1

        # Remove file data
        await pipeline.remove_file_data(test_file)

        # Verify pending relationships are removed
        assert len(pipeline.graph_builder._pending_relationships) == 0

    asyncio.run(run())
