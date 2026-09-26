"""Tests for event system fixtures and utilities.

This module verifies that the test fixtures and utilities work correctly
and can be used in other test files.
"""

import pytest

pytestmark = pytest.mark.integration

from agentic_inquiry.events.models import Event, EventStatus
from agentic_inquiry.events.store import EventStore
from agentic_inquiry.events.system import EventSystem
from tests.events.test_utils import (
    create_operation_events,
    create_test_event,
    create_test_events,
    event_capture,
    wait_for_events,
)


class TestFixtures:
    """Test suite for event system fixtures."""

    @pytest.mark.asyncio
    async def test_temp_event_store_fixture(self, temp_event_store: EventStore):
        """Test that temp_event_store fixture works."""
        assert temp_event_store is not None
        assert temp_event_store.project_id == "test_project"
        assert temp_event_store._initialized

        # Test basic storage
        event = Event(
            project_id="test_project",
            event_type="test.event",
            source="test",
            status=EventStatus.PROGRESS,
        )
        await temp_event_store.store_events([event])

        # Verify storage
        count = await temp_event_store.count_events()
        assert count == 1

    @pytest.mark.asyncio
    async def test_event_system_fixture(self, event_system: EventSystem):
        """Test that event_system fixture works."""
        assert event_system is not None
        assert event_system.project_id == "test_project"
        assert event_system._writer_task is not None

        # Test basic emission
        await event_system.emit("test.event", source="test")

        # Wait for flush
        await wait_for_events(event_system)

        # Verify event was stored
        count = await event_system.store.count_events()
        assert count == 1

    def test_sample_event_fixture(self, sample_event: Event):
        """Test that sample_event fixture works."""
        assert sample_event is not None
        assert sample_event.project_id == "test_project"
        assert sample_event.event_type == "test.event"
        assert sample_event.status == EventStatus.PROGRESS
        assert sample_event.source == "test_source"
        assert sample_event.metadata == {"test_key": "test_value"}


class TestUtilities:
    """Test suite for event system test utilities."""

    def test_create_test_event(self):
        """Test create_test_event utility."""
        event = create_test_event(
            event_type="indexing.started",
            source="pipeline",
            status=EventStatus.STARTED,
            file_path="/path/to/file.py",
        )

        assert event.event_type == "indexing.started"
        assert event.source == "pipeline"
        assert event.status == EventStatus.STARTED
        assert event.metadata["file_path"] == "/path/to/file.py"

    def test_create_test_events(self):
        """Test create_test_events utility."""
        events = create_test_events(
            count=5, event_type="test.progress", operation_id="op123"
        )

        assert len(events) == 5
        assert all(e.event_type == "test.progress" for e in events)
        assert all(e.operation_id == "op123" for e in events)

        # Verify sequential timestamps
        for i in range(1, len(events)):
            assert events[i].timestamp > events[i - 1].timestamp

    def test_create_operation_events_success(self):
        """Test create_operation_events for successful operation."""
        events = create_operation_events(
            operation_id="op123",
            operation_type="indexing",
            include_progress=True,
            fail=False,
        )

        assert len(events) == 4  # started + 2 progress + completed
        assert events[0].event_type == "indexing.started"
        assert events[0].status == EventStatus.STARTED
        assert events[1].event_type == "indexing.progress"
        assert events[2].event_type == "indexing.progress"
        assert events[3].event_type == "indexing.completed"
        assert events[3].status == EventStatus.COMPLETED

    def test_create_operation_events_failure(self):
        """Test create_operation_events for failed operation."""
        events = create_operation_events(
            operation_id="op456",
            operation_type="search",
            include_progress=False,
            fail=True,
        )

        assert len(events) == 2  # started + failed
        assert events[0].event_type == "search.started"
        assert events[1].event_type == "search.failed"
        assert events[1].status == EventStatus.FAILED
        assert "error" in events[1].metadata

    @pytest.mark.asyncio
    async def test_event_capture(self, event_system: EventSystem):
        """Test event_capture context manager."""
        async with event_capture(event_system) as captured:
            await event_system.emit("test.event1", source="test")
            await event_system.emit("test.event2", source="test")
            await event_system.emit("test.event3", source="test")

        assert len(captured) == 3
        assert captured[0].event_type == "test.event1"
        assert captured[1].event_type == "test.event2"
        assert captured[2].event_type == "test.event3"

    @pytest.mark.asyncio
    async def test_wait_for_events(self, event_system: EventSystem):
        """Test wait_for_events utility."""
        # Emit some events
        for i in range(5):
            await event_system.emit(f"test.event{i}", source="test")

        # Wait for flush
        await wait_for_events(event_system)

        # Queue should be empty
        assert event_system._queue.qsize() == 0

        # Events should be in store
        count = await event_system.store.count_events()
        assert count == 5
