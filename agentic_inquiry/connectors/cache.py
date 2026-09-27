"""Content cache for remote connectors.

Materializes remote content to local paths for parser compatibility.
Uses deterministic cache paths based on content hash for deduplication.
Implements LRU eviction when max_size is set.

See: docs/design/connector-architecture.md
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

from agentic_inquiry.connectors.lru_cache import CacheStats, FileCacheTracker

if TYPE_CHECKING:
    from agentic_inquiry.connectors.protocols import ConnectorProtocol
    from agentic_inquiry.connectors.types import SourceItem

logger = logging.getLogger(__name__)


class ContentMaterializer:
    """Materializes remote content to local paths for parser compatibility.

    Remote connectors (S3, GCS, GitHub, etc.) cannot directly provide local paths
    for parsers. This class downloads content to a local cache directory with
    deterministic paths based on content hash.

    The cache uses a two-level directory structure:
        {cache_root}/{hash_prefix}/{full_hash}.{extension}

    This prevents filesystem issues with too many files in a single directory
    and enables content deduplication across different URIs.

    Attributes:
        cache_root: Root directory for cached content.
        max_size: Maximum cache size in bytes (0 = unlimited).

    Example:
        >>> materializer = ContentMaterializer(cache_root="/tmp/ai_cache")
        >>> local_path = await materializer.materialize(connector, item)
        >>> # local_path is now a local file path suitable for parsers
        >>> parsed = await parser_chain.parse(local_path)
    """

    def __init__(
        self,
        cache_root: Optional[str] = None,
        max_size: int = 0,
    ) -> None:
        """Initialize the content materializer.

        Args:
            cache_root: Root directory for cached content.
                If None, uses a temp directory.
            max_size: Maximum cache size in bytes.
                0 means unlimited (no eviction).
        """
        if cache_root is None:
            cache_root = os.path.join(tempfile.gettempdir(), "agentic-inquiry_cache")

        self._cache_root = Path(cache_root)
        self._max_size = max_size
        self._lock = asyncio.Lock()

        # LRU cache tracker for size-based eviction
        self._tracker = FileCacheTracker(max_size=max_size)

        # Ensure cache directory exists
        self._cache_root.mkdir(parents=True, exist_ok=True)

    @property
    def cache_root(self) -> Path:
        """Get the cache root directory."""
        return self._cache_root

    async def materialize(
        self,
        connector: "ConnectorProtocol",
        item: "SourceItem",
    ) -> str:
        """Materialize remote content to a local path.

        If the content is already cached (based on content_hash), returns
        the existing cache path without re-downloading.

        For local filesystem items (no "://" in URI), returns the URI directly
        since no materialization is needed.

        When max_size is set, tracks cached files and evicts least recently
        used entries when the cache exceeds the limit.

        Args:
            connector: Connector to open the content.
            item: SourceItem to materialize.

        Returns:
            Local file path containing the content.

        Raises:
            ValueError: If item has no content_hash (required for caching).
            FileNotFoundError: If content cannot be retrieved.
        """
        # Local files don't need materialization
        if item.is_local:
            return item.uri

        # Remote content requires hash for deterministic caching
        if item.content_hash is None:
            raise ValueError(
                f"Cannot materialize remote content without content_hash: {item.uri}"
            )

        # Compute cache path
        cache_path = self._get_cache_path(item)
        cache_path_str = str(cache_path)

        # Check if already cached
        if cache_path.exists():
            logger.debug("Cache hit for %s at %s", item.uri, cache_path)
            # Record access for LRU tracking
            await self._tracker.access(cache_path_str)
            return cache_path_str

        # Download and cache
        async with self._lock:
            # Double-check after acquiring lock
            if cache_path.exists():
                await self._tracker.access(cache_path_str)
                return cache_path_str

            logger.debug("Materializing %s to %s", item.uri, cache_path)

            # Ensure parent directory exists
            cache_path.parent.mkdir(parents=True, exist_ok=True)

            # Fetch content
            content = await connector.open(item)
            content_size = len(content.data)

            # Write to cache atomically (write to temp, then rename)
            temp_path = cache_path.with_suffix(".tmp")
            try:
                await asyncio.to_thread(temp_path.write_bytes, content.data)
                await asyncio.to_thread(temp_path.rename, cache_path)
            except Exception:
                # Clean up temp file on failure
                if temp_path.exists():
                    temp_path.unlink()
                raise

            # Track in LRU cache and handle evictions
            evicted = await self._tracker.track(cache_path_str, content_size)

            # Delete evicted files
            for evicted_path in evicted:
                await self._delete_cache_file(evicted_path)

            logger.info("Materialized %s (%d bytes)", item.uri, content_size)

        return cache_path_str

    async def _delete_cache_file(self, cache_path: str) -> None:
        """Delete a cached file and clean up empty parent directories.

        Args:
            cache_path: Path to the cached file to delete.
        """
        path = Path(cache_path)
        try:
            if path.exists():
                await asyncio.to_thread(path.unlink)
                logger.debug("Deleted evicted cache file: %s", cache_path)

                # Clean up empty parent directory (hash prefix dir)
                parent = path.parent
                if parent.exists() and not any(parent.iterdir()):
                    await asyncio.to_thread(parent.rmdir)
        except Exception as e:
            logger.warning("Failed to delete evicted cache file %s: %s", cache_path, e)

    async def is_cached(self, item: "SourceItem") -> bool:
        """Check if content is already cached.

        Args:
            item: SourceItem to check.

        Returns:
            True if content is cached locally.
        """
        if item.is_local:
            return True

        if item.content_hash is None:
            return False

        cache_path = self._get_cache_path(item)
        return cache_path.exists()

    async def invalidate(self, item: "SourceItem") -> bool:
        """Remove cached content for an item.

        Args:
            item: SourceItem to invalidate.

        Returns:
            True if cache was invalidated, False if not cached.
        """
        if item.is_local or item.content_hash is None:
            return False

        cache_path = self._get_cache_path(item)
        cache_path_str = str(cache_path)

        if cache_path.exists():
            await asyncio.to_thread(cache_path.unlink)
            # Remove from LRU tracker
            await self._tracker.remove(cache_path_str)
            logger.debug("Invalidated cache for %s", item.uri)
            return True
        return False

    async def clear(self) -> int:
        """Clear all cached content.

        Returns:
            Number of files removed.
        """
        import shutil

        count = 0
        for child in self._cache_root.iterdir():
            if child.is_dir():
                # Remove hash directories
                files = list(child.iterdir())
                count += len(files)
                await asyncio.to_thread(shutil.rmtree, child)
            elif child.is_file():
                await asyncio.to_thread(child.unlink)
                count += 1

        # Clear the LRU tracker
        await self._tracker.clear()

        logger.info("Cleared %d cached files", count)
        return count

    def _get_cache_path(self, item: "SourceItem") -> Path:
        """Compute deterministic cache path for an item.

        Uses content_hash for path determination, with a two-level
        directory structure to avoid filesystem issues.

        Args:
            item: SourceItem with content_hash.

        Returns:
            Path where content should be cached.
        """
        assert item.content_hash is not None

        # Use first 2 chars of hash as subdirectory
        hash_prefix = item.content_hash[:2]
        full_hash = item.content_hash

        # Preserve original extension for MIME type detection
        ext = Path(item.uri).suffix or ".bin"

        return self._cache_root / hash_prefix / f"{full_hash}{ext}"

    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with total_files, total_bytes, and directory count.
        """

        def _collect_stats() -> Dict[str, Any]:
            total_files = 0
            total_bytes = 0
            directories = 0

            for child in self._cache_root.iterdir():
                if child.is_dir():
                    directories += 1
                    for file in child.iterdir():
                        if file.is_file():
                            total_files += 1
                            total_bytes += file.stat().st_size

            return {
                "total_files": total_files,
                "total_bytes": total_bytes,
                "directories": directories,
                "cache_root": str(self._cache_root),
            }

        return await asyncio.to_thread(_collect_stats)

    def get_lru_stats(self) -> CacheStats:
        """Get LRU cache performance statistics.

        Returns:
            CacheStats with hits, misses, evictions, and hit_rate.
        """
        return self._tracker.get_stats()
