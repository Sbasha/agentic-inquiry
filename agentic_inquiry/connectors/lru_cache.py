"""LRU Cache implementation for content connectors.

Provides a generic, thread-safe LRU cache with size-based eviction and statistics.
Used by ContentMaterializer for bounded content caching.

See: docs/design/connector-architecture.md (S5-005)
"""
from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, Generic, Optional, TypeVar

logger = logging.getLogger(__name__)

K = TypeVar("K")  # Key type
V = TypeVar("V")  # Value type


@dataclass
class CacheEntry(Generic[V]):
    """Entry in the LRU cache with size tracking.

    Attributes:
        value: The cached value.
        size: Size of the entry in bytes.
    """
    value: V
    size: int


@dataclass
class CacheStats:
    """Statistics for cache performance monitoring.

    Attributes:
        hits: Number of cache hits.
        misses: Number of cache misses.
        evictions: Number of items evicted due to size limit.
        current_size: Current total size in bytes.
        current_count: Current number of items.
        max_size: Maximum size limit in bytes.
    """
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    current_size: int = 0
    current_count: int = 0
    max_size: int = 0

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate as a ratio (0.0 to 1.0).

        Returns:
            Hit rate. Returns 0.0 if no requests have been made.
        """
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.hits / total

    def to_dict(self) -> Dict[str, Any]:
        """Convert stats to dictionary for JSON serialization.

        Returns:
            Dictionary with all stats including computed hit_rate.
        """
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "current_size": self.current_size,
            "current_count": self.current_count,
            "max_size": self.max_size,
            "hit_rate": self.hit_rate,
        }


class LRUCache(Generic[K, V]):
    """Thread-safe LRU cache with size-based eviction.

    Implements a Least Recently Used cache that evicts entries when the total
    size exceeds max_size. Uses asyncio.Lock for thread safety in async contexts.

    The cache tracks access order internally. When an item is accessed or added,
    it moves to the end of the order. When eviction is needed, items are removed
    from the front (least recently used).

    Attributes:
        max_size: Maximum cache size in bytes. 0 means unlimited.

    Example:
        >>> cache = LRUCache[str, bytes](max_size=1024 * 1024)  # 1MB limit
        >>> await cache.put("key1", b"data", size=100)
        >>> value = await cache.get("key1")
        >>> stats = cache.get_stats()
        >>> print(f"Hit rate: {stats.hit_rate:.2%}")
    """

    def __init__(self, max_size: int = 0) -> None:
        """Initialize the LRU cache.

        Args:
            max_size: Maximum cache size in bytes. 0 means unlimited (no eviction).
        """
        self._max_size = max_size
        self._lock = asyncio.Lock()
        self._cache: OrderedDict[K, CacheEntry[V]] = OrderedDict()
        self._current_size = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    @property
    def max_size(self) -> int:
        """Get the maximum cache size in bytes."""
        return self._max_size

    async def get(self, key: K) -> Optional[V]:
        """Get a value from the cache.

        If found, moves the entry to the end (most recently used).
        Updates hit/miss statistics.

        Args:
            key: Cache key to look up.

        Returns:
            Cached value if found, None otherwise.
        """
        async with self._lock:
            if key in self._cache:
                # Move to end (most recently used)
                self._cache.move_to_end(key)
                self._hits += 1
                return self._cache[key].value
            else:
                self._misses += 1
                return None

    async def put(self, key: K, value: V, size: int) -> None:
        """Add or update a value in the cache.

        If adding this entry would exceed max_size, evicts least recently used
        entries until there's room. If a single entry is larger than max_size,
        it won't be cached (logged as warning).

        Args:
            key: Cache key.
            value: Value to cache.
            size: Size of the value in bytes.
        """
        async with self._lock:
            # If key already exists, remove old size first
            if key in self._cache:
                old_entry = self._cache.pop(key)
                self._current_size -= old_entry.size

            # Check if single entry exceeds max_size (can't cache)
            if self._max_size > 0 and size > self._max_size:
                logger.warning(
                    "Cache entry size %d exceeds max_size %d, not caching key %s",
                    size, self._max_size, key
                )
                return

            # Evict entries if needed
            if self._max_size > 0:
                await self._evict_if_needed(size)

            # Add new entry at end (most recently used)
            self._cache[key] = CacheEntry(value=value, size=size)
            self._current_size += size

    async def remove(self, key: K) -> bool:
        """Remove an entry from the cache.

        Args:
            key: Cache key to remove.

        Returns:
            True if entry was removed, False if not found.
        """
        async with self._lock:
            if key in self._cache:
                entry = self._cache.pop(key)
                self._current_size -= entry.size
                return True
            return False

    async def contains(self, key: K) -> bool:
        """Check if key exists in cache without updating access order.

        Args:
            key: Cache key to check.

        Returns:
            True if key exists in cache.
        """
        async with self._lock:
            return key in self._cache

    async def clear(self) -> int:
        """Clear all entries from the cache.

        Returns:
            Number of entries removed.
        """
        async with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._current_size = 0
            return count

    def get_stats(self) -> CacheStats:
        """Get cache statistics.

        Note: This is synchronous since it only reads atomic values.
        For consistent snapshot during high concurrency, acquire lock first.

        Returns:
            CacheStats with current performance metrics.
        """
        return CacheStats(
            hits=self._hits,
            misses=self._misses,
            evictions=self._evictions,
            current_size=self._current_size,
            current_count=len(self._cache),
            max_size=self._max_size,
        )

    async def _evict_if_needed(self, new_entry_size: int) -> None:
        """Evict entries until there's room for new entry.

        Must be called with lock held. Evicts from front (least recently used)
        until current_size + new_entry_size <= max_size.

        Args:
            new_entry_size: Size of entry being added.
        """
        while (
            self._cache
            and self._current_size + new_entry_size > self._max_size
        ):
            # Pop from front (least recently used)
            key, entry = self._cache.popitem(last=False)
            self._current_size -= entry.size
            self._evictions += 1
            logger.debug(
                "Evicted cache entry %s (size=%d), current_size=%d",
                key, entry.size, self._current_size
            )


class FileCacheTracker:
    """Tracks file cache entries for ContentMaterializer.

    Wraps LRUCache to manage file-based cache entries. Tracks files by their
    cache paths and handles size-based eviction with file deletion.

    This is a specialized version that stores cache paths and coordinates
    with the filesystem to actually delete evicted files.

    Attributes:
        max_size: Maximum cache size in bytes.

    Example:
        >>> tracker = FileCacheTracker(max_size=100 * 1024 * 1024)  # 100MB
        >>> await tracker.track(cache_path, file_size)
        >>> # When eviction happens, call on_evict to delete the file
    """

    def __init__(
        self,
        max_size: int = 0,
        on_evict: Optional[Any] = None,  # Callable[[str], Awaitable[None]]
    ) -> None:
        """Initialize the file cache tracker.

        Args:
            max_size: Maximum cache size in bytes. 0 means unlimited.
            on_evict: Optional async callback called when a file is evicted.
                      Receives the cache path of the evicted file.
        """
        self._max_size = max_size
        self._on_evict = on_evict
        self._lock = asyncio.Lock()
        self._entries: OrderedDict[str, int] = OrderedDict()  # path -> size
        self._current_size = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    @property
    def max_size(self) -> int:
        """Get the maximum cache size in bytes."""
        return self._max_size

    async def access(self, cache_path: str) -> bool:
        """Record access to a cached file.

        Moves the entry to most recently used position.
        Updates hit/miss statistics.

        Args:
            cache_path: Path to the cached file.

        Returns:
            True if file was tracked (hit), False otherwise (miss).
        """
        async with self._lock:
            if cache_path in self._entries:
                self._entries.move_to_end(cache_path)
                self._hits += 1
                return True
            else:
                self._misses += 1
                return False

    async def track(self, cache_path: str, size: int) -> list[str]:
        """Track a new cache entry, evicting if needed.

        Args:
            cache_path: Path to the cached file.
            size: Size of the file in bytes.

        Returns:
            List of cache paths that were evicted (caller should delete files).
        """
        evicted: list[str] = []

        async with self._lock:
            # If already tracked, update size
            if cache_path in self._entries:
                old_size = self._entries.pop(cache_path)
                self._current_size -= old_size

            # Check if single entry exceeds max_size
            if self._max_size > 0 and size > self._max_size:
                logger.warning(
                    "File size %d exceeds max_size %d, not tracking %s",
                    size, self._max_size, cache_path
                )
                return evicted

            # Evict entries if needed
            if self._max_size > 0:
                while (
                    self._entries
                    and self._current_size + size > self._max_size
                ):
                    # Pop from front (least recently used)
                    old_path, old_size = self._entries.popitem(last=False)
                    self._current_size -= old_size
                    self._evictions += 1
                    evicted.append(old_path)
                    logger.debug(
                        "Evicted cache file %s (size=%d), current_size=%d",
                        old_path, old_size, self._current_size
                    )

            # Add new entry
            self._entries[cache_path] = size
            self._current_size += size

        return evicted

    async def remove(self, cache_path: str) -> bool:
        """Remove an entry from tracking.

        Args:
            cache_path: Path to stop tracking.

        Returns:
            True if entry was tracked and removed.
        """
        async with self._lock:
            if cache_path in self._entries:
                size = self._entries.pop(cache_path)
                self._current_size -= size
                return True
            return False

    async def clear(self) -> list[str]:
        """Clear all tracked entries.

        Returns:
            List of all cache paths (caller should delete files).
        """
        async with self._lock:
            paths = list(self._entries.keys())
            self._entries.clear()
            self._current_size = 0
            return paths

    def get_stats(self) -> CacheStats:
        """Get cache statistics.

        Returns:
            CacheStats with current performance metrics.
        """
        return CacheStats(
            hits=self._hits,
            misses=self._misses,
            evictions=self._evictions,
            current_size=self._current_size,
            current_count=len(self._entries),
            max_size=self._max_size,
        )


__all__ = [
    "CacheEntry",
    "CacheStats",
    "LRUCache",
    "FileCacheTracker",
]
