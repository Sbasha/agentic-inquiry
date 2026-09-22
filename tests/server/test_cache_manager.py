"""Tests for agentic_inquiry.server.cache.manager - LRU+TTL cache and dedup."""

import time

import pytest

from agentic_inquiry.server.cache.manager import LRUTTLCache, ServerCacheManager


class TestLRUTTLCache:
    """Test the LRU+TTL cache implementation."""

    def test_basic_get_put(self):
        cache = LRUTTLCache(max_size=10, default_ttl=60)
        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_miss_returns_none(self):
        cache = LRUTTLCache(max_size=10, default_ttl=60)
        assert cache.get("missing") is None

    def test_eviction_on_max_size(self):
        cache = LRUTTLCache(max_size=3, default_ttl=60)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        cache.put("d", 4)  # Should evict "a"
        assert cache.get("a") is None
        assert cache.get("d") == 4

    def test_ttl_expiry(self):
        cache = LRUTTLCache(max_size=10, default_ttl=0.1)
        cache.put("key1", "value1")
        time.sleep(0.15)
        assert cache.get("key1") is None

    def test_lru_ordering(self):
        cache = LRUTTLCache(max_size=3, default_ttl=60)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        # Access "a" to make it most recently used
        cache.get("a")
        cache.put("d", 4)  # Should evict "b" (least recently used)
        assert cache.get("a") == 1
        assert cache.get("b") is None

    def test_clear(self):
        cache = LRUTTLCache(max_size=10, default_ttl=60)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_stats(self):
        cache = LRUTTLCache(max_size=10, default_ttl=60)
        cache.put("a", 1)
        cache.get("a")  # hit
        cache.get("b")  # miss
        stats = cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1

    def test_invalidate_single(self):
        cache = LRUTTLCache(max_size=10, default_ttl=60)
        cache.put("a", 1)
        assert cache.invalidate("a")
        assert cache.get("a") is None

    def test_invalidate_missing(self):
        cache = LRUTTLCache(max_size=10, default_ttl=60)
        assert not cache.invalidate("nonexistent")


class TestServerCacheManager:
    """Test the server cache manager."""

    @pytest.fixture
    def manager(self):
        config = {
            "cache": {
                "context_size": 50,
                "context_ttl": 60,
                "memory_size": 50,
                "memory_ttl": 120,
            }
        }
        return ServerCacheManager(config)

    def test_context_cache(self, manager):
        key = manager.hash_key("test query", "session1")
        manager.put_context(key, {"context": "result"})
        assert manager.get_context(key) == {"context": "result"}

    def test_memory_cache(self, manager):
        key = manager.hash_key("recall query", "project1")
        manager.put_memories(key, [{"content": "memory1"}])
        assert manager.get_memories(key) == [{"content": "memory1"}]

    def test_invalidate_clears_context(self, manager):
        key = manager.hash_key("test", "session1")
        manager.put_context(key, {"data": "test"})
        count = manager.invalidate(["file1.py"])
        assert count == 1
        assert manager.get_context(key) is None

    def test_invalidate_memories(self, manager):
        key = manager.hash_key("recall", "project1")
        manager.put_memories(key, [{"content": "mem"}])
        manager.invalidate_memories()
        assert manager.get_memories(key) is None

    def test_hash_key_deterministic(self, manager):
        key1 = manager.hash_key("query", "session")
        key2 = manager.hash_key("query", "session")
        assert key1 == key2

    def test_hash_key_different_inputs(self, manager):
        key1 = manager.hash_key("query1", "session")
        key2 = manager.hash_key("query2", "session")
        assert key1 != key2

    def test_dedup_content(self, manager):
        content = "This is duplicate content"
        # First time should not be duplicate
        assert not manager.is_duplicate_content("session1", content, current_turn=1)
        # Second time should be duplicate (within 10-turn window)
        assert manager.is_duplicate_content("session1", content, current_turn=1)

    def test_dedup_window(self, manager):
        content = "Windowed content"
        manager.is_duplicate_content("session1", content, current_turn=1)
        # Same content at turn outside window (>10 turns later) should not be duplicate
        assert not manager.is_duplicate_content("session1", content, current_turn=100)

    def test_stats(self, manager):
        stats = manager.stats
        assert "context" in stats
        assert "memory" in stats
        assert "active_sessions" in stats

    def test_cleanup_session(self, manager):
        manager.is_duplicate_content("session1", "content", current_turn=1)
        assert manager.stats["active_sessions"] == 1
        manager.cleanup_session("session1")
        assert manager.stats["active_sessions"] == 0
