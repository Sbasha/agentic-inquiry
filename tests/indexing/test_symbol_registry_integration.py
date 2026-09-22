"""Test Symbol Registry integration with IndexingPipeline."""
import pytest

pytestmark = pytest.mark.integration

import asyncio
from unittest.mock import AsyncMock, MagicMock

from agent_vault.embeddings.base import Embedder
from agent_vault.embeddings.registry import EmbeddingRegistry
from agent_vault.indexing.pipeline import IndexingPipeline
from agent_vault.parsers.models import ParsedDocument, ParserChunk
from tests.utils.in_memory_lancedb_manager import InMemoryLanceDBManager


def _create_mock_event_system():
    """Create a mock event system for tests."""
    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    return mock_es


class _DummyEmbedder(Embedder):
    def __init__(self):
        self._ndims = 1

    def generate(self, texts):
        return [[float(len(text))] for text in texts]

    def ndims(self):
        return self._ndims


def test_symbol_registry_integration():
    """Test that symbols are registered with rich metadata."""
    async def run():
        from agent_vault.config import Config, StorageConfig
        
        config = Config()
        config.storage = StorageConfig(root="/tmp/project")
        
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-symbols")
        await mock_db_manager.create_tables_and_indexes()
        await mock_db_manager.connect()

        # Resolve paths to handle macOS /tmp -> /private/tmp symlink
        from pathlib import Path
        project_root = str(Path("/tmp/project").resolve())
        module_file = str(Path("/tmp/project/module.py").resolve())

        mock_event_system = _create_mock_event_system()
        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id="test_project",
            event_system=mock_event_system,
            registry=registry,
            project_root=project_root,
        )

        # Create a document with symbols
        doc = ParsedDocument(
            doc_id="doc-1",
            file_path=module_file,
            chunks=[
                ParserChunk(
                    content="class MyClass:\n    pass",
                    language="python",
                    line_start=1,
                    line_end=2,
                    symbols=["MyClass"],
                    symbol_metadata={
                        "MyClass": {
                            "type": "class",
                            "is_exported": True
                        }
                    }
                ),
                ParserChunk(
                    content="def my_function():\n    pass",
                    language="python",
                    line_start=4,
                    line_end=5,
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

        # Verify symbols were registered
        assert "MyClass" in pipeline.symbol_registry._by_name
        assert "my_function" in pipeline.symbol_registry._by_name

        # Verify metadata is correct
        my_class_metadata = pipeline.symbol_registry.lookup_by_name("MyClass")
        assert len(my_class_metadata) == 1
        assert my_class_metadata[0].name == "MyClass"
        assert my_class_metadata[0].entity_type == "class"
        assert my_class_metadata[0].language == "python"
        assert my_class_metadata[0].line_start == 1
        assert my_class_metadata[0].line_end == 2
        assert my_class_metadata[0].file_path == module_file
        assert my_class_metadata[0].is_exported is True

        my_function_metadata = pipeline.symbol_registry.lookup_by_name("my_function")
        assert len(my_function_metadata) == 1
        assert my_function_metadata[0].name == "my_function"
        assert my_function_metadata[0].entity_type == "function"

        # Verify lookup by name and type works
        class_lookup = pipeline.symbol_registry.lookup_by_name_and_type("MyClass", "class")
        assert len(class_lookup) == 1
        assert class_lookup[0].name == "MyClass"

        # Verify stats
        stats = await pipeline.symbol_registry.get_stats()
        # total_symbols includes file entity (3 = file + 2 code symbols)
        assert stats["total_symbols"] == 3
        assert stats["total_files"] == 1
        # total_entries includes file entity
        assert stats["total_entries"] == 3

    asyncio.run(run())


def test_symbol_registry_multiple_definitions():
    """Test that multiple definitions of the same symbol are tracked."""
    async def run():
        from agent_vault.config import Config, StorageConfig
        
        config = Config()
        config.storage = StorageConfig(root="/tmp/project")
        
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-multi")
        await mock_db_manager.create_tables_and_indexes()
        await mock_db_manager.connect()

        # Resolve paths to handle macOS /tmp -> /private/tmp symlink
        from pathlib import Path
        project_root = str(Path("/tmp/project").resolve())
        module1_file = str(Path("/tmp/project/module1.py").resolve())
        module2_file = str(Path("/tmp/project/module2.py").resolve())

        mock_event_system = _create_mock_event_system()
        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id="test_project",
            event_system=mock_event_system,
            registry=registry,
            project_root=project_root,
        )

        # Create two documents with the same symbol name
        doc1 = ParsedDocument(
            doc_id="doc-1",
            file_path=module1_file,
            chunks=[
                ParserChunk(
                    content="class Helper:\n    pass",
                    language="python",
                    symbols=["Helper"],
                    symbol_metadata={"Helper": {"type": "class"}}
                ),
            ],
        )

        doc2 = ParsedDocument(
            doc_id="doc-2",
            file_path=module2_file,
            chunks=[
                ParserChunk(
                    content="class Helper:\n    pass",
                    language="python",
                    symbols=["Helper"],
                    symbol_metadata={"Helper": {"type": "class"}}
                ),
            ],
        )

        await pipeline.process_document(doc1)
        await pipeline.process_document(doc2)

        # Verify both definitions are tracked
        helper_metadata = pipeline.symbol_registry.lookup_by_name("Helper")
        assert len(helper_metadata) == 2

        file_paths = {m.file_path for m in helper_metadata}
        assert module1_file in file_paths
        assert module2_file in file_paths

        # Verify stats
        stats = await pipeline.symbol_registry.get_stats()
        # 3 unique symbols: Helper (shared name) + 2 file paths
        assert stats["total_symbols"] == 3
        assert stats["total_files"] == 2
        # 4 entries: 2 Helper entries + 2 file entries
        assert stats["total_entries"] == 4

    asyncio.run(run())


def test_symbol_registry_get_symbol_count():
    """Test get_symbol_count() method."""
    async def run():
        from agent_vault.config import Config, StorageConfig
        
        config = Config()
        config.storage = StorageConfig(root="/tmp/project")
        
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-count")
        await mock_db_manager.create_tables_and_indexes()
        await mock_db_manager.connect()

        # Resolve paths to handle macOS /tmp -> /private/tmp symlink
        from pathlib import Path
        project_root = str(Path("/tmp/project").resolve())
        module_file = str(Path("/tmp/project/module.py").resolve())
        module2_file = str(Path("/tmp/project/module2.py").resolve())

        mock_event_system = _create_mock_event_system()
        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id="test_project",
            event_system=mock_event_system,
            registry=registry,
            project_root=project_root,
        )

        # Initially should be 0
        assert pipeline.symbol_registry.get_symbol_count() == 0

        # Create a document with symbols
        doc = ParsedDocument(
            doc_id="doc-1",
            file_path=module_file,
            chunks=[
                ParserChunk(
                    content="class MyClass:\n    pass",
                    language="python",
                    symbols=["MyClass"],
                    symbol_metadata={"MyClass": {"type": "class"}}
                ),
                ParserChunk(
                    content="def my_function():\n    pass",
                    language="python",
                    symbols=["my_function"],
                    symbol_metadata={"my_function": {"type": "function"}}
                ),
            ],
        )

        await pipeline.process_document(doc)

        # Should have 3 unique symbols: 1 file + 2 code symbols
        assert pipeline.symbol_registry.get_symbol_count() == 3

        # Add another document with one new symbol and one duplicate
        doc2 = ParsedDocument(
            doc_id="doc-2",
            file_path=module2_file,
            chunks=[
                ParserChunk(
                    content="class MyClass:\n    pass",  # Duplicate
                    language="python",
                    symbols=["MyClass"],
                    symbol_metadata={"MyClass": {"type": "class"}}
                ),
                ParserChunk(
                    content="def another_function():\n    pass",  # New
                    language="python",
                    symbols=["another_function"],
                    symbol_metadata={"another_function": {"type": "function"}}
                ),
            ],
        )

        await pipeline.process_document(doc2)

        # Should have 5 unique symbols: 2 files + 3 code symbols (MyClass, my_function, another_function)
        assert pipeline.symbol_registry.get_symbol_count() == 5

    asyncio.run(run())


def test_symbol_registry_get_file_count():
    """Test get_file_count() method."""
    async def run():
        from agent_vault.config import Config, StorageConfig
        
        config = Config()
        config.storage = StorageConfig(root="/tmp/project")
        
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-files")
        await mock_db_manager.create_tables_and_indexes()
        await mock_db_manager.connect()

        # Resolve paths to handle macOS /tmp -> /private/tmp symlink
        from pathlib import Path
        project_root = str(Path("/tmp/project").resolve())
        module1_file = str(Path("/tmp/project/module1.py").resolve())
        module2_file = str(Path("/tmp/project/module2.py").resolve())
        module3_file = str(Path("/tmp/project/module3.py").resolve())

        mock_event_system = _create_mock_event_system()
        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id="test_project",
            event_system=mock_event_system,
            registry=registry,
            project_root=project_root,
        )

        # Initially should be 0
        assert pipeline.symbol_registry.get_file_count() == 0

        # Add first file
        doc1 = ParsedDocument(
            doc_id="doc-1",
            file_path=module1_file,
            chunks=[
                ParserChunk(
                    content="class MyClass:\n    pass",
                    language="python",
                    symbols=["MyClass"],
                    symbol_metadata={"MyClass": {"type": "class"}}
                ),
            ],
        )

        await pipeline.process_document(doc1)
        assert pipeline.symbol_registry.get_file_count() == 1

        # Add second file
        doc2 = ParsedDocument(
            doc_id="doc-2",
            file_path=module2_file,
            chunks=[
                ParserChunk(
                    content="def my_function():\n    pass",
                    language="python",
                    symbols=["my_function"],
                    symbol_metadata={"my_function": {"type": "function"}}
                ),
            ],
        )

        await pipeline.process_document(doc2)
        assert pipeline.symbol_registry.get_file_count() == 2

        # Add third file
        doc3 = ParsedDocument(
            doc_id="doc-3",
            file_path=module3_file,
            chunks=[
                ParserChunk(
                    content="def another_function():\n    pass",
                    language="python",
                    symbols=["another_function"],
                    symbol_metadata={"another_function": {"type": "function"}}
                ),
            ],
        )

        await pipeline.process_document(doc3)
        assert pipeline.symbol_registry.get_file_count() == 3

    asyncio.run(run())


def test_symbol_registry_get_statistics():
    """Test get_statistics() method."""
    async def run():
        from agent_vault.config import Config, StorageConfig
        
        config = Config()
        config.storage = StorageConfig(root="/tmp/project")
        
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-stats")
        await mock_db_manager.create_tables_and_indexes()
        await mock_db_manager.connect()

        # Resolve paths to handle macOS /tmp -> /private/tmp symlink
        from pathlib import Path
        project_root = str(Path("/tmp/project").resolve())
        module_file = str(Path("/tmp/project/module.py").resolve())
        other_file = str(Path("/tmp/project/other.py").resolve())
        another_file = str(Path("/tmp/project/another.py").resolve())

        mock_event_system = _create_mock_event_system()
        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id="test_project",
            event_system=mock_event_system,
            registry=registry,
            project_root=project_root,
        )

        # Create documents with various symbol types
        doc = ParsedDocument(
            doc_id="doc-1",
            file_path=module_file,
            chunks=[
                ParserChunk(
                    content="class MyClass:\n    pass",
                    language="python",
                    symbols=["MyClass"],
                    symbol_metadata={"MyClass": {"type": "class"}}
                ),
                ParserChunk(
                    content="class AnotherClass:\n    pass",
                    language="python",
                    symbols=["AnotherClass"],
                    symbol_metadata={"AnotherClass": {"type": "class"}}
                ),
                ParserChunk(
                    content="def my_function():\n    pass",
                    language="python",
                    symbols=["my_function"],
                    symbol_metadata={"my_function": {"type": "function"}}
                ),
                ParserChunk(
                    content="MY_CONSTANT = 42",
                    language="python",
                    symbols=["MY_CONSTANT"],
                    symbol_metadata={"MY_CONSTANT": {"type": "variable"}}
                ),
            ],
        )

        await pipeline.process_document(doc)

        third_file = str(Path("/tmp/project/third.py").resolve())
        # Track some imports
        await pipeline.symbol_registry.track_import("MyClass", other_file, module_file)
        await pipeline.symbol_registry.track_import("MyClass", another_file, module_file)
        await pipeline.symbol_registry.track_import("MyClass", third_file, module_file)
        await pipeline.symbol_registry.track_import("my_function", other_file, module_file)

        # Get statistics
        stats = pipeline.symbol_registry.get_statistics()

        # Verify structure
        assert "symbol_count" in stats
        assert "file_count" in stats
        assert "type_breakdown" in stats
        assert "most_imported" in stats

        # Verify values: 5 symbols = 1 file + 4 code symbols
        assert stats["symbol_count"] == 5
        assert stats["file_count"] == 1

        # Verify type breakdown (file entity adds to the count)
        assert stats["type_breakdown"]["class"] == 2
        assert stats["type_breakdown"]["function"] == 1
        assert stats["type_breakdown"]["variable"] == 1
        assert stats["type_breakdown"]["file"] == 1

        # Verify most_imported
        assert len(stats["most_imported"]) > 0
        # MyClass should be most imported (3 times)
        most_imported_symbol, count = stats["most_imported"][0]
        assert most_imported_symbol == "MyClass"
        assert count == 3

    asyncio.run(run())
