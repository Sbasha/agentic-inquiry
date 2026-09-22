"""Bounded hash cache for content deduplication.

Provides an LRU-bounded cache for file hashes with optional fallback to a
persistent HashTrackerProtocol. Used for efficient duplicate detection during
indexing operations.

See: docs/design/connector-architecture.md (S5-011)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from agentic_inquiry.connectors.lru_cache import CacheStats, LRUCache
from agentic_inquiry.connectors.protocols import HashTrackerProtocol

logger = logging.getLogger(__name__)


@dataclass
class HashCacheStats:
    """Statistics for BoundedHashCache performance monitoring.

    Attributes:
        cache_hits: Number of cache hits (found in LRU cache).
        cache_misses: Number of cache misses (not in LRU cache).
        tracker_hits: Number of fallback tracker hits.
        tracker_misses: Number of fallback tracker misses.
        current_count: Current number of entries in cache.
        max_size: Maximum number of entries allowed.
        has_tracker: Whether a fallback tracker is configured.
    """
    cache_hits: int = 0
    cache_misses: int = 0
    tracker_hits: int = 0
    tracker_misses: int = 0
    current_count: int = 0
    max_size: int = 0
    has_tracker: bool = False

    @property
    def total_hits(self) -> int:
        """Total hits (cache + tracker)."""
        return self.cache_hits + self.tracker_hits

    @property
    def total_lookups(self) -> int:
        """Total lookup operations."""
        return self.cache_hits + self.cache_misses

    @property
    def hit_rate(self) -> float:
        """Combined hit rate (cache + tracker falls back).

        Returns:
            Hit rate as ratio (0.0 to 1.0). Returns 0.0 if no lookups.
        """
        if self.total_lookups == 0:
            return 0.0
        return self.total_hits / self.total_lookups

    @property
    def cache_hit_rate(self) -> float:
        """Cache-only hit rate.

        Returns:
            Hit rate as ratio (0.0 to 1.0). Returns 0.0 if no lookups.
        """
        if self.total_lookups == 0:
            return 0.0
        return self.cache_hits / self.total_lookups

    def to_dict(self) -> dict:
        """Convert stats to dictionary for JSON serialization."""
        return {
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "tracker_hits": self.tracker_hits,
            "tracker_misses": self.tracker_misses,
            "current_count": self.current_count,
            "max_size": self.max_size,
            "has_tracker": self.has_tracker,
            "hit_rate": self.hit_rate,
            "cache_hit_rate": self.cache_hit_rate,
        }


class BoundedHashCache:
    """Bounded LRU cache for file hashes with fallback to persistent tracker.

    Combines fast in-memory LRU caching with optional persistent storage via
    a HashTrackerProtocol implementation. Useful for:

    - Fast duplicate detection during indexing
    - Memory-bounded hash tracking
    - Hybrid cache + persistent storage strategies

    The cache maps file paths to their content hashes. When checking if a file
    is processed:
    1. First checks the in-memory LRU cache (fast path)
    2. Falls back to the HashTrackerProtocol if configured (persistent path)

    When marking a file as processed, both the cache and tracker are updated.

    Attributes:
        max_size: Maximum number of entries in the cache.

    Example:
        >>> from agentic_inquiry.connectors import InMemoryFileTracker
        >>> tracker = InMemoryFileTracker()
        >>> cache = BoundedHashCache(max_size=10000, file_tracker=tracker)
        >>>
        >>> # Check and mark as processed
        >>> if not await cache.is_processed("/path/file.py", "abc123"):
        ...     await cache.mark_processed("/path/file.py", "abc123")
    """

    def __init__(
        self,
        max_size: int = 10000,
        file_tracker: Optional[HashTrackerProtocol] = None,
    ) -> None:
        """Initialize the bounded hash cache.

        Args:
            max_size: Maximum number of entries to cache. Default 10000.
                      When exceeded, least recently used entries are evicted.
            file_tracker: Optional persistent tracker for fallback lookups.
                          Entries are also persisted here on mark_processed.
        """
        self._max_size = max_size
        self._file_tracker = file_tracker

        # Use LRUCache with size=1 per entry (count-based limit)
        # The cache maps: file_path -> file_hash
        self._cache: LRUCache[str, str] = LRUCache(max_size=max_size)

        # Stats tracking
        self._cache_hits = 0
        self._cache_misses = 0
        self._tracker_hits = 0
        self._tracker_misses = 0

    @property
    def max_size(self) -> int:
        """Get the maximum cache size (entry count)."""
        return self._max_size

    @property
    def has_tracker(self) -> bool:
        """Check if a fallback tracker is configured."""
        return self._file_tracker is not None

    async def is_processed(self, file_path: str, file_hash: str) -> bool:
        """Check if a file with given hash has been processed.

        First checks the in-memory cache for a matching hash at the given path.
        If not found and a file_tracker is configured, checks the tracker.

        Args:
            file_path: Path to the file (used as cache key).
            file_hash: Content hash of the file.

        Returns:
            True if the file (with matching hash) was previously processed.
        """
        # Check local cache first (fast path)
        cached_hash = await self._cache.get(file_path)
        if cached_hash == file_hash:
            self._cache_hits += 1
            return True

        self._cache_misses += 1

        # Fall back to file tracker if available
        if self._file_tracker is not None:
            is_tracked = await self._file_tracker.is_processed(file_hash)
            if is_tracked:
                self._tracker_hits += 1
                # Warm the cache with this entry
                await self._cache.put(file_path, file_hash, size=1)
                return True
            else:
                self._tracker_misses += 1

        return False

    async def mark_processed(self, file_path: str, file_hash: str) -> None:
        """Mark a file as processed.

        Updates both the in-memory cache and the persistent tracker (if configured).

        Args:
            file_path: Path to the file.
            file_hash: Content hash of the file.
        """
        # Update cache (size=1 for count-based limiting)
        await self._cache.put(file_path, file_hash, size=1)

        # Update tracker if available
        if self._file_tracker is not None:
            await self._file_tracker.mark_processed(file_hash)

    async def invalidate(self, file_path: str) -> bool:
        """Invalidate a cached entry for a file path.

        Removes the file from the cache but does NOT remove from the tracker
        (since the tracker tracks hashes, not paths).

        Args:
            file_path: Path to invalidate.

        Returns:
            True if entry was removed from cache.
        """
        return await self._cache.remove(file_path)

    async def clear(self) -> int:
        """Clear all cached entries.

        Only clears the in-memory cache. Does not clear the tracker.
        To clear the tracker as well, call tracker.clear() separately.

        Returns:
            Number of entries cleared from cache.
        """
        return await self._cache.clear()

    async def clear_all(self) -> tuple[int, int]:
        """Clear both cache and tracker.

        Returns:
            Tuple of (cache_entries_cleared, tracker_entries_cleared).
        """
        cache_cleared = await self._cache.clear()
        tracker_cleared = 0
        if self._file_tracker is not None:
            tracker_cleared = await self._file_tracker.clear()
        return cache_cleared, tracker_cleared

    def get_stats(self) -> HashCacheStats:
        """Get cache performance statistics.

        Returns:
            HashCacheStats with current metrics.
        """
        cache_stats: CacheStats = self._cache.get_stats()
        return HashCacheStats(
            cache_hits=self._cache_hits,
            cache_misses=self._cache_misses,
            tracker_hits=self._tracker_hits,
            tracker_misses=self._tracker_misses,
            current_count=cache_stats.current_count,
            max_size=self._max_size,
            has_tracker=self._file_tracker is not None,
        )

    async def get_processed_count(self) -> int:
        """Get count of processed entries.

        Returns the count from the tracker if available (more complete),
        otherwise returns the cache count.

        Returns:
            Number of processed entries.
        """
        if self._file_tracker is not None:
            return await self._file_tracker.get_processed_count()
        return self._cache.get_stats().current_count


__all__ = [
    "BoundedHashCache",
    "HashCacheStats",
]
