"""Property-based tests for IndexingPipeline context manager.

Feature: code-review-dec-2024-fixes
"""

import pytest

pytestmark = pytest.mark.unit

from unittest.mock import AsyncMock, MagicMock
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from agentic_inquiry.indexing.pipeline import IndexingPipeline
from agentic_inquiry.config import Config, StorageConfig
from agentic_inquiry.watching import register_watcher


class MockWatcher:
    """Mock watcher implementation for testing."""
    
    def __init__(self):
        self.callbacks = []
        self.watched_dirs = []
        self._running = False
        self.stop_called = False
    
    def register_callback(self, callback):
        self.callbacks.append(callback)
    
    def unregister_callback(self, callback):
        if callback in self.callbacks:
            self.callbacks.remove(callback)
    
    def watch_directory(self, path: str, recursive: bool = True, 
                       ignore_patterns=None):
        self.watched_dirs.append(path)
    
    def start(self):
        self._running = True
    
    def stop(self):
        self.stop_called = True
        self._running = False
    
    def pause(self):
        pass
    
    def resume(self):
        pass
    
    def is_running(self) -> bool:
        return self._running


@pytest.fixture
def mock_db_manager():
    """Create a mock database manager."""
    db = AsyncMock()
    db.add_document_chunks = AsyncMock()
    db.add_graph_entities = AsyncMock()
    db.add_graph_relationships = AsyncMock()
    return db


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


def _create_mock_event_system():
    """Create a mock event system for tests."""
    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    return mock_es


# Feature: code-review-dec-2024-fixes, Property 6: Context manager guarantees cleanup
@pytest.mark.asyncio
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    should_raise=st.booleans(),
)
async def test_context_manager_guarantees_cleanup(
    mock_db_manager,
    tmp_path,
    mock_watcher,
    should_raise,
):
    """Property: Context manager guarantees cleanup.
    
    For any IndexingPipeline used as an async context manager, when __aexit__
    is called (whether normally or via exception), the file watcher should be stopped.
    
    **Validates: Requirements 4.2**
    """
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    
    mock_event_system = _create_mock_event_system()
    
    # Create pipeline with watcher
    pipeline = IndexingPipeline(
        db_manager=mock_db_manager,
        config=config,
        project_id="test_project",
        event_system=mock_event_system,
        watcher_name=mock_watcher._test_watcher_name,
        auto_watch=True
    )
    
    # Reset the stop_called flag for this iteration (needed for property testing)
    mock_watcher.stop_called = False
    
    # Verify watcher is running
    assert mock_watcher.is_running()
    assert not mock_watcher.stop_called
    
    # Use context manager
    if should_raise:
        # Test exception path
        with pytest.raises(RuntimeError):
            async with pipeline:
                # Watcher should still be running inside context
                assert mock_watcher.is_running()
                # Raise an exception
                raise RuntimeError("Test exception")
    else:
        # Test normal exit path
        async with pipeline:
            # Watcher should still be running inside context
            assert mock_watcher.is_running()
            # Normal exit
    
    # After exiting context (either way), watcher should be stopped
    assert mock_watcher.stop_called
    assert not mock_watcher.is_running()
    assert pipeline.watcher is None


@pytest.mark.asyncio
async def test_context_manager_normal_exit(mock_db_manager, tmp_path, mock_watcher):
    """Test context manager with normal exit path.
    
    Verifies that stop_watching() is called on normal exit.
    """
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    
    mock_event_system = _create_mock_event_system()
    
    pipeline = IndexingPipeline(
        db_manager=mock_db_manager,
        config=config,
        project_id="test_project",
        event_system=mock_event_system,
        watcher_name=mock_watcher._test_watcher_name,
        auto_watch=True
    )
    
    assert mock_watcher.is_running()
    
    async with pipeline:
        assert mock_watcher.is_running()
    
    # After normal exit, watcher should be stopped
    assert mock_watcher.stop_called
    assert not mock_watcher.is_running()


@pytest.mark.asyncio
async def test_context_manager_exception_exit(mock_db_manager, tmp_path, mock_watcher):
    """Test context manager with exception exit path.
    
    Verifies that stop_watching() is called even when exception occurs.
    """
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    
    mock_event_system = _create_mock_event_system()
    
    pipeline = IndexingPipeline(
        db_manager=mock_db_manager,
        config=config,
        project_id="test_project",
        event_system=mock_event_system,
        watcher_name=mock_watcher._test_watcher_name,
        auto_watch=True
    )
    
    assert mock_watcher.is_running()
    
    with pytest.raises(ValueError):
        async with pipeline:
            assert mock_watcher.is_running()
            raise ValueError("Test exception")
    
    # After exception exit, watcher should still be stopped
    assert mock_watcher.stop_called
    assert not mock_watcher.is_running()


@pytest.mark.asyncio
async def test_context_manager_without_watcher(mock_db_manager, tmp_path):
    """Test context manager when no watcher is configured.
    
    Verifies that context manager works even without a watcher.
    """
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    
    mock_event_system = _create_mock_event_system()
    
    pipeline = IndexingPipeline(
        db_manager=mock_db_manager,
        config=config,
        project_id="test_project",
        event_system=mock_event_system,
    )
    
    assert pipeline.watcher is None
    
    # Should not raise an error
    async with pipeline:
        assert pipeline.watcher is None
    
    # Still no watcher after exit
    assert pipeline.watcher is None



# Feature: code-review-dec-2024-fixes, Property 7: Context manager propagates exceptions
@pytest.mark.asyncio
async def test_context_manager_propagates_exceptions(mock_db_manager, tmp_path, mock_watcher):
    """Property: Context manager propagates exceptions.
    
    For any exception raised within an IndexingPipeline context manager block,
    __aexit__ should return False to allow the exception to propagate after cleanup.
    
    **Validates: Requirements 4.4**
    """
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    
    mock_event_system = _create_mock_event_system()
    
    pipeline = IndexingPipeline(
        db_manager=mock_db_manager,
        config=config,
        project_id="test_project",
        event_system=mock_event_system,
        watcher_name=mock_watcher._test_watcher_name,
        auto_watch=True
    )
    
    # Test that various exception types propagate
    test_exceptions = [
        ValueError("Test ValueError"),
        RuntimeError("Test RuntimeError"),
        KeyError("Test KeyError"),
        Exception("Test generic Exception"),
    ]
    
    for exc in test_exceptions:
        # Reset the watcher state
        mock_watcher.stop_called = False
        mock_watcher._running = True
        pipeline.watcher = mock_watcher
        
        # Verify the exception propagates
        with pytest.raises(type(exc)) as exc_info:
            async with pipeline:
                raise exc
        
        # Verify it's the same exception
        assert str(exc_info.value) == str(exc)
        
        # Verify cleanup happened
        assert mock_watcher.stop_called


@pytest.mark.asyncio
async def test_aexit_returns_false(mock_db_manager, tmp_path, mock_watcher):
    """Test that __aexit__ returns False to propagate exceptions.
    
    This test directly verifies that __aexit__ returns False, which tells
    Python to propagate any exception that occurred in the context.
    """
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    
    mock_event_system = _create_mock_event_system()
    
    pipeline = IndexingPipeline(
        db_manager=mock_db_manager,
        config=config,
        project_id="test_project",
        event_system=mock_event_system,
        watcher_name=mock_watcher._test_watcher_name,
        auto_watch=True
    )
    
    # Call __aexit__ directly with exception info
    result = await pipeline.__aexit__(
        exc_type=ValueError,
        exc_val=ValueError("test"),
        exc_tb=None
    )
    
    # Should return False to propagate the exception
    assert result is False
    
    # Cleanup should have happened
    assert mock_watcher.stop_called


@pytest.mark.asyncio
async def test_aexit_returns_false_on_normal_exit(mock_db_manager, tmp_path, mock_watcher):
    """Test that __aexit__ returns False even on normal exit.
    
    This ensures consistent behavior whether or not an exception occurred.
    """
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    
    mock_event_system = _create_mock_event_system()
    
    pipeline = IndexingPipeline(
        db_manager=mock_db_manager,
        config=config,
        project_id="test_project",
        event_system=mock_event_system,
        watcher_name=mock_watcher._test_watcher_name,
        auto_watch=True
    )
    
    # Call __aexit__ directly with no exception (normal exit)
    result = await pipeline.__aexit__(
        exc_type=None,
        exc_val=None,
        exc_tb=None
    )
    
    # Should still return False
    assert result is False
    
    # Cleanup should have happened
    assert mock_watcher.stop_called
