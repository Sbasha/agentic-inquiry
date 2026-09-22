"""Tests for FileWatchManager.

This module tests the file watching functionality extracted from IndexingPipeline.
"""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock
from agentic_inquiry.indexing.file_watch_manager import FileWatchManager
from agentic_inquiry.watching import register_watcher
from tests.helpers.async_utils import AsyncTestHelper


class MockCache:
    """Mock cache implementation for testing."""

    def __init__(self):
        self._cache = {}
        self.invalidate_calls = []

    async def invalidate(self, path: str):
        self.invalidate_calls.append(path)
        if path in self._cache:
            del self._cache[path]


class MockWatcher:
    """Mock watcher implementation for testing."""

    def __init__(self):
        self.callbacks = []
        self.watched_dirs = []
        self._running = False
        self.register_callback_calls = []
        self.watch_directory_calls = []
        self.stop_called = False

    def register_callback(self, callback):
        self.register_callback_calls.append(callback)
        self.callbacks.append(callback)

    def unregister_callback(self, callback):
        if callback in self.callbacks:
            self.callbacks.remove(callback)

    def watch_directory(self, path: str, recursive: bool = True, ignore_patterns=None):
        self.watch_directory_calls.append((path, recursive, ignore_patterns))
        self.watched_dirs.append(path)

    def start(self):
        self._running = True

    def stop(self):
        self.stop_called = True
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def trigger_event(self, file_path: str, event_type: str):
        """Helper method to trigger events for testing."""
        for callback in self.callbacks:
            callback(file_path, event_type)


@pytest.fixture
def mock_cache():
    """Create a mock cache."""
    return MockCache()


@pytest.fixture
def mock_watcher(request):
    """Create and register a mock watcher with unique name per test."""
    watcher = MockWatcher()
    # Use test node name to create unique watcher name
    watcher_name = f"test_watcher_{request.node.name}_{id(request)}"
    register_watcher(watcher_name, watcher)
    # Store watcher name for tests to use
    watcher._test_watcher_name = watcher_name
    yield watcher
    # Cleanup
    from agentic_inquiry.watching import _watcher_registry
    try:
        _watcher_registry.unregister(watcher_name)
    except (KeyError, AttributeError):
        pass  # Already unregistered or registry doesn't exist


def test_file_watch_manager_init_without_cache(tmp_path):
    """Test FileWatchManager initialization without cache."""
    manager = FileWatchManager(
        project_root=str(tmp_path),
        cache=None
    )

    assert manager.project_root == str(tmp_path)
    assert manager.cache is None
    assert manager.watcher is None
    assert manager._watcher_name is None


def test_file_watch_manager_init_with_cache(tmp_path, mock_cache):
    """Test FileWatchManager initialization with cache."""
    manager = FileWatchManager(
        project_root=str(tmp_path),
        cache=mock_cache
    )

    assert manager.project_root == str(tmp_path)
    assert manager.cache is mock_cache
    assert manager.watcher is None


def test_setup_file_watching(tmp_path, mock_watcher):
    """Test setting up file watching."""
    manager = FileWatchManager(
        project_root=str(tmp_path),
        cache=None
    )

    # Setup file watching
    manager.setup_file_watching(mock_watcher._test_watcher_name)

    # Verify watcher was set up correctly
    assert manager.watcher is not None
    assert manager._watcher_name == mock_watcher._test_watcher_name
    assert mock_watcher.is_running()
    assert len(mock_watcher.register_callback_calls) == 1
    assert len(mock_watcher.watch_directory_calls) == 1

    # Verify watch_directory was called with correct arguments
    path, recursive, ignore_patterns = mock_watcher.watch_directory_calls[0]
    assert path == str(tmp_path)
    assert recursive is True
    assert ignore_patterns is not None
    assert "*.pyc" in ignore_patterns
    assert "__pycache__/*" in ignore_patterns


def test_setup_file_watching_with_invalid_watcher(tmp_path):
    """Test setup with invalid watcher name."""
    manager = FileWatchManager(
        project_root=str(tmp_path),
        cache=None
    )

    # Setup with non-existent watcher should not raise
    manager.setup_file_watching("nonexistent_watcher")

    # Watcher should be None
    assert manager.watcher is None


def test_stop_watching_with_active_watcher(tmp_path, mock_watcher):
    """Test stopping an active watcher."""
    manager = FileWatchManager(
        project_root=str(tmp_path),
        cache=None
    )

    # Setup and verify watcher is running
    manager.setup_file_watching(mock_watcher._test_watcher_name)
    assert mock_watcher.is_running()

    # Stop watching
    manager.stop_watching()

    # Verify watcher was stopped
    assert mock_watcher.stop_called
    assert not mock_watcher.is_running()
    assert manager.watcher is None


def test_stop_watching_without_watcher(tmp_path):
    """Test that stop_watching is safe to call without a watcher."""
    manager = FileWatchManager(
        project_root=str(tmp_path),
        cache=None
    )

    # Should not raise an error
    manager.stop_watching()
    assert manager.watcher is None


def test_is_watching_returns_true_when_active(tmp_path, mock_watcher):
    """Test is_watching returns True when watcher is active."""
    manager = FileWatchManager(
        project_root=str(tmp_path),
        cache=None
    )

    # Setup file watching
    manager.setup_file_watching(mock_watcher._test_watcher_name)

    # Should return True
    assert manager.is_watching() is True


def test_is_watching_returns_false_when_inactive(tmp_path):
    """Test is_watching returns False when no watcher is active."""
    manager = FileWatchManager(
        project_root=str(tmp_path),
        cache=None
    )

    # Should return False
    assert manager.is_watching() is False


def test_is_watching_returns_false_after_stop(tmp_path, mock_watcher):
    """Test is_watching returns False after stopping."""
    manager = FileWatchManager(
        project_root=str(tmp_path),
        cache=None
    )

    # Setup and stop
    manager.setup_file_watching(mock_watcher._test_watcher_name)
    manager.stop_watching()

    # Should return False
    assert manager.is_watching() is False


@pytest.mark.asyncio
async def test_file_change_callback_invalidates_cache(tmp_path, mock_watcher, mock_cache):
    """Test file change callback invalidates cache."""
    manager = FileWatchManager(
        project_root=str(tmp_path),
        cache=mock_cache
    )

    # Setup file watching
    manager.setup_file_watching(mock_watcher._test_watcher_name)

    # Add something to cache
    mock_cache._cache["/test/file.py"] = "test_content"

    # Trigger a modified event
    mock_watcher.trigger_event("/test/file.py", "modified")

    # Wait for cache to be invalidated
    success = await AsyncTestHelper.wait_for_condition(
        lambda: len(mock_cache.invalidate_calls) == 1,
        timeout=1.0
    )

    # Cache should be invalidated
    assert success, "Cache was not invalidated within timeout"
    assert len(mock_cache.invalidate_calls) == 1
    assert "/test/file.py" not in mock_cache._cache


@pytest.mark.asyncio
async def test_file_change_callback_created_event(tmp_path, mock_watcher, mock_cache):
    """Test file change callback for created events."""
    manager = FileWatchManager(
        project_root=str(tmp_path),
        cache=mock_cache
    )

    # Setup file watching
    manager.setup_file_watching(mock_watcher._test_watcher_name)

    # Trigger a created event
    mock_watcher.trigger_event("/test/new_file.py", "created")

    # Wait for cache invalidation attempt
    success = await AsyncTestHelper.wait_for_condition(
        lambda: len(mock_cache.invalidate_calls) == 1,
        timeout=1.0
    )

    # Cache invalidation should be called
    assert success
    assert len(mock_cache.invalidate_calls) == 1


@pytest.mark.asyncio
async def test_file_change_callback_deleted_event(tmp_path, mock_watcher, mock_cache):
    """Test file change callback for deleted events."""
    manager = FileWatchManager(
        project_root=str(tmp_path),
        cache=mock_cache
    )

    # Setup file watching
    manager.setup_file_watching(mock_watcher._test_watcher_name)

    # Add something to cache
    mock_cache._cache["/test/file.py"] = "test_content"

    # Trigger a deleted event
    mock_watcher.trigger_event("/test/file.py", "deleted")

    # Wait for cache to be invalidated
    success = await AsyncTestHelper.wait_for_condition(
        lambda: len(mock_cache.invalidate_calls) == 1,
        timeout=1.0
    )

    # Cache should be invalidated
    assert success
    assert len(mock_cache.invalidate_calls) == 1
    assert "/test/file.py" not in mock_cache._cache


@pytest.mark.asyncio
async def test_file_change_callback_without_cache(tmp_path, mock_watcher):
    """Test file change callback without cache (should not raise)."""
    manager = FileWatchManager(
        project_root=str(tmp_path),
        cache=None
    )

    # Setup file watching
    manager.setup_file_watching(mock_watcher._test_watcher_name)

    # Trigger event should not raise even without cache
    mock_watcher.trigger_event("/test/file.py", "modified")

    # Give it a moment to process
    await AsyncTestHelper.wait_for_condition(
        lambda: True,
        timeout=0.1
    )


@pytest.mark.asyncio
async def test_invalidate_cache_handles_errors(tmp_path):
    """Test that cache invalidation handles errors gracefully."""
    # Create a cache that raises errors
    error_cache = AsyncMock()
    error_cache.invalidate = AsyncMock(side_effect=Exception("Test error"))

    manager = FileWatchManager(
        project_root=str(tmp_path),
        cache=error_cache
    )

    # Should not raise
    await manager._invalidate_cache("/test/file.py")

    # Invalidate should have been called
    error_cache.invalidate.assert_called_once_with("/test/file.py")


def test_multiple_callbacks_registered(tmp_path, mock_watcher):
    """Test that multiple setups don't duplicate callbacks."""
    manager = FileWatchManager(
        project_root=str(tmp_path),
        cache=None
    )

    # Setup file watching twice
    manager.setup_file_watching(mock_watcher._test_watcher_name)
    initial_callback_count = len(mock_watcher.callbacks)

    # Stop and setup again
    manager.stop_watching()
    manager.setup_file_watching(mock_watcher._test_watcher_name)

    # Should have same number of callbacks (one per setup)
    assert len(mock_watcher.callbacks) == initial_callback_count + 1


def test_watcher_lifecycle(tmp_path, mock_watcher):
    """Test complete watcher lifecycle."""
    manager = FileWatchManager(
        project_root=str(tmp_path),
        cache=None
    )

    # Initial state
    assert not manager.is_watching()
    assert manager.watcher is None

    # Setup
    manager.setup_file_watching(mock_watcher._test_watcher_name)
    assert manager.is_watching()
    assert manager.watcher is not None
    assert mock_watcher.is_running()

    # Stop
    manager.stop_watching()
    assert not manager.is_watching()
    assert manager.watcher is None
    assert not mock_watcher.is_running()

    # Stop again (should be safe)
    manager.stop_watching()
    assert not manager.is_watching()
