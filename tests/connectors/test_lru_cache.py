"""Tests for LRU cache implementation (S5-005).

Tests cover:
- LRUCache: Generic LRU cache operations
- FileCacheTracker: File-based cache tracking
- CacheStats: Statistics collection
- Eviction behavior with max_size
- Thread safety with asyncio.Lock
"""
from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.unit

from agent_vault.connectors.lru_cache import (
    CacheStats,
    FileCacheTracker,
    LRUCache,
)


class TestCacheStats:
    """Tests for CacheStats dataclass."""

    def test_hit_rate_with_no_requests(self) -> None:
        """Hit rate is 0.0 when no requests made."""
        stats = CacheStats()
        assert stats.hit_rate == 0.0

    def test_hit_rate_all_hits(self) -> None:
        """Hit rate is 1.0 when all requests are hits."""
        stats = CacheStats(hits=10, misses=0)
        assert stats.hit_rate == 1.0

    def test_hit_rate_all_misses(self) -> None:
        """Hit rate is 0.0 when all requests are misses."""
        stats = CacheStats(hits=0, misses=10)
        assert stats.hit_rate == 0.0

    def test_hit_rate_mixed(self) -> None:
        """Hit rate calculated correctly for mixed hits/misses."""
        stats = CacheStats(hits=7, misses=3)
        assert stats.hit_rate == 0.7

    def test_to_dict(self) -> None:
        """Stats can be serialized to dict."""
        stats = CacheStats(
            hits=5,
            misses=5,
            evictions=2,
            current_size=1000,
            current_count=3,
            max_size=2000,
        )
        d = stats.to_dict()
        assert d["hits"] == 5
        assert d["misses"] == 5
        assert d["evictions"] == 2
        assert d["current_size"] == 1000
        assert d["current_count"] == 3
        assert d["max_size"] == 2000
        assert d["hit_rate"] == 0.5


class TestLRUCache:
    """Tests for generic LRUCache."""

    @pytest.mark.asyncio
    async def test_put_and_get(self) -> None:
        """Basic put and get operations."""
        cache: LRUCache[str, bytes] = LRUCache(max_size=1000)

        await cache.put("key1", b"value1", size=10)
        result = await cache.get("key1")

        assert result == b"value1"

    @pytest.mark.asyncio
    async def test_get_missing_key_returns_none(self) -> None:
        """Get returns None for missing keys."""
        cache: LRUCache[str, bytes] = LRUCache(max_size=1000)

        result = await cache.get("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_contains(self) -> None:
        """Contains checks key existence."""
        cache: LRUCache[str, bytes] = LRUCache(max_size=1000)

        await cache.put("key1", b"value1", size=10)

        assert await cache.contains("key1") is True
        assert await cache.contains("key2") is False

    @pytest.mark.asyncio
    async def test_remove(self) -> None:
        """Remove deletes an entry."""
        cache: LRUCache[str, bytes] = LRUCache(max_size=1000)

        await cache.put("key1", b"value1", size=10)
        removed = await cache.remove("key1")

        assert removed is True
        assert await cache.get("key1") is None

    @pytest.mark.asyncio
    async def test_remove_missing_returns_false(self) -> None:
        """Remove returns False for missing key."""
        cache: LRUCache[str, bytes] = LRUCache(max_size=1000)

        removed = await cache.remove("nonexistent")

        assert removed is False

    @pytest.mark.asyncio
    async def test_clear(self) -> None:
        """Clear removes all entries."""
        cache: LRUCache[str, bytes] = LRUCache(max_size=1000)

        await cache.put("key1", b"a", size=1)
        await cache.put("key2", b"b", size=1)
        await cache.put("key3", b"c", size=1)

        count = await cache.clear()

        assert count == 3
        assert await cache.get("key1") is None
        assert await cache.get("key2") is None
        assert await cache.get("key3") is None

    @pytest.mark.asyncio
    async def test_stats_tracking(self) -> None:
        """Stats track hits and misses."""
        cache: LRUCache[str, bytes] = LRUCache(max_size=1000)

        await cache.put("key1", b"value1", size=10)
        await cache.get("key1")  # hit
        await cache.get("key1")  # hit
        await cache.get("missing")  # miss

        stats = cache.get_stats()
        assert stats.hits == 2
        assert stats.misses == 1
        assert stats.hit_rate == pytest.approx(2 / 3)

    @pytest.mark.asyncio
    async def test_unlimited_cache(self) -> None:
        """max_size=0 means unlimited (no eviction)."""
        cache: LRUCache[str, bytes] = LRUCache(max_size=0)

        # Add many large items
        for i in range(100):
            await cache.put(f"key{i}", b"x" * 1000, size=1000)

        # All items should still be there
        for i in range(100):
            assert await cache.get(f"key{i}") == b"x" * 1000


class TestLRUCacheEviction:
    """Tests for LRU eviction behavior."""

    @pytest.mark.asyncio
    async def test_evicts_when_full(self) -> None:
        """Evicts oldest entry when cache is full."""
        cache: LRUCache[str, bytes] = LRUCache(max_size=100)

        # Fill cache
        await cache.put("key1", b"a" * 40, size=40)
        await cache.put("key2", b"b" * 40, size=40)

        # This should evict key1
        await cache.put("key3", b"c" * 40, size=40)

        assert await cache.get("key1") is None  # evicted
        assert await cache.get("key2") == b"b" * 40
        assert await cache.get("key3") == b"c" * 40

    @pytest.mark.asyncio
    async def test_evicts_multiple_if_needed(self) -> None:
        """Evicts multiple entries if needed."""
        cache: LRUCache[str, bytes] = LRUCache(max_size=100)

        # Add small items
        await cache.put("key1", b"a" * 30, size=30)
        await cache.put("key2", b"b" * 30, size=30)
        await cache.put("key3", b"c" * 30, size=30)

        # This large item should evict all three
        await cache.put("key4", b"d" * 90, size=90)

        assert await cache.get("key1") is None
        assert await cache.get("key2") is None
        assert await cache.get("key3") is None
        assert await cache.get("key4") == b"d" * 90

    @pytest.mark.asyncio
    async def test_lru_order_maintained(self) -> None:
        """Recently accessed items survive eviction."""
        cache: LRUCache[str, bytes] = LRUCache(max_size=100)

        # Add items
        await cache.put("key1", b"a" * 30, size=30)
        await cache.put("key2", b"b" * 30, size=30)
        await cache.put("key3", b"c" * 30, size=30)

        # Access key1 to make it recently used
        await cache.get("key1")

        # This should evict key2 (oldest accessed), not key1
        await cache.put("key4", b"d" * 30, size=30)

        assert await cache.get("key1") == b"a" * 30  # preserved (recently accessed)
        assert await cache.get("key2") is None  # evicted (oldest)
        assert await cache.get("key3") == b"c" * 30
        assert await cache.get("key4") == b"d" * 30

    @pytest.mark.asyncio
    async def test_eviction_stats(self) -> None:
        """Eviction count tracked in stats."""
        cache: LRUCache[str, bytes] = LRUCache(max_size=100)

        await cache.put("key1", b"a" * 50, size=50)
        await cache.put("key2", b"b" * 50, size=50)
        await cache.put("key3", b"c" * 50, size=50)  # evicts key1

        stats = cache.get_stats()
        assert stats.evictions == 1
        assert stats.current_count == 2
        assert stats.current_size == 100

    @pytest.mark.asyncio
    async def test_oversized_entry_not_cached(self) -> None:
        """Entry larger than max_size is not cached."""
        cache: LRUCache[str, bytes] = LRUCache(max_size=100)

        await cache.put("big", b"x" * 200, size=200)

        assert await cache.get("big") is None

    @pytest.mark.asyncio
    async def test_update_existing_key(self) -> None:
        """Updating existing key adjusts size correctly."""
        cache: LRUCache[str, bytes] = LRUCache(max_size=100)

        await cache.put("key1", b"a" * 50, size=50)
        stats_before = cache.get_stats()

        # Update with smaller value
        await cache.put("key1", b"b" * 20, size=20)
        stats_after = cache.get_stats()

        assert stats_before.current_size == 50
        assert stats_after.current_size == 20
        assert await cache.get("key1") == b"b" * 20


class TestFileCacheTracker:
    """Tests for FileCacheTracker."""

    @pytest.mark.asyncio
    async def test_track_and_access(self) -> None:
        """Track files and record access."""
        tracker = FileCacheTracker(max_size=1000)

        evicted = await tracker.track("/cache/file1.bin", size=100)
        assert evicted == []

        hit = await tracker.access("/cache/file1.bin")
        assert hit is True

        miss = await tracker.access("/cache/nonexistent.bin")
        assert miss is False

    @pytest.mark.asyncio
    async def test_eviction_returns_paths(self) -> None:
        """Track returns list of evicted paths."""
        tracker = FileCacheTracker(max_size=100)

        await tracker.track("/cache/file1.bin", size=50)
        await tracker.track("/cache/file2.bin", size=50)

        # This should evict file1
        evicted = await tracker.track("/cache/file3.bin", size=50)

        assert evicted == ["/cache/file1.bin"]

    @pytest.mark.asyncio
    async def test_lru_eviction_order(self) -> None:
        """Recently accessed files preserved during eviction."""
        tracker = FileCacheTracker(max_size=100)

        await tracker.track("/cache/file1.bin", size=30)
        await tracker.track("/cache/file2.bin", size=30)
        await tracker.track("/cache/file3.bin", size=30)

        # Access file1 to make it recent
        await tracker.access("/cache/file1.bin")

        # This should evict file2 (oldest accessed)
        evicted = await tracker.track("/cache/file4.bin", size=30)

        assert evicted == ["/cache/file2.bin"]

    @pytest.mark.asyncio
    async def test_remove(self) -> None:
        """Remove stops tracking a file."""
        tracker = FileCacheTracker(max_size=1000)

        await tracker.track("/cache/file1.bin", size=100)
        removed = await tracker.remove("/cache/file1.bin")

        assert removed is True
        assert await tracker.access("/cache/file1.bin") is False

    @pytest.mark.asyncio
    async def test_clear(self) -> None:
        """Clear returns all tracked paths."""
        tracker = FileCacheTracker(max_size=1000)

        await tracker.track("/cache/file1.bin", size=100)
        await tracker.track("/cache/file2.bin", size=100)
        await tracker.track("/cache/file3.bin", size=100)

        paths = await tracker.clear()

        assert len(paths) == 3
        assert "/cache/file1.bin" in paths
        assert "/cache/file2.bin" in paths
        assert "/cache/file3.bin" in paths

    @pytest.mark.asyncio
    async def test_stats(self) -> None:
        """Stats track hits, misses, and evictions."""
        tracker = FileCacheTracker(max_size=100)

        await tracker.track("/cache/file1.bin", size=50)
        await tracker.track("/cache/file2.bin", size=50)

        await tracker.access("/cache/file1.bin")  # hit
        await tracker.access("/cache/missing.bin")  # miss

        # Evict file1
        await tracker.track("/cache/file3.bin", size=50)

        stats = tracker.get_stats()
        assert stats.hits == 1
        assert stats.misses == 1
        assert stats.evictions == 1
        assert stats.current_count == 2
        assert stats.current_size == 100


class TestConcurrency:
    """Tests for thread safety."""

    @pytest.mark.asyncio
    async def test_concurrent_puts(self) -> None:
        """Concurrent puts don't corrupt state."""
        cache: LRUCache[str, bytes] = LRUCache(max_size=10000)

        async def put_items(start: int, count: int) -> None:
            for i in range(start, start + count):
                await cache.put(f"key{i}", b"x", size=1)

        # Run concurrent puts
        await asyncio.gather(
            put_items(0, 100),
            put_items(100, 100),
            put_items(200, 100),
        )

        # All items should be accessible
        for i in range(300):
            assert await cache.get(f"key{i}") == b"x"

    @pytest.mark.asyncio
    async def test_concurrent_get_and_put(self) -> None:
        """Concurrent gets and puts work correctly."""
        cache: LRUCache[str, bytes] = LRUCache(max_size=1000)

        # Pre-populate
        for i in range(50):
            await cache.put(f"key{i}", f"value{i}".encode(), size=10)

        async def getter() -> int:
            hits = 0
            for i in range(50):
                result = await cache.get(f"key{i}")
                if result is not None:
                    hits += 1
            return hits

        async def putter() -> None:
            for i in range(50, 100):
                await cache.put(f"key{i}", f"value{i}".encode(), size=10)

        # Run concurrently
        results = await asyncio.gather(
            getter(),
            getter(),
            putter(),
        )

        # Both getters should have found some hits
        assert results[0] > 0
        assert results[1] > 0

    @pytest.mark.asyncio
    async def test_concurrent_eviction(self) -> None:
        """Concurrent operations with eviction don't corrupt state."""
        tracker = FileCacheTracker(max_size=100)

        async def add_and_evict(batch: int) -> None:
            for i in range(10):
                await tracker.track(f"/cache/batch{batch}_file{i}.bin", size=20)
                await asyncio.sleep(0.001)  # Allow interleaving

        # Run concurrent adds that will cause evictions
        await asyncio.gather(
            add_and_evict(1),
            add_and_evict(2),
            add_and_evict(3),
        )

        # State should be consistent
        stats = tracker.get_stats()
        assert stats.current_size <= 100
        assert stats.current_count <= 5  # 100 / 20 = 5 max items
