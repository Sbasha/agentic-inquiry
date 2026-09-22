"""Tests for EventStore query methods.

This module tests the additional query methods added to EventStore:
- get_events_by_type
- get_events_by_time_range
- get_latest_events
- get_operation_status
- count_events
"""

import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from agentic_inquiry.events.models import Event, EventStatus
from agentic_inquiry.events.store import EventStore


@pytest.fixture
async def event_store(tmp_path: Path) -> EventStore:
    """Create a temporary event store for testing."""
    db_path = tmp_path / "test_events.db"
    store = await EventStore.from_config(
        db_path=db_path,
        project_id="test_project"
    )
    yield store
    await store.close()


@pytest.fixture
async def populated_store(event_store: EventStore) -> EventStore:
    """Create an event store populated with test data."""
    base_time = time.time()
    
    test_events = [
        Event(
            project_id="test_project",
            operation_id="op1",
            timestamp=base_time,
            event_type="indexing.started",
            status=EventStatus.STARTED,
            source="test",
            metadata={"file": "test1.py"}
        ),
        Event(
            project_id="test_project",
            operation_id="op1",
            timestamp=base_time + 1,
            event_type="indexing.progress",
            status=EventStatus.PROGRESS,
            source="test",
            metadata={"files_processed": 5}
        ),
        Event(
            project_id="test_project",
            operation_id="op1",
            timestamp=base_time + 2,
            event_type="indexing.completed",
            status=EventStatus.COMPLETED,
            source="test",
            metadata={"total_files": 10}
        ),
        Event(
            project_id="test_project",
            operation_id="op2",
            timestamp=base_time + 3,
            event_type="search.query.started",
            status=EventStatus.STARTED,
            source="test",
            metadata={"query": "test"}
        ),
        Event(
            project_id="test_project",
            operation_id="op2",
            timestamp=base_time + 4,
            event_type="search.query.failed",
            status=EventStatus.FAILED,
            source="test",
            metadata={"error": "timeout"}
        ),
        Event(
            project_id="test_project",
            operation_id="op3",
            timestamp=base_time + 5,
            event_type="parsing.started",
            status=EventStatus.STARTED,
            source="test",
            metadata={"file": "test2.py"}
        ),
    ]
    
    await event_store.store_events(test_events)
    
    # Store base_time for use in tests
    event_store._test_base_time = base_time
    
    return event_store


@pytest.mark.asyncio
class TestEventStoreQueries:
    """Test suite for EventStore query methods."""
    
    async def test_get_events_by_type(self, populated_store: EventStore):
        """Test filtering events by type."""
        events = await populated_store.get_events_by_type("indexing.started")
        
        assert len(events) == 1
        assert events[0].event_type == "indexing.started"
        assert events[0].operation_id == "op1"
    
    async def test_get_events_by_type_multiple_results(self, populated_store: EventStore):
        """Test filtering events by type with multiple results."""
        # Add more events of the same type
        base_time = populated_store._test_base_time
        more_events = [
            Event(
                project_id="test_project",
                operation_id="op4",
                timestamp=base_time + 10,
                event_type="indexing.started",
                status=EventStatus.STARTED,
                source="test",
            ),
        ]
        await populated_store.store_events(more_events)
        
        events = await populated_store.get_events_by_type("indexing.started")
        
        assert len(events) == 2
        # Should be in descending order by timestamp
        assert events[0].timestamp > events[1].timestamp
    
    async def test_get_events_by_type_with_limit(self, populated_store: EventStore):
        """Test limiting results when filtering by type."""
        events = await populated_store.get_events_by_type(
            "indexing.started",
            limit=1
        )
        
        assert len(events) == 1
    
    async def test_get_events_by_time_range(self, populated_store: EventStore):
        """Test filtering events by time range."""
        base_time = populated_store._test_base_time
        
        events = await populated_store.get_events_by_time_range(
            start_time=base_time,
            end_time=base_time + 3
        )
        
        assert len(events) == 4
        # Should be in ascending order
        assert events[0].timestamp == base_time
        assert events[-1].timestamp == base_time + 3
    
    async def test_get_events_by_time_range_with_type_filter(self, populated_store: EventStore):
        """Test filtering events by time range and type."""
        base_time = populated_store._test_base_time
        
        events = await populated_store.get_events_by_time_range(
            start_time=base_time,
            end_time=base_time + 5,
            event_type="indexing.progress"
        )
        
        assert len(events) == 1
        assert events[0].event_type == "indexing.progress"
    
    async def test_get_latest_events(self, populated_store: EventStore):
        """Test getting latest events."""
        events = await populated_store.get_latest_events(limit=3)
        
        assert len(events) == 3
        # Should be in descending order
        assert events[0].timestamp > events[1].timestamp
        assert events[1].timestamp > events[2].timestamp
    
    async def test_get_latest_events_with_status_filter(self, populated_store: EventStore):
        """Test getting latest events filtered by status."""
        events = await populated_store.get_latest_events(
            limit=10,
            status=EventStatus.FAILED
        )
        
        assert len(events) == 1
        assert events[0].status == EventStatus.FAILED
        assert events[0].event_type == "search.query.failed"
    
    async def test_get_operation_status_completed(self, populated_store: EventStore):
        """Test getting status for a completed operation."""
        status = await populated_store.get_operation_status("op1")
        
        assert status["operation_id"] == "op1"
        assert status["project_id"] == "test_project"
        assert status["event_count"] == 3
        assert status["error_count"] == 0
        assert status["status"] == "completed"
        assert status["duration"] == 2.0
        assert status["start_time"] is not None
        assert status["end_time"] is not None
    
    async def test_get_operation_status_failed(self, populated_store: EventStore):
        """Test getting status for a failed operation."""
        status = await populated_store.get_operation_status("op2")
        
        assert status["operation_id"] == "op2"
        assert status["event_count"] == 2
        assert status["error_count"] == 1
        assert status["status"] == "failed"
        assert status["duration"] == 1.0
    
    async def test_get_operation_status_nonexistent(self, populated_store: EventStore):
        """Test getting status for a non-existent operation."""
        status = await populated_store.get_operation_status("nonexistent")
        
        assert status["operation_id"] == "nonexistent"
        assert status["event_count"] == 0
        assert status["error_count"] == 0
        assert status["status"] is None
        assert status["start_time"] is None
        assert status["end_time"] is None
        assert status["duration"] is None
    
    async def test_count_events_no_filters(self, populated_store: EventStore):
        """Test counting all events."""
        count = await populated_store.count_events()
        
        assert count == 6
    
    async def test_count_events_with_type_filter(self, populated_store: EventStore):
        """Test counting events filtered by type."""
        count = await populated_store.count_events(
            event_type="indexing.progress"
        )
        
        assert count == 1
    
    async def test_count_events_with_status_filter(self, populated_store: EventStore):
        """Test counting events filtered by status."""
        count = await populated_store.count_events(
            status=EventStatus.FAILED
        )
        
        assert count == 1
    
    async def test_count_events_with_time_range(self, populated_store: EventStore):
        """Test counting events in a time range."""
        base_time = populated_store._test_base_time
        
        count = await populated_store.count_events(
            start_time=base_time,
            end_time=base_time + 2
        )
        
        assert count == 3
    
    async def test_count_events_with_multiple_filters(self, populated_store: EventStore):
        """Test counting events with multiple filters."""
        base_time = populated_store._test_base_time
        
        count = await populated_store.count_events(
            event_type="indexing.progress",
            status=EventStatus.PROGRESS,
            start_time=base_time,
            end_time=base_time + 5
        )
        
        assert count == 1
    
    async def test_count_events_no_matches(self, populated_store: EventStore):
        """Test counting events when no matches exist."""
        count = await populated_store.count_events(
            event_type="nonexistent.type"
        )
        
        assert count == 0
