"""Connector data types.

Defines canonical types for content discovery and retrieval:
- SourceItem: Discoverable unit of content (metadata only)
- SourceContent: Retrieved content with data

See: docs/design/connector-architecture.md
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class SourceItem:
    """A discoverable unit of content.

    Represents metadata about a content source without the actual content.
    Used for enumeration, change detection, and filtering.

    Attributes:
        uri: Stable identifier for the content.
            - Filesystem: absolute local path (not file:// URI)
            - S3: s3://bucket/key
            - GCS: gcs://bucket/object
            - GitHub: github://org/repo/path@sha
        content_hash: Optional stable hash for change detection.
            May come from backend (ETag, md5) or be computed locally.
        modified_at: Optional last modification timestamp.
        size: Optional size in bytes.
        content_type: Optional MIME type or inferred type.
        metadata: Additional source-specific metadata.

    URI Conventions:
        - Filesystem paths use absolute local paths (e.g., /home/user/file.py)
          to remain compatible with validate_file_path() and path-based tooling.
        - Remote URIs use protocol prefixes (s3://, gcs://, github://).

    Example:
        >>> item = SourceItem(
        ...     uri="/path/to/file.py",
        ...     content_hash="abc123",
        ...     size=1024,
        ...     content_type="text/x-python",
        ... )
        >>> item.is_local
        True
    """

    uri: str
    content_hash: Optional[str] = None
    modified_at: Optional[datetime] = None
    size: Optional[int] = None
    content_type: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate URI is not empty."""
        if not self.uri:
            raise ValueError("uri cannot be empty")

    @property
    def is_local(self) -> bool:
        """Check if this is a local filesystem path.

        Returns:
            True if the URI is a local path (no protocol prefix).
        """
        return "://" not in self.uri

    @property
    def protocol(self) -> str:
        """Extract protocol from URI.

        Returns:
            Protocol string (e.g., 's3', 'gcs', 'github') or 'file' for local paths.
        """
        if "://" in self.uri:
            return self.uri.split("://", 1)[0]
        return "file"

    @property
    def path(self) -> str:
        """Extract path portion from URI.

        Returns:
            Path without protocol prefix.
        """
        if "://" in self.uri:
            return self.uri.split("://", 1)[1]
        return self.uri

    def with_hash(self, content_hash: str) -> "SourceItem":
        """Return a copy with updated content_hash.

        Args:
            content_hash: New hash value.

        Returns:
            New SourceItem with updated hash.
        """
        return SourceItem(
            uri=self.uri,
            content_hash=content_hash,
            modified_at=self.modified_at,
            size=self.size,
            content_type=self.content_type,
            metadata=self.metadata,
        )


@dataclass(frozen=True)
class SourceContent:
    """Retrieved content with metadata.

    Contains the actual data from a content source along with
    encoding and source-specific metadata.

    Attributes:
        data: Raw content bytes.
        encoding: Optional text encoding (e.g., 'utf-8').
            None for binary content.
        metadata: Source-specific metadata (must be JSON-serializable).
            Should include 'uri' for provenance tracking.

    Example:
        >>> content = SourceContent(
        ...     data=b"print('hello')",
        ...     encoding="utf-8",
        ...     metadata={"uri": "/path/to/file.py"},
        ... )
        >>> content.text
        "print('hello')"
    """

    data: bytes
    encoding: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        """Decode data as text using the specified encoding.

        Returns:
            Decoded text content.

        Raises:
            ValueError: If encoding is not specified.
            UnicodeDecodeError: If data cannot be decoded.
        """
        if self.encoding is None:
            raise ValueError("Cannot decode binary content as text (encoding is None)")
        return self.data.decode(self.encoding)

    @property
    def is_binary(self) -> bool:
        """Check if this is binary content.

        Returns:
            True if encoding is None (binary content).
        """
        return self.encoding is None

    @property
    def size(self) -> int:
        """Get content size in bytes.

        Returns:
            Length of data.
        """
        return len(self.data)


def compute_content_hash(data: bytes, algorithm: str = "sha256") -> str:
    """Compute a hash of content for change detection.

    Args:
        data: Content bytes to hash.
        algorithm: Hash algorithm (default: sha256).

    Returns:
        Hex-encoded hash string.

    Example:
        >>> compute_content_hash(b"hello world")
        'b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9'
    """
    hasher = hashlib.new(algorithm)
    hasher.update(data)
    return hasher.hexdigest()
