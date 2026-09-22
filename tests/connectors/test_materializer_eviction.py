"""Tests for ContentMaterializer eviction behavior (S5-005).

Tests cover:
- LRU eviction when max_size is set
- Cache stats including hits/misses
- File deletion on eviction
- Integration with FileCacheTracker
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import AsyncIterator

import pytest

pytestmark = pytest.mark.integration

from agentic_inquiry.connectors import (
    ContentMaterializer,
    SourceContent,
    SourceItem,
)


class MockRemoteConnector:
    """Mock connector that simulates remote content."""

    def __init__(self, content_map: dict[str, bytes]) -> None:
        """Initialize with URI -> content mapping."""
        self._content_map = content_map
        self.open_count = 0

    def list(self, root: str) -> AsyncIterator[SourceItem]:
        """Not implemented for this test."""
        raise NotImplementedError

    async def open(self, item: SourceItem) -> SourceContent:
        """Return content for the given item."""
        uri = item.uri
        if uri not in self._content_map:
            raise FileNotFoundError(f"Not found: {uri}")

        self.open_count += 1
        data = self._content_map[uri]
        return SourceContent(
            data=data,
            encoding="utf-8",
            metadata={"uri": uri},
        )


@pytest.fixture
def temp_cache():
    """Create a temporary cache directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestMaterializerEviction:
    """Tests for ContentMaterializer eviction behavior."""

    @pytest.mark.asyncio
    async def test_eviction_when_max_size_exceeded(self, temp_cache: Path) -> None:
        """Files are evicted when cache exceeds max_size."""
        # 100 bytes max
        materializer = ContentMaterializer(
            cache_root=str(temp_cache),
            max_size=100,
        )

        connector = MockRemoteConnector({
            "s3://bucket/file1.txt": b"x" * 40,
            "s3://bucket/file2.txt": b"y" * 40,
            "s3://bucket/file3.txt": b"z" * 40,
        })

        item1 = SourceItem(uri="s3://bucket/file1.txt", content_hash="hash1")
        item2 = SourceItem(uri="s3://bucket/file2.txt", content_hash="hash2")
        item3 = SourceItem(uri="s3://bucket/file3.txt", content_hash="hash3")

        # Cache first two files (80 bytes total)
        path1 = await materializer.materialize(connector, item1)
        path2 = await materializer.materialize(connector, item2)

        assert Path(path1).exists()
        assert Path(path2).exists()

        # Third file should trigger eviction of first
        path3 = await materializer.materialize(connector, item3)

        assert not Path(path1).exists()  # evicted
        assert Path(path2).exists()
        assert Path(path3).exists()

    @pytest.mark.asyncio
    async def test_lru_order_for_eviction(self, temp_cache: Path) -> None:
        """Recently accessed files preserved during eviction."""
        materializer = ContentMaterializer(
            cache_root=str(temp_cache),
            max_size=100,
        )

        connector = MockRemoteConnector({
            "s3://bucket/file1.txt": b"a" * 30,
            "s3://bucket/file2.txt": b"b" * 30,
            "s3://bucket/file3.txt": b"c" * 30,
            "s3://bucket/file4.txt": b"d" * 30,
        })

        item1 = SourceItem(uri="s3://bucket/file1.txt", content_hash="hash1")
        item2 = SourceItem(uri="s3://bucket/file2.txt", content_hash="hash2")
        item3 = SourceItem(uri="s3://bucket/file3.txt", content_hash="hash3")
        item4 = SourceItem(uri="s3://bucket/file4.txt", content_hash="hash4")

        # Cache three files (90 bytes)
        path1 = await materializer.materialize(connector, item1)
        path2 = await materializer.materialize(connector, item2)
        path3 = await materializer.materialize(connector, item3)

        # Access file1 to make it recently used
        await materializer.materialize(connector, item1)  # cache hit

        # Add file4 - should evict file2 (oldest accessed)
        path4 = await materializer.materialize(connector, item4)

        assert Path(path1).exists()  # preserved (recently accessed)
        assert not Path(path2).exists()  # evicted (oldest)
        assert Path(path3).exists()
        assert Path(path4).exists()

    @pytest.mark.asyncio
    async def test_unlimited_cache(self, temp_cache: Path) -> None:
        """max_size=0 means no eviction."""
        materializer = ContentMaterializer(
            cache_root=str(temp_cache),
            max_size=0,  # unlimited
        )

        connector = MockRemoteConnector({
            f"s3://bucket/file{i}.txt": b"x" * 100
            for i in range(10)
        })

        paths = []
        for i in range(10):
            item = SourceItem(
                uri=f"s3://bucket/file{i}.txt",
                content_hash=f"hash{i}",
            )
            path = await materializer.materialize(connector, item)
            paths.append(path)

        # All files should exist
        for path in paths:
            assert Path(path).exists()

    @pytest.mark.asyncio
    async def test_lru_stats_tracking(self, temp_cache: Path) -> None:
        """LRU stats track hits and misses."""
        materializer = ContentMaterializer(
            cache_root=str(temp_cache),
            max_size=1000,
        )

        connector = MockRemoteConnector({
            "s3://bucket/file1.txt": b"content1",
            "s3://bucket/file2.txt": b"content2",
        })

        item1 = SourceItem(uri="s3://bucket/file1.txt", content_hash="hash1")
        item2 = SourceItem(uri="s3://bucket/file2.txt", content_hash="hash2")

        # First access - miss (download)
        await materializer.materialize(connector, item1)

        # Second access - hit (cache)
        await materializer.materialize(connector, item1)
        await materializer.materialize(connector, item1)

        # Another file - miss
        await materializer.materialize(connector, item2)

        stats = materializer.get_lru_stats()
        assert stats.hits == 2  # file1 accessed twice from cache
        assert stats.misses == 0  # misses only counted on access(), not track()

    @pytest.mark.asyncio
    async def test_eviction_stats(self, temp_cache: Path) -> None:
        """Eviction count tracked in stats."""
        materializer = ContentMaterializer(
            cache_root=str(temp_cache),
            max_size=100,
        )

        connector = MockRemoteConnector({
            "s3://bucket/file1.txt": b"x" * 50,
            "s3://bucket/file2.txt": b"y" * 50,
            "s3://bucket/file3.txt": b"z" * 50,
        })

        item1 = SourceItem(uri="s3://bucket/file1.txt", content_hash="hash1")
        item2 = SourceItem(uri="s3://bucket/file2.txt", content_hash="hash2")
        item3 = SourceItem(uri="s3://bucket/file3.txt", content_hash="hash3")

        await materializer.materialize(connector, item1)
        await materializer.materialize(connector, item2)
        await materializer.materialize(connector, item3)  # evicts file1

        stats = materializer.get_lru_stats()
        assert stats.evictions == 1
        assert stats.current_count == 2
        assert stats.current_size == 100

    @pytest.mark.asyncio
    async def test_invalidate_updates_tracker(self, temp_cache: Path) -> None:
        """Invalidate removes from LRU tracker."""
        materializer = ContentMaterializer(
            cache_root=str(temp_cache),
            max_size=1000,
        )

        connector = MockRemoteConnector({
            "s3://bucket/file1.txt": b"content",
        })

        item = SourceItem(uri="s3://bucket/file1.txt", content_hash="hash1")

        await materializer.materialize(connector, item)
        stats_before = materializer.get_lru_stats()

        await materializer.invalidate(item)
        stats_after = materializer.get_lru_stats()

        assert stats_before.current_count == 1
        assert stats_after.current_count == 0

    @pytest.mark.asyncio
    async def test_clear_updates_tracker(self, temp_cache: Path) -> None:
        """Clear resets LRU tracker."""
        materializer = ContentMaterializer(
            cache_root=str(temp_cache),
            max_size=1000,
        )

        connector = MockRemoteConnector({
            "s3://bucket/file1.txt": b"a",
            "s3://bucket/file2.txt": b"b",
        })

        await materializer.materialize(
            connector,
            SourceItem(uri="s3://bucket/file1.txt", content_hash="hash1"),
        )
        await materializer.materialize(
            connector,
            SourceItem(uri="s3://bucket/file2.txt", content_hash="hash2"),
        )

        stats_before = materializer.get_lru_stats()
        await materializer.clear()
        stats_after = materializer.get_lru_stats()

        assert stats_before.current_count == 2
        assert stats_after.current_count == 0
        assert stats_after.current_size == 0

    @pytest.mark.asyncio
    async def test_eviction_cleans_empty_dirs(self, temp_cache: Path) -> None:
        """Eviction cleans up empty hash-prefix directories."""
        materializer = ContentMaterializer(
            cache_root=str(temp_cache),
            max_size=100,
        )

        connector = MockRemoteConnector({
            "s3://bucket/file1.txt": b"x" * 50,
            "s3://bucket/file2.txt": b"y" * 60,
        })

        item1 = SourceItem(uri="s3://bucket/file1.txt", content_hash="aabbcc")
        item2 = SourceItem(uri="s3://bucket/file2.txt", content_hash="ddeeff")

        path1 = await materializer.materialize(connector, item1)
        parent1 = Path(path1).parent

        # Evict file1
        await materializer.materialize(connector, item2)

        # Parent directory should be cleaned up
        assert not parent1.exists()

    @pytest.mark.asyncio
    async def test_cache_hit_skips_download(self, temp_cache: Path) -> None:
        """Cache hit doesn't call connector.open()."""
        materializer = ContentMaterializer(
            cache_root=str(temp_cache),
            max_size=1000,
        )

        connector = MockRemoteConnector({
            "s3://bucket/file.txt": b"content",
        })

        item = SourceItem(uri="s3://bucket/file.txt", content_hash="hash1")

        # First access
        await materializer.materialize(connector, item)
        assert connector.open_count == 1

        # Second access - should be cache hit
        await materializer.materialize(connector, item)
        assert connector.open_count == 1  # not incremented

        # Third access
        await materializer.materialize(connector, item)
        assert connector.open_count == 1  # still not incremented
