"""Tests for timing instrumentation in critical operations.

This test verifies that timing is properly instrumented for:
- Resolution operations (RelationshipResolver)
- Database queries (LanceDBManager)
- Embedding generation (SentenceTransformerEmbedder)
"""

import pytest


from agentic_inquiry.metrics import get_metrics_tracker, reset_metrics


class TestResolutionTiming:
    """Test timing instrumentation for resolution operations."""

    @pytest.mark.asyncio
    async def test_relationship_resolver_tracks_timing(self):
        """Verify RelationshipResolver tracks resolution timing."""
        from agentic_inquiry.indexing.relationship_resolver import RelationshipResolver
        from agentic_inquiry.indexing.symbol_registry import SymbolRegistry
        import tempfile

        # Reset metrics
        reset_metrics()
        tracker = get_metrics_tracker()

        # Create resolver with temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = SymbolRegistry(project_root=tmpdir, project_id="test")
            resolver = RelationshipResolver(
                symbol_registry=registry, project_root=tmpdir
            )

            # Perform resolution (will fail but timing should be tracked)
            await resolver.resolve_import(
                target_name="TestClass",
                target_type="class",
                source_file="test.py",
                source_language="python",
            )

            # Verify timing was tracked
            metrics = tracker.get_latency_metrics("resolver.resolve_import")
            assert metrics.count == 1
            assert metrics.total_time > 0
            assert metrics.avg_time > 0


class TestDatabaseTiming:
    """Test timing instrumentation for database operations."""

    @pytest.mark.asyncio
    async def test_add_document_chunks_tracks_timing(self, tmp_path):
        """Verify add_document_chunks tracks timing."""
        from agentic_inquiry.database.lancedb_manager import LanceDBManager
        from agentic_inquiry.config import Config, StorageConfig

        # Reset metrics
        reset_metrics()
        tracker = get_metrics_tracker()

        # Create config with temp directory
        config = Config()
        config.storage = StorageConfig(root=str(tmp_path))

        async with LanceDBManager.from_config(config) as db:
            # Add empty chunks (should complete quickly)
            await db.add_document_chunks([])

            # Verify timing was tracked
            metrics = tracker.get_latency_metrics("db.add_document_chunks")
            assert metrics.count == 1
            assert metrics.total_time >= 0

    @pytest.mark.asyncio
    async def test_add_graph_entities_tracks_timing(self, tmp_path):
        """Verify add_graph_entities tracks timing."""
        from agentic_inquiry.database.lancedb_manager import LanceDBManager
        from agentic_inquiry.config import Config, StorageConfig

        # Reset metrics
        reset_metrics()
        tracker = get_metrics_tracker()

        # Create config with temp directory
        config = Config()
        config.storage = StorageConfig(root=str(tmp_path))

        async with LanceDBManager.from_config(config) as db:
            # Add empty entities
            await db.add_graph_entities([])

            # Verify timing was tracked
            metrics = tracker.get_latency_metrics("db.add_graph_entities")
            assert metrics.count == 1
            assert metrics.total_time >= 0

    @pytest.mark.asyncio
    async def test_add_graph_relationships_tracks_timing(self, tmp_path):
        """Verify add_graph_relationships tracks timing."""
        from agentic_inquiry.database.lancedb_manager import LanceDBManager
        from agentic_inquiry.config import Config, StorageConfig

        # Reset metrics
        reset_metrics()
        tracker = get_metrics_tracker()

        # Create config with temp directory
        config = Config()
        config.storage = StorageConfig(root=str(tmp_path))

        async with LanceDBManager.from_config(config) as db:
            # Add empty relationships
            await db.add_graph_relationships([])

            # Verify timing was tracked
            metrics = tracker.get_latency_metrics("db.add_graph_relationships")
            assert metrics.count == 1
            assert metrics.total_time >= 0

    @pytest.mark.asyncio
    async def test_advanced_filter_tracks_timing(self, tmp_path):
        """Verify advanced_filter tracks timing."""
        from agentic_inquiry.database.lancedb_manager import LanceDBManager
        from agentic_inquiry.config import Config, StorageConfig

        # Reset metrics
        reset_metrics()
        tracker = get_metrics_tracker()

        # Create config with temp directory
        config = Config()
        config.storage = StorageConfig(root=str(tmp_path))

        async with LanceDBManager.from_config(config) as db:
            # Query non-existent table (should return empty)
            await db.advanced_filter("document_chunks", limit=10)

            # Verify timing was tracked
            metrics = tracker.get_latency_metrics("db.advanced_filter")
            assert metrics.count == 1
            assert metrics.total_time >= 0

    @pytest.mark.asyncio
    async def test_query_across_projects_tracks_timing(self, tmp_path):
        """Verify query_across_projects tracks timing."""
        from agentic_inquiry.database.lancedb_manager import LanceDBManager
        from agentic_inquiry.config import Config, StorageConfig

        # Reset metrics
        reset_metrics()
        tracker = get_metrics_tracker()

        # Create config with temp directory
        config = Config()
        config.storage = StorageConfig(root=str(tmp_path))

        async with LanceDBManager.from_config(config) as db:
            # Query across projects
            await db.query_across_projects(
                "document_chunks", filters={}, project_ids=["test1", "test2"], limit=10
            )

            # Verify timing was tracked
            metrics = tracker.get_latency_metrics("db.query_across_projects")
            assert metrics.count == 1
            assert metrics.total_time >= 0


class TestEmbeddingTiming:
    """Test timing instrumentation for embedding generation."""

    @pytest.mark.slow
    def test_embedder_tracks_timing(self):
        """Verify SentenceTransformerEmbedder tracks timing."""
        from agentic_inquiry.embeddings.sentence_transformer import (
            SentenceTransformerEmbedder,
        )

        # Reset metrics
        reset_metrics()
        tracker = get_metrics_tracker()

        # Create embedder
        embedder = SentenceTransformerEmbedder(ndims=384)

        # Generate embeddings
        texts = ["test text 1", "test text 2"]
        vectors = embedder.generate(texts)

        # Verify timing was tracked
        metrics = tracker.get_latency_metrics("embeddings.generate")
        assert metrics.count == 1
        assert metrics.total_time > 0
        assert metrics.avg_time > 0

        # Verify embeddings were generated
        assert len(vectors) == 2
        assert len(vectors[0]) == 384


class TestPerformanceMetrics:
    """Test that performance metrics are logged for slow operations."""

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_slow_operations_logged(self, caplog):
        """Verify slow operations are logged as warnings."""
        from agentic_inquiry.metrics import MetricsTracker
        import time

        tracker = MetricsTracker()

        # Simulate slow operation (> 1 second)
        with caplog.at_level("WARNING"):
            with tracker.track_latency("slow_operation"):
                time.sleep(1.1)

        # Verify warning was logged
        assert any(
            "Slow operation detected" in record.message for record in caplog.records
        )
        assert any("slow_operation" in record.message for record in caplog.records)

    def test_metrics_summary_includes_all_operations(self):
        """Verify metrics summary includes all tracked operations."""
        from agentic_inquiry.metrics import MetricsTracker

        tracker = MetricsTracker()

        # Track multiple operations
        with tracker.track_latency("operation1"):
            pass

        with tracker.track_latency("operation2"):
            pass

        with tracker.track_latency("operation1"):
            pass

        # Get summary
        summary = tracker.get_summary()

        # Verify summary structure
        assert "latency_metrics" in summary
        assert "total_operations" in summary

        # Verify operations are tracked
        assert "operation1" in summary["latency_metrics"]
        assert "operation2" in summary["latency_metrics"]

        # Verify counts
        assert summary["latency_metrics"]["operation1"]["count"] == 2
        assert summary["latency_metrics"]["operation2"]["count"] == 1
        assert summary["total_operations"] == 3
