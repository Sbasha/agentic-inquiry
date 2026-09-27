#!/usr/bin/env python3
"""Unit tests for DocumentCache.

Tests cache functionality including:
- Cache hit/miss behavior
- Invalidation on file changes
- LRU eviction
- Cache statistics
"""

import pytest

pytestmark = pytest.mark.unit

import time

from agentic_inquiry.cache import (
    DocumentCache,
    get_cache,
    register_cache,
    available_caches,
)
from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk


@pytest.fixture
async def cache():
    """Create a DocumentCache instance for testing."""
    cache = DocumentCache(max_size=3)
    # Load from disk if enabled
    if cache._disk_enabled:
        await cache._load_from_disk()
    return cache


@pytest.fixture
def sample_document():
    """Create a sample ParsedDocument for testing."""
    return ParsedDocument(
        doc_id="/test/file.py",
        file_path="/test/file.py",
        chunks=[ParserChunk(content="def hello():\n    print('Hello')")],
        metadata={"parser": "unified_code"},
    )


class TestDocumentCacheBasic:
    """Basic cache functionality tests."""

    @pytest.mark.smoke
    @pytest.mark.asyncio
    async def test_cache_initialization(self, cache):
        """Test that cache initializes correctly."""
        assert cache.max_size == 3
        assert cache.hits == 0
        assert cache.misses == 0
        assert len(cache._cache) == 0

    @pytest.mark.asyncio
    async def test_cache_put_and_get(self, cache, sample_document, tmp_path):
        """Test basic put and get operations."""
        # Create a test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        # Put document in cache
        await cache.put(str(test_file), sample_document)

        # Get document from cache
        result = await cache.get(str(test_file))

        assert result is not None
        assert result.doc_id == sample_document.doc_id
        assert cache.hits == 1
        assert cache.misses == 0

    @pytest.mark.asyncio
    async def test_cache_miss(self, cache, tmp_path):
        """Test cache miss behavior."""
        # Create a test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        # Try to get non-existent document
        result = await cache.get(str(test_file))

        assert result is None
        assert cache.hits == 0
        assert cache.misses == 1

    @pytest.mark.asyncio
    async def test_cache_invalidation(self, cache, sample_document, tmp_path):
        """Test cache invalidation."""
        # Create a test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        # Put document in cache
        await cache.put(str(test_file), sample_document)

        # Verify it's cached
        assert await cache.get(str(test_file)) is not None

        # Invalidate cache
        await cache.invalidate(str(test_file))

        # Should be cache miss now
        result = await cache.get(str(test_file))
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_clear(self, cache, sample_document, tmp_path):
        """Test clearing entire cache."""
        # Create test files
        test_file1 = tmp_path / "test1.py"
        test_file1.write_text("def hello(): pass")
        test_file2 = tmp_path / "test2.py"
        test_file2.write_text("def world(): pass")

        # Put documents in cache
        await cache.put(str(test_file1), sample_document)
        await cache.put(str(test_file2), sample_document)

        # Clear cache
        await cache.clear()

        # Cache should be empty
        assert len(cache._cache) == 0
        assert cache.hits == 0
        assert cache.misses == 0


class TestCacheInvalidation:
    """Tests for cache invalidation on file changes."""

    @pytest.mark.asyncio
    async def test_invalidation_on_file_modification(
        self, cache, sample_document, tmp_path
    ):
        """Test that cache is invalidated when file is modified."""
        # Create a test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        # Put document in cache
        await cache.put(str(test_file), sample_document)

        # Verify it's cached
        assert await cache.get(str(test_file)) is not None

        # Modify the file
        time.sleep(0.01)  # Ensure mtime changes
        test_file.write_text("def hello():\n    print('Modified')")

        # Cache should miss because file was modified
        result = await cache.get(str(test_file))
        assert result is None

    @pytest.mark.asyncio
    async def test_cache_hit_for_unchanged_file(self, cache, sample_document, tmp_path):
        """Test that cache hits for unchanged files."""
        # Create a test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        # Put document in cache
        await cache.put(str(test_file), sample_document)

        # Get multiple times - should all be hits
        for _ in range(3):
            result = await cache.get(str(test_file))
            assert result is not None

        assert cache.hits == 3
        assert cache.misses == 0


class TestLRUEviction:
    """Tests for LRU eviction when cache is full."""

    @pytest.mark.asyncio
    async def test_lru_eviction(self, cache, sample_document, tmp_path):
        """Test that oldest entry is evicted when cache is full."""
        # Create test files
        files = []
        for i in range(4):
            test_file = tmp_path / f"test{i}.py"
            test_file.write_text(f"def func{i}(): pass")
            files.append(test_file)

        # Fill cache (max_size=3)
        for i in range(3):
            await cache.put(str(files[i]), sample_document)

        # Cache should be full
        assert len(cache._cache) == 3

        # Add one more - should evict oldest
        await cache.put(str(files[3]), sample_document)

        # Cache should still have 3 entries
        assert len(cache._cache) == 3

        # First file should be evicted
        result = await cache.get(str(files[0]))
        assert result is None

        # Other files should still be cached
        for i in range(1, 4):
            result = await cache.get(str(files[i]))
            assert result is not None


class TestCacheStatistics:
    """Tests for cache statistics."""

    @pytest.mark.asyncio
    async def test_cache_stats(self, cache, sample_document, tmp_path):
        """Test cache statistics tracking."""
        # Create test files
        test_file1 = tmp_path / "test1.py"
        test_file1.write_text("def hello(): pass")
        test_file2 = tmp_path / "test2.py"
        test_file2.write_text("def world(): pass")

        # Put one document
        await cache.put(str(test_file1), sample_document)

        # Get cached document (hit)
        await cache.get(str(test_file1))

        # Get non-cached document (miss)
        await cache.get(str(test_file2))

        # Check stats
        stats = cache.stats()
        assert stats["size"] == 1
        assert stats["max_size"] == 3
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_cache_stats_after_clear(self, cache, sample_document, tmp_path):
        """Test that stats are reset after clear."""
        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        # Put and get to generate stats
        await cache.put(str(test_file), sample_document)
        await cache.get(str(test_file))

        # Clear cache
        await cache.clear()

        # Stats should be reset
        stats = cache.stats()
        assert stats["size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0


class TestCacheRegistry:
    """Tests for cache registry functionality."""

    def test_register_and_get_cache(self):
        """Test registering and retrieving a cache."""
        cache = DocumentCache(max_size=10)
        register_cache("test_cache", cache)

        try:
            retrieved = get_cache("test_cache")
            assert retrieved is cache
        finally:
            # Cleanup
            from agentic_inquiry.cache import _cache_registry

            _cache_registry.unregister("test_cache")

    def test_get_default_cache(self):
        """Test getting the default cache."""
        cache = get_cache()
        assert cache is not None

    def test_available_caches(self):
        """Test listing available caches."""
        caches = available_caches()
        assert isinstance(caches, list)
        assert "default" in caches

    def test_import_has_no_side_effects(self):
        """``import agentic_inquiry.cache`` must not trigger Config.load() or
        construct DocumentCache eagerly. Default cache registration is
        deferred to first ``get_cache()`` / ``available_caches()`` call.

        Regression for PR #170 review (Copilot, 2026-04-28): an earlier
        revision registered DocumentCache() at module import time, which
        called Config.load() and could touch disk for cache persistence.

        Runs in a subprocess so popping/re-importing the module cannot
        contaminate other tests in this suite that hold module-level
        references to agentic_inquiry.cache.
        """
        import subprocess
        import sys
        import textwrap

        probe = textwrap.dedent(
            """
            import sys
            calls = []

            # Patch Config.load BEFORE importing agentic_inquiry.cache
            import agentic_inquiry.config as cfg
            original = cfg.Config.load

            def spy(*args, **kwargs):
                calls.append(True)
                return original(*args, **kwargs)

            cfg.Config.load = classmethod(lambda cls, *a, **kw: spy(*a, **kw))

            import agentic_inquiry.cache  # noqa: F401

            print(f"LOAD_COUNT={len(calls)}")
            sys.exit(0 if len(calls) == 0 else 1)
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            "importing agentic_inquiry.cache had side effects:\n"
            f"  stdout: {result.stdout}\n"
            f"  stderr: {result.stderr}"
        )
        assert "LOAD_COUNT=0" in result.stdout


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_get_nonexistent_file(self, cache):
        """Test getting cache for non-existent file."""
        result = await cache.get("/nonexistent/file.py")
        assert result is None

    @pytest.mark.asyncio
    async def test_put_nonexistent_file(self, cache, sample_document):
        """Test putting cache for non-existent file."""
        # Should not crash, but may not cache
        await cache.put("/nonexistent/file.py", sample_document)

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent_file(self, cache):
        """Test invalidating non-existent file."""
        # Should not crash
        await cache.invalidate("/nonexistent/file.py")


class TestDiskPersistence:
    """Tests for disk persistence functionality."""

    @pytest.fixture
    def disk_cache_config(self, tmp_path):
        """Create a config with disk persistence enabled."""
        from agentic_inquiry.config import (
            Config,
            StorageConfig,
            DocumentCacheStorageConfig,
            CacheConfig,
            DocumentCacheConfig,
        )

        storage_config = StorageConfig(
            root=str(tmp_path / "storage"),
            default_project_id="test_project",
            document_cache=DocumentCacheStorageConfig(
                enabled=True, path="document_cache"
            ),
        )

        cache_config = CacheConfig(document_cache=DocumentCacheConfig(max_size=10))

        # Create a minimal config
        config = Config(storage=storage_config, cache=cache_config)

        return config

    @pytest.fixture
    async def disk_cache(self, disk_cache_config):
        """Create a DocumentCache with disk persistence enabled."""
        cache = await DocumentCache.from_config(
            disk_cache_config, project_id="test_project"
        )
        return cache

    @pytest.mark.asyncio
    async def test_disk_persistence_initialization(self, disk_cache, disk_cache_config):
        """Test that disk persistence initializes correctly."""
        assert disk_cache._disk_enabled is True
        cache_path = disk_cache_config.storage.get_document_cache_path()
        assert disk_cache._cache_dir == cache_path
        assert disk_cache._entries_dir.exists()
        assert disk_cache._cache_dir.exists()

    @pytest.mark.asyncio
    async def test_save_and_load_from_disk(
        self, disk_cache, disk_cache_config, sample_document, tmp_path
    ):
        """Test saving cache entries to disk and loading them back."""
        # Create a test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        # Put document in cache (should save to disk)
        await disk_cache.put(str(test_file), sample_document)

        # Verify it's in memory cache
        assert await disk_cache.get(str(test_file)) is not None

        # Create a new cache instance (should load from disk)
        new_cache = await DocumentCache.from_config(
            disk_cache_config, project_id="test_project"
        )

        # Should load the cached document from disk
        result = await new_cache.get(str(test_file))
        assert result is not None
        assert result.doc_id == sample_document.doc_id

    @pytest.mark.asyncio
    async def test_project_id_isolation(self, tmp_path, sample_document):
        """Test that cache keys are isolated by project_id."""
        from agentic_inquiry.config import (
            Config,
            StorageConfig,
            DocumentCacheStorageConfig,
            CacheConfig,
            DocumentCacheConfig,
        )

        # Create config with shared storage root
        storage_root = tmp_path / "storage"

        config = Config(
            storage=StorageConfig(
                root=str(storage_root),
                document_cache=DocumentCacheStorageConfig(
                    enabled=True, path="document_cache"
                ),
            ),
            cache=CacheConfig(document_cache=DocumentCacheConfig(max_size=10)),
        )

        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        # Cache with project1
        cache1 = await DocumentCache.from_config(config, project_id="project1")
        await cache1.put(str(test_file), sample_document)

        # Cache with project2 should not see project1's data
        cache2 = await DocumentCache.from_config(config, project_id="project2")
        result = await cache2.get(str(test_file))
        assert result is None

        # But project1 should still see its data
        assert await cache1.get(str(test_file)) is not None

    @pytest.mark.asyncio
    async def test_disk_persistence_error_fallback(self, tmp_path, sample_document):
        """Test that cache falls back to memory-only mode on disk errors."""
        from agentic_inquiry.config import (
            Config,
            StorageConfig,
            DocumentCacheStorageConfig,
            CacheConfig,
            DocumentCacheConfig,
        )

        # Create config with invalid path (to trigger error)
        config = Config(
            storage=StorageConfig(
                root="/invalid/nonexistent/path",
                document_cache=DocumentCacheStorageConfig(
                    enabled=True, path="document_cache"
                ),
            ),
            cache=CacheConfig(document_cache=DocumentCacheConfig(max_size=10)),
        )

        # Should not crash, but fall back to memory-only mode
        cache = DocumentCache(config, project_id="test_project")
        assert cache._disk_enabled is False

        # Should still work in memory-only mode
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")
        await cache.put(str(test_file), sample_document)
        assert await cache.get(str(test_file)) is not None

    @pytest.mark.asyncio
    async def test_cache_index_updates(self, disk_cache, sample_document, tmp_path):
        """Test that cache index is updated correctly."""
        # Create test files
        test_file1 = tmp_path / "test1.py"
        test_file1.write_text("def hello(): pass")
        test_file2 = tmp_path / "test2.py"
        test_file2.write_text("def world(): pass")

        # Put documents in cache
        await disk_cache.put(str(test_file1), sample_document)
        await disk_cache.put(str(test_file2), sample_document)

        # Check that index file exists and contains entries
        assert disk_cache._index_file.exists()

        import json

        with open(disk_cache._index_file, "r") as f:
            index = json.load(f)

        # Should have 2 entries for test_project
        project_entries = [k for k in index.keys() if k.startswith("test_project:")]
        assert len(project_entries) == 2

    @pytest.mark.asyncio
    async def test_memory_only_mode(self, tmp_path, sample_document):
        """Test that memory-only mode works when disk persistence is disabled."""
        from agentic_inquiry.config import (
            Config,
            StorageConfig,
            DocumentCacheStorageConfig,
            CacheConfig,
            DocumentCacheConfig,
        )

        config = Config(
            storage=StorageConfig(
                root=str(tmp_path / "storage"),
                document_cache=DocumentCacheStorageConfig(
                    enabled=False, path="document_cache"
                ),
            ),
            cache=CacheConfig(document_cache=DocumentCacheConfig(max_size=10)),
        )

        cache = DocumentCache(config, project_id="test_project")
        assert cache._disk_enabled is False

        # Create test file
        test_file = tmp_path / "test.py"
        test_file.write_text("def hello(): pass")

        # Put and get should work in memory
        await cache.put(str(test_file), sample_document)
        assert await cache.get(str(test_file)) is not None

        # But should not persist to disk
        new_cache = DocumentCache(config, project_id="test_project")
        assert await new_cache.get(str(test_file)) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
