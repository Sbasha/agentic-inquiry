"""Tests for relationship extraction and storage in IndexingPipeline.

These tests verify that:
1. Relationships are created after single document processing
2. Relationships are included in IndexingResult
3. Import relationships are properly created
4. Class-method relationships (defines) are created
"""
import pytest

pytestmark = pytest.mark.integration
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from agentic_inquiry.config import Config
from agentic_inquiry.embeddings.base import Embedder
from agentic_inquiry.embeddings.registry import EmbeddingRegistry
from agentic_inquiry.indexing.pipeline import IndexingPipeline
from agentic_inquiry.indexing.models import IndexingResult
from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk, ParserRelationship
from tests.utils.in_memory_lancedb_manager import InMemoryLanceDBManager


class _DummyEmbedder(Embedder):
    """Dummy embedder for tests."""

    def __init__(self):
        self._ndims = 384

    def generate(self, texts):
        return [[0.1] * 384 for _ in texts]

    def ndims(self):
        return self._ndims


def _create_mock_event_system():
    """Create a mock event system for tests."""
    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    return mock_es


@pytest.fixture
def sample_python_with_imports(tmp_path: Path) -> Path:
    """Create a Python file with import statements."""
    code = '''
from typing import List, Dict
import os
import json

class MyClass:
    def __init__(self):
        pass

    def my_method(self):
        return os.path.exists("test")
'''
    file_path = tmp_path / "sample.py"
    file_path.write_text(code)
    return file_path


class TestRelationshipFlushAfterDocument:
    """Test that relationships are flushed after document processing."""

    @pytest.mark.asyncio
    async def test_single_document_creates_relationships(self):
        """Verify that processing a single document creates relationships."""
        import uuid

        config = Config.load()
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        db_manager = InMemoryLanceDBManager(uri="memory://test-single-doc-rels")
        await db_manager.create_tables_and_indexes()
        await db_manager.connect()

        project_id = f"test_{uuid.uuid4().hex[:8]}"
        mock_event_system = _create_mock_event_system()

        pipeline = IndexingPipeline(
            db_manager=db_manager,
            config=config,
            project_id=project_id,
            registry=registry,
            event_system=mock_event_system,
        )

        # Create document with class definition
        doc1 = ParsedDocument(
            doc_id="doc-1",
            file_path="utils/helper.py",
            chunks=[
                ParserChunk(
                    content="class Helper:\n    def do_work(self):\n        pass",
                    language="python",
                    symbols=["Helper", "do_work"],
                    symbol_metadata={
                        "Helper": {"type": "class"},
                        "do_work": {"type": "method", "parent": "Helper"},
                    },
                    relationships=[
                        ParserRelationship(
                            source_type="class",
                            source_name="Helper",
                            target_type="method",
                            target_name="do_work",
                            type="defines",
                        )
                    ],
                ),
            ],
        )

        # Create document that imports from the first
        doc2 = ParsedDocument(
            doc_id="doc-2",
            file_path="main.py",
            chunks=[
                ParserChunk(
                    content="from utils.helper import Helper\n\ndef main():\n    h = Helper()",
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
                    ],
                ),
            ],
        )

        # Process both documents
        await pipeline.process_document(doc1)
        await pipeline.process_document(doc2)

        # Check relationships were created
        relationships = await db_manager.advanced_filter("graph_relationships", {})

        # Should have at least 2 relationships: defines and imports
        assert len(relationships) >= 2, (
            f"Expected at least 2 relationships (defines, imports), got {len(relationships)}"
        )

        # Verify relationship types
        rel_types = [r.get("type") for r in relationships]
        # At minimum, we should have either defines or imports relationships
        assert any(t in ["defines", "imports"] for t in rel_types), (
            f"Expected 'defines' or 'imports' in relationship types, got {rel_types}"
        )

    @pytest.mark.asyncio
    async def test_process_document_impl_flushes_relationships(self):
        """Verify _process_document_impl calls flush_pending_relationships."""
        import uuid

        config = Config.load()
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        db_manager = InMemoryLanceDBManager(uri="memory://test-impl-flush")
        await db_manager.create_tables_and_indexes()
        await db_manager.connect()

        project_id = f"test_{uuid.uuid4().hex[:8]}"
        mock_event_system = _create_mock_event_system()

        pipeline = IndexingPipeline(
            db_manager=db_manager,
            config=config,
            project_id=project_id,
            registry=registry,
            event_system=mock_event_system,
        )

        # Create a document with a relationship
        doc = ParsedDocument(
            doc_id="doc-1",
            file_path="main.py",
            chunks=[
                ParserChunk(
                    content="import os\n\ndef main():\n    os.getcwd()",
                    language="python",
                    symbols=["main"],
                    symbol_metadata={"main": {"type": "function"}},
                    relationships=[
                        ParserRelationship(
                            source_type="function",
                            source_name="main",
                            target_type="module",
                            target_name="os",
                            type="imports",
                        )
                    ],
                ),
            ],
        )

        # Process the document (this should now flush relationships)
        await pipeline.process_document(doc)

        # Verify relationships were stored
        relationships = await db_manager.advanced_filter("graph_relationships", {})

        # Should have at least 1 relationship (imports os)
        assert len(relationships) >= 1, (
            f"Expected at least 1 relationship after processing, got {len(relationships)}"
        )


class TestIndexingResultRelationships:
    """Test IndexingResult includes relationships_created field."""

    def test_indexing_result_has_relationships_field(self):
        """Verify IndexingResult has relationships_created field."""
        result = IndexingResult(
            operation_id="test",
            status="completed",
            chunks_created=10,
            entities_created=5,
            relationships_created=3,
        )

        assert result.relationships_created == 3
        assert result.has_graph_data() is True

    def test_indexing_result_default_relationships_zero(self):
        """Verify relationships_created defaults to 0 for backward compatibility."""
        result = IndexingResult(
            operation_id="test",
            status="completed",
            chunks_created=10,
            entities_created=5,
        )

        assert result.relationships_created == 0

    def test_indexing_result_has_graph_data(self):
        """Verify has_graph_data() returns True when graph data exists."""
        # Only entities
        result1 = IndexingResult(
            operation_id="test",
            status="completed",
            chunks_created=0,
            entities_created=5,
            relationships_created=0,
        )
        assert result1.has_graph_data() is True

        # Only relationships
        result2 = IndexingResult(
            operation_id="test",
            status="completed",
            chunks_created=0,
            entities_created=0,
            relationships_created=3,
        )
        assert result2.has_graph_data() is True

        # Both
        result3 = IndexingResult(
            operation_id="test",
            status="completed",
            chunks_created=0,
            entities_created=5,
            relationships_created=3,
        )
        assert result3.has_graph_data() is True

        # Neither
        result4 = IndexingResult(
            operation_id="test",
            status="completed",
            chunks_created=0,
            entities_created=0,
            relationships_created=0,
        )
        assert result4.has_graph_data() is False

    def test_indexing_result_to_dict_includes_relationships(self):
        """Verify to_dict() includes relationships_created."""
        result = IndexingResult(
            operation_id="test",
            status="completed",
            chunks_created=10,
            entities_created=5,
            relationships_created=3,
        )

        d = result.to_dict()
        assert "relationships_created" in d
        assert d["relationships_created"] == 3
