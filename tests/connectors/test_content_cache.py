"""Tests for content cache and materialization.

Tests cover:
- ContentMaterializer creation and configuration
- Local file passthrough (no materialization needed)
- Remote content caching with hash-based paths
- Cache hits and misses
- Cache invalidation
- Integration with connector → parser flow
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.unit

from agentic_inquiry.connectors import (
    ContentMaterializer,
    SourceContent,
    SourceItem,
)
from agentic_inquiry.connectors.protocols import ConnectorProtocol


class MockRemoteConnector:
    """Mock connector that simulates remote content."""

    def __init__(self, content_map: dict[str, bytes]) -> None:
        """Initialize with URI -> content mapping."""
        self._content_map = content_map

    def list(self, root: str) -> AsyncIterator[SourceItem]:
        """Not implemented for this test."""
        raise NotImplementedError

    async def open(self, item: SourceItem) -> SourceContent:
        """Return content for the given item."""
        uri = item.uri
        if uri not in self._content_map:
            raise FileNotFoundError(f"Not found: {uri}")

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


class TestContentMaterializerCreation:
    """Tests for ContentMaterializer creation."""

    def test_create_with_default_root(self) -> None:
        """Create materializer with default cache root."""
        materializer = ContentMaterializer()
        assert materializer.cache_root.exists()

    def test_create_with_custom_root(self, temp_cache: Path) -> None:
        """Create materializer with custom cache root."""
        materializer = ContentMaterializer(cache_root=str(temp_cache))
        assert materializer.cache_root == temp_cache

    def test_create_ensures_directory(self) -> None:
        """Creating materializer ensures cache directory exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "nested" / "cache"
            materializer = ContentMaterializer(cache_root=str(cache_path))
            assert materializer.cache_root.exists()


class TestLocalFilePassthrough:
    """Tests for local file passthrough (no materialization)."""

    @pytest.mark.asyncio
    async def test_local_file_returns_uri_directly(self, temp_cache: Path) -> None:
        """Local files are returned without materialization."""
        materializer = ContentMaterializer(cache_root=str(temp_cache))

        # Create a local file item
        local_path = "/path/to/local/file.py"
        item = SourceItem(
            uri=local_path,
            content_hash="abc123",
        )

        # Mock connector (shouldn't be called for local files)
        connector = AsyncMock(spec=ConnectorProtocol)

        result = await materializer.materialize(connector, item)

        # Should return the original path
        assert result == local_path

        # Connector should not be called
        connector.open.assert_not_called()

    @pytest.mark.asyncio
    async def test_local_file_is_cached_returns_true(self, temp_cache: Path) -> None:
        """Local files are always considered cached."""
        materializer = ContentMaterializer(cache_root=str(temp_cache))

        item = SourceItem(uri="/path/to/file.py")
        assert await materializer.is_cached(item) is True


class TestRemoteMaterialization:
    """Tests for remote content materialization."""

    @pytest.mark.asyncio
    async def test_materialize_remote_content(self, temp_cache: Path) -> None:
        """Remote content is downloaded and cached."""
        materializer = ContentMaterializer(cache_root=str(temp_cache))

        content_data = b"print('hello from s3')"
        connector = MockRemoteConnector({
            "s3://bucket/path/file.py": content_data,
        })

        item = SourceItem(
            uri="s3://bucket/path/file.py",
            content_hash="abc123def456",
        )

        result = await materializer.materialize(connector, item)

        # Should return a local path in cache
        assert result.startswith(str(temp_cache))
        assert Path(result).exists()

        # Content should match
        assert Path(result).read_bytes() == content_data

    @pytest.mark.asyncio
    async def test_cache_hit_skips_download(self, temp_cache: Path) -> None:
        """Cached content is returned without re-downloading."""
        materializer = ContentMaterializer(cache_root=str(temp_cache))

        content_data = b"cached content"
        connector = MockRemoteConnector({
            "s3://bucket/file.txt": content_data,
        })

        item = SourceItem(
            uri="s3://bucket/file.txt",
            content_hash="cached123",
        )

        # First call - downloads
        result1 = await materializer.materialize(connector, item)
        assert Path(result1).exists()

        # Second call with new connector that would fail
        empty_connector = MockRemoteConnector({})
        result2 = await materializer.materialize(empty_connector, item)

        # Should return same path (cache hit, no download)
        assert result1 == result2

    @pytest.mark.asyncio
    async def test_requires_content_hash(self, temp_cache: Path) -> None:
        """Remote content without hash raises ValueError."""
        materializer = ContentMaterializer(cache_root=str(temp_cache))

        connector = MockRemoteConnector({})
        item = SourceItem(
            uri="s3://bucket/file.txt",
            content_hash=None,  # No hash
        )

        with pytest.raises(ValueError, match="content_hash"):
            await materializer.materialize(connector, item)

    @pytest.mark.asyncio
    async def test_preserves_file_extension(self, temp_cache: Path) -> None:
        """Cached files preserve original extension."""
        materializer = ContentMaterializer(cache_root=str(temp_cache))

        connector = MockRemoteConnector({
            "s3://bucket/script.py": b"# python",
            "gcs://bucket/data.json": b"{}",
        })

        py_item = SourceItem(
            uri="s3://bucket/script.py",
            content_hash="hash1",
        )
        json_item = SourceItem(
            uri="gcs://bucket/data.json",
            content_hash="hash2",
        )

        py_path = await materializer.materialize(connector, py_item)
        json_path = await materializer.materialize(connector, json_item)

        assert py_path.endswith(".py")
        assert json_path.endswith(".json")


class TestCacheManagement:
    """Tests for cache management operations."""

    @pytest.mark.asyncio
    async def test_invalidate_removes_cached_content(self, temp_cache: Path) -> None:
        """Invalidate removes cached content."""
        materializer = ContentMaterializer(cache_root=str(temp_cache))

        connector = MockRemoteConnector({
            "s3://bucket/file.txt": b"content",
        })

        item = SourceItem(
            uri="s3://bucket/file.txt",
            content_hash="to_invalidate",
        )

        # Materialize first
        path = await materializer.materialize(connector, item)
        assert Path(path).exists()

        # Invalidate
        result = await materializer.invalidate(item)
        assert result is True
        assert not Path(path).exists()

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent_returns_false(
        self, temp_cache: Path
    ) -> None:
        """Invalidate returns False for non-cached content."""
        materializer = ContentMaterializer(cache_root=str(temp_cache))

        item = SourceItem(
            uri="s3://bucket/never_cached.txt",
            content_hash="not_cached",
        )

        result = await materializer.invalidate(item)
        assert result is False

    @pytest.mark.asyncio
    async def test_clear_removes_all_content(self, temp_cache: Path) -> None:
        """Clear removes all cached content."""
        materializer = ContentMaterializer(cache_root=str(temp_cache))

        connector = MockRemoteConnector({
            "s3://bucket/file1.txt": b"content1",
            "s3://bucket/file2.txt": b"content2",
            "s3://bucket/file3.txt": b"content3",
        })

        # Cache multiple files
        for i in range(1, 4):
            item = SourceItem(
                uri=f"s3://bucket/file{i}.txt",
                content_hash=f"hash{i}",
            )
            await materializer.materialize(connector, item)

        # Verify cached
        stats = await materializer.get_cache_stats()
        assert stats["total_files"] == 3

        # Clear
        removed = await materializer.clear()
        assert removed == 3

        # Verify empty
        stats = await materializer.get_cache_stats()
        assert stats["total_files"] == 0

    @pytest.mark.asyncio
    async def test_get_cache_stats(self, temp_cache: Path) -> None:
        """Get cache statistics."""
        materializer = ContentMaterializer(cache_root=str(temp_cache))

        connector = MockRemoteConnector({
            "s3://bucket/file.txt": b"test content here",
        })

        item = SourceItem(
            uri="s3://bucket/file.txt",
            content_hash="stats_test",
        )

        await materializer.materialize(connector, item)

        stats = await materializer.get_cache_stats()
        assert stats["total_files"] == 1
        assert stats["total_bytes"] == len(b"test content here")
        assert stats["cache_root"] == str(temp_cache)


class TestIntegrationWithParsers:
    """Integration tests for connector → materializer → parser flow."""

    @pytest.mark.asyncio
    async def test_filesystem_connector_no_materialization(
        self, temp_cache: Path
    ) -> None:
        """FileSystemConnector items don't need materialization."""
        from agentic_inquiry.connectors import FileSystemConnector

        # Create a temp directory with a test file
        with tempfile.TemporaryDirectory() as project_dir:
            test_file = Path(project_dir) / "test.py"
            test_file.write_text("print('hello')")

            connector = FileSystemConnector(root=project_dir)
            materializer = ContentMaterializer(cache_root=str(temp_cache))

            # Get items from filesystem
            items = []
            async for item in connector.list():
                items.append(item)

            assert len(items) == 1

            # Materialize should return original path
            local_path = await materializer.materialize(connector, items[0])
            # Should be the original file path (resolved)
            assert Path(local_path).resolve() == test_file.resolve()

    @pytest.mark.asyncio
    async def test_remote_connector_materialization_for_parser(
        self, temp_cache: Path
    ) -> None:
        """Remote content is materialized to local path for parser."""
        materializer = ContentMaterializer(cache_root=str(temp_cache))

        # Simulate remote Python file
        python_code = b'''"""Sample module."""

def hello():
    """Say hello."""
    print("Hello from remote!")
'''
        connector = MockRemoteConnector({
            "s3://my-bucket/code/hello.py": python_code,
        })

        item = SourceItem(
            uri="s3://my-bucket/code/hello.py",
            content_hash="remote_py_hash",
            content_type="text/x-python",
        )

        # Materialize for parser
        local_path = await materializer.materialize(connector, item)

        # Verify local path exists and has correct content
        assert Path(local_path).exists()
        assert Path(local_path).read_bytes() == python_code
        assert local_path.endswith(".py")

        # Path can now be passed to ParserChain.parse(local_path)
        # (actual parser integration would require full parser setup)

    @pytest.mark.asyncio
    async def test_concurrent_materialization(self, temp_cache: Path) -> None:
        """Concurrent materializations don't conflict."""
        import asyncio

        materializer = ContentMaterializer(cache_root=str(temp_cache))

        # Same content accessed concurrently
        content = b"shared content"
        connector = MockRemoteConnector({
            "s3://bucket/shared.txt": content,
        })

        item = SourceItem(
            uri="s3://bucket/shared.txt",
            content_hash="concurrent_test",
        )

        # Concurrent materializations
        results = await asyncio.gather(
            materializer.materialize(connector, item),
            materializer.materialize(connector, item),
            materializer.materialize(connector, item),
        )

        # All should return same path
        assert len(set(results)) == 1
        assert Path(results[0]).read_bytes() == content
