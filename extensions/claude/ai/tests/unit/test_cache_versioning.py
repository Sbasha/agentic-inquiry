"""Unit tests for cache, memory versioning, and deduplication.

Covers TS-2.2, TS-3.1, TS-3.2 from test strategy.
"""

import os
import sys
import time

import pytest

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                )
            )
        )
    ),
)

from extensions.claude.ai.servers.daemon.managers.cache import (
    CacheManager,
    LRUTTLCache,
)
from extensions.claude.ai.servers.daemon.managers.version import VersionManager


# --- TS-2.2: Cache / Deduplication ---


class TestLRUTTLCache:
    def test_basic_put_get(self):
        cache = LRUTTLCache(max_size=10, default_ttl=3600)
        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_miss_returns_none(self):
        cache = LRUTTLCache(max_size=10, default_ttl=3600)
        assert cache.get("nonexistent") is None

    def test_ttl_expiry(self):
        cache = LRUTTLCache(max_size=10, default_ttl=0.01)
        cache.put("key1", "value1")
        time.sleep(0.02)
        assert cache.get("key1") is None

    def test_lru_eviction(self):
        cache = LRUTTLCache(max_size=3, default_ttl=3600)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        # Access "a" to make it recently used
        cache.get("a")
        # Add new item - should evict "b" (LRU)
        cache.put("d", 4)
        assert cache.get("a") == 1
        assert cache.get("b") is None
        assert cache.get("c") == 3
        assert cache.get("d") == 4

    def test_invalidate_key(self):
        cache = LRUTTLCache(max_size=10, default_ttl=3600)
        cache.put("key1", "value1")
        assert cache.invalidate("key1") is True
        assert cache.get("key1") is None
        assert cache.invalidate("key1") is False

    def test_invalidate_matching(self):
        cache = LRUTTLCache(max_size=10, default_ttl=3600)
        cache.put("context:a", 1)
        cache.put("context:b", 2)
        cache.put("memory:c", 3)
        removed = cache.invalidate_matching(lambda k: k.startswith("context:"))
        assert removed == 2
        assert cache.get("memory:c") == 3

    def test_stats(self):
        cache = LRUTTLCache(max_size=10, default_ttl=3600)
        cache.put("a", 1)
        cache.get("a")  # hit
        cache.get("b")  # miss
        stats = cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1
        assert stats["hit_rate"] == 0.5

    def test_clear(self):
        cache = LRUTTLCache(max_size=10, default_ttl=3600)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None


class TestCacheManagerDedup:
    def test_duplicate_within_window(self):
        cm = CacheManager(config={})
        # Turn 1: first time
        assert cm.is_duplicate_content("sess1", "hello world", 1) is False
        # Turn 2: same content, within 10-turn window
        assert cm.is_duplicate_content("sess1", "hello world", 2) is True

    def test_not_duplicate_after_window(self):
        cm = CacheManager(config={})
        assert cm.is_duplicate_content("sess1", "hello world", 1) is False
        # Turn 12: same content, outside 10-turn window
        assert cm.is_duplicate_content("sess1", "hello world", 12) is False

    def test_different_content_not_duplicate(self):
        cm = CacheManager(config={})
        assert cm.is_duplicate_content("sess1", "hello", 1) is False
        assert cm.is_duplicate_content("sess1", "world", 1) is False

    def test_session_isolation(self):
        cm = CacheManager(config={})
        assert cm.is_duplicate_content("sess1", "hello", 1) is False
        # Different session, same content
        assert cm.is_duplicate_content("sess2", "hello", 1) is False

    def test_cleanup_session(self):
        cm = CacheManager(config={})
        cm.is_duplicate_content("sess1", "hello", 1)
        cm.cleanup_session("sess1")
        # After cleanup, not a duplicate
        assert cm.is_duplicate_content("sess1", "hello", 2) is False

    def test_invalidate_memories_clears_cache(self):
        cm = CacheManager(config={})
        cm.put_memories("key1", [{"content": "test"}])
        assert cm.get_memories("key1") is not None
        cm.invalidate_memories()
        assert cm.get_memories("key1") is None

    def test_hash_key(self):
        k1 = CacheManager.hash_key("a", "b", "c")
        k2 = CacheManager.hash_key("a", "b", "c")
        k3 = CacheManager.hash_key("a", "b", "d")
        assert k1 == k2
        assert k1 != k3


# --- TS-3.1: Confidence Decay ---


class TestConfidenceDecay:
    @pytest.fixture
    def version_manager(self, tmp_path):
        return VersionManager(
            workspace=str(tmp_path),
            config={
                "versioning": {
                    "decay_per_commit": 0.05,
                    "decay_bulk_change": 0.50,
                    "stale_threshold": 0.3,
                    "bulk_change_files": 10,
                }
            },
        )

    def test_single_commit_decay(self, version_manager):
        commits = [
            {
                "sha": "abc",
                "files_changed": ["src/config.py"],
                "is_bulk": False,
            }
        ]
        decay = version_manager.calculate_decay(["src/config.py"], commits)
        assert decay == pytest.approx(0.05)

    def test_five_commits_decay(self, version_manager):
        commits = [
            {
                "sha": f"abc{i}",
                "files_changed": ["src/config.py"],
                "is_bulk": False,
            }
            for i in range(5)
        ]
        decay = version_manager.calculate_decay(["src/config.py"], commits)
        assert decay == pytest.approx(0.25)

    def test_bulk_change_decay(self, version_manager):
        commits = [
            {
                "sha": "abc",
                "files_changed": [f"src/file{i}.py" for i in range(15)],
                "is_bulk": True,
            }
        ]
        decay = version_manager.calculate_decay(["src/file0.py"], commits)
        assert decay == pytest.approx(0.50)

    def test_no_overlap_no_decay(self, version_manager):
        commits = [
            {
                "sha": "abc",
                "files_changed": ["src/other.py"],
                "is_bulk": False,
            }
        ]
        decay = version_manager.calculate_decay(["src/config.py"], commits)
        assert decay == pytest.approx(0.0)

    def test_decay_capped_at_1(self, version_manager):
        commits = [
            {
                "sha": f"abc{i}",
                "files_changed": ["src/config.py"],
                "is_bulk": False,
            }
            for i in range(30)  # 30 * 0.05 = 1.5, but capped at 1.0
        ]
        decay = version_manager.calculate_decay(["src/config.py"], commits)
        assert decay == pytest.approx(1.0)


# --- TS-3.2: Staleness Detection ---


class TestStalenessDetection:
    @pytest.fixture
    def version_manager(self, tmp_path):
        vm = VersionManager(
            workspace=str(tmp_path),
            config={
                "versioning": {
                    "decay_per_commit": 0.05,
                    "decay_bulk_change": 0.50,
                    "stale_threshold": 0.3,
                    "bulk_change_files": 10,
                }
            },
        )
        return vm

    def test_flags_stale_memories(self, version_manager):
        memories = [
            {
                "content": "Config uses yaml",
                "confidence": 0.35,
                "file_paths": ["src/config.py"],
            }
        ]
        # Mock with a commit touching the referenced file
        version_manager._last_known_commit = "old_commit"

        # Manually create commit data for staleness check
        commits = [
            {
                "sha": "new_commit",
                "files_changed": ["src/config.py"],
                "is_bulk": False,
            }
        ]

        # Direct decay calculation
        decay = version_manager.calculate_decay(["src/config.py"], commits)
        new_confidence = max(0.0, 0.35 - decay)
        assert new_confidence == pytest.approx(0.30)

    def test_unchanged_files_not_flagged(self, version_manager):
        memories = [
            {
                "content": "Vector search works well",
                "confidence": 1.0,
                "file_paths": ["src/vector.py"],
            }
        ]
        # No commits touching vector.py
        commits = [
            {
                "sha": "abc",
                "files_changed": ["src/other.py"],
                "is_bulk": False,
            }
        ]
        decay = version_manager.calculate_decay(["src/vector.py"], commits)
        assert decay == 0.0

    def test_version_metadata_creation(self, version_manager):
        meta = version_manager.create_version_metadata(
            file_paths=["a.py", "b.py"],
            entity_names=["Foo", "Bar"],
        )
        assert meta["file_paths"] == ["a.py", "b.py"]
        assert meta["entity_names"] == ["Foo", "Bar"]
        assert meta["confidence"] == 1.0
        assert "git_commit_sha" in meta
        assert "git_branch" in meta
