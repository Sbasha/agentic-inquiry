"""Base connector using fsspec.

Provides a foundation for all fsspec-based content connectors.
Subclasses customize ignore patterns, binary filtering, and backend-specific behavior.

See: docs/design/connector-architecture.md
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import mimetypes
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Set

import fsspec

from agentic_inquiry.connectors.protocols import ConnectorProtocol, HashTrackerProtocol
from agentic_inquiry.connectors.types import (
    SourceContent,
    SourceItem,
    compute_content_hash,
)

logger = logging.getLogger(__name__)

# Default patterns to ignore during file discovery
# NOTE: tests/ directories are NOT excluded by default and WILL be indexed.
# To exclude tests, add "tests/" or "test_*.py" to config ignore_patterns.
DEFAULT_IGNORE_PATTERNS: List[str] = [
    "*.pyc",
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    ".DS_Store",
    "*.egg-info",
    "*.egg",
    ".tox",
    ".nox",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
    ".venv",
    "venv",
    "*.lock",
]

# Default binary extensions (skip for text processing)
# Note: Document formats (.pdf, .doc, .docx, .xls, .xlsx, .ppt, .pptx) are
# intentionally NOT included - they have dedicated parsers in agentic_inquiry/parsers/
DEFAULT_BINARY_EXTENSIONS: Set[str] = {
    # Executables and compiled code
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
    ".obj",
    ".o",
    ".a",
    ".lib",
    ".pyc",
    ".pyo",
    ".class",
    ".jar",
    ".war",
    ".ear",
    # Archives
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
    # Images
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".bmp",
    ".ico",
    ".webp",
    ".svg",
    # Audio/Video
    ".mp3",
    ".mp4",
    ".avi",
    ".mov",
    ".mkv",
    ".wav",
    ".flac",
    # Fonts
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".otf",
}


class FsspecConnector(ConnectorProtocol):
    """Base connector using fsspec for file operations.

    Provides a foundation for all fsspec-based connectors. Subclasses
    customize ignore patterns, binary filtering, and backend-specific behavior.

    The connector uses asyncio.to_thread() to offload blocking fsspec calls
    to a thread pool, keeping the library async-only.

    Attributes:
        fs: The fsspec filesystem instance.
        ignore_patterns: List of glob patterns to ignore.
        binary_extensions: Set of extensions to treat as binary.

    Example:
        >>> connector = FsspecConnector(protocol="file")
        >>> async for item in connector.list("/path/to/project"):
        ...     if not connector._is_binary(item.uri):
        ...         content = await connector.open(item)
        ...         process(content.text)
    """

    def __init__(
        self,
        protocol: str = "file",
        storage_options: Optional[Dict[str, Any]] = None,
        ignore_patterns: Optional[List[str]] = None,
        binary_extensions: Optional[Set[str]] = None,
    ) -> None:
        """Initialize the connector.

        Args:
            protocol: fsspec protocol (e.g., 'file', 's3', 'gcs').
            storage_options: Backend-specific options (credentials, etc.).
            ignore_patterns: Glob patterns to ignore during enumeration.
                Defaults to DEFAULT_IGNORE_PATTERNS.
            binary_extensions: File extensions to treat as binary.
                Defaults to DEFAULT_BINARY_EXTENSIONS.
        """
        self._protocol = protocol
        self._storage_options = storage_options or {}
        self.ignore_patterns = ignore_patterns or list(DEFAULT_IGNORE_PATTERNS)
        self.binary_extensions = binary_extensions or set(DEFAULT_BINARY_EXTENSIONS)

        # Initialize filesystem lazily to allow subclass configuration
        self._fs: Optional[fsspec.AbstractFileSystem] = None

    @property
    def fs(self) -> fsspec.AbstractFileSystem:
        """Get the fsspec filesystem instance (lazy initialization)."""
        if self._fs is None:
            self._fs = fsspec.filesystem(self._protocol, **self._storage_options)
        return self._fs

    @property
    def protocol(self) -> str:
        """Get the fsspec protocol."""
        return self._protocol

    async def list(self, root: str) -> AsyncIterator[SourceItem]:
        """Enumerate files using fsspec.

        Yields SourceItem for each non-ignored file under root.
        Uses glob pattern to find all files recursively.

        Args:
            root: Root path or URI to enumerate.

        Yields:
            SourceItem for each discovered file.

        Note:
            Most fsspec filesystem implementations are synchronous.
            This method offloads blocking calls to a thread pool.
        """
        # Normalize root path
        root = root.rstrip("/")

        # Get all files recursively
        pattern = f"{root}/**"
        try:
            paths = await asyncio.to_thread(self.fs.glob, pattern)
        except Exception as e:
            logger.error("Failed to enumerate %s: %s", root, e)
            raise FileNotFoundError(f"Cannot enumerate {root}: {e}") from e

        for path in paths:
            # Check if it's a file (not directory)
            try:
                is_file = await asyncio.to_thread(self.fs.isfile, path)
            except Exception:
                continue

            if not is_file:
                continue

            # Check ignore patterns
            if self._should_ignore(path, root):
                continue

            # Get file info
            try:
                info = await asyncio.to_thread(self.fs.info, path)
            except Exception as e:
                logger.warning("Failed to get info for %s: %s", path, e)
                continue

            # Build URI
            uri = self._build_uri(path)

            # Extract metadata
            content_hash = self._extract_hash(info)
            modified_at = self._extract_modified_at(info)
            size = info.get("size")
            content_type = self._infer_content_type(path)

            yield SourceItem(
                uri=uri,
                content_hash=content_hash,
                modified_at=modified_at,
                size=size,
                content_type=content_type,
            )

    async def open(self, item: SourceItem) -> SourceContent:
        """Read content using fsspec.

        Fetches the actual content data for a source item.

        Args:
            item: SourceItem from list() to retrieve.

        Returns:
            SourceContent with data and metadata.

        Raises:
            FileNotFoundError: If item no longer exists.
        """
        # Extract path from URI
        path = self._uri_to_path(item.uri)

        # Read content in thread
        def _read_all() -> bytes:
            with self.fs.open(path, "rb") as f:
                return f.read()

        try:
            data = await asyncio.to_thread(_read_all)
        except Exception as e:
            logger.error("Failed to read %s: %s", item.uri, e)
            raise FileNotFoundError(f"Cannot read {item.uri}: {e}") from e

        # Determine encoding
        encoding = None if self._is_binary(item.uri) else "utf-8"

        # Build metadata
        metadata: Dict[str, Any] = {"uri": item.uri}
        if item.content_type:
            metadata["content_type"] = item.content_type

        return SourceContent(
            data=data,
            encoding=encoding,
            metadata=metadata,
        )

    def _should_ignore(self, path: str, root: str) -> bool:
        """Check if a path should be ignored.

        Args:
            path: Full path to check.
            root: Root path for relative matching.

        Returns:
            True if path matches any ignore pattern.
        """
        # Get filename and relative path for pattern matching
        filename = Path(path).name
        rel_path = path[len(root) :].lstrip("/") if path.startswith(root) else path

        for pattern in self.ignore_patterns:
            # Match against filename
            if fnmatch.fnmatch(filename, pattern):
                return True
            # Match against relative path
            if fnmatch.fnmatch(rel_path, pattern):
                return True
            # Match against any path component
            for component in Path(rel_path).parts:
                if fnmatch.fnmatch(component, pattern):
                    return True

        return False

    def _is_binary(self, path: str) -> bool:
        """Check if a file should be treated as binary.

        Args:
            path: File path to check.

        Returns:
            True if file extension is in binary_extensions.
        """
        suffix = Path(path).suffix.lower()
        return suffix in self.binary_extensions

    def _build_uri(self, path: str) -> str:
        """Build URI from path.

        For local filesystem, returns the path as-is.
        For remote backends, prefixes with protocol.

        Args:
            path: Raw path from fsspec.

        Returns:
            URI string.
        """
        if self._protocol == "file":
            return path
        return f"{self._protocol}://{path}"

    def _uri_to_path(self, uri: str) -> str:
        """Extract path from URI.

        Args:
            uri: URI to parse.

        Returns:
            Path without protocol prefix.
        """
        if "://" in uri and self._protocol != "file":
            return uri.split("://", 1)[1]
        return uri

    def _extract_hash(self, info: Dict[str, Any]) -> Optional[str]:
        """Extract content hash from fsspec info.

        Different backends provide hashes differently:
        - S3: ETag
        - GCS: md5Hash
        - Local: None (compute manually if needed)

        Args:
            info: File info dict from fsspec.

        Returns:
            Hash string if available, None otherwise.
        """
        # Try common hash fields
        for field in ["ETag", "etag", "md5Hash", "md5", "checksum"]:
            if field in info and info[field]:
                # Clean up ETag (remove quotes)
                value = str(info[field]).strip('"')
                return value
        return None

    def _extract_modified_at(self, info: Dict[str, Any]) -> Optional[Any]:
        """Extract modification time from fsspec info.

        Args:
            info: File info dict from fsspec.

        Returns:
            Modification time if available (type depends on backend).
        """
        for field in ["mtime", "LastModified", "updated", "timeModified"]:
            if field in info:
                return info[field]
        return None

    def _infer_content_type(self, path: str) -> Optional[str]:
        """Infer MIME type from file path.

        Args:
            path: File path.

        Returns:
            MIME type string or None if unknown.
        """
        mime_type, _ = mimetypes.guess_type(path)
        return mime_type

    async def compute_hash(self, item: SourceItem) -> str:
        """Compute content hash for an item.

        Useful when the backend doesn't provide a hash.

        Args:
            item: SourceItem to hash.

        Returns:
            SHA256 hash of content.
        """
        content = await self.open(item)
        return compute_content_hash(content.data)


class InMemoryFileTracker(HashTrackerProtocol):
    """In-memory implementation of HashTrackerProtocol.

    A simple reference implementation that stores processed hashes in memory.
    Useful for testing and single-process scenarios.

    Note:
        This implementation is not persistent across restarts and not
        thread-safe. For production use, consider a persistent implementation
        with proper synchronization.

    Example:
        >>> tracker = InMemoryFileTracker()
        >>> await tracker.mark_processed("abc123")
        >>> assert await tracker.is_processed("abc123")
        >>> assert await tracker.get_processed_count() == 1
    """

    def __init__(self) -> None:
        """Initialize the in-memory tracker."""
        self._processed: Set[str] = set()

    async def is_processed(self, file_hash: str) -> bool:
        """Check if a file hash has been processed.

        Args:
            file_hash: Content hash to check.

        Returns:
            True if the hash has been marked as processed.
        """
        return file_hash in self._processed

    async def mark_processed(self, file_hash: str) -> None:
        """Mark a file hash as processed.

        Args:
            file_hash: Content hash to mark.
        """
        self._processed.add(file_hash)

    async def get_processed_count(self) -> int:
        """Get the count of processed file hashes.

        Returns:
            Number of unique hashes marked as processed.
        """
        return len(self._processed)

    async def clear(self) -> int:
        """Clear all tracking data.

        Returns:
            Number of entries cleared.
        """
        count = len(self._processed)
        self._processed.clear()
        return count
