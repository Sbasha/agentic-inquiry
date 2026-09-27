"""Tests for lifecycle contracts across components.

These tests verify that:
1. Components have public initialize() methods (not just private _ensure_initialized)
2. initialize() is idempotent (safe to call multiple times)
3. Components follow consistent lifecycle patterns
"""

import pytest

pytestmark = pytest.mark.integration

import asyncio

from agentic_inquiry.events.store import EventStore
from agentic_inquiry.watching.file_tracker import FileTracker
from agentic_inquiry.watching.watcher import FileWatcher


class TestEventStoreLifecycle:
    """Test EventStore lifecycle contracts."""

    @pytest.mark.asyncio
    async def test_has_public_initialize_method(self):
        """Verify EventStore has a public initialize() method."""
        assert hasattr(EventStore, "initialize")
        assert callable(getattr(EventStore, "initialize"))
        assert not EventStore.initialize.__name__.startswith("_")

    @pytest.mark.asyncio
    async def test_initialize_is_idempotent(self, tmp_path):
        """Verify initialize() can be called multiple times safely."""
        db_path = tmp_path / "events.db"
        store = EventStore(db_path=db_path, project_id="test")

        # Call initialize multiple times
        await store.initialize()
        await store.initialize()
        await store.initialize()

        # Should still work
        assert store._initialized
        await store.close()

    @pytest.mark.asyncio
    async def test_from_config_uses_initialize(self, tmp_path):
        """Verify from_config() properly initializes."""
        db_path = tmp_path / "events.db"
        store = await EventStore.from_config(db_path=db_path, project_id="test")

        assert store._initialized
        await store.close()


class TestFileTrackerLifecycle:
    """Test FileTracker lifecycle contracts."""

    @pytest.mark.asyncio
    async def test_has_public_initialize_method(self):
        """Verify FileTracker has a public initialize() method."""
        assert hasattr(FileTracker, "initialize")
        assert callable(getattr(FileTracker, "initialize"))
        assert not FileTracker.initialize.__name__.startswith("_")

    @pytest.mark.asyncio
    async def test_initialize_is_idempotent(self, tmp_path):
        """Verify initialize() can be called multiple times safely."""
        db_path = tmp_path / "tracker.db"
        tracker = FileTracker(db_path=db_path, project_id="test")

        # Call initialize multiple times
        await tracker.initialize()
        await tracker.initialize()
        await tracker.initialize()

        # Should still work
        assert tracker._initialized

    @pytest.mark.asyncio
    async def test_from_config_uses_initialize(self, tmp_path):
        """Verify from_config() properly initializes."""
        db_path = tmp_path / "tracker.db"
        tracker = await FileTracker.from_config(db_path=db_path, project_id="test")

        assert tracker._initialized


class TestFileWatcherLifecycle:
    """Test FileWatcher lifecycle contracts."""

    @pytest.mark.asyncio
    async def test_has_public_initialize_method(self):
        """Verify FileWatcher has a public initialize() method."""
        assert hasattr(FileWatcher, "initialize")
        assert callable(getattr(FileWatcher, "initialize"))
        assert not FileWatcher.initialize.__name__.startswith("_")

    @pytest.mark.asyncio
    async def test_initialize_is_idempotent(self, tmp_path):
        """Verify initialize() can be called multiple times safely."""
        db_path = tmp_path / "tracker.db"
        tracker = FileTracker(db_path=db_path, project_id="test")
        watcher = FileWatcher(file_tracker=tracker)

        # Call initialize multiple times
        await watcher.initialize()
        await watcher.initialize()
        await watcher.initialize()

        # Should still work
        assert watcher._initialized

    @pytest.mark.asyncio
    async def test_from_config_uses_initialize(self, tmp_path):
        """Verify from_config() properly initializes."""
        db_path = tmp_path / "tracker.db"
        tracker = FileTracker(db_path=db_path, project_id="test")
        watcher = await FileWatcher.from_config(file_tracker=tracker)

        assert watcher._initialized


class TestLifecycleConsistency:
    """Test that components follow consistent lifecycle patterns."""

    def test_all_components_have_initialize(self):
        """All lifecycle components should have public initialize()."""
        components = [EventStore, FileTracker, FileWatcher]

        for component in components:
            assert hasattr(component, "initialize"), (
                f"{component.__name__} missing initialize()"
            )
            method = getattr(component, "initialize")
            assert asyncio.iscoroutinefunction(method), (
                f"{component.__name__}.initialize() should be async"
            )

    def test_all_components_have_from_config(self):
        """All lifecycle components should have from_config factory."""
        components = [EventStore, FileTracker, FileWatcher]

        for component in components:
            assert hasattr(component, "from_config"), (
                f"{component.__name__} missing from_config()"
            )
            method = getattr(component, "from_config")
            assert asyncio.iscoroutinefunction(method), (
                f"{component.__name__}.from_config() should be async"
            )
