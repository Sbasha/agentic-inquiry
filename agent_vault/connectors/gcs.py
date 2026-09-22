"""GCS connector.

Provides access to GCS buckets for indexing via fsspec/gcsfs.

Requires gcsfs package: pip install gcsfs
Or install with: pip install agent-vault[gcs]

See: docs/design/connector-architecture.md
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, List, Optional, Set

from agent_vault.connectors.base import (
    DEFAULT_BINARY_EXTENSIONS,
    DEFAULT_IGNORE_PATTERNS,
    FsspecConnector,
)
from agent_vault.connectors.registry import register_connector

logger = logging.getLogger(__name__)


@register_connector("gcs")
class GCSConnector(FsspecConnector):
    """GCS connector using gcsfs via fsspec.

    Provides access to GCS buckets for content enumeration and retrieval.
    Uses gcsfs for underlying GCS operations with async I/O via to_thread.

    Authentication:
        Credentials can be provided via:
        1. storage_options dict (token, project)
        2. Environment variable (GOOGLE_APPLICATION_CREDENTIALS)
        3. Service account (when running on GCP infrastructure)
        4. gcloud SDK credentials (~/.config/gcloud/)

    Attributes:
        bucket: The GCS bucket name.
        prefix: Optional prefix to filter objects (subdirectory).

    Example:
        >>> connector = GCSConnector(bucket="my-bucket")
        >>> async for item in connector.list():
        ...     content = await connector.open(item)
        ...     process(content)
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        storage_options: Optional[Dict[str, Any]] = None,
        ignore_patterns: Optional[List[str]] = None,
        binary_extensions: Optional[Set[str]] = None,
    ) -> None:
        """Initialize the GCS connector.

        Args:
            bucket: GCS bucket name.
            prefix: Optional prefix for filtering objects.
            storage_options: gcsfs-specific options including credentials.
                Common options:
                - token: Path to service account JSON or "google_default"
                - project: GCP project ID
                - access: "read_only" or "read_write"
            ignore_patterns: Glob patterns to ignore during enumeration.
            binary_extensions: File extensions to treat as binary.

        Raises:
            ImportError: If gcsfs is not installed.
        """
        try:
            import gcsfs  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "gcsfs is required for GCS connector. "
                "Install with: pip install gcsfs or pip install agent-vault[gcs]"
            ) from e

        opts = storage_options.copy() if storage_options else {}

        super().__init__(
            protocol="gcs",
            storage_options=opts,
            ignore_patterns=ignore_patterns or list(DEFAULT_IGNORE_PATTERNS),
            binary_extensions=binary_extensions or set(DEFAULT_BINARY_EXTENSIONS),
        )

        self._bucket = bucket
        self._prefix = prefix.strip("/")

    @property
    def bucket(self) -> str:
        """Get the GCS bucket name."""
        return self._bucket

    @property
    def prefix(self) -> str:
        """Get the GCS prefix (subdirectory)."""
        return self._prefix

    def _get_root_path(self) -> str:
        """Get the root path for enumeration."""
        if self._prefix:
            return f"{self._bucket}/{self._prefix}"
        return self._bucket

    async def list(self, root: str = "") -> AsyncIterator["SourceItem"]:
        """Enumerate objects in the GCS bucket.

        Args:
            root: Optional subdirectory within the bucket/prefix.

        Yields:
            SourceItem for each discovered object.
        """
        if root:
            base = self._get_root_path()
            enum_root = f"{base}/{root.strip('/')}"
        else:
            enum_root = self._get_root_path()

        async for item in super().list(enum_root):
            yield item

    def _build_uri(self, path: str) -> str:
        """Build GCS URI from path.

        Uses the ``gcs://`` scheme to match the registered connector name
        (``"gcs"``), ``SourceItem.protocol``, and the connector guide. The
        fsspec *protocol* passed to the base (``protocol="gcs"``) is a separate
        concern — gcsfs accepts ``gcs`` — and is intentionally left unchanged.

        Args:
            path: Raw path from fsspec (bucket/object format).

        Returns:
            GCS URI in format: gcs://bucket/object
        """
        return f"gcs://{path}"

    def _uri_to_path(self, uri: str) -> str:
        """Extract path from a GCS URI.

        Accepts both the current ``gcs://`` scheme and the legacy ``gs://``
        scheme, so any URIs persisted before the scheme was aligned still
        resolve rather than being treated as raw paths.

        Args:
            uri: GCS URI to parse.

        Returns:
            Path in bucket/object format.
        """
        if uri.startswith("gcs://"):
            return uri[6:]  # Remove "gcs://" prefix
        if uri.startswith("gs://"):
            return uri[5:]  # Legacy scheme, kept for backward compatibility
        return uri


if TYPE_CHECKING:
    from agent_vault.connectors.types import SourceItem
