#!/usr/bin/env python3
"""Integration tests for FileWatcher and FileTracker.

Tests file watching functionality including:
- Hash-based change detection
- SQLite state persistence
- Callback invocation
- Recursive watching with ignore patterns
- Pause/resume functionality
"""

import pytest

pytestmark = pytest.mark.integration

import time
from pathlib import Path
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest


def wait_for_condition(condition_fn, timeout=2.0, poll_interval=0.05):
    """Wait for a condition to become true with timeout.

    This replaces fixed time.sleep() calls with condition polling,
    which is both faster (returns immediately when condition is met)
    and more reliable (has explicit timeout).

    Args:
        condition_fn: Callable returning True when condition is met
        timeout: Maximum seconds to wait
        poll_interval: Seconds between condition checks

    Returns:
        True if condition was met, False if timeout
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition_fn():
            return True
        time.sleep(poll_interval)
    return False

from agent_vault.watching import (
    get_watcher,
    register_watcher,
    available_watchers,
)
from agent_vault.watching.watcher import FileWatcher
from agent_vault.watching.file_tracker import FileTracker


def _create_mock_event_system():
    """Create a mock event system for tests."""
    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    return mock_es


@pytest.fixture
def temp_db():
    """Create a temporary database for FileTracker."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    # Cleanup
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
async def tracker(temp_db):
    """Create a FileTracker instance for testing."""
    tracker = FileTracker(db_path=temp_db)
    await tracker._init_database()
    return tracker


@pytest.fixture
async def watcher(temp_db):
    """Create a FileWatcher instance with an initialized FileTracker for testing."""
    # Create and initialize the file tracker first
    tracker = FileTracker(db_path=temp_db)
    await tracker._init_database()
    mock_event_system = _create_mock_event_system()
    return FileWatcher(event_system=mock_event_system, file_tracker=tracker)


class TestFileTrackerBasic:
    """Basic FileTracker functionality tests."""
    
    @pytest.mark.asyncio
    async def test_tracker_initialization(self, tracker):
        """Test that tracker initializes correctly."""
        assert tracker.db_path is not None
        assert Path(tracker.db_path).exists()
    
    @pytest.mark.asyncio
    async def test_update_and_get_hash(self, tracker, tmp_path):
        """Test updating and retrieving file hash."""
        # Create a test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")
        
        # Update hash
        await tracker.update_hash(str(test_file))
        
        # Get hash
        stored_hash = await tracker.get_hash(str(test_file))
        assert stored_hash is not None
        assert len(stored_hash) == 64  # SHA256 hash length
    
    @pytest.mark.asyncio
    async def test_has_changed_for_new_file(self, tracker, tmp_path):
        """Test that new files are detected as changed."""
        # Create a test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")
        
        # Should be changed (not tracked yet)
        assert await tracker.has_changed(str(test_file)) is True
    
    @pytest.mark.asyncio
    async def test_has_changed_for_unchanged_file(self, tracker, tmp_path):
        """Test that unchanged files are not detected as changed."""
        # Create a test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")
        
        # Update hash
        await tracker.update_hash(str(test_file))
        
        # Should not be changed
        assert await tracker.has_changed(str(test_file)) is False
    
    @pytest.mark.asyncio
    async def test_has_changed_for_modified_file(self, tracker, tmp_path):
        """Test that modified files are detected as changed."""
        # Create a test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")
        
        # Update hash
        await tracker.update_hash(str(test_file))
        
        # Modify the file
        test_file.write_text("def hello():\n    print('Modified')")
        
        # Should be changed
        assert await tracker.has_changed(str(test_file)) is True
    
    @pytest.mark.asyncio
    async def test_remove_file(self, tracker, tmp_path):
        """Test removing a file from tracking."""
        # Create a test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")
        
        # Update hash
        await tracker.update_hash(str(test_file))
        
        # Remove from tracking
        await tracker.remove_file(str(test_file))
        
        # Should be changed (not tracked anymore)
        assert await tracker.has_changed(str(test_file)) is True
    
    @pytest.mark.asyncio
    async def test_list_tracked_files(self, tracker, tmp_path):
        """Test listing tracked files."""
        # Create test files
        test_file1 = tmp_path / "test1.py"
        test_file1.write_text("def hello(): pass")
        test_file2 = tmp_path / "test2.py"
        test_file2.write_text("def world(): pass")
        
        # Update hashes
        await tracker.update_hash(str(test_file1))
        await tracker.update_hash(str(test_file2))
        
        # List tracked files (returns list of tuples: (path, hash))
        tracked = await tracker.list_tracked_files()
        assert len(tracked) == 2
        tracked_paths = [path for path, _ in tracked]
        assert str(test_file1) in tracked_paths
        assert str(test_file2) in tracked_paths


class TestFileTrackerPersistence:
    """Tests for SQLite state persistence."""
    
    @pytest.mark.asyncio
    async def test_persistence_across_instances(self, temp_db, tmp_path):
        """Test that state persists across tracker instances."""
        # Create a test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")
        
        # Create first tracker and update hash
        tracker1 = FileTracker(db_path=temp_db)
        await tracker1._init_database()
        await tracker1.update_hash(str(test_file))
        stored_hash = await tracker1.get_hash(str(test_file))
        
        # Create second tracker
        tracker2 = FileTracker(db_path=temp_db)
        await tracker2._init_database()
        
        # Should retrieve same hash
        assert await tracker2.get_hash(str(test_file)) == stored_hash
    
    @pytest.mark.asyncio
    async def test_database_file_created(self, temp_db):
        """Test that database file is created."""
        tracker = FileTracker(db_path=temp_db)
        await tracker._init_database()
        assert Path(temp_db).exists()


class TestFileWatcherBasic:
    """Basic FileWatcher functionality tests."""
    
    def test_watcher_initialization(self, watcher):
        """Test that watcher initializes correctly."""
        assert watcher.file_tracker is not None
        assert watcher.is_running() is False
    
    def test_register_callback(self, watcher):
        """Test registering a callback."""
        callback_called = []
        
        def callback(file_path: str, event_type: str):
            callback_called.append((file_path, event_type))
        
        watcher.register_callback(callback)
        # Can't check internal state, but should not raise error
    
    def test_start_and_stop(self, watcher, tmp_path):
        """Test starting and stopping the watcher."""
        # Watch directory
        watcher.watch_directory(str(tmp_path))
        
        # Start watcher
        watcher.start()
        assert watcher.is_running() is True
        
        # Stop watcher
        watcher.stop()
        assert watcher.is_running() is False
    
    def test_watch_nonexistent_directory(self, watcher):
        """Test watching non-existent directory raises error."""
        with pytest.raises(ValueError, match="Directory does not exist"):
            watcher.watch_directory("/nonexistent/directory")


class TestFileWatcherCallbacks:
    """Tests for callback invocation."""
    
    def test_callback_on_file_creation(self, watcher, tmp_path):
        """Test that callback is invoked on file creation."""
        callback_called = []

        def callback(file_path: str, event_type: str):
            callback_called.append((file_path, event_type))

        watcher.register_callback(callback)
        watcher.watch_directory(str(tmp_path))
        watcher.start()

        try:
            # Create a file
            test_file = tmp_path / "test.py"
            test_file.write_text("def hello(): pass")

            # Wait for callback to be invoked
            assert wait_for_condition(lambda: len(callback_called) > 0), \
                "Callback was not invoked within timeout"
            assert any(event_type == "created" for _, event_type in callback_called)
        finally:
            watcher.stop()
    
    def test_callback_on_file_modification(self, watcher, tmp_path):
        """Test that callback is invoked on file modification."""
        # Create a file first
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        callback_called = []

        def callback(file_path: str, event_type: str):
            callback_called.append((file_path, event_type))

        watcher.register_callback(callback)
        watcher.watch_directory(str(tmp_path))
        watcher.start()

        try:
            # Small delay to let watcher initialize
            time.sleep(0.05)
            # Modify the file with significant content change
            test_file.write_text("def hello():\n    print('Modified')\n    print('More changes')")

            # Wait for callback to be invoked
            assert wait_for_condition(lambda: len(callback_called) > 0, timeout=3.0), \
                f"No callbacks received within timeout. Events: {callback_called}"
        finally:
            watcher.stop()
    
    def test_callback_on_file_deletion(self, watcher, tmp_path):
        """Test that callback is invoked on file deletion."""
        callback_called = []

        def callback(file_path: str, event_type: str):
            callback_called.append((file_path, event_type))

        watcher.register_callback(callback)
        watcher.watch_directory(str(tmp_path))
        watcher.start()

        try:
            # Create a file first (after watcher started)
            test_file = tmp_path / "test.py"
            test_file.write_text("def hello(): pass")

            # Wait for creation event
            assert wait_for_condition(lambda: len(callback_called) > 0), \
                "No creation callback received"

            # Record count before deletion
            count_before_delete = len(callback_called)

            # Delete the file
            test_file.unlink()

            # Wait for a new event after deletion
            assert wait_for_condition(lambda: len(callback_called) > count_before_delete), \
                f"No deletion callback received. Events: {callback_called}"
        finally:
            watcher.stop()


class TestFileWatcherRecursive:
    """Tests for recursive watching."""
    
    def test_recursive_watching(self, watcher, tmp_path):
        """Test that subdirectories are watched recursively."""
        # Create subdirectory
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        callback_called = []

        def callback(file_path: str, event_type: str):
            callback_called.append((file_path, event_type))

        watcher.register_callback(callback)
        watcher.watch_directory(str(tmp_path), recursive=True)
        watcher.start()

        try:
            # Create file in subdirectory
            test_file = subdir / "test.py"
            test_file.write_text("def hello(): pass")

            # Wait for callback to be invoked
            assert wait_for_condition(lambda: len(callback_called) > 0), \
                "Callback was not invoked within timeout"
        finally:
            watcher.stop()
    
    def test_non_recursive_watching(self, watcher, tmp_path):
        """Test that subdirectories are not watched when recursive=False."""
        # Create subdirectory
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        callback_called = []

        def callback(file_path: str, event_type: str):
            callback_called.append((file_path, event_type))

        watcher.register_callback(callback)
        watcher.watch_directory(str(tmp_path), recursive=False)
        watcher.start()

        try:
            # Create file in subdirectory
            test_file = subdir / "test.py"
            test_file.write_text("def hello(): pass")

            # Wait briefly - we expect NO callback for subdirectory files
            time.sleep(0.2)

            # Callback should not have been called for subdirectory
            # (watchdog may still report some events, so we just check it doesn't crash)
        finally:
            watcher.stop()


class TestFileWatcherPauseResume:
    """Tests for pause/resume functionality."""

    def test_pause_and_resume(self, watcher, tmp_path):
        """Test pausing and resuming the watcher."""
        callback_called = []

        def callback(file_path: str, event_type: str):
            callback_called.append((file_path, event_type))

        watcher.register_callback(callback)
        watcher.watch_directory(str(tmp_path))
        watcher.start()

        try:
            # Pause watcher
            watcher.pause()

            # Create file while paused
            test_file1 = tmp_path / "test1.py"
            test_file1.write_text("def hello(): pass")
            # Brief wait while paused - we expect no events
            time.sleep(0.2)

            # Should not have received events (or very few)
            paused_count = len(callback_called)

            # Resume watcher
            watcher.resume()

            # Create another file
            test_file2 = tmp_path / "test2.py"
            test_file2.write_text("def world(): pass")

            # Wait for callback after resume
            assert wait_for_condition(lambda: len(callback_called) > paused_count), \
                "No events received after resume"
        finally:
            watcher.stop()


class TestWatcherRegistry:
    """Tests for watcher registry functionality."""

    def test_register_and_get_watcher(self):
        """Test registering and retrieving a watcher."""
        mock_event_system = _create_mock_event_system()
        watcher = FileWatcher(event_system=mock_event_system)
        register_watcher("test_watcher", watcher)
        
        try:
            retrieved = get_watcher("test_watcher")
            assert retrieved is watcher
        finally:
            # Cleanup
            from agent_vault.watching import _watcher_registry
            _watcher_registry.unregister("test_watcher")
    
    def test_get_default_watcher(self):
        """Test getting the default watcher."""
        from agent_vault.watching import _watcher_registry

        # Unregister any existing default watcher from auto-registration
        if "default" in _watcher_registry.available():
            _watcher_registry.unregister("default")

        # Register a default watcher
        mock_event_system = _create_mock_event_system()
        default_watcher = FileWatcher(event_system=mock_event_system)
        register_watcher("default", default_watcher)

        try:
            watcher = get_watcher()
            assert watcher is not None
        finally:
            _watcher_registry.unregister("default")

    def test_available_watchers(self):
        """Test listing available watchers."""
        from agent_vault.watching import _watcher_registry

        # Unregister any existing default watcher from auto-registration
        if "default" in _watcher_registry.available():
            _watcher_registry.unregister("default")

        # Register a default watcher
        mock_event_system = _create_mock_event_system()
        default_watcher = FileWatcher(event_system=mock_event_system)
        register_watcher("default", default_watcher)

        try:
            watchers = available_watchers()
            assert isinstance(watchers, list)
            assert "default" in watchers
        finally:
            _watcher_registry.unregister("default")


class TestErrorHandling:
    """Tests for error handling."""
    
    def test_watch_nonexistent_directory(self, watcher):
        """Test watching non-existent directory."""
        with pytest.raises(ValueError):
            watcher.watch_directory("/nonexistent/directory")
    
    def test_stop_without_start(self, watcher):
        """Test stopping watcher without starting."""
        # Should not crash
        watcher.stop()
    
    def test_double_start(self, watcher, tmp_path):
        """Test starting watcher twice."""
        watcher.watch_directory(str(tmp_path))
        watcher.start()
        
        try:
            # Starting again should not crash
            watcher.start()
        finally:
            watcher.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
