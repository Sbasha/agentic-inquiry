"""Basic tests for IndexingPipeline."""

import asyncio
import logging

import pytest

pytestmark = pytest.mark.integration

from unittest.mock import AsyncMock, MagicMock

from agentic_inquiry.config import Config
from agentic_inquiry.embeddings.base import Embedder
from agentic_inquiry.embeddings.registry import EmbeddingRegistry
from agentic_inquiry.indexing.pipeline import IndexingPipeline
from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk
from tests.utils.in_memory_lancedb_manager import InMemoryLanceDBManager


def _create_mock_event_system():
    """Create a mock event system for tests."""
    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    return mock_es


class _DummyEmbedder(Embedder):
    def __init__(self):
        self._ndims = 1
        self.generated_texts = []

    def generate(self, texts):
        self.generated_texts.extend(texts)
        return [[float(len(text))] for text in texts]

    def ndims(self):
        return self._ndims


class _FallbackEmbedder(_DummyEmbedder):
    def get_fallback_text(self, chunk: ParserChunk):
        return (chunk.metadata or {}).get("fallback")


def test_pipeline_skips_chunks_without_text(caplog):
    async def run():
        import uuid
        config = Config.load()
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test")
        await mock_db_manager.create_tables_and_indexes()
        await mock_db_manager.connect()

        project_id = f"test_{uuid.uuid4().hex[:8]}"
        mock_event_system = _create_mock_event_system()
        pipeline = IndexingPipeline(db_manager=mock_db_manager, config=config, project_id=project_id, event_system=mock_event_system, registry=registry)

        doc = ParsedDocument(
            doc_id="doc-1",
            file_path="file.py",
            chunks=[
                ParserChunk(content="valid chunk"),
                ParserChunk(content=None),
            ],
        )

        caplog.set_level(logging.WARNING)
        await pipeline.process_document(doc)

        rows = await mock_db_manager.advanced_filter("document_chunks", {"doc_id": "doc-1"})
        assert len(rows) == 1
        assert rows[0]["content"] == "valid chunk"
        assert rows[0]["project_id"] == pipeline.project_hash
        assert rows[0]["chunk_index"] == 0
        assert rows[0]["total_chunks"] == 2
        assert any("Skipping chunk" in record.message for record in caplog.records)

    asyncio.run(run())


def test_pipeline_uses_fallback_text_when_available():
    async def run():
        import uuid
        config = Config.load()
        registry = EmbeddingRegistry(default_embedder=_FallbackEmbedder())
        mock_db_manager = InMemoryLanceDBManager(uri="memory://test-fallback")
        await mock_db_manager.create_tables_and_indexes()
        await mock_db_manager.connect()

        project_id = f"test_{uuid.uuid4().hex[:8]}"
        mock_event_system = _create_mock_event_system()
        pipeline = IndexingPipeline(db_manager=mock_db_manager, config=config, project_id=project_id, event_system=mock_event_system, registry=registry)

        doc = ParsedDocument(
            doc_id="doc-2",
            file_path="file.py",
            chunks=[
                ParserChunk(content=None, metadata={"fallback": "generated fallback"}),
            ],
        )

        await pipeline.process_document(doc)

        rows = await mock_db_manager.advanced_filter("document_chunks", {"doc_id": "doc-2"})
        assert len(rows) == 1
        assert rows[0]["content"] == "generated fallback"
        assert rows[0]["project_id"] == pipeline.project_hash
        assert rows[0]["chunk_index"] == 0

    asyncio.run(run())
