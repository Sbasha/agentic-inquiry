"""Tests for PrecomputedCache."""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta

from agentic_inquiry.cache.precomputed import PrecomputedCache, CacheEntry


class TestCacheEntry:
    """Tests for CacheEntry dataclass."""

    def test_cache_entry_creation(self) -> None:
        """Test creating a cache entry."""
        entry = CacheEntry(
            key="test:key",
            query_type="symbol_deps",
            data={"deps": ["a", "b"]},
        )
        assert entry.key == "test:key"
        assert entry.query_type == "symbol_deps"
        assert entry.data == {"deps": ["a", "b"]}

    def test_cache_entry_default_ttl(self) -> None:
        """Test default TTL is set."""
        entry = CacheEntry(
            key="test:key",
            query_type="symbol_deps",
            data={},
        )
        assert entry.ttl_seconds == 3600  # 1 hour

    def test_cache_entry_not_expired(self) -> None:
        """Test entry is not expired initially."""
        entry = CacheEntry(
            key="test:key",
            query_type="symbol_deps",
            data={},
            ttl_seconds=3600,
        )
        assert entry.is_expired is False

    def test_cache_entry_expired(self) -> None:
        """Test expired entry detection."""
        entry = CacheEntry(
            key="test:key",
            query_type="symbol_deps",
            data={},
            ttl_seconds=0,  # Immediate expiry
            created_at=datetime.utcnow() - timedelta(seconds=1),
        )
        assert entry.is_expired is True

    def test_cache_entry_to_dict(self) -> None:
        """Test converting entry to dictionary."""
        entry = CacheEntry(
            key="test:key",
            query_type="symbol_deps",
            data={"a": 1},
            entity_ids=["id1"],
            file_paths=["/test.py"],
        )
        data = entry.to_dict()
        assert data["key"] == "test:key"
        assert data["query_type"] == "symbol_deps"
        assert data["entity_ids"] == ["id1"]
        assert data["file_paths"] == ["/test.py"]

    def test_cache_entry_from_dict(self) -> None:
        """Test creating entry from dictionary."""
        data = {
            "key": "test:key",
            "query_type": "def_lookup",
            "data": '{"id": "123"}',
            "entity_ids": ["id1"],
            "file_paths": ["/test.py"],
            "created_at": datetime.utcnow().isoformat(),
            "ttl_seconds": 1800,
            "hit_count": 5,
        }
        entry = CacheEntry.from_dict(data)
        assert entry.key == "test:key"
        assert entry.query_type == "def_lookup"
        assert entry.data == {"id": "123"}
        assert entry.ttl_seconds == 1800
        assert entry.hit_count == 5

    def test_cache_entry_from_dict_json_data(self) -> None:
        """Test creating entry from dict with JSON string data."""
        data = {
            "key": "test:key",
            "query_type": "file_refs",
            "data": '["a", "b", "c"]',
            "created_at": datetime.utcnow().isoformat(),
        }
        entry = CacheEntry.from_dict(data)
        assert entry.data == ["a", "b", "c"]


class TestPrecomputedCache:
    """Tests for PrecomputedCache."""

    @pytest.fixture
    def cache(self) -> PrecomputedCache:
        """Create cache without storage."""
        return PrecomputedCache(project_id="test_project")

    @pytest.fixture
    def cache_with_file(self, tmp_path: Path) -> PrecomputedCache:
        """Create cache with file storage."""
        return PrecomputedCache(
            project_id="test_project",
            cache_dir=tmp_path / "cache",
        )

    @pytest.mark.asyncio
    async def test_set_and_get_memory(self, cache: PrecomputedCache) -> None:
        """Test set and get with memory cache."""
        await cache.set(
            query_type="symbol_deps",
            key="func1",
            data={"deps": ["a", "b"]},
        )

        result = await cache.get(
            query_type="symbol_deps",
            key="func1",
        )
        assert result == {"deps": ["a", "b"]}

    @pytest.mark.asyncio
    async def test_get_miss(self, cache: PrecomputedCache) -> None:
        """Test cache miss returns default."""
        result = await cache.get(
            query_type="symbol_deps",
            key="nonexistent",
            default=None,
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_get_miss_custom_default(self, cache: PrecomputedCache) -> None:
        """Test cache miss returns custom default."""
        result = await cache.get(
            query_type="symbol_deps",
            key="nonexistent",
            default={"empty": True},
        )
        assert result == {"empty": True}

    @pytest.mark.asyncio
    async def test_set_and_get_file(self, cache_with_file: PrecomputedCache) -> None:
        """Test set and get with file cache."""
        await cache_with_file.set(
            query_type="def_lookup",
            key="MyClass",
            data={"file": "test.py", "line": 10},
        )

        result = await cache_with_file.get(
            query_type="def_lookup",
            key="MyClass",
        )
        assert result == {"file": "test.py", "line": 10}

    @pytest.mark.asyncio
    async def test_invalidate_specific_key(self, cache: PrecomputedCache) -> None:
        """Test invalidating specific key."""
        await cache.set("symbol_deps", "func1", {"deps": ["a"]})
        await cache.set("symbol_deps", "func2", {"deps": ["b"]})

        count = await cache.invalidate(
            query_type="symbol_deps",
            key="func1",
        )
        assert count == 1

        # func1 should be gone
        result1 = await cache.get("symbol_deps", "func1")
        assert result1 is None

        # func2 should still exist
        result2 = await cache.get("symbol_deps", "func2")
        assert result2 == {"deps": ["b"]}

    @pytest.mark.asyncio
    async def test_invalidate_by_type(self, cache: PrecomputedCache) -> None:
        """Test invalidating all entries of a type."""
        await cache.set("symbol_deps", "func1", {"deps": ["a"]})
        await cache.set("symbol_deps", "func2", {"deps": ["b"]})
        await cache.set("def_lookup", "MyClass", {"file": "test.py"})

        count = await cache.invalidate(query_type="symbol_deps")
        assert count == 2

        # Both symbol_deps entries should be gone
        assert await cache.get("symbol_deps", "func1") is None
        assert await cache.get("symbol_deps", "func2") is None

        # def_lookup should still exist
        assert await cache.get("def_lookup", "MyClass") is not None

    @pytest.mark.asyncio
    async def test_invalidate_by_file_path(self, cache: PrecomputedCache) -> None:
        """Test invalidating by file path."""
        await cache.set(
            "symbol_deps",
            "func1",
            {"deps": ["a"]},
            file_paths=["/test.py"],
        )
        await cache.set(
            "symbol_deps",
            "func2",
            {"deps": ["b"]},
            file_paths=["/other.py"],
        )

        count = await cache.invalidate(file_path="/test.py")
        assert count == 1

        assert await cache.get("symbol_deps", "func1") is None
        assert await cache.get("symbol_deps", "func2") is not None

    @pytest.mark.asyncio
    async def test_invalidate_by_entity_id(self, cache: PrecomputedCache) -> None:
        """Test invalidating by entity ID."""
        await cache.set(
            "symbol_deps",
            "func1",
            {"deps": ["a"]},
            entity_ids=["entity-123"],
        )
        await cache.set(
            "symbol_deps",
            "func2",
            {"deps": ["b"]},
            entity_ids=["entity-456"],
        )

        count = await cache.invalidate(entity_id="entity-123")
        assert count == 1

        assert await cache.get("symbol_deps", "func1") is None
        assert await cache.get("symbol_deps", "func2") is not None

    @pytest.mark.asyncio
    async def test_refresh_on_index(self, cache: PrecomputedCache) -> None:
        """Test refresh after index updates."""
        await cache.set(
            "symbol_deps",
            "func1",
            {"deps": ["a"]},
            file_paths=["/changed.py"],
        )
        await cache.set(
            "symbol_deps",
            "func2",
            {"deps": ["b"]},
            file_paths=["/unchanged.py"],
        )

        count = await cache.refresh_on_index(
            changed_files=["/changed.py"],
        )
        assert count == 1

    def test_get_stats_initial(self, cache: PrecomputedCache) -> None:
        """Test initial statistics."""
        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["stores"] == 0
        assert stats["hit_rate"] == 0.0
        assert stats["memory_entries"] == 0

    @pytest.mark.asyncio
    async def test_get_stats_after_operations(self, cache: PrecomputedCache) -> None:
        """Test statistics after operations."""
        await cache.set("symbol_deps", "func1", {"deps": []})
        await cache.get("symbol_deps", "func1")  # Hit
        await cache.get("symbol_deps", "nonexistent")  # Miss

        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["stores"] == 1
        assert stats["hit_rate"] == 0.5
        assert stats["memory_entries"] == 1

    def test_make_key_normal(self, cache: PrecomputedCache) -> None:
        """Test key creation with normal input."""
        key = cache._make_key("symbol_deps", "func1")
        assert key == "test_project:symbol_deps:func1"

    def test_make_key_long_input(self, cache: PrecomputedCache) -> None:
        """Test key creation with long input is truncated."""
        long_key = "a" * 150  # Longer than 100 chars
        key = cache._make_key("symbol_deps", long_key)
        assert len(key) < len(long_key) + 50  # Should be truncated


class TestCacheQueryTypes:
    """Tests for cache query type constants."""

    def test_query_types_defined(self) -> None:
        """Test that all query types are defined."""
        assert "symbol_deps" in PrecomputedCache.QUERY_TYPES
        assert "file_refs" in PrecomputedCache.QUERY_TYPES
        assert "def_lookup" in PrecomputedCache.QUERY_TYPES
        assert "call_chain" in PrecomputedCache.QUERY_TYPES
        assert "lineage_paths" in PrecomputedCache.QUERY_TYPES
        assert "impact_graph" in PrecomputedCache.QUERY_TYPES
        assert "service_map" in PrecomputedCache.QUERY_TYPES
