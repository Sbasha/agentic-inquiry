"""Tests for event context managers.

This module tests the OperationTracker class and track_operation context
manager, including automatic event emission, correlation ID integration,
and error handling.
"""

import asyncio

import pytest

pytestmark = pytest.mark.integration

from agentic_inquiry.correlation import get_correlation_id
from tests.helpers.async_utils import AsyncTestHelper
from agentic_inquiry.events.context_managers import OperationTracker, track_operation
from agentic_inquiry.events.models import EventStatus


class TestOperationTracker:
    """Test suite for OperationTracker class."""

    @pytest.mark.asyncio
    async def test_progress_emits_progress_event(self, event_system):
        """Test progress() emits progress event with correct metadata."""
        tracker = OperationTracker(
            event_system=event_system,
            operation_type="indexing",
            source="test_source",
            operation_id="test_op_123",
        )

        # Emit progress event
        await tracker.progress(files_processed=10, current_file="test.py")

        # Wait for background writer to flush
        await asyncio.sleep(0.2)

        # Query events
        events = await event_system.store.get_operation_events("test_op_123")

        # Should have one progress event
        assert len(events) == 1
        event = events[0]

        assert event.event_type == "indexing.progress"
        assert event.status == EventStatus.PROGRESS
        assert event.source == "test_source"
        assert event.operation_id == "test_op_123"
        assert event.metadata["files_processed"] == 10
        assert event.metadata["current_file"] == "test.py"

    @pytest.mark.asyncio
    async def test_progress_multiple_calls(self, event_system):
        """Test progress() can be called multiple times."""
        tracker = OperationTracker(
            event_system=event_system,
            operation_type="indexing",
            source="test_source",
            operation_id="test_op_456",
        )

        # Emit multiple progress events
        await tracker.progress(files_processed=5)
        await tracker.progress(files_processed=10)
        await tracker.progress(files_processed=15)

        # Wait for background writer to flush
        await asyncio.sleep(0.2)

        # Query events
        events = await event_system.store.get_operation_events("test_op_456")

        # Should have three progress events
        assert len(events) == 3
        assert all(e.event_type == "indexing.progress" for e in events)
        assert events[0].metadata["files_processed"] == 5
        assert events[1].metadata["files_processed"] == 10
        assert events[2].metadata["files_processed"] == 15

    @pytest.mark.asyncio
    async def test_complete_emits_completed_event(self, event_system):
        """Test complete() emits completed event with correct metadata."""
        tracker = OperationTracker(
            event_system=event_system,
            operation_type="indexing",
            source="test_source",
            operation_id="test_op_789",
        )

        # Emit completion event
        await tracker.complete(total_files=42, duration_seconds=10.5)

        # Wait for background writer to flush
        await asyncio.sleep(0.2)

        # Query events
        events = await event_system.store.get_operation_events("test_op_789")

        # Should have one completed event
        assert len(events) == 1
        event = events[0]

        assert event.event_type == "indexing.completed"
        assert event.status == EventStatus.COMPLETED
        assert event.source == "test_source"
        assert event.operation_id == "test_op_789"
        assert event.metadata["total_files"] == 42
        assert event.metadata["duration_seconds"] == 10.5

    @pytest.mark.asyncio
    async def test_fail_emits_failed_event(self, event_system):
        """Test fail() emits failed event with error message."""
        tracker = OperationTracker(
            event_system=event_system,
            operation_type="indexing",
            source="test_source",
            operation_id="test_op_error",
        )

        # Emit failure event
        await tracker.fail(
            error="File not found", error_code=404, file_path="/missing/file.py"
        )

        # Wait for background writer to flush
        await asyncio.sleep(0.2)

        # Query events
        events = await event_system.store.get_operation_events("test_op_error")

        # Should have one failed event
        assert len(events) == 1
        event = events[0]

        assert event.event_type == "indexing.failed"
        assert event.status == EventStatus.FAILED
        assert event.source == "test_source"
        assert event.operation_id == "test_op_error"
        assert event.metadata["error"] == "File not found"
        assert event.metadata["error_code"] == 404
        assert event.metadata["file_path"] == "/missing/file.py"

    @pytest.mark.asyncio
    async def test_tracker_with_different_operation_types(self, event_system):
        """Test OperationTracker works with different operation types."""
        # Test with search operation
        search_tracker = OperationTracker(
            event_system=event_system,
            operation_type="search",
            source="search_service",
            operation_id="search_op_1",
        )

        await search_tracker.progress(query="test query")
        await search_tracker.complete(results_count=10)

        # Test with parsing operation
        parse_tracker = OperationTracker(
            event_system=event_system,
            operation_type="parsing",
            source="parser",
            operation_id="parse_op_1",
        )

        await parse_tracker.progress(chunks_created=5)
        await parse_tracker.complete(total_chunks=10)

        # Wait for background writer to flush
        success = await AsyncTestHelper.wait_for_async_condition(
            lambda: event_system.store.get_operation_events("search_op_1"),
            lambda events: len(events) == 2,
            timeout=5.0,
        )
        assert success, "Search events were not stored in time"

        # Query search events
        search_events = await event_system.store.get_operation_events("search_op_1")
        assert len(search_events) == 2
        assert search_events[0].event_type == "search.progress"
        assert search_events[1].event_type == "search.completed"

        # Query parsing events
        parse_events = await event_system.store.get_operation_events("parse_op_1")
        assert len(parse_events) == 2
        assert parse_events[0].event_type == "parsing.progress"
        assert parse_events[1].event_type == "parsing.completed"


class TestTrackOperationContextManager:
    """Test suite for track_operation context manager."""

    @pytest.mark.asyncio
    async def test_emits_started_event_on_entry(self, event_system):
        """Test track_operation emits started event when entering context."""
        async with track_operation(
            event_system=event_system,
            operation_type="indexing",
            source="test_source",
            operation_id="test_track_1",
            file_path="/test/file.py",
        ):
            # Just enter and exit
            pass

        # Wait for background writer to flush
        await asyncio.sleep(0.2)

        # Query events
        events = await event_system.store.get_operation_events("test_track_1")

        # Should have started and completed events
        assert len(events) >= 1
        started_event = events[0]

        assert started_event.event_type == "indexing.started"
        assert started_event.status == EventStatus.STARTED
        assert started_event.source == "test_source"
        assert started_event.operation_id == "test_track_1"
        assert started_event.metadata["file_path"] == "/test/file.py"

    @pytest.mark.asyncio
    async def test_emits_completed_event_on_success(self, event_system):
        """Test track_operation emits completed event on successful exit."""
        async with track_operation(
            event_system=event_system,
            operation_type="indexing",
            source="test_source",
            operation_id="test_track_2",
        ) as tracker:
            # Simulate successful operation
            await tracker.progress(files_processed=5)

        # Wait for background writer to flush
        await asyncio.sleep(0.2)

        # Query events
        events = await event_system.store.get_operation_events("test_track_2")

        # Should have started, progress, and completed events
        assert len(events) == 3

        assert events[0].event_type == "indexing.started"
        assert events[0].status == EventStatus.STARTED

        assert events[1].event_type == "indexing.progress"
        assert events[1].status == EventStatus.PROGRESS

        assert events[2].event_type == "indexing.completed"
        assert events[2].status == EventStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_emits_failed_event_on_exception(self, event_system):
        """Test track_operation emits failed event when exception occurs."""
        with pytest.raises(ValueError, match="Test error"):
            async with track_operation(
                event_system=event_system,
                operation_type="indexing",
                source="test_source",
                operation_id="test_track_3",
            ) as tracker:
                # Simulate operation that fails
                await tracker.progress(files_processed=3)
                raise ValueError("Test error")

        # Wait for background writer to flush
        await asyncio.sleep(0.2)

        # Query events
        events = await event_system.store.get_operation_events("test_track_3")

        # Should have started, progress, and failed events
        assert len(events) == 3

        assert events[0].event_type == "indexing.started"
        assert events[0].status == EventStatus.STARTED

        assert events[1].event_type == "indexing.progress"
        assert events[1].status == EventStatus.PROGRESS

        assert events[2].event_type == "indexing.failed"
        assert events[2].status == EventStatus.FAILED
        assert "Test error" in events[2].metadata["error"]

    @pytest.mark.asyncio
    async def test_correlation_id_integration_with_explicit_id(self, event_system):
        """Test track_operation uses provided operation_id."""
        explicit_id = "explicit_operation_id"

        async with track_operation(
            event_system=event_system,
            operation_type="indexing",
            source="test_source",
            operation_id=explicit_id,
        ) as tracker:
            # Verify tracker has correct operation_id
            assert tracker.operation_id == explicit_id

        # Wait for background writer to flush
        await asyncio.sleep(0.2)

        # Query events
        events = await event_system.store.get_operation_events(explicit_id)

        # All events should have the explicit operation_id
        assert len(events) >= 2  # started and completed
        assert all(e.operation_id == explicit_id for e in events)

    @pytest.mark.asyncio
    async def test_correlation_id_integration_auto_generation(self, event_system):
        """Test track_operation auto-generates correlation ID when not provided."""
        # Don't provide operation_id - should use correlation context
        async with track_operation(
            event_system=event_system,
            operation_type="indexing",
            source="test_source",
        ) as tracker:
            # Should have generated an operation_id
            assert tracker.operation_id is not None
            assert tracker.operation_id != ""
            operation_id = tracker.operation_id

        # Wait for background writer to flush
        await asyncio.sleep(0.2)

        # Query events
        events = await event_system.store.get_operation_events(operation_id)

        # Should have events with the auto-generated operation_id
        assert len(events) >= 2  # started and completed
        assert all(e.operation_id == operation_id for e in events)

    @pytest.mark.asyncio
    async def test_correlation_id_propagates_to_nested_calls(self, event_system):
        """Test correlation ID propagates through nested operations."""

        async with track_operation(
            event_system=event_system,
            operation_type="indexing",
            source="pipeline",
            operation_id="parent_op",
        ) as parent_tracker:
            # Inside context, correlation ID should be set
            current_corr_id = get_correlation_id()
            assert current_corr_id == "parent_op"

            # Emit progress from parent
            await parent_tracker.progress(step="processing")

        # Wait for background writer to flush
        await asyncio.sleep(0.2)

        # Query events
        events = await event_system.store.get_operation_events("parent_op")

        # All events should have the same operation_id
        assert len(events) >= 2
        assert all(e.operation_id == "parent_op" for e in events)

    @pytest.mark.asyncio
    async def test_yields_operation_tracker(self, event_system):
        """Test track_operation yields OperationTracker instance."""
        async with track_operation(
            event_system=event_system,
            operation_type="indexing",
            source="test_source",
            operation_id="test_track_yield",
        ) as tracker:
            # Should yield OperationTracker
            assert isinstance(tracker, OperationTracker)
            assert tracker.event_system is event_system
            assert tracker.operation_type == "indexing"
            assert tracker.source == "test_source"
            assert tracker.operation_id == "test_track_yield"

    @pytest.mark.asyncio
    async def test_start_metadata_included_in_started_event(self, event_system):
        """Test start metadata is included in started event."""
        async with track_operation(
            event_system=event_system,
            operation_type="indexing",
            source="test_source",
            operation_id="test_track_metadata",
            file_count=100,
            directory="/test/dir",
            recursive=True,
        ):
            pass

        # Wait for background writer to flush
        await asyncio.sleep(0.2)

        # Query events
        events = await event_system.store.get_operation_events("test_track_metadata")

        # Started event should have metadata
        started_event = events[0]
        assert started_event.event_type == "indexing.started"
        assert started_event.metadata["file_count"] == 100
        assert started_event.metadata["directory"] == "/test/dir"
        assert started_event.metadata["recursive"] is True

    @pytest.mark.asyncio
    async def test_exception_propagates_after_failed_event(self, event_system):
        """Test exception is re-raised after emitting failed event."""

        class CustomError(Exception):
            pass

        with pytest.raises(CustomError, match="Custom error message"):
            async with track_operation(
                event_system=event_system,
                operation_type="indexing",
                source="test_source",
                operation_id="test_track_exception",
            ):
                raise CustomError("Custom error message")

        # Wait for background writer to flush
        await asyncio.sleep(0.2)

        # Query events
        events = await event_system.store.get_operation_events("test_track_exception")

        # Should have started and failed events
        assert len(events) == 2
        assert events[0].event_type == "indexing.started"
        assert events[1].event_type == "indexing.failed"
        assert "Custom error message" in events[1].metadata["error"]

    @pytest.mark.asyncio
    async def test_multiple_operations_isolated(self, event_system):
        """Test multiple operations are properly isolated."""
        # Run two operations concurrently
        async with track_operation(
            event_system=event_system,
            operation_type="indexing",
            source="source1",
            operation_id="op1",
        ) as tracker1:
            await tracker1.progress(step=1)

        async with track_operation(
            event_system=event_system,
            operation_type="search",
            source="source2",
            operation_id="op2",
        ) as tracker2:
            await tracker2.progress(step=2)

        # Wait for background writer to flush
        await asyncio.sleep(0.2)

        # Query events for each operation
        events1 = await event_system.store.get_operation_events("op1")
        events2 = await event_system.store.get_operation_events("op2")

        # Each operation should have its own events
        assert len(events1) == 3  # started, progress, completed
        assert all(e.operation_id == "op1" for e in events1)
        assert all(e.event_type.startswith("indexing") for e in events1)

        assert len(events2) == 3  # started, progress, completed
        assert all(e.operation_id == "op2" for e in events2)
        assert all(e.event_type.startswith("search") for e in events2)

    @pytest.mark.asyncio
    async def test_empty_operation_emits_start_and_complete(self, event_system):
        """Test empty operation (no progress calls) still emits start/complete."""
        async with track_operation(
            event_system=event_system,
            operation_type="indexing",
            source="test_source",
            operation_id="test_track_empty",
        ):
            # Don't call any methods on tracker
            pass

        # Wait for background writer to flush
        await asyncio.sleep(0.2)

        # Query events
        events = await event_system.store.get_operation_events("test_track_empty")

        # Should have started and completed events
        assert len(events) == 2
        assert events[0].event_type == "indexing.started"
        assert events[0].status == EventStatus.STARTED
        assert events[1].event_type == "indexing.completed"
        assert events[1].status == EventStatus.COMPLETED
