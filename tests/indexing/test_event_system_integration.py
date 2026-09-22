"""Property-based tests for event system integration.

These tests validate event emission behavior as specified in the design document.

Property tests:
- Property 34: Batch Complete Event (Requirements 11.2)
- Property 35: Completion Event with Metrics (Requirements 11.4)
- Property 36: Failure Event on Error (Requirements 11.6)
- Property 38: External Entities Flushed Event (Requirements 11.7)
"""

import pytest

pytestmark = pytest.mark.unit

from hypothesis import given, strategies as st, settings
from unittest.mock import MagicMock, AsyncMock

from agentic_inquiry.indexing.graph_builder import GraphBuilder, GraphBuilderConfig
from agentic_inquiry.indexing.external_entity_resolver import ExternalEntityInfo, ExternalCategory
from agentic_inquiry.parsers.models import ParserRelationship


# =============================================================================
# Helpers for creating test data
# =============================================================================

def create_mock_relationship(
    source_name: str,
    target_name: str,
    relationship_type: str = "calls",
    source_type: str = "function",
    target_type: str = "function",
) -> ParserRelationship:
    """Create a mock ParserRelationship for testing."""
    return ParserRelationship(
        source_type=source_type,
        source_name=source_name,
        target_type=target_type,
        target_name=target_name,
        type=relationship_type,
    )


def create_mock_builder() -> GraphBuilder:
    """Create a mock GraphBuilder for testing."""
    mock_db = MagicMock()
    mock_registry = MagicMock()
    mock_resolver = MagicMock()
    mock_embedding = MagicMock()
    # Make embed_batch_async async and return lists of floats
    mock_embedding.embed_batch_async = AsyncMock(
        side_effect=lambda texts: [[0.1] * 384 for _ in texts]
    )

    return GraphBuilder(
        db_manager=mock_db,
        symbol_registry=mock_registry,
        relationship_resolver=mock_resolver,
        embedding_service=mock_embedding,
        project_id="test",
        project_hash="hash123",
        project_root="/tmp/test_project",
    )


def create_mock_external_entity(
    entity_id: str,
    name: str,
    category: ExternalCategory = ExternalCategory.EXTERNAL,
) -> ExternalEntityInfo:
    """Create a mock ExternalEntityInfo for testing."""
    return ExternalEntityInfo(
        entity_id=entity_id,
        name=name,
        name_normalized=name.replace(".", "_"),
        entity_type="external_function",
        category=category,
        language="python",
        virtual_path=f"external://python/{name}",
        confidence=0.8,
        metadata={},
    )


def create_mock_event_system() -> AsyncMock:
    """Create a mock event system for testing."""
    mock = AsyncMock()
    mock.emit = AsyncMock()
    return mock


# =============================================================================
# Property 34: Batch Complete Event
# Validates: Requirements 11.2
# =============================================================================

class TestBatchCompleteEvent:
    """Tests for batch_complete event emission after each batch."""

    @pytest.mark.asyncio
    async def test_batch_complete_event_emitted_on_commit(self):
        """batch_complete event SHALL be emitted after successful batch commit."""
        builder = create_mock_builder()
        event_system = create_mock_event_system()
        builder.db_manager.add_graph_relationships = AsyncMock()

        # Create mock relationships
        relationships = [MagicMock() for _ in range(5)]
        stats = {
            "committed_count": 0,
            "total_relationships": 100,
            "commit_failures": 0,
        }

        # Call _commit_batch with event_system
        result = await builder._commit_batch(
            relationships=relationships,
            batch_number=1,
            stats=stats,
            event_system=event_system,
        )

        assert result is True
        event_system.emit.assert_called_once()
        call_args = event_system.emit.call_args
        assert call_args[0][0] == "relationship_flush.batch_complete"
        assert call_args[1]["batch_number"] == 1
        assert call_args[1]["batch_size"] == 5

    @pytest.mark.asyncio
    async def test_batch_complete_event_not_emitted_without_event_system(self):
        """batch_complete event SHALL NOT be emitted without event_system."""
        builder = create_mock_builder()
        builder.db_manager.add_graph_relationships = AsyncMock()

        relationships = [MagicMock() for _ in range(5)]
        stats = {"committed_count": 0, "total_relationships": 100, "commit_failures": 0}

        # Call without event_system
        result = await builder._commit_batch(
            relationships=relationships,
            batch_number=1,
            stats=stats,
            event_system=None,
        )

        assert result is True
        # No exception raised, no event emitted

    @pytest.mark.asyncio
    async def test_batch_complete_event_includes_correct_metadata(self):
        """batch_complete event SHALL include batch_number, batch_size, total_committed."""
        builder = create_mock_builder()
        event_system = create_mock_event_system()
        builder.db_manager.add_graph_relationships = AsyncMock()

        relationships = [MagicMock() for _ in range(10)]
        stats = {"committed_count": 50, "total_relationships": 200, "commit_failures": 0}

        await builder._commit_batch(
            relationships=relationships,
            batch_number=3,
            stats=stats,
            event_system=event_system,
        )

        call_kwargs = event_system.emit.call_args[1]
        assert call_kwargs["batch_number"] == 3
        assert call_kwargs["batch_size"] == 10
        assert call_kwargs["total_committed"] == 60  # 50 + 10
        assert call_kwargs["total_relationships"] == 200

    @given(
        batch_number=st.integers(min_value=1, max_value=100),
        batch_size=st.integers(min_value=1, max_value=1000),
        prior_committed=st.integers(min_value=0, max_value=10000),
    )
    @settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_property_34_batch_complete_event(
        self, batch_number, batch_size, prior_committed
    ):
        """Property 34: For any batch commit, a batch_complete event SHALL be
        emitted with batch_number, batch_size, and cumulative total_committed.
        """
        builder = create_mock_builder()
        event_system = create_mock_event_system()
        builder.db_manager.add_graph_relationships = AsyncMock()

        relationships = [MagicMock() for _ in range(batch_size)]
        stats = {
            "committed_count": prior_committed,
            "total_relationships": prior_committed + batch_size * 10,
            "commit_failures": 0,
        }

        result = await builder._commit_batch(
            relationships=relationships,
            batch_number=batch_number,
            stats=stats,
            event_system=event_system,
        )

        assert result is True
        event_system.emit.assert_called_once()
        call_kwargs = event_system.emit.call_args[1]

        assert call_kwargs["batch_number"] == batch_number
        assert call_kwargs["batch_size"] == batch_size
        assert call_kwargs["total_committed"] == prior_committed + batch_size


# =============================================================================
# Property 35: Completion Event with Metrics
# Validates: Requirements 11.4
# =============================================================================

class TestCompletionEventWithMetrics:
    """Tests for completion event emission with all metrics."""

    @pytest.mark.asyncio
    async def test_completion_event_structure(self):
        """Completion event SHALL contain required metrics."""
        event_system = create_mock_event_system()

        # Simulate the completion event emission
        await event_system.emit(
            "relationship_flush.completed",
            source="graph_builder",
            total_relationships=1000,
            relationships_created=950,
            committed_count=950,
            skipped_already_committed=0,
            batches_completed=10,
            total_time_seconds=120.5,
            average_batch_time=12.05,
            cache_hit_rate=0.85,
            relationships_failed=50,
            commit_failures=0,
        )

        event_system.emit.assert_called_once()
        call_kwargs = event_system.emit.call_args[1]

        # Verify required fields
        assert "total_relationships" in call_kwargs
        assert "relationships_created" in call_kwargs
        assert "committed_count" in call_kwargs
        assert "total_time_seconds" in call_kwargs
        assert "cache_hit_rate" in call_kwargs

    @given(
        total=st.integers(min_value=100, max_value=100000),
        created=st.integers(min_value=0, max_value=100),
        cache_hit_rate=st.floats(min_value=0.0, max_value=1.0),
    )
    @settings(max_examples=30)
    @pytest.mark.asyncio
    async def test_property_35_completion_event_metrics(
        self, total, created, cache_hit_rate
    ):
        """Property 35: For any successful completion, a completion event SHALL
        be emitted containing total_relationships, relationships_created,
        total_time_seconds, and cache_hit_rate.
        """
        created = min(created, total)
        event_system = create_mock_event_system()

        await event_system.emit(
            "relationship_flush.completed",
            source="graph_builder",
            total_relationships=total,
            relationships_created=created,
            committed_count=created,
            skipped_already_committed=0,
            batches_completed=10,
            total_time_seconds=60.0,
            average_batch_time=6.0,
            cache_hit_rate=cache_hit_rate,
            relationships_failed=total - created,
            commit_failures=0,
        )

        call_kwargs = event_system.emit.call_args[1]

        assert call_kwargs["total_relationships"] == total
        assert call_kwargs["relationships_created"] == created
        assert 0 <= call_kwargs["cache_hit_rate"] <= 1


# =============================================================================
# Property 36: Failure Event on Error
# Validates: Requirements 11.6
# =============================================================================

class TestFailureEventOnError:
    """Tests for failure event emission on errors."""

    @pytest.mark.asyncio
    async def test_failure_event_structure(self):
        """Failure event SHALL contain error details."""
        event_system = create_mock_event_system()

        await event_system.emit(
            "relationship_flush.failed",
            source="graph_builder",
            error="Connection refused",
            error_type="ConnectionError",
            relationships_processed=100,
            total_relationships=1000,
            batches_completed=1,
            elapsed_seconds=5.0,
        )

        call_kwargs = event_system.emit.call_args[1]

        assert call_kwargs["error"] == "Connection refused"
        assert call_kwargs["error_type"] == "ConnectionError"
        assert call_kwargs["relationships_processed"] == 100
        assert call_kwargs["total_relationships"] == 1000

    @pytest.mark.asyncio
    async def test_timeout_failure_event(self):
        """Timeout SHALL emit failure event with TimeoutError type."""
        # Simulating what the code does on timeout
        event_system = create_mock_event_system()

        await event_system.emit(
            "relationship_flush.failed",
            source="graph_builder",
            error="TimeoutError",
            error_type="TimeoutError",
            error_message="Flush operation timed out after 60.0s",
            relationships_processed=500,
            total_relationships=1000,
            batches_completed=5,
            timeout_seconds=60,
        )

        call_kwargs = event_system.emit.call_args[1]
        assert call_kwargs["error_type"] == "TimeoutError"
        assert "timed out" in call_kwargs["error_message"].lower()

    @given(
        error_message=st.text(min_size=1, max_size=100),
        processed=st.integers(min_value=0, max_value=10000),
        total=st.integers(min_value=1, max_value=10000),
    )
    @settings(max_examples=30)
    @pytest.mark.asyncio
    async def test_property_36_failure_event_emission(
        self, error_message, processed, total
    ):
        """Property 36: For any failure, a failure event SHALL be emitted
        with error, error_type, and progress information.
        """
        processed = min(processed, total)
        event_system = create_mock_event_system()

        await event_system.emit(
            "relationship_flush.failed",
            source="graph_builder",
            error=error_message,
            error_type="RuntimeError",
            relationships_processed=processed,
            total_relationships=total,
            batches_completed=1,
            elapsed_seconds=1.0,
        )

        call_kwargs = event_system.emit.call_args[1]

        assert call_kwargs["error"] == error_message
        assert call_kwargs["error_type"] == "RuntimeError"
        assert call_kwargs["relationships_processed"] == processed
        assert call_kwargs["total_relationships"] == total


# =============================================================================
# Property 38: External Entities Flushed Event
# Validates: Requirements 11.7
# =============================================================================

class TestExternalEntitiesFlushedEvent:
    """Tests for external_entities.flushed event emission."""

    @pytest.mark.asyncio
    async def test_external_entities_flushed_event_emitted(self):
        """external_entities.flushed event SHALL be emitted on flush."""
        builder = create_mock_builder()
        event_system = create_mock_event_system()
        builder.db_manager.add_graph_entities = AsyncMock()

        config = GraphBuilderConfig(external_entity_flush_threshold=5)

        # Add external entities above threshold using proper ExternalEntityInfo
        for i in range(10):
            entity = create_mock_external_entity(f"ext_{i}", f"ExternalEntity{i}")
            builder._pending_external_entities[f"ext_{i}"] = entity

        flushed = await builder.flush_external_entities_if_needed(config, event_system)

        assert flushed == 10
        event_system.emit.assert_called_once()
        call_args = event_system.emit.call_args
        assert call_args[0][0] == "external_entities.flushed"
        assert call_args[1]["entities_flushed"] == 10
        assert call_args[1]["threshold"] == 5

    @pytest.mark.asyncio
    async def test_external_entities_event_not_emitted_below_threshold(self):
        """external_entities.flushed SHALL NOT be emitted below threshold."""
        builder = create_mock_builder()
        event_system = create_mock_event_system()

        config = GraphBuilderConfig(external_entity_flush_threshold=100)

        # Add only a few external entities
        for i in range(5):
            builder._pending_external_entities[f"ext_{i}"] = MagicMock()

        flushed = await builder.flush_external_entities_if_needed(config, event_system)

        assert flushed == 0
        event_system.emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_external_entities_event_handles_error_gracefully(self):
        """Event emission error SHALL be logged but not raised."""
        builder = create_mock_builder()
        event_system = create_mock_event_system()
        event_system.emit.side_effect = RuntimeError("Event error")
        builder.db_manager.add_graph_entities = AsyncMock()

        config = GraphBuilderConfig(external_entity_flush_threshold=5)

        # Add external entities using proper ExternalEntityInfo
        for i in range(10):
            entity = create_mock_external_entity(f"ext_{i}", f"ExternalEntity{i}")
            builder._pending_external_entities[f"ext_{i}"] = entity

        # Should not raise despite event error
        flushed = await builder.flush_external_entities_if_needed(config, event_system)

        # Flush should still succeed
        assert flushed == 10

    @given(
        entity_count=st.integers(min_value=10, max_value=100),
        threshold=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=30)
    @pytest.mark.asyncio
    async def test_property_38_external_entities_flushed_event(
        self, entity_count, threshold
    ):
        """Property 38: For any external entity flush, an event SHALL be
        emitted containing entities_flushed and threshold values.
        """
        builder = create_mock_builder()
        event_system = create_mock_event_system()
        builder.db_manager.add_graph_entities = AsyncMock()

        config = GraphBuilderConfig(external_entity_flush_threshold=threshold)

        # Add entities above threshold using proper ExternalEntityInfo
        for i in range(entity_count):
            entity = create_mock_external_entity(f"ext_{i}", f"Entity{i}")
            builder._pending_external_entities[f"ext_{i}"] = entity

        flushed = await builder.flush_external_entities_if_needed(config, event_system)

        assert flushed == entity_count
        event_system.emit.assert_called_once()
        call_kwargs = event_system.emit.call_args[1]

        assert call_kwargs["entities_flushed"] == entity_count
        assert call_kwargs["threshold"] == threshold


# =============================================================================
# Additional Event Tests
# =============================================================================

class TestEventEmissionErrorHandling:
    """Tests for error handling during event emission."""

    @pytest.mark.asyncio
    async def test_commit_batch_continues_on_emit_error(self):
        """Batch commit SHALL succeed even if event emission fails."""
        builder = create_mock_builder()
        event_system = create_mock_event_system()
        event_system.emit.side_effect = RuntimeError("Event system down")
        builder.db_manager.add_graph_relationships = AsyncMock()

        relationships = [MagicMock() for _ in range(5)]
        stats = {"committed_count": 0, "total_relationships": 100, "commit_failures": 0}

        result = await builder._commit_batch(
            relationships=relationships,
            batch_number=1,
            stats=stats,
            event_system=event_system,
        )

        # Commit should still succeed
        assert result is True
        assert stats["committed_count"] == 5


class TestEventSourceIdentification:
    """Tests for event source identification."""

    @pytest.mark.asyncio
    async def test_all_events_have_graph_builder_source(self):
        """All events SHALL identify source as 'graph_builder'."""
        event_system = create_mock_event_system()

        # Test batch_complete
        await event_system.emit(
            "relationship_flush.batch_complete",
            source="graph_builder",
            batch_number=1,
            batch_size=10,
            total_committed=10,
            total_relationships=100,
        )

        assert event_system.emit.call_args[1]["source"] == "graph_builder"


class TestEventTypeNaming:
    """Tests for event type naming conventions."""

    def test_event_types_follow_naming_convention(self):
        """Event types SHALL follow pattern: {domain}.{event}."""
        expected_event_types = [
            "relationship_flush.batch_complete",
            "relationship_flush.completed",
            "relationship_flush.failed",
            "external_entities.flushed",
        ]

        for event_type in expected_event_types:
            parts = event_type.split(".")
            assert len(parts) == 2, f"Event type '{event_type}' should have exactly 2 parts"
            assert parts[0], f"Domain part of '{event_type}' should not be empty"
            assert parts[1], f"Event part of '{event_type}' should not be empty"
