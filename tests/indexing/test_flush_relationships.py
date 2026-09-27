"""Test flush_pending_relationships with enhanced resolution."""
import asyncio

import pytest

pytestmark = pytest.mark.integration

from unittest.mock import AsyncMock, MagicMock

from agentic_inquiry.config import Config
from agentic_inquiry.embeddings.base import Embedder
from agentic_inquiry.embeddings.registry import EmbeddingRegistry
from agentic_inquiry.indexing.pipeline import IndexingPipeline
from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk, ParserRelationship
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


def test_flush_relationships_with_enhanced_resolution(tmp_path):
    """Test that flush_pending_relationships uses enhanced resolution and tracks statistics."""
    async def run():
        import uuid
        from agentic_inquiry.events import EventSystem
        
        config = Config.load()
        config.storage.root = str(tmp_path)
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-flush")
        await mock_db_manager.create_tables_and_indexes()
        await mock_db_manager.connect()

        project_id = f"test_{uuid.uuid4().hex[:8]}"
        
        # Create EventSystem for the pipeline
        event_system = await EventSystem.from_config(config, project_id=project_id)
        
        try:
            pipeline = IndexingPipeline(
                db_manager=mock_db_manager,
                config=config,
                project_id=project_id,
                registry=registry,
                event_system=event_system,
            )

            # Create a document with a symbol definition
            doc1 = ParsedDocument(
                doc_id="doc-1",
                file_path="utils/helper.py",
                chunks=[
                    ParserChunk(
                        content="class Helper:\n    pass",
                        language="python",
                        symbols=["Helper"],
                        symbol_metadata={"Helper": {"type": "class"}},
                        relationships=[]
                    ),
                ],
            )

            # Create a document that imports from the first
            doc2 = ParsedDocument(
                doc_id="doc-2",
                file_path="main.py",
                chunks=[
                    ParserChunk(
                        content="from utils.helper import Helper",
                        language="python",
                        symbols=["main"],
                        symbol_metadata={"main": {"type": "function"}},
                        relationships=[
                            ParserRelationship(
                                source_type="function",
                                source_name="main",
                                target_type="class",
                                target_name="Helper",
                                type="imports",
                            )
                        ]
                    ),
                ],
            )

            # Process both documents (disable auto-flush to test manual flush)
            await pipeline.process_document(doc1, flush_relationships=False)
            await pipeline.process_document(doc2, flush_relationships=False)

            # Manually flush relationships
            count = await pipeline.flush_pending_relationships()

            # Verify relationship was created
            assert count == 1

            # Verify statistics were tracked
            assert pipeline._last_resolution_stats is not None
            stats = pipeline._last_resolution_stats

            assert stats["total"] == 1
            assert stats["resolved_cross_file"] == 1
            assert stats["unresolved_external"] == 0

            # Verify relationship exists in database
            relationships = await mock_db_manager.advanced_filter("graph_relationships", {})
            assert len(relationships) == 1

            rel = relationships[0]
            assert rel["type"] == "imports"
            assert "Helper" in rel["target_id"]
            assert "utils/helper.py" in rel["target_id"]
        finally:
            await event_system.stop()

    asyncio.run(run())


def test_flush_relationships_external_dependency():
    """Test that external dependencies are handled correctly."""
    async def run():
        import uuid
        from agentic_inquiry.config import Config, StorageConfig
        
        config = Config()
        config.storage = StorageConfig(root="/tmp/project")
        
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-external")
        await mock_db_manager.create_tables_and_indexes()
        await mock_db_manager.connect()

        project_id = f"test_{uuid.uuid4().hex[:8]}"
        mock_event_system = _create_mock_event_system()
        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id=project_id,
            event_system=mock_event_system,
            registry=registry,
            project_root="/tmp/project",
        )

        # Create a document that imports an external library
        doc = ParsedDocument(
            doc_id="doc-1",
            file_path="/tmp/project/main.py",
            chunks=[
                ParserChunk(
                    content="import numpy as np",
                    language="python",
                    symbols=["main"],
                    symbol_metadata={"main": {"type": "function"}},
                    relationships=[
                        ParserRelationship(
                            source_type="function",
                            source_name="main",
                            target_type="module",
                            target_name="numpy",
                            type="imports",
                        )
                    ]
                ),
            ],
        )

        # Process document (disable auto-flush to test manual flush)
        await pipeline.process_document(doc, flush_relationships=False)

        # Manually flush relationships
        count = await pipeline.flush_pending_relationships()

        # Verify external dependency WAS added (now creates external entity)
        assert count == 1

        # Verify statistics show external entity was created
        stats = pipeline._last_resolution_stats
        assert stats["unresolved_external"] == 1
        assert stats["resolved_cross_file"] == 0

        # Verify relationship was created in database
        relationships = await mock_db_manager.advanced_filter("graph_relationships", {})
        assert len(relationships) == 1

        # Verify external entity was created
        entities = await mock_db_manager.advanced_filter("graph_entities", {})
        # Should have: 1 file entity + 1 code entity (main) + 1 external entity (numpy)
        external_entities = [e for e in entities if e.get("type", "").startswith("external_")]
        assert len(external_entities) == 1
        assert "numpy" in external_entities[0].get("name", "")

    asyncio.run(run())


def test_flush_relationships_confidence_tracking():
    """Test that confidence levels are tracked correctly."""
    async def run():
        import uuid
        from agentic_inquiry.config import Config, StorageConfig
        
        config = Config()
        config.storage = StorageConfig(root="/tmp/project")
        
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-confidence")
        await mock_db_manager.create_tables_and_indexes()
        await mock_db_manager.connect()

        project_id = f"test_{uuid.uuid4().hex[:8]}"
        mock_event_system = _create_mock_event_system()
        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id=project_id,
            event_system=mock_event_system,
            registry=registry,
            project_root="/tmp/project",
        )

        # Create documents with exact type match (high confidence)
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

        # Process documents (disable auto-flush to test manual flush)
        await pipeline.process_document(doc1, flush_relationships=False)
        await pipeline.process_document(doc2, flush_relationships=False)

        # Manually flush relationships
        await pipeline.flush_pending_relationships()

        # Verify high confidence was tracked
        stats = pipeline._last_resolution_stats
        assert stats["confidence_levels"]["high"] >= 1

        # Verify relationship has confidence metadata
        relationships = await mock_db_manager.advanced_filter("graph_relationships", {})
        assert len(relationships) == 1
        
        import json
        metadata = json.loads(relationships[0]["metadata"])
        assert "resolution_confidence" in metadata
        assert metadata["resolution_confidence"] >= 0.8

    asyncio.run(run())


def test_get_resolution_stats_api():
    """Test the get_resolution_stats() public API method."""
    async def run():
        import uuid
        from agentic_inquiry.config import Config, StorageConfig
        
        config = Config()
        config.storage = StorageConfig(root="/tmp/project")
        
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-stats-api")
        await mock_db_manager.create_tables_and_indexes()
        await mock_db_manager.connect()

        project_id = f"test_{uuid.uuid4().hex[:8]}"
        mock_event_system = _create_mock_event_system()
        pipeline = IndexingPipeline(
            db_manager=mock_db_manager,
            config=config,
            project_id=project_id,
            event_system=mock_event_system,
            registry=registry,
            project_root="/tmp/project",
        )

        # Before any flush, stats should be None
        assert pipeline.get_resolution_stats() is None

        # Create documents with various resolution scenarios
        doc1 = ParsedDocument(
            doc_id="doc-1",
            file_path="/tmp/project/utils/helper.py",
            chunks=[
                ParserChunk(
                    content="class Helper:\n    pass",
                    language="python",
                    symbols=["Helper"],
                    symbol_metadata={"Helper": {"type": "class"}},
                    relationships=[]
                ),
            ],
        )

        doc2 = ParsedDocument(
            doc_id="doc-2",
            file_path="/tmp/project/main.py",
            chunks=[
                ParserChunk(
                    content="from utils.helper import Helper\nimport numpy",
                    language="python",
                    symbols=["main"],
                    symbol_metadata={"main": {"type": "function"}},
                    relationships=[
                        # Cross-file import (should resolve)
                        ParserRelationship(
                            source_type="function",
                            source_name="main",
                            target_type="class",
                            target_name="Helper",
                            type="imports",
                        ),
                        # External import (should not resolve)
                        ParserRelationship(
                            source_type="function",
                            source_name="main",
                            target_type="module",
                            target_name="numpy",
                            type="imports",
                        ),
                    ]
                ),
            ],
        )

        # Process documents (disable auto-flush to test manual flush)
        await pipeline.process_document(doc1, flush_relationships=False)
        await pipeline.process_document(doc2, flush_relationships=False)

        # Manually flush relationships
        await pipeline.flush_pending_relationships()

        # Get statistics via public API
        stats = pipeline.get_resolution_stats()
        
        # Verify stats structure and content
        assert stats is not None
        assert isinstance(stats, dict)
        
        # Verify all required fields are present
        assert "total" in stats
        assert "resolved_cross_file" in stats
        assert "unresolved_external" in stats
        assert "same_file_fallback" in stats
        assert "by_strategy" in stats
        assert "confidence_levels" in stats
        assert "ambiguous_resolutions" in stats
        assert "average_confidence" in stats
        assert "resolution_time_seconds" in stats
        assert "resolver_cache_statistics" in stats
        
        # Verify counts
        assert stats["total"] == 2
        assert stats["resolved_cross_file"] == 1
        assert stats["unresolved_external"] == 1
        
        # Verify strategy tracking (updated to match RelationshipResolver strategy names)
        assert isinstance(stats["by_strategy"], dict)
        assert "exact_match" in stats["by_strategy"]  # Changed from exact_type_match
        assert "import_path" in stats["by_strategy"]  # Added import_path strategy
        assert "module_path" in stats["by_strategy"]
        assert "proximity" in stats["by_strategy"]
        assert "no_resolution" in stats["by_strategy"]
        
        # Verify confidence tracking
        assert isinstance(stats["confidence_levels"], dict)
        assert "high" in stats["confidence_levels"]
        assert "medium" in stats["confidence_levels"]
        assert "low" in stats["confidence_levels"]
        
        # Verify average confidence is calculated
        assert isinstance(stats["average_confidence"], float)
        assert 0.0 <= stats["average_confidence"] <= 1.0
        
        # Verify resolution time is tracked
        assert isinstance(stats["resolution_time_seconds"], float)
        assert stats["resolution_time_seconds"] >= 0.0
        
        # Verify resolver cache statistics (renamed from cache_statistics)
        assert isinstance(stats["resolver_cache_statistics"], dict)
        assert "cache_hits" in stats["resolver_cache_statistics"]
        assert "cache_misses" in stats["resolver_cache_statistics"]
        assert "cache_size" in stats["resolver_cache_statistics"]
        
        # Verify internal tracking data is not exposed
        assert "confidence_scores" not in stats
        
        # Verify returned stats is a copy (modifications don't affect internal state)
        stats["total"] = 999
        new_stats = pipeline.get_resolution_stats()
        assert new_stats["total"] == 2  # Original value unchanged

    asyncio.run(run())
