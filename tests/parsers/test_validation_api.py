"""Test validate_relationships API."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.integration

from agent_vault.config import Config, StorageConfig
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
    def __init__(self):
        self._ndims = 1

    def generate(self, texts):
        return [[float(len(text))] for text in texts]

    def ndims(self):
        return self._ndims


def test_validate_relationships_all_valid():
    """Test validation when all relationships are valid."""
    async def run():
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-validate-valid")
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

        # Create documents with valid relationships
        doc1 = ParsedDocument(
            doc_id="doc-1",
            file_path="/tmp/project/models.py",
            chunks=[
                ParserChunk(
                    content="class User:\n    pass",
                    language="python",
                    symbols=["User"],
                    symbol_metadata={"User": {"type": "class"}},
                    relationships=[]
                ),
            ],
        )

        doc2 = ParsedDocument(
            doc_id="doc-2",
            file_path="/tmp/project/views.py",
            chunks=[
                ParserChunk(
                    content="from models import User",
                    language="python",
                    symbols=["view"],
                    symbol_metadata={"view": {"type": "function"}},
                    relationships=[
                        ParserRelationship(
                            source_type="function",
                            source_name="view",
                            target_type="class",
                            target_name="User",
                            type="imports",
                        )
                    ]
                ),
            ],
        )

        # Process documents and flush relationships
        await pipeline.process_document(doc1)
        await pipeline.process_document(doc2)
        await pipeline.flush_pending_relationships()

        # Validate relationships
        results = await pipeline.validate_relationships()

        # Verify all relationships are valid
        assert results["total_relationships"] == 1
        assert results["valid_relationships"] == 1
        assert len(results["broken_links"]) == 0
        assert results["summary"]["broken_count"] == 0
        assert results["summary"]["health_percentage"] == 100.0

    asyncio.run(run())


def test_validate_relationships_broken_target():
    """Test validation when target entity is missing."""
    async def run():
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-validate-broken")
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

        # Create a document with a relationship
        doc = ParsedDocument(
            doc_id="doc-1",
            file_path="/tmp/project/main.py",
            chunks=[
                ParserChunk(
                    content="from models import User",
                    language="python",
                    symbols=["main"],
                    symbol_metadata={"main": {"type": "function"}},
                    relationships=[
                        ParserRelationship(
                            source_type="function",
                            source_name="main",
                            target_type="class",
                            target_name="User",
                            type="imports",
                            target_path="/tmp/project/models.py",  # Specify target path
                        )
                    ]
                ),
            ],
        )

        # Process document and flush relationships
        await pipeline.process_document(doc)
        await pipeline.flush_pending_relationships()

        # Validate relationships (target entity doesn't exist)
        results = await pipeline.validate_relationships()

        # Verify broken link is detected
        assert results["total_relationships"] == 1
        assert results["valid_relationships"] == 0
        assert len(results["broken_links"]) == 1
        
        broken = results["broken_links"][0]
        assert broken["issue"] == "target_missing"
        assert "User" in broken["target_id"]
        assert broken["type"] == "imports"
        
        assert results["summary"]["broken_count"] == 1
        assert results["summary"]["health_percentage"] == 0.0

    asyncio.run(run())


def test_validate_relationships_circular_dependencies():
    """Test circular dependency detection."""
    async def run():
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-validate-circular")
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

        # Create documents with circular dependencies: A -> B -> C -> A
        doc_a = ParsedDocument(
            doc_id="doc-a",
            file_path="/tmp/project/a.py",
            chunks=[
                ParserChunk(
                    content="class A:\n    pass",
                    language="python",
                    symbols=["A"],
                    symbol_metadata={"A": {"type": "class"}},
                    relationships=[
                        ParserRelationship(
                            source_type="class",
                            source_name="A",
                            target_type="class",
                            target_name="B",
                            type="imports",
                        )
                    ]
                ),
            ],
        )

        doc_b = ParsedDocument(
            doc_id="doc-b",
            file_path="/tmp/project/b.py",
            chunks=[
                ParserChunk(
                    content="class B:\n    pass",
                    language="python",
                    symbols=["B"],
                    symbol_metadata={"B": {"type": "class"}},
                    relationships=[
                        ParserRelationship(
                            source_type="class",
                            source_name="B",
                            target_type="class",
                            target_name="C",
                            type="imports",
                        )
                    ]
                ),
            ],
        )

        doc_c = ParsedDocument(
            doc_id="doc-c",
            file_path="/tmp/project/c.py",
            chunks=[
                ParserChunk(
                    content="class C:\n    pass",
                    language="python",
                    symbols=["C"],
                    symbol_metadata={"C": {"type": "class"}},
                    relationships=[
                        ParserRelationship(
                            source_type="class",
                            source_name="C",
                            target_type="class",
                            target_name="A",
                            type="imports",
                        )
                    ]
                ),
            ],
        )

        # Process documents and flush relationships
        await pipeline.process_document(doc_a)
        await pipeline.process_document(doc_b)
        await pipeline.process_document(doc_c)
        await pipeline.flush_pending_relationships()

        # Validate with circular dependency detection
        results = await pipeline.validate_relationships(check_circular_dependencies=True)

        # Verify circular dependency is detected
        assert "circular_dependencies" in results
        assert len(results["circular_dependencies"]) >= 1
        
        # Find the A -> B -> C -> A cycle
        cycle_found = False
        for cycle_info in results["circular_dependencies"]:
            cycle = cycle_info["cycle"]
            # Check if this is our expected cycle (in any rotation)
            if len(cycle) == 4:  # 3 unique nodes + 1 repeated
                cycle_set = set(cycle[:-1])  # Remove duplicate end node
                if all(any(node_id.endswith(f"::{name}") for node_id in cycle_set) 
                       for name in ["A", "B", "C"]):
                    cycle_found = True
                    assert cycle_info["length"] == 3
                    break
        
        assert cycle_found, f"Expected cycle not found. Cycles: {results['circular_dependencies']}"
        
        assert results["summary"]["circular_count"] >= 1

    asyncio.run(run())


def test_validate_relationships_no_relationships():
    """Test validation when there are no relationships."""
    async def run():
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-validate-empty")
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

        # Validate without any relationships
        results = await pipeline.validate_relationships()

        # Verify empty results
        assert results["total_relationships"] == 0
        assert results["valid_relationships"] == 0
        assert len(results["broken_links"]) == 0
        assert results["summary"]["broken_count"] == 0
        assert results["summary"]["health_percentage"] == 100.0

    asyncio.run(run())


def test_validate_relationships_mixed_health():
    """Test validation with mix of valid and broken relationships."""
    async def run():
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-validate-mixed")
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

        # Create documents with some valid and some broken relationships
        doc1 = ParsedDocument(
            doc_id="doc-1",
            file_path="/tmp/project/models.py",
            chunks=[
                ParserChunk(
                    content="class User:\n    pass",
                    language="python",
                    symbols=["User"],
                    symbol_metadata={"User": {"type": "class"}},
                    relationships=[]
                ),
            ],
        )

        doc2 = ParsedDocument(
            doc_id="doc-2",
            file_path="/tmp/project/views.py",
            chunks=[
                ParserChunk(
                    content="from models import User, Product",
                    language="python",
                    symbols=["view"],
                    symbol_metadata={"view": {"type": "function"}},
                    relationships=[
                        # Valid relationship
                        ParserRelationship(
                            source_type="function",
                            source_name="view",
                            target_type="class",
                            target_name="User",
                            type="imports",
                        ),
                        # Broken relationship (Product doesn't exist)
                        ParserRelationship(
                            source_type="function",
                            source_name="view",
                            target_type="class",
                            target_name="Product",
                            type="imports",
                            target_path="/tmp/project/models.py",
                        ),
                    ]
                ),
            ],
        )

        # Process documents and flush relationships
        await pipeline.process_document(doc1)
        await pipeline.process_document(doc2)
        await pipeline.flush_pending_relationships()

        # Validate relationships
        results = await pipeline.validate_relationships()

        # Verify mixed health
        assert results["total_relationships"] == 2
        assert results["valid_relationships"] == 1
        assert len(results["broken_links"]) == 1
        assert results["summary"]["broken_count"] == 1
        assert results["summary"]["health_percentage"] == 50.0
        
        # Verify broken link details
        broken = results["broken_links"][0]
        assert broken["issue"] == "target_missing"
        assert "Product" in broken["target_id"]

    asyncio.run(run())
