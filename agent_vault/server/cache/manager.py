"""Server Cache Manager - LRU + TTL caching.

Provides per-project caching for context assembly and memory
recall results with content deduplication.
"""

import hashlib
import logging
import time
from collections import OrderedDict

logger = logging.getLogger("agv.server.cache")


class _TTLEntry:
    """Cache entry with TTL tracking."""

    __slots__ = ("value", "expires_at", "created_at")

    def __init__(self, value, ttl: float) -> None:
        self.value = value
        self.created_at = time.monotonic()
        self.expires_at = self.created_at + ttl


class LRUTTLCache:
    """LRU cache with per-entry TTL."""

    def __init__(self, max_size: int = 100, default_ttl: float = 3600) -> None:
        self._cache: OrderedDict[str, _TTLEntry] = OrderedDict()
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._hits = 0
        self._misses = 0

    def get(self, key: str):
        """Get a value, returning None if expired or missing."""
        entry = self._cache.get(key)
        if entry is None:
            self._misses += 1
            return None

        if time.monotonic() > entry.expires_at:
            del self._cache[key]
            self._misses += 1
            return None

        self._cache.move_to_end(key)
        self._hits += 1
        return entry.value

    def put(self, key: str, value, ttl: float | None = None) -> None:
        """Store a value with optional TTL override."""
        if key in self._cache:
            del self._cache[key]
        elif len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)

        self._cache[key] = _TTLEntry(value, ttl or self._default_ttl)

    def invalidate(self, key: str) -> bool:
        """Remove a specific key. Returns True if found."""
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def invalidate_matching(self, predicate) -> int:
        """Remove all entries matching a predicate on keys."""
        keys_to_remove = [k for k in self._cache if predicate(k)]
        for k in keys_to_remove:
            del self._cache[k]
        return len(keys_to_remove)

    def clear(self) -> None:
        """Clear all entries."""
        self._cache.clear()

    @property
    def stats(self) -> dict:
        """Cache hit/miss statistics."""
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self._hits / total if total > 0 else 0.0,
        }


class ServerCacheManager:
    """Manages multiple named caches for the server."""

    def __init__(self, config: dict | None = None) -> None:
        config = config or {}
        cache_config = config.get("cache", {})

        self.context_cache = LRUTTLCache(
            max_size=cache_config.get("context_size", 100),
            default_ttl=cache_config.get("context_ttl", 3600),
        )
        self.memory_cache = LRUTTLCache(
            max_size=cache_config.get("memory_size", 50),
            default_ttl=cache_config.get("memory_ttl", 600),
        )
        self._content_hashes: dict[str, dict[str, int]] = {}

    def get_context(self, prompt_hash: str):
        return self.context_cache.get(prompt_hash)

    def put_context(self, prompt_hash: str, result: dict) -> None:
        self.context_cache.put(prompt_hash, result)

    def get_memories(self, query_hash: str):
        return self.memory_cache.get(query_hash)

    def put_memories(self, query_hash: str, result: list) -> None:
        self.memory_cache.put(query_hash, result)

    def invalidate(self, file_paths: list[str]) -> int:
        """Invalidate caches affected by file changes."""
        self.context_cache.clear()
        logger.debug("Cache invalidated for %d file changes", len(file_paths))
        return len(file_paths)

    def invalidate_memories(self) -> None:
        self.memory_cache.clear()

    def is_duplicate_content(
        self, session_id: str, content: str, current_turn: int
    ) -> bool:
        """Check if content was already injected within dedup window."""
        content_hash = hashlib.md5(content.encode()).hexdigest()
        session_hashes = self._content_hashes.setdefault(session_id, {})

        last_turn = session_hashes.get(content_hash)
        if last_turn is not None and (current_turn - last_turn) < 10:
            return True

        session_hashes[content_hash] = current_turn
        return False

    def cleanup_session(self, session_id: str) -> None:
        self._content_hashes.pop(session_id, None)

    @property
    def stats(self) -> dict:
        return {
            "context": self.context_cache.stats,
            "memory": self.memory_cache.stats,
            "active_sessions": len(self._content_hashes),
        }

    @staticmethod
    def hash_key(*parts: str) -> str:
        combined = "|".join(parts)
        return hashlib.md5(combined.encode()).hexdigest()
