"""Property-based tests for memory management features.

These tests validate memory pressure detection, automatic flushing,
and cleanup behavior as specified in the design document.

Property tests:
- Property 30: Automatic Flush Threshold (Requirements 10.1)
- Property 24: Automatic External Entity Flush (Requirements 7.5)
- Property 31: Memory Cleanup After Commit (Requirements 10.3)
- Property 32: Queue Cleanup on Completion (Requirements 10.4)
- Property 33: Adaptive Batch Size (Requirements 10.5)
"""

import pytest

pytestmark = pytest.mark.unit

from hypothesis import given, strategies as st, settings
from unittest.mock import MagicMock

from agent_vault.indexing.graph_builder import GraphBuilder, GraphBuilderConfig
from agent_vault.parsers.models import ParserRelationship


# =============================================================================
# Helpers for creating test data
# =============================================================================

def create_mock_relationship(
    source_name: str,
    target_name: str,
    relationship_type: str = "calls",
) -> ParserRelationship:
    """Create a mock ParserRelationship for testing."""
    return ParserRelationship(
        source_type="function",
        source_name=source_name,
        target_type="function",
        target_name=target_name,
        type=relationship_type,
    )


def create_mock_builder() -> GraphBuilder:
    """Create a mock GraphBuilder for testing."""
    mock_db = MagicMock()
    mock_registry = MagicMock()
    mock_resolver = MagicMock()
    mock_embedding = MagicMock()

    return GraphBuilder(
        db_manager=mock_db,
        symbol_registry=mock_registry,
        relationship_resolver=mock_resolver,
        embedding_service=mock_embedding,
        project_id="test",
        project_hash="hash123",
        project_root="/tmp/test_project",
    )


# =============================================================================
# Property 30: Automatic Flush Threshold
# Validates: Requirements 10.1
# =============================================================================

class TestAutomaticFlushThreshold:
    """Tests for automatic flush when pending relationships exceed threshold."""

    def test_check_memory_pressure_no_pressure(self):
        """Should report no pressure when under thresholds."""
        builder = create_mock_builder()

        # Add some relationships under threshold
        for i in range(100):
            rel = create_mock_relationship(f"func_{i}", f"target_{i}")
            builder.add_pending_relationship(rel, f"file_{i}.py")

        config = GraphBuilderConfig(auto_flush_threshold=50000)
        pressure = builder._check_memory_pressure(config)

        assert not pressure["needs_relationship_flush"]
        assert pressure["pending_relationships"] == 100

    def test_check_memory_pressure_at_threshold(self):
        """Should report pressure when at or above threshold."""
        builder = create_mock_builder()
        config = GraphBuilderConfig(auto_flush_threshold=50)

        # Add relationships to reach threshold
        for i in range(50):
            rel = create_mock_relationship(f"func_{i}", f"target_{i}")
            builder.add_pending_relationship(rel, f"file_{i}.py")

        pressure = builder._check_memory_pressure(config)

        assert pressure["needs_relationship_flush"]
        assert pressure["pending_relationships"] == 50

    @given(
        pending_count=st.integers(min_value=0, max_value=1000),
        threshold=st.integers(min_value=1, max_value=500),
    )
    @settings(max_examples=50)
    def test_property_30_automatic_flush_threshold(self, pending_count, threshold):
        """Property 30: For any pending relationship count >= auto_flush_threshold,
        _check_memory_pressure SHALL return needs_relationship_flush=True.
        """
        builder = create_mock_builder()
        config = GraphBuilderConfig(auto_flush_threshold=threshold)

        # Add pending relationships
        for i in range(pending_count):
            rel = create_mock_relationship(f"f{i}", f"t{i}")
            builder.add_pending_relationship(rel, f"f{i}.py")

        pressure = builder._check_memory_pressure(config)

        if pending_count >= threshold:
            assert pressure["needs_relationship_flush"]
        else:
            assert not pressure["needs_relationship_flush"]


# =============================================================================
# Property 24: Automatic External Entity Flush
# Validates: Requirements 7.5
# =============================================================================

class TestAutomaticExternalEntityFlush:
    """Tests for automatic external entity flush when threshold exceeded."""

    def test_check_memory_pressure_external_entities(self):
        """Should report pressure when external entities exceed threshold."""
        builder = create_mock_builder()
        config = GraphBuilderConfig(external_entity_flush_threshold=10)

        # Add external entities directly to the dict
        for i in range(10):
            # Mock external entity info
            builder._pending_external_entities[f"ext_{i}"] = MagicMock(
                entity_id=f"ext_{i}",
                name=f"ExternalEntity{i}",
                source_path=f"external/{i}.py",
                target_path=None,
            )

        pressure = builder._check_memory_pressure(config)

        assert pressure["needs_external_entity_flush"]
        assert pressure["pending_external_entities"] == 10

    @given(
        external_count=st.integers(min_value=0, max_value=100),
        threshold=st.integers(min_value=1, max_value=50),
    )
    @settings(max_examples=50)
    def test_property_24_external_entity_threshold(self, external_count, threshold):
        """Property 24: For any pending external entity count >= threshold,
        _check_memory_pressure SHALL return needs_external_entity_flush=True.
        """
        builder = create_mock_builder()
        config = GraphBuilderConfig(external_entity_flush_threshold=threshold)

        # Add external entities
        for i in range(external_count):
            builder._pending_external_entities[f"ext_{i}"] = MagicMock()

        pressure = builder._check_memory_pressure(config)

        if external_count >= threshold:
            assert pressure["needs_external_entity_flush"]
        else:
            assert not pressure["needs_external_entity_flush"]


# =============================================================================
# Property 31: Memory Cleanup After Commit
# Validates: Requirements 10.3
# =============================================================================

class TestMemoryCleanupAfterCommit:
    """Tests for memory cleanup after batch commits."""

    def test_cleanup_processed_batch_removes_relationships(self):
        """Cleanup should remove processed relationships from pending queue."""
        builder = create_mock_builder()

        # Add some relationships
        rels = []
        for i in range(10):
            rel = create_mock_relationship(f"func_{i}", f"target_{i}")
            builder.add_pending_relationship(rel, f"file_{i}.py")
            rels.append((rel, f"file_{i}.py"))

        # Process some of them
        processed = rels[:5]

        removed = builder._cleanup_processed_batch(processed)

        assert removed == 5
        assert len(builder._pending_relationships) == 5

    def test_cleanup_processed_batch_empty_list(self):
        """Cleanup with empty list should do nothing."""
        builder = create_mock_builder()

        rel = create_mock_relationship("func", "target")
        builder.add_pending_relationship(rel, "file.py")

        removed = builder._cleanup_processed_batch([])

        assert removed == 0
        assert len(builder._pending_relationships) == 1

    @given(
        total_count=st.integers(min_value=5, max_value=100),
        processed_count=st.integers(min_value=0, max_value=5),
    )
    @settings(max_examples=50)
    def test_property_31_cleanup_removes_processed(self, total_count, processed_count):
        """Property 31: For any batch that is committed, the processed
        relationships SHALL be removed from the pending queue.
        """
        processed_count = min(processed_count, total_count)
        builder = create_mock_builder()

        # Add relationships
        rels = []
        for i in range(total_count):
            rel = create_mock_relationship(f"f{i}", f"t{i}")
            builder.add_pending_relationship(rel, f"f{i}.py")
            rels.append((rel, f"f{i}.py"))

        # Process some
        processed = rels[:processed_count]
        removed = builder._cleanup_processed_batch(processed)

        assert removed == processed_count
        assert len(builder._pending_relationships) == total_count - processed_count


# =============================================================================
# Property 32: Queue Cleanup on Completion
# Validates: Requirements 10.4
# =============================================================================

class TestQueueCleanupOnCompletion:
    """Tests for queue cleanup on flush completion."""

    def test_cleanup_queues_clears_all(self):
        """Cleanup should clear all pending queues."""
        builder = create_mock_builder()

        # Add relationships
        for i in range(5):
            rel = create_mock_relationship(f"func_{i}", f"target_{i}")
            builder.add_pending_relationship(rel, f"file_{i}.py")

        # Add external entities
        for i in range(3):
            builder._pending_external_entities[f"ext_{i}"] = MagicMock()

        result = builder._cleanup_queues()

        assert result["relationships_cleared"] == 5
        assert result["external_entities_cleared"] == 3
        assert len(builder._pending_relationships) == 0
        assert len(builder._pending_external_entities) == 0

    def test_cleanup_queues_empty(self):
        """Cleanup on empty queues should return zero counts."""
        builder = create_mock_builder()

        result = builder._cleanup_queues()

        assert result["relationships_cleared"] == 0
        assert result["external_entities_cleared"] == 0

    @given(
        rel_count=st.integers(min_value=0, max_value=100),
        ext_count=st.integers(min_value=0, max_value=50),
    )
    @settings(max_examples=50)
    def test_property_32_queue_cleanup_clears_all(self, rel_count, ext_count):
        """Property 32: For any flush completion, _cleanup_queues SHALL
        clear all pending relationships and external entities.
        """
        builder = create_mock_builder()

        # Add relationships
        for i in range(rel_count):
            rel = create_mock_relationship(f"f{i}", f"t{i}")
            builder.add_pending_relationship(rel, f"f{i}.py")

        # Add external entities
        for i in range(ext_count):
            builder._pending_external_entities[f"ext_{i}"] = MagicMock()

        result = builder._cleanup_queues()

        assert result["relationships_cleared"] == rel_count
        assert result["external_entities_cleared"] == ext_count
        assert len(builder._pending_relationships) == 0
        assert len(builder._pending_external_entities) == 0


# =============================================================================
# Property 33: Adaptive Batch Size
# Validates: Requirements 10.5
# =============================================================================

class TestAdaptiveBatchSize:
    """Tests for adaptive batch sizing under memory pressure."""

    def test_adaptive_batch_size_no_pressure(self):
        """Batch size should not change when under 75% threshold."""
        builder = create_mock_builder()
        config = GraphBuilderConfig(auto_flush_threshold=1000)

        # Add a few relationships (under 75% of 1000)
        for i in range(100):
            rel = create_mock_relationship(f"f{i}", f"t{i}")
            builder.add_pending_relationship(rel, f"f{i}.py")

        adapted_size = builder.get_adaptive_batch_size(100, config)

        assert adapted_size == 100  # Full batch size

    def test_adaptive_batch_size_under_pressure(self):
        """Batch size should reduce when approaching threshold."""
        builder = create_mock_builder()
        config = GraphBuilderConfig(auto_flush_threshold=100)

        # Add relationships to 80% of threshold
        for i in range(80):
            rel = create_mock_relationship(f"f{i}", f"t{i}")
            builder.add_pending_relationship(rel, f"f{i}.py")

        adapted_size = builder.get_adaptive_batch_size(100, config)

        assert adapted_size < 100  # Reduced batch size

    def test_adaptive_batch_size_high_pressure(self):
        """Batch size should be significantly reduced at 100%+ pressure."""
        builder = create_mock_builder()
        config = GraphBuilderConfig(auto_flush_threshold=100)

        # Add relationships to exceed threshold
        for i in range(120):
            rel = create_mock_relationship(f"f{i}", f"t{i}")
            builder.add_pending_relationship(rel, f"f{i}.py")

        adapted_size = builder.get_adaptive_batch_size(100, config)

        assert adapted_size == 25  # 25% of original

    @given(
        pending_count=st.integers(min_value=0, max_value=200),
        threshold=st.integers(min_value=10, max_value=100),
        base_batch_size=st.integers(min_value=10, max_value=200),
    )
    @settings(max_examples=50)
    def test_property_33_adaptive_batch_size(
        self, pending_count, threshold, base_batch_size
    ):
        """Property 33: For any memory pressure level, the adaptive batch size
        SHALL be reduced proportionally, with minimum of 1.
        """
        builder = create_mock_builder()
        config = GraphBuilderConfig(auto_flush_threshold=threshold)

        # Add relationships
        for i in range(pending_count):
            rel = create_mock_relationship(f"f{i}", f"t{i}")
            builder.add_pending_relationship(rel, f"f{i}.py")

        adapted_size = builder.get_adaptive_batch_size(base_batch_size, config)

        # Should always be at least 1
        assert adapted_size >= 1

        # Should never exceed base batch size
        assert adapted_size <= base_batch_size

        # Under 75% pressure, should be full batch size
        pressure_ratio = pending_count / threshold
        if pressure_ratio < 0.75:
            assert adapted_size == base_batch_size


# =============================================================================
# Additional Tests
# =============================================================================

class TestMemoryPressureLogging:
    """Tests for memory pressure logging."""

    def test_pressure_logs_warning_when_exceeded(self, caplog):
        """Memory pressure should log warning when threshold exceeded."""
        import logging

        builder = create_mock_builder()
        config = GraphBuilderConfig(auto_flush_threshold=10)

        # Add relationships to exceed threshold
        for i in range(15):
            rel = create_mock_relationship(f"f{i}", f"t{i}")
            builder.add_pending_relationship(rel, f"f{i}.py")

        with caplog.at_level(logging.WARNING):
            builder._check_memory_pressure(config)

        assert any("Memory pressure" in record.message for record in caplog.records)


class TestDefaultConfiguration:
    """Tests for default memory management configuration."""

    def test_default_auto_flush_threshold(self):
        """Default auto flush threshold should be 50000."""
        config = GraphBuilderConfig()
        assert config.auto_flush_threshold == 50000

    def test_default_external_entity_threshold(self):
        """Default external entity threshold should be 10000."""
        config = GraphBuilderConfig()
        assert config.external_entity_flush_threshold == 10000

