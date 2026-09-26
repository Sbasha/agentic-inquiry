"""Tests for relational protocol compliance.

This module tests that EventStore and FileTracker implementations conform
to the EventStoreProtocol and FileTrackerProtocol interfaces.
"""

import time
from typing import List

import pytest

pytestmark = pytest.mark.integration

from agentic_inquiry.database.relational_protocols import (
    EventStoreProtocol,
    FileTrackerProtocol,
)
from agentic_inquiry.events.models import Event, EventStatus
from agentic_inquiry.events.store import EventStore
from agentic_inquiry.watching.file_tracker import FileTracker


# --- Fixtures ---


@pytest.fixture
async def temp_event_store(tmp_path):
    """Create a temporary EventStore for testing."""
    db_path = tmp_path / "test_events.db"
    store = EventStore(project_id="test_project", db_path=db_path)
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
async def temp_file_tracker(tmp_path):
    """Create a temporary FileTracker for testing."""
    db_path = tmp_path / "test_files.db"
    tracker = FileTracker(project_id="test_project", db_path=db_path)
    await tracker.initialize()
    yield tracker
    tracker.close()


@pytest.fixture
def sample_events() -> List[Event]:
    """Create sample events for testing."""
    base_time = time.time()
    return [
        Event(
            event_id="evt_1",
            project_id="test_project",
            operation_id="op_123",
            session_id="session_1",
            timestamp=base_time,
            event_type="indexing.started",
            status=EventStatus.PROGRESS,
            source="IndexingPipeline",
            metadata={"files": 10},
        ),
        Event(
            event_id="evt_2",
            project_id="test_project",
            operation_id="op_123",
            session_id="session_1",
            timestamp=base_time + 1.0,
            event_type="indexing.file_processed",
            status=EventStatus.COMPLETED,
            source="IndexingPipeline",
            metadata={"file": "test.py"},
        ),
        Event(
            event_id="evt_3",
            project_id="test_project",
            operation_id="op_123",
            session_id="session_1",
            timestamp=base_time + 2.0,
            event_type="indexing.completed",
            status=EventStatus.COMPLETED,
            source="IndexingPipeline",
            metadata={"total_files": 10},
        ),
    ]


# --- EventStoreProtocol Tests ---


class TestEventStoreProtocolCompliance:
    """Test that EventStore conforms to EventStoreProtocol."""

    def test_isinstance_check(self, temp_event_store):
        """EventStore should be recognized as EventStoreProtocol."""
        assert isinstance(temp_event_store, EventStoreProtocol)

    def test_has_required_properties(self, temp_event_store):
        """EventStore should have project_id and db_path properties."""
        assert hasattr(temp_event_store, "project_id")
        assert hasattr(temp_event_store, "db_path")
        assert temp_event_store.project_id == "test_project"
        assert temp_event_store.db_path is not None

    async def test_initialize_idempotent(self, tmp_path):
        """Calling initialize() multiple times should be safe."""
        db_path = tmp_path / "test.db"
        store = EventStore(project_id="test_project", db_path=db_path)

        # Initialize multiple times
        await store.initialize()
        await store.initialize()
        await store.initialize()

        # Should still work
        assert store._initialized

        await store.close()

    async def test_close_idempotent(self, tmp_path):
        """Calling close() multiple times should be safe."""
        db_path = tmp_path / "test.db"
        store = EventStore(project_id="test_project", db_path=db_path)
        await store.initialize()

        # Close multiple times
        await store.close()
        await store.close()
        await store.close()

        # Should not raise

    async def test_store_and_retrieve_events(self, temp_event_store, sample_events):
        """Should store events and retrieve them by operation."""
        # Store events
        await temp_event_store.store_events(sample_events)

        # Retrieve by operation
        retrieved = await temp_event_store.get_operation_events("op_123")

        # Should get all events for this operation
        assert len(retrieved) == 3
        # Should be ordered by timestamp
        assert retrieved[0].event_id == "evt_1"
        assert retrieved[1].event_id == "evt_2"
        assert retrieved[2].event_id == "evt_3"

    async def test_get_events_by_type(self, temp_event_store, sample_events):
        """Should filter events by type."""
        await temp_event_store.store_events(sample_events)

        # Get specific event type
        events = await temp_event_store.get_events_by_type("indexing.file_processed")

        assert len(events) == 1
        assert events[0].event_type == "indexing.file_processed"

    async def test_get_events_by_time_range(self, temp_event_store, sample_events):
        """Should filter events by time range."""
        await temp_event_store.store_events(sample_events)

        base_time = sample_events[0].timestamp
        start_time = base_time + 0.5
        end_time = base_time + 1.5

        events = await temp_event_store.get_events_by_time_range(start_time, end_time)

        # Should only get events within range
        assert len(events) == 1
        assert events[0].event_id == "evt_2"

    async def test_get_latest_events(self, temp_event_store, sample_events):
        """Should get latest events ordered by timestamp."""
        await temp_event_store.store_events(sample_events)

        events = await temp_event_store.get_latest_events(limit=2)

        # Should get 2 most recent events in descending order
        assert len(events) == 2
        assert events[0].event_id == "evt_3"  # Most recent
        assert events[1].event_id == "evt_2"

    async def test_get_operation_status(self, temp_event_store, sample_events):
        """Should provide operation summary statistics."""
        await temp_event_store.store_events(sample_events)

        status = await temp_event_store.get_operation_status("op_123")

        assert status["operation_id"] == "op_123"
        assert status["project_id"] == "test_project"
        assert status["event_count"] == 3
        assert status["error_count"] == 0
        assert status["status"] == "completed"
        assert status["duration"] is not None
        assert status["duration"] >= 2.0  # At least 2 seconds between first and last

    async def test_count_events(self, temp_event_store, sample_events):
        """Should count events with various filters."""
        await temp_event_store.store_events(sample_events)

        # Count all events
        total = await temp_event_store.count_events()
        assert total == 3

        # Count by type
        count = await temp_event_store.count_events(event_type="indexing.started")
        assert count == 1

        # Count by status
        count = await temp_event_store.count_events(status=EventStatus.COMPLETED)
        assert count == 2

    async def test_cleanup_old_events(self, temp_event_store):
        """Should delete events older than retention period."""
        # Create old and new events
        old_time = time.time() - (40 * 24 * 60 * 60)  # 40 days ago
        new_time = time.time()

        old_event = Event(
            event_id="old_1",
            project_id="test_project",
            operation_id="old_op",
            timestamp=old_time,
            event_type="test.event",
            status=EventStatus.COMPLETED,
            source="test",
        )

        new_event = Event(
            event_id="new_1",
            project_id="test_project",
            operation_id="new_op",
            timestamp=new_time,
            event_type="test.event",
            status=EventStatus.COMPLETED,
            source="test",
        )

        await temp_event_store.store_events([old_event, new_event])

        # Cleanup events older than 30 days
        deleted = await temp_event_store.cleanup_old_events(retention_days=30)

        assert deleted == 1

        # New event should still exist
        events = await temp_event_store.get_operation_events("new_op")
        assert len(events) == 1

        # Old event should be gone
        events = await temp_event_store.get_operation_events("old_op")
        assert len(events) == 0

    async def test_cleanup_requires_positive_retention(self, temp_event_store):
        """cleanup_old_events should reject invalid retention_days."""
        with pytest.raises(ValueError, match="retention_days must be positive"):
            await temp_event_store.cleanup_old_events(retention_days=0)

        with pytest.raises(ValueError, match="retention_days must be positive"):
            await temp_event_store.cleanup_old_events(retention_days=-1)

    async def test_vacuum(self, temp_event_store, sample_events):
        """Should compact database without errors."""
        await temp_event_store.store_events(sample_events)

        # Vacuum should not raise
        await temp_event_store.vacuum()

        # Data should still be accessible
        events = await temp_event_store.get_operation_events("op_123")
        assert len(events) == 3


# --- FileTrackerProtocol Tests ---


class TestFileTrackerProtocolCompliance:
    """Test that FileTracker conforms to FileTrackerProtocol."""

    def test_isinstance_check(self, temp_file_tracker):
        """FileTracker should be recognized as FileTrackerProtocol."""
        assert isinstance(temp_file_tracker, FileTrackerProtocol)

    def test_has_required_properties(self, temp_file_tracker):
        """FileTracker should have project_id and db_path properties."""
        assert hasattr(temp_file_tracker, "project_id")
        assert hasattr(temp_file_tracker, "db_path")
        assert temp_file_tracker.project_id == "test_project"
        assert temp_file_tracker.db_path is not None

    async def test_initialize_idempotent(self, tmp_path):
        """Calling initialize() multiple times should be safe."""
        db_path = tmp_path / "test.db"
        tracker = FileTracker(project_id="test_project", db_path=db_path)

        # Initialize multiple times
        await tracker.initialize()
        await tracker.initialize()
        await tracker.initialize()

        # Should still work
        assert tracker._initialized

        tracker.close()

    def test_close_idempotent(self, tmp_path):
        """Calling close() multiple times should be safe."""
        db_path = tmp_path / "test.db"
        tracker = FileTracker(project_id="test_project", db_path=db_path)

        # Close multiple times (note: close is sync)
        tracker.close()
        tracker.close()
        tracker.close()

        # Should not raise

    async def test_hash_storage_and_retrieval(self, temp_file_tracker, tmp_path):
        """Should store and retrieve file hashes."""
        # Create a test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!")

        # Update hash (computes from file)
        stored_hash = await temp_file_tracker.update_hash(str(test_file))
        assert stored_hash is not None

        # Retrieve hash
        retrieved_hash = await temp_file_tracker.get_hash(str(test_file))
        assert retrieved_hash == stored_hash

    async def test_hash_with_precomputed_value(self, temp_file_tracker):
        """Should store pre-computed hash."""
        file_path = "/path/to/file.txt"
        precomputed_hash = "abc123def456"

        # Store pre-computed hash
        stored_hash = await temp_file_tracker.update_hash(
            file_path, content_hash=precomputed_hash
        )
        assert stored_hash == precomputed_hash

        # Retrieve hash
        retrieved_hash = await temp_file_tracker.get_hash(file_path)
        assert retrieved_hash == precomputed_hash

    async def test_has_changed_new_file(self, temp_file_tracker, tmp_path):
        """New files should be considered changed."""
        test_file = tmp_path / "new.txt"
        test_file.write_text("New content")

        # Not tracked yet
        changed = await temp_file_tracker.has_changed(str(test_file))
        assert changed is True

    async def test_has_changed_unchanged_file(self, temp_file_tracker, tmp_path):
        """Unchanged files should not be considered changed."""
        test_file = tmp_path / "unchanged.txt"
        test_file.write_text("Same content")

        # Track file
        await temp_file_tracker.update_hash(str(test_file))

        # Should not be changed
        changed = await temp_file_tracker.has_changed(str(test_file))
        assert changed is False

    async def test_has_changed_modified_file(self, temp_file_tracker, tmp_path):
        """Modified files should be detected."""
        test_file = tmp_path / "modified.txt"
        test_file.write_text("Original content")

        # Track file
        await temp_file_tracker.update_hash(str(test_file))

        # Modify file
        test_file.write_text("Modified content")

        # Should be changed
        changed = await temp_file_tracker.has_changed(str(test_file))
        assert changed is True

    async def test_has_changed_missing_file(self, temp_file_tracker):
        """Missing files should be considered changed."""
        nonexistent = "/path/to/nonexistent.txt"

        # Should be considered changed (conservative behavior)
        changed = await temp_file_tracker.has_changed(nonexistent)
        assert changed is True

    async def test_remove_file(self, temp_file_tracker, tmp_path):
        """Should remove files from tracking."""
        test_file = tmp_path / "remove_me.txt"
        test_file.write_text("Content")

        # Track file
        await temp_file_tracker.update_hash(str(test_file))

        # Verify it's tracked
        hash_val = await temp_file_tracker.get_hash(str(test_file))
        assert hash_val is not None

        # Remove from tracking
        removed = await temp_file_tracker.remove_file(str(test_file))
        assert removed is True

        # Should no longer be tracked
        hash_val = await temp_file_tracker.get_hash(str(test_file))
        assert hash_val is None

        # Removing again should return False
        removed = await temp_file_tracker.remove_file(str(test_file))
        assert removed is False

    async def test_list_tracked_files(self, temp_file_tracker, tmp_path):
        """Should list all tracked files for project."""
        # Track multiple files
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("Content 1")
        file2.write_text("Content 2")

        hash1 = await temp_file_tracker.update_hash(str(file1))
        hash2 = await temp_file_tracker.update_hash(str(file2))

        # List tracked files
        tracked = await temp_file_tracker.list_tracked_files()

        # Should have both files
        assert len(tracked) == 2
        paths = {path for path, _ in tracked}
        hashes = {hash_val for _, hash_val in tracked}

        assert str(file1) in paths
        assert str(file2) in paths
        assert hash1 in hashes
        assert hash2 in hashes

    async def test_clear(self, temp_file_tracker, tmp_path):
        """Should clear all tracked files for project."""
        # Track files
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("Content 1")
        file2.write_text("Content 2")

        await temp_file_tracker.update_hash(str(file1))
        await temp_file_tracker.update_hash(str(file2))

        # Verify tracked
        tracked = await temp_file_tracker.list_tracked_files()
        assert len(tracked) == 2

        # Clear
        await temp_file_tracker.clear()

        # Should be empty
        tracked = await temp_file_tracker.list_tracked_files()
        assert len(tracked) == 0

    def test_sync_wrappers(self, temp_file_tracker, tmp_path):
        """Synchronous wrappers should work for watchdog compatibility."""
        test_file = tmp_path / "sync_test.txt"
        test_file.write_text("Sync content")

        # update_hash_sync
        stored_hash = temp_file_tracker.update_hash_sync(str(test_file))
        assert stored_hash is not None

        # has_changed_sync
        changed = temp_file_tracker.has_changed_sync(str(test_file))
        assert changed is False

        # Modify file
        test_file.write_text("Modified sync content")
        changed = temp_file_tracker.has_changed_sync(str(test_file))
        assert changed is True

        # remove_file_sync
        removed = temp_file_tracker.remove_file_sync(str(test_file))
        assert removed is True


# --- Project Isolation Tests ---


class TestProjectIsolation:
    """Test that different projects don't interfere with each other."""

    async def test_event_store_project_isolation(self, tmp_path):
        """Events should be isolated by project_id."""
        db_path = tmp_path / "shared_events.db"

        # Create two stores with different projects
        store1 = EventStore(project_id="project_a", db_path=db_path)
        store2 = EventStore(project_id="project_b", db_path=db_path)

        await store1.initialize()
        await store2.initialize()

        # Store events in each project
        event1 = Event(
            event_id="evt_a",
            project_id="project_a",
            operation_id="op_a",
            timestamp=time.time(),
            event_type="test.event",
            status=EventStatus.COMPLETED,
            source="test",
        )

        event2 = Event(
            event_id="evt_b",
            project_id="project_b",
            operation_id="op_b",
            timestamp=time.time(),
            event_type="test.event",
            status=EventStatus.COMPLETED,
            source="test",
        )

        await store1.store_events([event1])
        await store2.store_events([event2])

        # Each store should only see its own events
        events_a = await store1.get_latest_events()
        events_b = await store2.get_latest_events()

        assert len(events_a) == 1
        assert events_a[0].event_id == "evt_a"

        assert len(events_b) == 1
        assert events_b[0].event_id == "evt_b"

        await store1.close()
        await store2.close()

    async def test_file_tracker_project_isolation(self, tmp_path):
        """File hashes should be isolated by project_id."""
        db_path = tmp_path / "shared_files.db"
        test_file = tmp_path / "shared_file.txt"
        test_file.write_text("Content")

        # Create two trackers with different projects
        tracker1 = FileTracker(project_id="project_a", db_path=db_path)
        tracker2 = FileTracker(project_id="project_b", db_path=db_path)

        await tracker1.initialize()
        await tracker2.initialize()

        # Track same file in both projects
        hash1 = await tracker1.update_hash(str(test_file))
        hash2 = await tracker2.update_hash(str(test_file))

        # Both should track independently
        assert hash1 == hash2  # Same file, same hash

        # Each tracker should only see its own tracked files
        tracked1 = await tracker1.list_tracked_files()
        tracked2 = await tracker2.list_tracked_files()

        assert len(tracked1) == 1
        assert len(tracked2) == 1

        # Clear in one project shouldn't affect the other
        await tracker1.clear()

        tracked1 = await tracker1.list_tracked_files()
        tracked2 = await tracker2.list_tracked_files()

        assert len(tracked1) == 0
        assert len(tracked2) == 1

        tracker1.close()
        tracker2.close()
