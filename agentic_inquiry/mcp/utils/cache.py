"""Cache manager for MCP responses with filter support."""

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional


class MCPCacheManager:
    """Manage MCP-level caching with filter-aware keys.

    Implements:
    - Filter-aware cache key generation
    - TTL-based expiration
    - Cache invalidation by pattern
    """

    def __init__(self, ttl_seconds: int = 300):
        """Initialize cache manager.

        Args:
            ttl_seconds: Time-to-live for cache entries in seconds
        """
        self.cache: Dict[str, tuple[Any, datetime]] = {}
        self.ttl = timedelta(seconds=ttl_seconds)
        self.hits = 0
        self.misses = 0
        self.invalidations = 0

    def get(self, key: str) -> Optional[Any]:
        """Get cached response.

        Args:
            key: Cache key

        Returns:
            Cached value if found and not expired, None otherwise
        """
        if key in self.cache:
            value, timestamp = self.cache[key]
            if datetime.now() - timestamp < self.ttl:
                self.hits += 1
                return value
            else:
                # Expired, remove from cache
                del self.cache[key]
                self.misses += 1
        else:
            self.misses += 1
        return None

    def set(self, key: str, value: Any) -> None:
        """Cache response.

        Args:
            key: Cache key
            value: Value to cache
        """
        self.cache[key] = (value, datetime.now())

    def invalidate(self, pattern: str) -> int:
        """Invalidate cache entries matching pattern.

        Args:
            pattern: Pattern to match against cache keys

        Returns:
            Number of entries invalidated
        """
        keys_to_delete = [k for k in self.cache.keys() if pattern in k]
        count = len(keys_to_delete)
        for key in keys_to_delete:
            del self.cache[key]
        self.invalidations += count
        return count

    def clear(self) -> None:
        """Clear all cache entries."""
        self.cache.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats including hit rate
        """
        now = datetime.now()
        active_entries = sum(
            1 for _, timestamp in self.cache.values() if now - timestamp < self.ttl
        )

        total_requests = self.hits + self.misses
        hit_rate = (self.hits / total_requests * 100) if total_requests > 0 else 0.0

        return {
            "total_entries": len(self.cache),
            "active_entries": active_entries,
            "expired_entries": len(self.cache) - active_entries,
            "ttl_seconds": self.ttl.total_seconds(),
            "hits": self.hits,
            "misses": self.misses,
            "total_requests": total_requests,
            "hit_rate_percent": round(hit_rate, 2),
            "invalidations": self.invalidations,
        }

    @staticmethod
    def generate_cache_key(
        tool_name: str,
        session_id: str,
        query: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> str:
        """Generate cache key with filter support.

        The cache key includes all parameters that affect the result,
        including filters, to ensure correct cache hits.

        Args:
            tool_name: Name of the tool
            session_id: Session ID
            query: Optional query string
            filters: Optional filters dictionary
            **kwargs: Additional parameters to include in key

        Returns:
            Cache key string
        """
        # Build key components
        key_parts = [tool_name, session_id]

        if query:
            key_parts.append(query)

        # Include filters in key (sorted for consistency)
        if filters:
            # Sort filters to ensure consistent key generation
            sorted_filters = json.dumps(filters, sort_keys=True)
            key_parts.append(sorted_filters)

        # Include additional parameters (sorted for consistency)
        if kwargs:
            sorted_kwargs = json.dumps(kwargs, sort_keys=True)
            key_parts.append(sorted_kwargs)

        # Generate hash of key parts
        key_string = ":".join(str(p) for p in key_parts)
        key_hash = hashlib.sha256(key_string.encode()).hexdigest()[:16]

        # Return readable key with hash
        return f"{tool_name}:{session_id}:{key_hash}"

    def cleanup_expired(self) -> int:
        """Remove expired entries from cache.

        Returns:
            Number of entries removed
        """
        now = datetime.now()
        keys_to_delete = [
            k for k, (_, timestamp) in self.cache.items() if now - timestamp >= self.ttl
        ]
        for key in keys_to_delete:
            del self.cache[key]
        return len(keys_to_delete)

    def reset_stats(self) -> None:
        """Reset cache statistics."""
        self.hits = 0
        self.misses = 0
        self.invalidations = 0
