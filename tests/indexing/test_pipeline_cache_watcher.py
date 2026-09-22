"""Tests for IndexingPipeline cache and watcher integration."""

import pytest

pytestmark = pytest.mark.unit

from unittest.mock import AsyncMock, MagicMock
from agent_vault.indexing.pipeline import IndexingPipeline
from agent_vault.parsers.models import ParsedDocument, ParserChunk
from agent_vault.cache import register_cache
from agent_vault.watching import register_watcher
from tests.helpers.async_utils import AsyncTestHelper


def _create_mock_event_system():
    """Create a mock event system for tests."""
    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    return mock_es


class MockCache:
    """Mock cache implementation for testing."""
    
    def __init__(self):
        self._cache = {}
        self.get_calls = []
        self.put_calls = []
        self.invalidate_calls = []
    
    async def get(self, path: str):
        self.get_calls.append(path)
        return self._cache.get(path)
    
    async def put(self, path: str, document):
        self.put_calls.append((path, document))
        self._cache[path] = document
    
    async def invalidate(self, path: str):
        self.invalidate_calls.append(path)
        if path in self._cache:
            del self._cache[path]
    
    async def clear(self):
        self._cache.clear()


class MockWatcher:
    """Mock watcher implementation for testing."""
    
    def __init__(self):
        self.callbacks = []
        self.watched_dirs = []
        self._running = False
        self.register_callback_calls = []
        self.watch_directory_calls = []
    
    def register_callback(self, callback):
        self.register_callback_calls.append(callback)
        self.callbacks.append(callback)
    
    def unregister_callback(self, callback):
        if callback in self.callbacks:
            self.callbacks.remove(callback)
    
    def watch_directory(self, path: str, recursive: bool = True, 
                       ignore_patterns=None):
        self.watch_directory_calls.append((path, recursive, ignore_patterns))
        self.watched_dirs.append(path)
    
    def start(self):
        self._running = True
    
    def stop(self):
        self._running = False
    
    def pause(self):
        pass
    
    def resume(self):
        pass
    
    def is_running(self) -> bool:
        return self._running
    
    def trigger_event(self, file_path: str, event_type: str):
        """Helper method to trigger events for testing."""
        for callback in self.callbacks:
            callback(file_path, event_type)


@pytest.fixture
def mock_db_manager():
    """Create a mock database manager."""
    db = AsyncMock()
    db.add_document_chunks = AsyncMock()
    db.add_graph_entities = AsyncMock()
    db.add_graph_relationships = AsyncMock()
    return db


@pytest.fixture
def mock_cache(request):
    """Create and register a mock cache with unique name per test."""
    cache = MockCache()
    # Use test node name to create unique cache name
    cache_name = f"test_cache_{request.node.name}_{id(request)}"
    register_cache(cache_name, cache)
    # Store cache name for tests to use
    cache._test_cache_name = cache_name
    yield cache
    # Cleanup
    from agent_vault.cache import _cache_registry
    try:
        _cache_registry.unregister(cache_name)
    except (KeyError, AttributeError):
        pass  # Already unregistered or registry doesn't exist


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
    from agent_vault.watching import _watcher_registry
    try:
        _watcher_registry.unregister(watcher_name)
    except (KeyError, AttributeError):
        pass  # Already unregistered or registry doesn't exist


def test_pipeline_without_cache_and_watcher(mock_db_manager, tmp_path):
    """Test that pipeline works without cache or watcher."""
    from agent_vault.config import Config, StorageConfig
    
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    
    mock_event_system = _create_mock_event_system()
    pipeline = IndexingPipeline(
        db_manager=mock_db_manager,
        config=config,
        project_id="test_project",
        event_system=mock_event_system,
    )
    
    assert pipeline.cache is None
    assert pipeline.watcher is None


def test_pipeline_with_cache(mock_db_manager, tmp_path, mock_cache):
    """Test that pipeline initializes with cache."""
    from agent_vault.config import Config, StorageConfig
    
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    
    mock_event_system = _create_mock_event_system()
    pipeline = IndexingPipeline(
        db_manager=mock_db_manager,
        config=config,
        project_id="test_project",
        event_system=mock_event_system,
        cache_name=mock_cache._test_cache_name
    )
    
    assert pipeline.cache is not None
    assert isinstance(pipeline.cache, MockCache)


def test_pipeline_with_watcher(mock_db_manager, tmp_path, mock_watcher):
    """Test that pipeline initializes with watcher."""
    from agent_vault.config import Config, StorageConfig

    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))

    mock_event_system = _create_mock_event_system()
    pipeline = IndexingPipeline(
        db_manager=mock_db_manager,
        config=config,
        project_id="test_project",
        event_system=mock_event_system,
        watcher_name=mock_watcher._test_watcher_name,
        auto_watch=True,
        project_root=str(tmp_path),
    )
    
    assert pipeline.watcher is not None
    assert isinstance(pipeline.watcher, MockWatcher)
    assert mock_watcher.is_running()
    assert len(mock_watcher.register_callback_calls) == 1
    assert len(mock_watcher.watch_directory_calls) == 1
    assert mock_watcher.watched_dirs[0] == str(tmp_path)


def test_pipeline_watcher_without_auto_watch(mock_db_manager, tmp_path, mock_watcher):
    """Test that watcher is not started if auto_watch is False."""
    from agent_vault.config import Config, StorageConfig
    
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    
    mock_event_system = _create_mock_event_system()
    pipeline = IndexingPipeline(
        db_manager=mock_db_manager,
        config=config,
        project_id="test_project",
        event_system=mock_event_system,
        watcher_name=mock_watcher._test_watcher_name,
        auto_watch=False
    )
    
    assert pipeline.watcher is None
    assert not mock_watcher.is_running()


@pytest.mark.asyncio
async def test_cache_document(mock_db_manager, tmp_path, mock_cache):
    """Test caching a parsed document."""
    from agent_vault.config import Config, StorageConfig
    
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    
    mock_event_system = _create_mock_event_system()
    pipeline = IndexingPipeline(
        db_manager=mock_db_manager,
        config=config,
        project_id="test_project",
        event_system=mock_event_system,
        cache_name=mock_cache._test_cache_name
    )
    
    # Create a test document
    doc = ParsedDocument(
        doc_id="test_doc",
        file_path="/test/file.py",
        chunks=[],
        metadata={}
    )
    
    # Cache the document
    await pipeline.cache_document(doc)
    
    assert len(mock_cache.put_calls) == 1
    assert mock_cache.put_calls[0][0] == "/test/file.py"
    assert mock_cache.put_calls[0][1] == doc


@pytest.mark.asyncio
async def test_get_cached_document(mock_db_manager, tmp_path, mock_cache):
    """Test retrieving a cached document."""
    from agent_vault.config import Config, StorageConfig
    
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    
    mock_event_system = _create_mock_event_system()
    pipeline = IndexingPipeline(
        db_manager=mock_db_manager,
        config=config,
        project_id="test_project",
        event_system=mock_event_system,
        cache_name=mock_cache._test_cache_name
    )
    
    # Create and cache a test document
    doc = ParsedDocument(
        doc_id="test_doc",
        file_path="/test/file.py",
        chunks=[],
        metadata={}
    )
    mock_cache._cache["/test/file.py"] = doc
    
    # Retrieve from cache
    cached_doc = await pipeline.get_cached_document("/test/file.py")
    
    assert cached_doc is not None
    assert cached_doc == doc
    assert len(mock_cache.get_calls) == 1


@pytest.mark.asyncio
async def test_invalidate_cache(mock_db_manager, tmp_path, mock_cache):
    """Test invalidating cache entry."""
    from agent_vault.config import Config, StorageConfig
    
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    
    mock_event_system = _create_mock_event_system()
    pipeline = IndexingPipeline(
        db_manager=mock_db_manager,
        config=config,
        project_id="test_project",
        event_system=mock_event_system,
        cache_name=mock_cache._test_cache_name
    )
    
    # Add something to cache
    doc = ParsedDocument(
        doc_id="test_doc",
        file_path="/test/file.py",
        chunks=[],
        metadata={}
    )
    mock_cache._cache["/test/file.py"] = doc
    
    # Invalidate
    await pipeline.invalidate_cache("/test/file.py")
    
    assert len(mock_cache.invalidate_calls) == 1
    assert "/test/file.py" not in mock_cache._cache


@pytest.mark.asyncio
async def test_file_change_callback_modified(mock_db_manager, tmp_path, mock_watcher, mock_cache):
    """Test file change callback for modified files."""
    from agent_vault.config import Config, StorageConfig
    
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    
    mock_event_system = _create_mock_event_system()
    IndexingPipeline(
        db_manager=mock_db_manager,
        config=config,
        project_id="test_project",
        event_system=mock_event_system,
        watcher_name=mock_watcher._test_watcher_name,
        cache_name=mock_cache._test_cache_name,
        auto_watch=True
    )
    
    # Add something to cache
    doc = ParsedDocument(
        doc_id="test_doc",
        file_path="/test/file.py",
        chunks=[],
        metadata={}
    )
    mock_cache._cache["/test/file.py"] = doc
    
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
async def test_file_change_callback_deleted(mock_db_manager, tmp_path, mock_watcher, mock_cache):
    """Test file change callback for deleted files."""
    from agent_vault.config import Config, StorageConfig
    
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    
    mock_event_system = _create_mock_event_system()
    IndexingPipeline(
        db_manager=mock_db_manager,
        config=config,
        project_id="test_project",
        event_system=mock_event_system,
        watcher_name=mock_watcher._test_watcher_name,
        cache_name=mock_cache._test_cache_name,
        auto_watch=True
    )
    
    # Add something to cache
    doc = ParsedDocument(
        doc_id="test_doc",
        file_path="/test/file.py",
        chunks=[],
        metadata={}
    )
    mock_cache._cache["/test/file.py"] = doc
    
    # Trigger a deleted event
    mock_watcher.trigger_event("/test/file.py", "deleted")
    
    # Wait for cache to be invalidated
    success = await AsyncTestHelper.wait_for_condition(
        lambda: len(mock_cache.invalidate_calls) == 1,
        timeout=1.0
    )
    
    # Cache should be invalidated
    assert success, "Cache was not invalidated within timeout"
    assert len(mock_cache.invalidate_calls) == 1
    assert "/test/file.py" not in mock_cache._cache


def test_stop_watching(mock_db_manager, tmp_path, mock_watcher):
    """Test stopping the file watcher."""
    from agent_vault.config import Config, StorageConfig
    
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
    
    # Stop watching
    pipeline.stop_watching()
    
    assert not mock_watcher.is_running()
    assert pipeline.watcher is None


def test_stop_watching_without_watcher(mock_db_manager, tmp_path):
    """Test that stop_watching is safe to call without a watcher."""
    from agent_vault.config import Config, StorageConfig
    
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    
    mock_event_system = _create_mock_event_system()
    pipeline = IndexingPipeline(
        db_manager=mock_db_manager,
        config=config,
        project_id="test_project",
        event_system=mock_event_system,
    )
    
    # Should not raise an error
    pipeline.stop_watching()
    assert pipeline.watcher is None


@pytest.mark.asyncio
async def test_process_document_caches_result(mock_db_manager, tmp_path, mock_cache):
    """Test that process_document caches the parsed document."""
    from agent_vault.config import Config, StorageConfig
    from agent_vault.embeddings.registry import EmbeddingRegistry
    from agent_vault.embeddings.hashing import HashingEmbedder
    
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    
    # Create a registry with a default embedder
    registry = EmbeddingRegistry()
    registry.configure_default_embedder(HashingEmbedder(), ndims=128)
    
    mock_event_system = _create_mock_event_system()
    pipeline = IndexingPipeline(
        db_manager=mock_db_manager,
        config=config,
        project_id="test_project",
        event_system=mock_event_system,
        cache_name=mock_cache._test_cache_name,
        registry=registry,
        project_root=str(tmp_path),
    )

    # Create a test document with a chunk
    doc = ParsedDocument(
        doc_id="test_doc",
        file_path=str(tmp_path / "test.py"),
        chunks=[
            ParserChunk(
                content="test content",
                fts_text="test content",
                content_type="CODE",
                language="python",
                symbols=[],
                relationships=[],
                metadata={},
                ranking_signals={}
            )
        ],
        metadata={}
    )
    
    # Process the document
    await pipeline.process_document(doc)
    
    # Document should be cached
    assert len(mock_cache.put_calls) == 1
    assert mock_cache.put_calls[0][0] == str(tmp_path / "test.py")


def test_invalid_cache_name(mock_db_manager, tmp_path):
    """Test that invalid cache name is handled gracefully."""
    from agent_vault.config import Config, StorageConfig
    
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    
    mock_event_system = _create_mock_event_system()
    pipeline = IndexingPipeline(
        db_manager=mock_db_manager,
        config=config,
        project_id="test_project",
        event_system=mock_event_system,
        cache_name="nonexistent_cache"
    )
    
    # Should not raise an error, cache should be None
    assert pipeline.cache is None


def test_invalid_watcher_name(mock_db_manager, tmp_path):
    """Test that invalid watcher name is handled gracefully."""
    from agent_vault.config import Config, StorageConfig
    
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path))
    
    mock_event_system = _create_mock_event_system()
    pipeline = IndexingPipeline(
        db_manager=mock_db_manager,
        config=config,
        project_id="test_project",
        event_system=mock_event_system,
        watcher_name="nonexistent_watcher",
        auto_watch=True
    )
    
    # Should not raise an error, watcher should be None
    assert pipeline.watcher is None
