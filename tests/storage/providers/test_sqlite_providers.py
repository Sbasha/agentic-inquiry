"""Tests for SQLite storage providers.

These tests verify that the SQLite providers:
1. Implement their respective protocols correctly
2. Have the required SUPPORTED_ROLES attribute
3. Added methods work correctly (run_maintenance, get_hash_sync, async close)
"""

import pytest
from datetime import datetime

from agentic_inquiry.events.models import Event, EventStatus
from agentic_inquiry.storage.protocols.events import EventStorageProtocol
from agentic_inquiry.storage.protocols.file_tracker import FileTrackerProtocol
from agentic_inquiry.storage.providers.sqlite import (
    SQLiteEventProvider,
    SQLiteFileTrackerProvider,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def temp_db_path(tmp_path):
    """Provide a temporary database path."""
    return tmp_path / "test.db"


@pytest.fixture
def sample_file(tmp_path):
    """Create a sample file for testing."""
    file_path = tmp_path / "sample.txt"
    file_path.write_text("Hello, World!")
    return str(file_path)


class TestSQLiteEventProviderProtocol:
    """Test SQLiteEventProvider protocol compliance."""

    def test_implements_protocol(self, temp_db_path):
        """Test that SQLiteEventProvider implements EventStorageProtocol."""
        provider = SQLiteEventProvider(
            db_path=temp_db_path,
            project_id="test_project",
        )
        assert isinstance(provider, EventStorageProtocol)

    def test_supported_roles(self, temp_db_path):
        """Test that SUPPORTED_ROLES is defined correctly."""
        provider = SQLiteEventProvider(
            db_path=temp_db_path,
            project_id="test_project",
        )
        assert hasattr(provider, "SUPPORTED_ROLES")
        assert provider.SUPPORTED_ROLES == frozenset({"events"})
        # Also check class-level attribute
        assert SQLiteEventProvider.SUPPORTED_ROLES == frozenset({"events"})


class TestSQLiteEventProviderMaintenance:
    """Test SQLiteEventProvider run_maintenance method."""

    @pytest.mark.asyncio
    async def test_run_maintenance_returns_dict(self, temp_db_path):
        """Test that run_maintenance returns expected dict."""
        provider = SQLiteEventProvider(
            db_path=temp_db_path,
            project_id="test_project",
        )
        await provider.initialize()

        result = await provider.run_maintenance()

        assert isinstance(result, dict)
        assert result["action"] == "vacuum"
        assert result["status"] == "completed"
        assert "db_path" in result

        await provider.close()

    @pytest.mark.asyncio
    async def test_run_maintenance_after_writes(self, temp_db_path):
        """Test maintenance works after writing events."""
        provider = SQLiteEventProvider(
            db_path=temp_db_path,
            project_id="test_project",
        )
        await provider.initialize()

        # Write some events
        events = [
            Event(
                event_id=f"evt-{i}",
                project_id="test_project",
                operation_id="op-1",
                session_id="sess-1",
                timestamp=datetime.now().timestamp(),
                event_type="test.event",
                status=EventStatus.COMPLETED,
                source="test",
            )
            for i in range(5)
        ]
        written = await provider.write_events(events)
        assert written == 5

        # Run maintenance
        result = await provider.run_maintenance()
        assert result["status"] == "completed"

        await provider.close()


class TestSQLiteFileTrackerProviderProtocol:
    """Test SQLiteFileTrackerProvider protocol compliance."""

    def test_implements_protocol(self, temp_db_path):
        """Test that SQLiteFileTrackerProvider implements FileTrackerProtocol."""
        provider = SQLiteFileTrackerProvider(
            db_path=temp_db_path,
            project_id="test_project",
        )
        assert isinstance(provider, FileTrackerProtocol)

    def test_supported_roles(self, temp_db_path):
        """Test that SUPPORTED_ROLES is defined correctly."""
        provider = SQLiteFileTrackerProvider(
            db_path=temp_db_path,
            project_id="test_project",
        )
        assert hasattr(provider, "SUPPORTED_ROLES")
        assert provider.SUPPORTED_ROLES == frozenset({"file_tracker"})
        # Also check class-level attribute
        assert SQLiteFileTrackerProvider.SUPPORTED_ROLES == frozenset({"file_tracker"})


class TestSQLiteFileTrackerProviderMethods:
    """Test SQLiteFileTrackerProvider added methods."""

    @pytest.mark.asyncio
    async def test_async_close(self, temp_db_path):
        """Test that async close works correctly."""
        provider = SQLiteFileTrackerProvider(
            db_path=temp_db_path,
            project_id="test_project",
        )
        await provider.initialize()

        # Should not raise
        await provider.close()

    def test_get_hash_sync(self, temp_db_path, sample_file):
        """Test synchronous get_hash_sync method."""
        provider = SQLiteFileTrackerProvider(
            db_path=temp_db_path,
            project_id="test_project",
        )
        # Initialize using sync wrapper
        import asyncio

        asyncio.run(provider.initialize())

        # First call should return None (not tracked)
        result = provider.get_hash_sync(sample_file)
        assert result is None

        # Update hash and verify we can retrieve it
        provider.update_hash_sync(sample_file)
        result = provider.get_hash_sync(sample_file)
        assert result is not None
        assert len(result) == 64  # SHA256 hex length

    @pytest.mark.asyncio
    async def test_full_lifecycle(self, temp_db_path, sample_file):
        """Test full provider lifecycle."""
        provider = SQLiteFileTrackerProvider(
            db_path=temp_db_path,
            project_id="test_project",
        )
        await provider.initialize()

        # Check file is new
        assert await provider.has_changed(sample_file)

        # Update and verify
        await provider.update_hash(sample_file)
        assert not await provider.has_changed(sample_file)

        # Get hash
        hash_value = await provider.get_hash(sample_file)
        assert hash_value is not None

        # List files
        files = await provider.list_tracked_files()
        assert len(files) == 1
        assert files[0][0] == sample_file

        # Remove file
        removed = await provider.remove_file(sample_file)
        assert removed

        # Verify removed
        assert await provider.get_hash(sample_file) is None

        await provider.close()


class TestSQLiteProviderRegistry:
    """Test SQLite providers work with registry."""

    def test_registry_returns_correct_classes(self):
        """Test that registry returns SQLite provider classes."""
        from agentic_inquiry.storage.registry import get_provider_class

        event_class = get_provider_class("sqlite", "events")
        assert event_class is SQLiteEventProvider

        file_tracker_class = get_provider_class("sqlite", "file_tracker")
        assert file_tracker_class is SQLiteFileTrackerProvider

    def test_registry_unsupported_roles(self):
        """Test that registry raises for unsupported SQLite roles."""
        from agentic_inquiry.storage.registry import (
            get_provider_class,
            UnsupportedRoleError,
        )

        # SQLite doesn't support vector or graph
        with pytest.raises(UnsupportedRoleError):
            get_provider_class("sqlite", "vector")

        with pytest.raises(UnsupportedRoleError):
            get_provider_class("sqlite", "graph")
