# tests/connectors/test_hash_cache.py
"""Tests for BoundedHashCache implementation."""

import pytest

pytestmark = pytest.mark.unit
from typing import Set

from agentic_inquiry.connectors.hash_cache import BoundedHashCache, HashCacheStats
from agentic_inquiry.connectors.base import InMemoryFileTracker


class TestHashCacheStats:
    """Tests for HashCacheStats dataclass."""

    def test_default_values(self):
        """Test default values are all zero/false."""
        stats = HashCacheStats()
        assert stats.cache_hits == 0
        assert stats.cache_misses == 0
        assert stats.tracker_hits == 0
        assert stats.tracker_misses == 0
        assert stats.current_count == 0
        assert stats.max_size == 0
        assert stats.has_tracker is False

    def test_total_hits(self):
        """Test total_hits computed property."""
        stats = HashCacheStats(cache_hits=10, tracker_hits=5)
        assert stats.total_hits == 15

    def test_total_lookups(self):
        """Test total_lookups computed property."""
        stats = HashCacheStats(cache_hits=10, cache_misses=5)
        assert stats.total_lookups == 15

    def test_hit_rate_with_lookups(self):
        """Test hit_rate computation."""
        stats = HashCacheStats(cache_hits=8, cache_misses=2, tracker_hits=1)
        # Total hits = 9, total lookups = 10
        assert stats.hit_rate == 0.9

    def test_hit_rate_zero_lookups(self):
        """Test hit_rate returns 0.0 when no lookups."""
        stats = HashCacheStats()
        assert stats.hit_rate == 0.0

    def test_cache_hit_rate(self):
        """Test cache-only hit rate."""
        stats = HashCacheStats(cache_hits=6, cache_misses=4)
        assert stats.cache_hit_rate == 0.6

    def test_to_dict(self):
        """Test serialization to dictionary."""
        stats = HashCacheStats(
            cache_hits=10,
            cache_misses=5,
            tracker_hits=3,
            tracker_misses=2,
            current_count=100,
            max_size=1000,
            has_tracker=True,
        )
        d = stats.to_dict()
        assert d["cache_hits"] == 10
        assert d["cache_misses"] == 5
        assert d["tracker_hits"] == 3
        assert d["tracker_misses"] == 2
        assert d["current_count"] == 100
        assert d["max_size"] == 1000
        assert d["has_tracker"] is True
        assert "hit_rate" in d
        assert "cache_hit_rate" in d


class TestBoundedHashCacheBasic:
    """Basic tests for BoundedHashCache without tracker."""

    @pytest.fixture
    def cache(self) -> BoundedHashCache:
        """Create a cache without tracker."""
        return BoundedHashCache(max_size=100)

    def test_initialization(self, cache: BoundedHashCache):
        """Test cache initialization."""
        assert cache.max_size == 100
        assert cache.has_tracker is False

    @pytest.mark.asyncio
    async def test_is_processed_returns_false_initially(self, cache: BoundedHashCache):
        """Test that new files are not processed."""
        result = await cache.is_processed("/path/file.py", "hash123")
        assert result is False

    @pytest.mark.asyncio
    async def test_mark_processed_then_is_processed(self, cache: BoundedHashCache):
        """Test mark and check workflow."""
        file_path = "/path/file.py"
        file_hash = "abc123def456"

        # Initially not processed
        assert await cache.is_processed(file_path, file_hash) is False

        # Mark as processed
        await cache.mark_processed(file_path, file_hash)

        # Now should be processed
        assert await cache.is_processed(file_path, file_hash) is True

    @pytest.mark.asyncio
    async def test_different_hash_not_processed(self, cache: BoundedHashCache):
        """Test that different hash for same path returns False."""
        file_path = "/path/file.py"

        await cache.mark_processed(file_path, "hash_v1")

        # Different hash should not be processed
        assert await cache.is_processed(file_path, "hash_v2") is False

    @pytest.mark.asyncio
    async def test_updated_hash(self, cache: BoundedHashCache):
        """Test updating hash for same path."""
        file_path = "/path/file.py"

        await cache.mark_processed(file_path, "hash_v1")
        assert await cache.is_processed(file_path, "hash_v1") is True

        # Update with new hash
        await cache.mark_processed(file_path, "hash_v2")

        # Old hash no longer matches
        assert await cache.is_processed(file_path, "hash_v1") is False
        # New hash matches
        assert await cache.is_processed(file_path, "hash_v2") is True

    @pytest.mark.asyncio
    async def test_invalidate(self, cache: BoundedHashCache):
        """Test invalidating a cache entry."""
        file_path = "/path/file.py"
        file_hash = "abc123"

        await cache.mark_processed(file_path, file_hash)
        assert await cache.is_processed(file_path, file_hash) is True

        # Invalidate
        removed = await cache.invalidate(file_path)
        assert removed is True

        # No longer processed
        assert await cache.is_processed(file_path, file_hash) is False

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent(self, cache: BoundedHashCache):
        """Test invalidating nonexistent entry returns False."""
        removed = await cache.invalidate("/nonexistent/path.py")
        assert removed is False

    @pytest.mark.asyncio
    async def test_clear(self, cache: BoundedHashCache):
        """Test clearing the cache."""
        await cache.mark_processed("/file1.py", "hash1")
        await cache.mark_processed("/file2.py", "hash2")
        await cache.mark_processed("/file3.py", "hash3")

        cleared = await cache.clear()
        assert cleared == 3

        # All entries gone
        assert await cache.is_processed("/file1.py", "hash1") is False
        assert await cache.is_processed("/file2.py", "hash2") is False
        assert await cache.is_processed("/file3.py", "hash3") is False

    @pytest.mark.asyncio
    async def test_get_processed_count_without_tracker(self, cache: BoundedHashCache):
        """Test get_processed_count without tracker."""
        assert await cache.get_processed_count() == 0

        await cache.mark_processed("/file1.py", "hash1")
        await cache.mark_processed("/file2.py", "hash2")

        assert await cache.get_processed_count() == 2


class TestBoundedHashCacheWithTracker:
    """Tests for BoundedHashCache with FileTrackerProtocol fallback."""

    @pytest.fixture
    def tracker(self) -> InMemoryFileTracker:
        """Create an in-memory tracker."""
        return InMemoryFileTracker()

    @pytest.fixture
    def cache(self, tracker: InMemoryFileTracker) -> BoundedHashCache:
        """Create a cache with tracker."""
        return BoundedHashCache(max_size=100, file_tracker=tracker)

    def test_has_tracker(self, cache: BoundedHashCache):
        """Test that cache reports having tracker."""
        assert cache.has_tracker is True

    @pytest.mark.asyncio
    async def test_mark_processed_updates_tracker(
        self, cache: BoundedHashCache, tracker: InMemoryFileTracker
    ):
        """Test that mark_processed updates the tracker."""
        file_path = "/path/file.py"
        file_hash = "abc123"

        await cache.mark_processed(file_path, file_hash)

        # Tracker should have the hash
        assert await tracker.is_processed(file_hash) is True

    @pytest.mark.asyncio
    async def test_fallback_to_tracker(
        self, cache: BoundedHashCache, tracker: InMemoryFileTracker
    ):
        """Test fallback to tracker when not in cache."""
        file_hash = "abc123"

        # Add to tracker directly (not in cache)
        await tracker.mark_processed(file_hash)

        # Cache should fall back to tracker
        result = await cache.is_processed("/path/file.py", file_hash)
        assert result is True

    @pytest.mark.asyncio
    async def test_cache_warm_on_tracker_hit(
        self, cache: BoundedHashCache, tracker: InMemoryFileTracker
    ):
        """Test that cache is warmed when tracker returns hit."""
        file_path = "/path/file.py"
        file_hash = "abc123"

        # Add to tracker directly
        await tracker.mark_processed(file_hash)

        # First check - falls back to tracker
        assert await cache.is_processed(file_path, file_hash) is True

        # Get stats - should show tracker hit
        stats = cache.get_stats()
        assert stats.tracker_hits == 1

        # Second check - should hit cache (warmed from first check)
        assert await cache.is_processed(file_path, file_hash) is True
        stats = cache.get_stats()
        # Now should have cache hit
        assert stats.cache_hits == 1

    @pytest.mark.asyncio
    async def test_tracker_not_cleared_on_cache_clear(
        self, cache: BoundedHashCache, tracker: InMemoryFileTracker
    ):
        """Test that cache.clear() doesn't clear tracker."""
        file_hash = "abc123"
        await cache.mark_processed("/file.py", file_hash)

        # Clear cache
        await cache.clear()

        # Tracker should still have the hash
        assert await tracker.is_processed(file_hash) is True

    @pytest.mark.asyncio
    async def test_clear_all(
        self, cache: BoundedHashCache, tracker: InMemoryFileTracker
    ):
        """Test clear_all clears both cache and tracker."""
        await cache.mark_processed("/file1.py", "hash1")
        await cache.mark_processed("/file2.py", "hash2")

        cache_cleared, tracker_cleared = await cache.clear_all()

        assert cache_cleared == 2
        assert tracker_cleared == 2
        assert await tracker.get_processed_count() == 0

    @pytest.mark.asyncio
    async def test_get_processed_count_uses_tracker(
        self, cache: BoundedHashCache, tracker: InMemoryFileTracker
    ):
        """Test get_processed_count returns tracker count."""
        # Add directly to tracker (3 unique hashes)
        await tracker.mark_processed("hash1")
        await tracker.mark_processed("hash2")
        await tracker.mark_processed("hash3")

        # Add to cache (which also adds to tracker)
        await cache.mark_processed("/file.py", "hash4")

        # Should return tracker count
        count = await cache.get_processed_count()
        assert count == 4


class TestBoundedHashCacheLRUEviction:
    """Tests for LRU eviction behavior."""

    @pytest.mark.asyncio
    async def test_eviction_on_max_size(self):
        """Test that entries are evicted when max_size exceeded."""
        cache = BoundedHashCache(max_size=3)

        # Add 3 entries
        await cache.mark_processed("/file1.py", "hash1")
        await cache.mark_processed("/file2.py", "hash2")
        await cache.mark_processed("/file3.py", "hash3")

        # All should be present
        assert await cache.is_processed("/file1.py", "hash1") is True
        assert await cache.is_processed("/file2.py", "hash2") is True
        assert await cache.is_processed("/file3.py", "hash3") is True

        # Add 4th entry - should evict file1 (LRU)
        await cache.mark_processed("/file4.py", "hash4")

        # file1 should be evicted
        assert await cache.is_processed("/file1.py", "hash1") is False
        # Others should still be present
        assert await cache.is_processed("/file4.py", "hash4") is True

    @pytest.mark.asyncio
    async def test_access_updates_recency(self):
        """Test that accessing an entry updates its recency."""
        cache = BoundedHashCache(max_size=3)

        # Add 3 entries
        await cache.mark_processed("/file1.py", "hash1")
        await cache.mark_processed("/file2.py", "hash2")
        await cache.mark_processed("/file3.py", "hash3")

        # Access file1 (makes it most recently used)
        await cache.is_processed("/file1.py", "hash1")

        # Add new entry - should evict file2 (now LRU)
        await cache.mark_processed("/file4.py", "hash4")

        # file1 should still be present (accessed recently)
        assert await cache.is_processed("/file1.py", "hash1") is True
        # file2 should be evicted (was LRU)
        assert await cache.is_processed("/file2.py", "hash2") is False


class TestBoundedHashCacheStats:
    """Tests for statistics tracking."""

    @pytest.mark.asyncio
    async def test_stats_initial(self):
        """Test initial stats are zero."""
        cache = BoundedHashCache(max_size=100)
        stats = cache.get_stats()

        assert stats.cache_hits == 0
        assert stats.cache_misses == 0
        assert stats.tracker_hits == 0
        assert stats.tracker_misses == 0
        assert stats.current_count == 0
        assert stats.max_size == 100
        assert stats.has_tracker is False

    @pytest.mark.asyncio
    async def test_stats_cache_hits_and_misses(self):
        """Test cache hit/miss tracking."""
        cache = BoundedHashCache(max_size=100)

        # Miss
        await cache.is_processed("/file.py", "hash1")

        stats = cache.get_stats()
        assert stats.cache_misses == 1
        assert stats.cache_hits == 0

        # Add entry
        await cache.mark_processed("/file.py", "hash1")

        # Hit
        await cache.is_processed("/file.py", "hash1")

        stats = cache.get_stats()
        assert stats.cache_hits == 1
        assert stats.cache_misses == 1

    @pytest.mark.asyncio
    async def test_stats_tracker_hits_and_misses(self):
        """Test tracker hit/miss tracking."""
        tracker = InMemoryFileTracker()
        cache = BoundedHashCache(max_size=100, file_tracker=tracker)

        # Add to tracker directly
        await tracker.mark_processed("hash_in_tracker")

        # Check for hash in tracker (tracker hit)
        await cache.is_processed("/file1.py", "hash_in_tracker")

        # Check for hash not in tracker (tracker miss)
        await cache.is_processed("/file2.py", "hash_not_in_tracker")

        stats = cache.get_stats()
        assert stats.tracker_hits == 1
        assert stats.tracker_misses == 1

    @pytest.mark.asyncio
    async def test_stats_current_count(self):
        """Test current_count reflects cache size."""
        cache = BoundedHashCache(max_size=100)

        await cache.mark_processed("/file1.py", "hash1")
        await cache.mark_processed("/file2.py", "hash2")

        stats = cache.get_stats()
        assert stats.current_count == 2


class TestCustomFileTrackerCompliance:
    """Tests to verify BoundedHashCache works with custom trackers."""

    @pytest.mark.asyncio
    async def test_with_custom_tracker(self):
        """Test that custom FileTrackerProtocol works with BoundedHashCache."""

        class CustomTracker:
            """Custom tracker implementation."""

            def __init__(self):
                self._hashes: Set[str] = set()

            async def is_processed(self, file_hash: str) -> bool:
                return file_hash in self._hashes

            async def mark_processed(self, file_hash: str) -> None:
                self._hashes.add(file_hash)

            async def get_processed_count(self) -> int:
                return len(self._hashes)

            async def clear(self) -> int:
                count = len(self._hashes)
                self._hashes.clear()
                return count

        tracker = CustomTracker()
        cache = BoundedHashCache(max_size=100, file_tracker=tracker)

        # Mark via cache
        await cache.mark_processed("/file.py", "custom_hash")

        # Verify tracker has it
        assert await tracker.is_processed("custom_hash") is True

        # Verify cache can find it via fallback
        await cache.clear()  # Clear cache
        assert await cache.is_processed("/file.py", "custom_hash") is True
