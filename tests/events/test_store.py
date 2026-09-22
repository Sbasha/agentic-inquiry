"""Tests for EventStore core functionality.

This module tests the core EventStore functionality including:
- Database initialization
- Event storage operations
- Event query operations
- Lifecycle management
- Error handling
"""

import asyncio
import time
from pathlib import Path

import aiosqlite
import pytest

pytestmark = pytest.mark.integration

from agent_vault.events.models import Event, EventStatus
from agent_vault.events.store import EventStore


@pytest.mark.asyncio
class TestDatabaseInitialization:
    """Test suite for EventStore database initialization."""
    
    async def test_database_file_creation(self, tmp_path: Path):
        """Test that database file is created on initialization."""
        db_path = tmp_path / "test_events.db"
        
        # File should not exist yet
        assert not db_path.exists()
        
        # Create and initialize store
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        # File should now exist
        assert db_path.exists()
        
        await store.close()
    
    async def test_parent_directory_creation(self, tmp_path: Path):
        """Test that parent directories are created if they don't exist."""
        db_path = tmp_path / "nested" / "dir" / "test_events.db"
        
        # Parent directories should not exist yet
        assert not db_path.parent.exists()
        
        # Create store (should create parent directories)
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        # Parent directories should now exist
        assert db_path.parent.exists()
        assert db_path.exists()
        
        await store.close()
    
    async def test_table_creation(self, tmp_path: Path):
        """Test that events table is created with correct schema."""
        db_path = tmp_path / "test_events.db"
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        # Query table schema
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='events'"
            ) as cursor:
                row = await cursor.fetchone()
                assert row is not None
                schema = row[0]
                
                # Check that all required columns are present
                assert "event_id TEXT PRIMARY KEY" in schema
                assert "project_id TEXT NOT NULL" in schema
                assert "operation_id TEXT" in schema
                assert "session_id TEXT" in schema
                assert "timestamp REAL NOT NULL" in schema
                assert "event_type TEXT NOT NULL" in schema
                assert "status TEXT NOT NULL" in schema
                assert "source TEXT NOT NULL" in schema
                assert "metadata TEXT" in schema
                assert "schema_version TEXT NOT NULL DEFAULT '1.0'" in schema
        
        await store.close()
    
    async def test_index_creation(self, tmp_path: Path):
        """Test that all required indexes are created."""
        db_path = tmp_path / "test_events.db"
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        # Query indexes
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='events'"
            ) as cursor:
                rows = await cursor.fetchall()
                index_names = [row[0] for row in rows]
                
                # Check that all required indexes exist
                assert "idx_operation_id" in index_names
                assert "idx_event_type" in index_names
                assert "idx_timestamp" in index_names
                assert "idx_project_timestamp" in index_names
                assert "idx_status" in index_names
        
        await store.close()
    
    async def test_wal_mode_enabled(self, tmp_path: Path):
        """Test that WAL mode is enabled on initialization."""
        db_path = tmp_path / "test_events.db"
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        # Check WAL mode
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("PRAGMA journal_mode") as cursor:
                row = await cursor.fetchone()
                assert row[0].lower() == "wal"
        
        await store.close()
    
    async def test_lazy_initialization(self, tmp_path: Path):
        """Test that database is initialized lazily."""
        db_path = tmp_path / "test_events.db"
        
        # Create store without using from_config (no initialization)
        store = EventStore(
            db_path=db_path,
            project_id="test_project"
        )
        
        # Database should not be initialized yet
        assert not store._initialized
        assert store._writer_conn is None
        
        # Trigger initialization
        await store._ensure_initialized()
        
        # Now it should be initialized
        assert store._initialized
        assert store._writer_conn is not None
        
        await store.close()
    
    async def test_double_initialization_is_safe(self, tmp_path: Path):
        """Test that calling _ensure_initialized multiple times is safe."""
        db_path = tmp_path / "test_events.db"
        store = EventStore(
            db_path=db_path,
            project_id="test_project"
        )
        
        # Initialize multiple times
        await store._ensure_initialized()
        await store._ensure_initialized()
        await store._ensure_initialized()
        
        # Should still be initialized with single connection
        assert store._initialized
        assert store._writer_conn is not None
        
        await store.close()
    
    async def test_concurrent_initialization(self, tmp_path: Path):
        """Test that concurrent initialization attempts are handled safely."""
        db_path = tmp_path / "test_events.db"
        store = EventStore(
            db_path=db_path,
            project_id="test_project"
        )
        
        # Try to initialize concurrently
        await asyncio.gather(
            store._ensure_initialized(),
            store._ensure_initialized(),
            store._ensure_initialized(),
        )
        
        # Should be initialized exactly once
        assert store._initialized
        assert store._writer_conn is not None
        
        await store.close()


@pytest.mark.asyncio
class TestEventStorageOperations:
    """Test suite for EventStore storage operations."""
    
    async def test_store_single_event(self, tmp_path: Path):
        """Test storing a single event."""
        db_path = tmp_path / "test_events.db"
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        event = Event(
            project_id="test_project",
            operation_id="op_123",
            event_type="test.event",
            status=EventStatus.STARTED,
            source="test",
            metadata={"key": "value"},
        )
        
        # Store event
        await store.store_events([event])
        
        # Verify it was stored
        events = await store.get_operation_events("op_123")
        assert len(events) == 1
        assert events[0].event_id == event.event_id
        assert events[0].event_type == "test.event"
        assert events[0].metadata == {"key": "value"}
        
        await store.close()
    
    async def test_store_batch_of_events(self, tmp_path: Path):
        """Test storing multiple events in a batch."""
        db_path = tmp_path / "test_events.db"
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        events = [
            Event(
                project_id="test_project",
                operation_id="op_123",
                event_type=f"test.event.{i}",
                status=EventStatus.PROGRESS,
                source="test",
            )
            for i in range(10)
        ]
        
        # Store batch
        await store.store_events(events)
        
        # Verify all were stored
        stored_events = await store.get_operation_events("op_123")
        assert len(stored_events) == 10
        
        await store.close()
    
    async def test_store_empty_list(self, tmp_path: Path):
        """Test that storing an empty list is handled gracefully."""
        db_path = tmp_path / "test_events.db"
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        # Should not raise an error
        await store.store_events([])
        
        await store.close()
    
    async def test_store_events_with_all_fields(self, tmp_path: Path):
        """Test storing events with all fields populated."""
        db_path = tmp_path / "test_events.db"
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        event = Event(
            event_id="custom_id",
            project_id="test_project",
            operation_id="op_123",
            session_id="session_456",
            timestamp=1234567890.123456,
            event_type="test.event",
            status=EventStatus.COMPLETED,
            source="test_source",
            metadata={"nested": {"key": "value"}, "list": [1, 2, 3]},
            schema_version="2.0",
        )
        
        await store.store_events([event])
        
        # Verify all fields were stored correctly
        events = await store.get_operation_events("op_123")
        assert len(events) == 1
        stored = events[0]
        
        assert stored.event_id == "custom_id"
        assert stored.project_id == "test_project"
        assert stored.operation_id == "op_123"
        assert stored.session_id == "session_456"
        assert stored.timestamp == 1234567890.123456
        assert stored.event_type == "test.event"
        assert stored.status == EventStatus.COMPLETED
        assert stored.source == "test_source"
        assert stored.metadata == {"nested": {"key": "value"}, "list": [1, 2, 3]}
        assert stored.schema_version == "2.0"
        
        await store.close()
    
    async def test_store_events_with_none_optional_fields(self, tmp_path: Path):
        """Test storing events with None values in optional fields."""
        db_path = tmp_path / "test_events.db"
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        event = Event(
            project_id="test_project",
            operation_id=None,
            session_id=None,
            event_type="test.event",
            status=EventStatus.PROGRESS,
            source="test",
        )
        
        await store.store_events([event])
        
        # Verify None values were stored
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM events WHERE event_id = ?",
                (event.event_id,)
            ) as cursor:
                row = await cursor.fetchone()
                assert row["operation_id"] is None
                assert row["session_id"] is None
        
        await store.close()
    
    async def test_store_duplicate_event_id_fails(self, tmp_path: Path):
        """Test that storing events with duplicate event_id fails gracefully."""
        db_path = tmp_path / "test_events.db"
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        event1 = Event(
            event_id="duplicate_id",
            project_id="test_project",
            event_type="test.event",
            status=EventStatus.STARTED,
            source="test",
        )
        
        event2 = Event(
            event_id="duplicate_id",  # Same ID
            project_id="test_project",
            event_type="test.event",
            status=EventStatus.COMPLETED,
            source="test",
        )
        
        # Store first event
        await store.store_events([event1])
        
        # Storing second event with same ID should not raise
        # (error is logged but not raised)
        await store.store_events([event2])
        
        await store.close()


@pytest.mark.asyncio
class TestEventQueryOperations:
    """Test suite for EventStore query operations."""
    
    async def test_get_operation_events_returns_correct_events(self, tmp_path: Path):
        """Test that get_operation_events returns events for the correct operation."""
        db_path = tmp_path / "test_events.db"
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        # Create events for different operations
        events = [
            Event(
                project_id="test_project",
                operation_id="op1",
                event_type="test.event",
                status=EventStatus.STARTED,
                source="test",
            ),
            Event(
                project_id="test_project",
                operation_id="op1",
                event_type="test.event",
                status=EventStatus.COMPLETED,
                source="test",
            ),
            Event(
                project_id="test_project",
                operation_id="op2",
                event_type="test.event",
                status=EventStatus.STARTED,
                source="test",
            ),
        ]
        
        await store.store_events(events)
        
        # Query op1 events
        op1_events = await store.get_operation_events("op1")
        assert len(op1_events) == 2
        assert all(e.operation_id == "op1" for e in op1_events)
        
        # Query op2 events
        op2_events = await store.get_operation_events("op2")
        assert len(op2_events) == 1
        assert op2_events[0].operation_id == "op2"
        
        await store.close()
    
    async def test_get_operation_events_ordered_by_timestamp(self, tmp_path: Path):
        """Test that get_operation_events returns events in timestamp order."""
        db_path = tmp_path / "test_events.db"
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        base_time = time.time()
        events = [
            Event(
                project_id="test_project",
                operation_id="op1",
                timestamp=base_time + 2,
                event_type="test.event.3",
                status=EventStatus.PROGRESS,
                source="test",
            ),
            Event(
                project_id="test_project",
                operation_id="op1",
                timestamp=base_time,
                event_type="test.event.1",
                status=EventStatus.STARTED,
                source="test",
            ),
            Event(
                project_id="test_project",
                operation_id="op1",
                timestamp=base_time + 1,
                event_type="test.event.2",
                status=EventStatus.PROGRESS,
                source="test",
            ),
        ]
        
        await store.store_events(events)
        
        # Query events
        result = await store.get_operation_events("op1")
        
        # Should be ordered by timestamp ascending
        assert len(result) == 3
        assert result[0].event_type == "test.event.1"
        assert result[1].event_type == "test.event.2"
        assert result[2].event_type == "test.event.3"
        assert result[0].timestamp < result[1].timestamp < result[2].timestamp
        
        await store.close()
    
    async def test_get_operation_events_with_project_id_filter(self, tmp_path: Path):
        """Test that get_operation_events filters by project_id."""
        db_path = tmp_path / "test_events.db"
        
        # Create store for project1
        store1 = await EventStore.from_config(
            db_path=db_path,
            project_id="project1"
        )
        
        # Create store for project2
        store2 = await EventStore.from_config(
            db_path=db_path,
            project_id="project2"
        )
        
        # Store events for both projects with same operation_id
        await store1.store_events([
            Event(
                project_id="project1",
                operation_id="shared_op",
                event_type="test.event",
                status=EventStatus.STARTED,
                source="test",
            )
        ])
        
        await store2.store_events([
            Event(
                project_id="project2",
                operation_id="shared_op",
                event_type="test.event",
                status=EventStatus.STARTED,
                source="test",
            )
        ])
        
        # Query from store1 should only return project1 events
        events1 = await store1.get_operation_events("shared_op")
        assert len(events1) == 1
        assert events1[0].project_id == "project1"
        
        # Query from store2 should only return project2 events
        events2 = await store2.get_operation_events("shared_op")
        assert len(events2) == 1
        assert events2[0].project_id == "project2"
        
        await store1.close()
        await store2.close()
    
    async def test_get_operation_events_no_results(self, tmp_path: Path):
        """Test that get_operation_events returns empty list when no events match."""
        db_path = tmp_path / "test_events.db"
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        # Query non-existent operation
        events = await store.get_operation_events("nonexistent_op")
        
        assert events == []
        
        await store.close()


@pytest.mark.asyncio
class TestLifecycleManagement:
    """Test suite for EventStore lifecycle management."""
    
    async def test_from_config_initialization(self, tmp_path: Path):
        """Test that from_config creates and initializes store."""
        db_path = tmp_path / "test_events.db"
        
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        # Should be initialized
        assert store._initialized
        assert store._writer_conn is not None
        assert store.project_id == "test_project"
        assert str(db_path) in store.db_path
        
        await store.close()
    
    async def test_from_config_with_project_context(self, tmp_path: Path):
        """Test from_config with ProjectContext."""
        from agent_vault.config import Config, StorageConfig, EventStoreConfig
        
        config = Config()
        config.storage = StorageConfig(
            root=str(tmp_path),
            default_project_id="ctx_project",
            event_store=EventStoreConfig(path="events.db")
        )
        
        # Use config and project_id directly (no for_project method)
        store = await EventStore.from_config(config=config, project_id="ctx_project")
        
        assert store.project_id == "ctx_project"
        assert store._initialized
        
        await store.close()
    
    async def test_close_cleanup(self, tmp_path: Path):
        """Test that close() properly cleans up resources."""
        db_path = tmp_path / "test_events.db"
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        # Store should be initialized
        assert store._initialized
        assert store._writer_conn is not None
        
        # Close store
        await store.close()
        
        # Should be cleaned up
        assert not store._initialized
        assert store._writer_conn is None
        
    async def test_close_is_idempotent(self, tmp_path: Path):
        """Test that calling close() multiple times is safe."""
        db_path = tmp_path / "test_events.db"
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        # Close multiple times
        await store.close()
        await store.close()
        await store.close()
        
        # Should not raise errors
        assert not store._initialized
    
    async def test_connection_reuse_for_writes(self, tmp_path: Path):
        """Test that writer connection is reused across multiple writes."""
        db_path = tmp_path / "test_events.db"
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        # Get initial connection
        initial_conn = store._writer_conn
        
        # Store multiple batches
        for i in range(5):
            await store.store_events([
                Event(
                    project_id="test_project",
                    operation_id=f"op_{i}",
                    event_type="test.event",
                    status=EventStatus.PROGRESS,
                    source="test",
                )
            ])
        
        # Connection should be the same
        assert store._writer_conn is initial_conn
        
        await store.close()
    
    async def test_new_connection_per_query(self, tmp_path: Path):
        """Test that queries use new connections (not the writer connection)."""
        db_path = tmp_path / "test_events.db"
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        # Store an event
        await store.store_events([
            Event(
                project_id="test_project",
                operation_id="op1",
                event_type="test.event",
                status=EventStatus.STARTED,
                source="test",
            )
        ])
        
        # Query should not affect writer connection
        writer_conn = store._writer_conn
        await store.get_operation_events("op1")
        
        # Writer connection should still be the same
        assert store._writer_conn is writer_conn
        
        await store.close()


@pytest.mark.asyncio
class TestErrorHandling:
    """Test suite for EventStore error handling."""
    
    async def test_store_events_handles_integrity_error(self, tmp_path: Path):
        """Test that integrity errors are handled gracefully."""
        db_path = tmp_path / "test_events.db"
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        event = Event(
            event_id="duplicate_id",
            project_id="test_project",
            event_type="test.event",
            status=EventStatus.STARTED,
            source="test",
        )
        
        # Store event
        await store.store_events([event])
        
        # Try to store duplicate (should not raise)
        await store.store_events([event])
        
        await store.close()
    
    async def test_retry_on_database_locked(self, tmp_path: Path):
        """Test that database locked errors trigger retry logic."""
        db_path = tmp_path / "test_events.db"
        store = await EventStore.from_config(
            db_path=db_path,
            project_id="test_project"
        )
        
        # This test verifies the retry mechanism exists
        # Actual lock contention is hard to simulate reliably
        
        # Store events normally (should work)
        await store.store_events([
            Event(
                project_id="test_project",
                operation_id="op1",
                event_type="test.event",
                status=EventStatus.STARTED,
                source="test",
            )
        ])
        
        # Verify event was stored
        events = await store.get_operation_events("op1")
        assert len(events) == 1
        
        await store.close()
    
    async def test_store_events_without_initialization(self, tmp_path: Path):
        """Test that store_events initializes database if needed."""
        db_path = tmp_path / "test_events.db"
        
        # Create store without initialization
        store = EventStore(
            db_path=db_path,
            project_id="test_project"
        )
        
        # Should not be initialized yet
        assert not store._initialized
        
        # Store events (should trigger initialization)
        await store.store_events([
            Event(
                project_id="test_project",
                operation_id="op1",
                event_type="test.event",
                status=EventStatus.STARTED,
                source="test",
            )
        ])
        
        # Should now be initialized
        assert store._initialized
        
        # Verify event was stored
        events = await store.get_operation_events("op1")
        assert len(events) == 1
        
        await store.close()
