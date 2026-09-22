"""Tests for MCP cache manager."""

import pytest

pytestmark = pytest.mark.unit

import time

from agentic_inquiry.mcp.utils.cache import MCPCacheManager


def test_cache_set_and_get():
    """Test basic cache set and get operations."""
    cache = MCPCacheManager(ttl_seconds=300)
    
    # Set a value
    cache.set("key1", {"data": "value1"})
    
    # Get the value
    result = cache.get("key1")
    assert result == {"data": "value1"}


def test_cache_get_nonexistent():
    """Test getting a nonexistent key."""
    cache = MCPCacheManager(ttl_seconds=300)
    
    result = cache.get("nonexistent")
    assert result is None


def test_cache_expiration():
    """Test cache entry expiration."""
    cache = MCPCacheManager(ttl_seconds=1)  # 1 second TTL
    
    # Set a value
    cache.set("key1", {"data": "value1"})
    
    # Should be available immediately
    result = cache.get("key1")
    assert result is not None
    assert result == {"data": "value1"}
    
    # Wait for expiration
    time.sleep(1.1)
    
    # Should be expired
    assert cache.get("key1") is None


def test_cache_invalidate_pattern():
    """Test cache invalidation by pattern."""
    cache = MCPCacheManager(ttl_seconds=300)
    
    # Set multiple values
    cache.set("search:session1:abc", {"data": "value1"})
    cache.set("search:session1:def", {"data": "value2"})
    cache.set("search:session2:ghi", {"data": "value3"})
    cache.set("context:session1:jkl", {"data": "value4"})
    
    # Invalidate all search:session1 entries
    count = cache.invalidate("search:session1")
    
    assert count == 2
    assert cache.get("search:session1:abc") is None
    assert cache.get("search:session1:def") is None
    assert cache.get("search:session2:ghi") == {"data": "value3"}
    assert cache.get("context:session1:jkl") == {"data": "value4"}


def test_cache_clear():
    """Test clearing all cache entries."""
    cache = MCPCacheManager(ttl_seconds=300)
    
    # Set multiple values
    cache.set("key1", {"data": "value1"})
    cache.set("key2", {"data": "value2"})
    cache.set("key3", {"data": "value3"})
    
    # Clear cache
    cache.clear()
    
    # All entries should be gone
    assert cache.get("key1") is None
    assert cache.get("key2") is None
    assert cache.get("key3") is None


def test_cache_stats():
    """Test cache statistics."""
    cache = MCPCacheManager(ttl_seconds=1)
    
    # Set some values
    cache.set("key1", {"data": "value1"})
    cache.set("key2", {"data": "value2"})
    
    # Get stats immediately
    stats = cache.get_stats()
    assert stats["total_entries"] == 2
    assert stats["active_entries"] == 2
    assert stats["expired_entries"] == 0
    
    # Wait for expiration
    time.sleep(1.1)
    
    # Get stats after expiration
    stats = cache.get_stats()
    assert stats["total_entries"] == 2
    assert stats["active_entries"] == 0
    assert stats["expired_entries"] == 2


def test_generate_cache_key_basic():
    """Test basic cache key generation."""
    key = MCPCacheManager.generate_cache_key(
        tool_name="search_knowledge",
        session_id="session123",
        query="test query",
    )
    
    assert "search_knowledge" in key
    assert "session123" in key
    assert len(key) > 0


def test_generate_cache_key_with_filters():
    """Test cache key generation with filters."""
    key1 = MCPCacheManager.generate_cache_key(
        tool_name="search_knowledge",
        session_id="session123",
        query="test",
        filters={"type": "code"},
    )
    
    key2 = MCPCacheManager.generate_cache_key(
        tool_name="search_knowledge",
        session_id="session123",
        query="test",
        filters={"type": "doc"},
    )
    
    # Keys should be different due to different filters
    assert key1 != key2


def test_generate_cache_key_filter_order():
    """Test that filter order doesn't affect cache key."""
    key1 = MCPCacheManager.generate_cache_key(
        tool_name="search_knowledge",
        session_id="session123",
        query="test",
        filters={"type": "code", "language": "python"},
    )
    
    key2 = MCPCacheManager.generate_cache_key(
        tool_name="search_knowledge",
        session_id="session123",
        query="test",
        filters={"language": "python", "type": "code"},
    )
    
    # Keys should be identical (filters are sorted)
    assert key1 == key2


def test_generate_cache_key_with_kwargs():
    """Test cache key generation with additional kwargs."""
    key1 = MCPCacheManager.generate_cache_key(
        tool_name="search_knowledge",
        session_id="session123",
        query="test",
        limit=20,
        preview=True,
    )
    
    key2 = MCPCacheManager.generate_cache_key(
        tool_name="search_knowledge",
        session_id="session123",
        query="test",
        limit=50,
        preview=False,
    )
    
    # Keys should be different due to different kwargs
    assert key1 != key2


def test_cleanup_expired():
    """Test cleanup of expired entries."""
    cache = MCPCacheManager(ttl_seconds=1)
    
    # Set some values
    cache.set("key1", {"data": "value1"})
    cache.set("key2", {"data": "value2"})
    
    # Wait for expiration
    time.sleep(1.1)
    
    # Add a new value (not expired)
    cache.set("key3", {"data": "value3"})
    
    # Cleanup expired entries
    removed = cache.cleanup_expired()

    assert removed == 2
    assert cache.get("key1") is None
    assert cache.get("key2") is None
    assert cache.get("key3") == {"data": "value3"}


def test_cache_key_consistency():
    """Test that cache keys are consistent across calls."""
    key1 = MCPCacheManager.generate_cache_key(
        tool_name="search_knowledge",
        session_id="session123",
        query="test query",
        filters={"type": "code"},
    )
    
    key2 = MCPCacheManager.generate_cache_key(
        tool_name="search_knowledge",
        session_id="session123",
        query="test query",
        filters={"type": "code"},
    )
    
    # Keys should be identical
    assert key1 == key2


def test_cache_hit_rate_tracking():
    """Test cache hit rate tracking."""
    cache = MCPCacheManager(ttl_seconds=300)
    
    # Set a value
    cache.set("key1", {"data": "value1"})
    
    # Hit: Get existing key
    cache.get("key1")
    
    # Miss: Get nonexistent key
    cache.get("key2")
    
    # Hit: Get existing key again
    cache.get("key1")
    
    # Miss: Get another nonexistent key
    cache.get("key3")
    
    # Check stats
    stats = cache.get_stats()
    assert stats["hits"] == 2
    assert stats["misses"] == 2
    assert stats["total_requests"] == 4
    assert stats["hit_rate_percent"] == 50.0


def test_cache_hit_rate_with_expiration():
    """Test that expired entries count as misses."""
    cache = MCPCacheManager(ttl_seconds=1)
    
    # Set a value
    cache.set("key1", {"data": "value1"})
    
    # Hit: Get before expiration
    result = cache.get("key1")
    assert result is not None
    assert result == {"data": "value1"}
    
    # Wait for expiration
    time.sleep(1.1)
    
    # Miss: Get after expiration
    result = cache.get("key1")
    assert result is None
    
    # Check stats
    stats = cache.get_stats()
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["hit_rate_percent"] == 50.0


def test_cache_invalidation_tracking():
    """Test that invalidations are tracked."""
    cache = MCPCacheManager(ttl_seconds=300)
    
    # Set multiple values
    cache.set("search:session1:abc", {"data": "value1"})
    cache.set("search:session1:def", {"data": "value2"})
    cache.set("search:session2:ghi", {"data": "value3"})
    
    # Invalidate some entries
    cache.invalidate("search:session1")
    
    # Check stats
    stats = cache.get_stats()
    assert stats["invalidations"] == 2
    
    # Invalidate more entries
    cache.invalidate("search:session2")
    
    # Check stats again
    stats = cache.get_stats()
    assert stats["invalidations"] == 3


def test_cache_reset_stats():
    """Test resetting cache statistics."""
    cache = MCPCacheManager(ttl_seconds=300)
    
    # Set and get some values
    cache.set("key1", {"data": "value1"})
    cache.get("key1")
    cache.get("key2")
    cache.invalidate("key1")
    
    # Check stats are non-zero
    stats = cache.get_stats()
    assert stats["hits"] > 0
    assert stats["misses"] > 0
    assert stats["invalidations"] > 0
    
    # Reset stats
    cache.reset_stats()
    
    # Check stats are zero
    stats = cache.get_stats()
    assert stats["hits"] == 0
    assert stats["misses"] == 0
    assert stats["invalidations"] == 0
    assert stats["total_requests"] == 0
    assert stats["hit_rate_percent"] == 0.0


def test_cache_hit_rate_zero_requests():
    """Test hit rate calculation with zero requests."""
    cache = MCPCacheManager(ttl_seconds=300)
    
    # No requests yet
    stats = cache.get_stats()
    assert stats["hits"] == 0
    assert stats["misses"] == 0
    assert stats["total_requests"] == 0
    assert stats["hit_rate_percent"] == 0.0
