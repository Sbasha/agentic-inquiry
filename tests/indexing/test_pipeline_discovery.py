"""Tests for file discovery and status handling in IndexingPipeline.

These tests verify that:
1. Empty directories return 'no_files_found' status
2. Directories with only ignored files return proper status
3. Diagnostics are included in results
4. IndexingResult helper methods work correctly
"""

import pytest

pytestmark = pytest.mark.integration

import tempfile
from pathlib import Path

from agentic_inquiry.config import Config
from agentic_inquiry.embeddings.base import Embedder
from agentic_inquiry.embeddings.registry import EmbeddingRegistry
from agentic_inquiry.indexing.models import IndexingResult
from agentic_inquiry.indexing.pipeline import IndexingPipeline
from tests.utils.in_memory_lancedb_manager import InMemoryLanceDBManager


class _DummyEmbedder(Embedder):
    """Dummy embedder for tests."""

    def __init__(self):
        self._ndims = 384

    def generate(self, texts):
        return [[0.1] * 384 for _ in texts]

    def ndims(self):
        return self._ndims


class TestEmptyDirectoryHandling:
    """Test handling of empty directories."""

    @pytest.mark.asyncio
    async def test_empty_directory_returns_no_files_found(self):
        """Verify empty directory returns no_files_found status."""
        import uuid

        config = Config.load()
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        db_manager = InMemoryLanceDBManager(uri="memory://test-empty-dir")
        await db_manager.create_tables_and_indexes()
        await db_manager.connect()

        project_id = f"test_{uuid.uuid4().hex[:8]}"

        pipeline = IndexingPipeline(
            db_manager=db_manager,
            config=config,
            project_id=project_id,
            registry=registry,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            result = await pipeline.index_directory(
                path=tmpdir,
                content_type="directory",
                wait=True,
            )

            # index_directory returns a dict via to_dict()
            assert result["status"] == "no_files_found", (
                f"Expected 'no_files_found' for empty directory, got '{result['status']}'"
            )
            assert result["files_processed"] == 0
            assert "No indexable files" in result["message"]

    @pytest.mark.asyncio
    async def test_all_ignored_directory_returns_no_files_found(self):
        """Verify directory with only ignored files returns no_files_found."""
        import uuid

        config = Config.load()
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        db_manager = InMemoryLanceDBManager(uri="memory://test-ignored-dir")
        await db_manager.create_tables_and_indexes()
        await db_manager.connect()

        project_id = f"test_{uuid.uuid4().hex[:8]}"

        pipeline = IndexingPipeline(
            db_manager=db_manager,
            config=config,
            project_id=project_id,
            registry=registry,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create only binary/ignored files
            Path(tmpdir, "test.pyc").write_bytes(b"compiled")
            Path(tmpdir, "test.exe").write_bytes(b"binary")
            Path(tmpdir, "test.dll").write_bytes(b"library")

            result = await pipeline.index_directory(
                path=tmpdir,
                content_type="directory",
                wait=True,
            )

            # index_directory returns a dict via to_dict()
            assert result["status"] == "no_files_found", (
                f"Expected 'no_files_found' for ignored-only directory, got '{result['status']}'"
            )
            assert result["files_processed"] == 0


class TestDiagnosticsInResult:
    """Test that diagnostics are included in IndexingResult."""

    @pytest.mark.asyncio
    async def test_diagnostics_included_in_result(self):
        """Verify diagnostics are included in result when indexing empty directory."""
        import uuid

        config = Config.load()
        registry = EmbeddingRegistry(default_embedder=_DummyEmbedder())
        db_manager = InMemoryLanceDBManager(uri="memory://test-diagnostics")
        await db_manager.create_tables_and_indexes()
        await db_manager.connect()

        project_id = f"test_{uuid.uuid4().hex[:8]}"

        pipeline = IndexingPipeline(
            db_manager=db_manager,
            config=config,
            project_id=project_id,
            registry=registry,
        )

        # Use an empty temp directory to avoid security constraints
        with tempfile.TemporaryDirectory() as tmpdir:
            result = await pipeline.index_directory(
                path=tmpdir,
                content_type="directory",
                wait=True,
            )

            # index_directory returns a dict via to_dict()
            # diagnostics should be present for no_files_found case
            assert "diagnostics" in result, "Expected diagnostics to be present"
            assert "files_discovered" in result["diagnostics"]
            assert "files_processed" in result["diagnostics"]
            assert "files_failed" in result["diagnostics"]

    @pytest.mark.asyncio
    async def test_files_discovered_property(self):
        """Verify files_discovered property works correctly."""
        # With diagnostics
        result = IndexingResult(
            operation_id="test",
            status="completed",
            chunks_created=10,
            entities_created=5,
            files_processed=3,
            files_failed=2,
            diagnostics={
                "files_discovered": 10,
                "files_processed": 3,
                "files_failed": 2,
            },
        )
        assert result.files_discovered == 10

        # Without diagnostics (fallback)
        result2 = IndexingResult(
            operation_id="test",
            status="completed",
            chunks_created=10,
            entities_created=5,
            files_processed=3,
            files_failed=2,
        )
        assert result2.files_discovered == 5  # files_processed + files_failed


class TestStatusValues:
    """Test distinct status values for different scenarios."""

    def test_completed_status(self):
        """Verify 'completed' status for successful indexing."""
        result = IndexingResult(
            operation_id="test",
            status="completed",
            chunks_created=10,
            entities_created=5,
            files_processed=3,
        )
        assert result.is_success()
        assert not result.is_empty_result()

    def test_completed_with_errors_status(self):
        """Verify 'completed_with_errors' is still considered success."""
        result = IndexingResult(
            operation_id="test",
            status="completed_with_errors",
            chunks_created=10,
            entities_created=5,
            files_processed=3,
            files_failed=1,
        )
        assert result.is_success()
        assert result.is_partial_success()

    def test_no_files_found_status(self):
        """Verify 'no_files_found' status is not considered success."""
        result = IndexingResult(
            operation_id="test",
            status="no_files_found",
            chunks_created=0,
            entities_created=0,
            files_processed=0,
        )
        assert not result.is_success()
        assert result.is_empty_result()

    def test_all_files_failed_status(self):
        """Verify 'all_files_failed' status is not considered success."""
        result = IndexingResult(
            operation_id="test",
            status="all_files_failed",
            chunks_created=0,
            entities_created=0,
            files_processed=0,
            files_failed=5,
        )
        assert not result.is_success()
        assert result.is_empty_result()

    def test_failed_status(self):
        """Verify 'failed' status is not considered success."""
        result = IndexingResult(
            operation_id="test",
            status="failed",
            chunks_created=0,
            entities_created=0,
            message="Indexing failed: error",
        )
        assert not result.is_success()


class TestIndexingResultHelpers:
    """Test IndexingResult helper methods."""

    def test_is_success(self):
        """Test is_success() method."""
        result = IndexingResult(
            operation_id="test",
            status="completed",
            chunks_created=10,
            entities_created=5,
        )
        assert result.is_success()

        result2 = IndexingResult(
            operation_id="test",
            status="failed",
            chunks_created=0,
            entities_created=0,
        )
        assert not result2.is_success()

    def test_is_empty_result(self):
        """Test is_empty_result() method."""
        result = IndexingResult(
            operation_id="test",
            status="no_files_found",
            chunks_created=0,
            entities_created=0,
            files_processed=0,
        )
        assert result.is_empty_result()

        result2 = IndexingResult(
            operation_id="test",
            status="completed",
            chunks_created=10,
            entities_created=5,
            files_processed=3,
        )
        assert not result2.is_empty_result()

    def test_has_graph_data(self):
        """Test has_graph_data() method."""
        result = IndexingResult(
            operation_id="test",
            status="completed",
            chunks_created=10,
            entities_created=5,
            relationships_created=3,
        )
        assert result.has_graph_data()

        result2 = IndexingResult(
            operation_id="test",
            status="completed",
            chunks_created=10,
            entities_created=0,
            relationships_created=0,
        )
        assert not result2.has_graph_data()

    def test_to_dict_includes_diagnostics(self):
        """Test to_dict() includes diagnostics when present."""
        result = IndexingResult(
            operation_id="test",
            status="completed",
            chunks_created=10,
            entities_created=5,
            diagnostics={"files_discovered": 5, "files_processed": 3},
        )

        d = result.to_dict()
        assert "diagnostics" in d
        assert d["diagnostics"]["files_discovered"] == 5

        # Without diagnostics
        result2 = IndexingResult(
            operation_id="test",
            status="completed",
            chunks_created=10,
            entities_created=5,
        )

        d2 = result2.to_dict()
        assert "diagnostics" not in d2
