"""S3 connector.

Provides access to S3 buckets for indexing via fsspec/s3fs.

Requires s3fs package: pip install s3fs
Or install with: pip install agent-vault[s3]

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


@register_connector("s3")
class S3Connector(FsspecConnector):
    """S3 connector using s3fs via fsspec.

    Provides access to S3 buckets for content enumeration and retrieval.
    Uses s3fs for underlying S3 operations with async I/O via to_thread.

    Authentication:
        Credentials can be provided via:
        1. storage_options dict (key, secret, token)
        2. Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
        3. IAM role (when running on AWS infrastructure)
        4. AWS credentials file (~/.aws/credentials)

    Attributes:
        bucket: The S3 bucket name.
        prefix: Optional prefix to filter objects (subdirectory).

    Example:
        >>> # Using environment variables or IAM role
        >>> connector = S3Connector(bucket="my-bucket")
        >>> async for item in connector.list():
        ...     content = await connector.open(item)
        ...     process(content)

        >>> # Explicit credentials
        >>> connector = S3Connector(
        ...     bucket="my-bucket",
        ...     storage_options={
        ...         "key": "AKIAIOSFODNN7EXAMPLE",
        ...         "secret": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        ...         "region": "us-east-1",
        ...     }
        ... )
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        storage_options: Optional[Dict[str, Any]] = None,
        ignore_patterns: Optional[List[str]] = None,
        binary_extensions: Optional[Set[str]] = None,
        endpoint_url: Optional[str] = None,
    ) -> None:
        """Initialize the S3 connector.

        Args:
            bucket: S3 bucket name.
            prefix: Optional prefix for filtering objects.
                Example: "data/raw/" to only list objects under that path.
            storage_options: s3fs-specific options including credentials.
                Common options:
                - key: AWS access key ID
                - secret: AWS secret access key
                - token: AWS session token (for temporary credentials)
                - region: AWS region
                - endpoint_url: Custom endpoint (for S3-compatible stores)
                - anon: Set to True for anonymous access to public buckets
            ignore_patterns: Glob patterns to ignore during enumeration.
                Defaults to DEFAULT_IGNORE_PATTERNS.
            binary_extensions: File extensions to treat as binary.
                Defaults to DEFAULT_BINARY_EXTENSIONS.
            endpoint_url: Custom S3 endpoint URL (MinIO, LocalStack, etc.).
                Also can be specified via storage_options["endpoint_url"].

        Raises:
            ImportError: If s3fs is not installed.
        """
        # Validate s3fs availability early
        try:
            import s3fs  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "s3fs is required for S3 connector. "
                "Install with: pip install s3fs or pip install agent-vault[s3]"
            ) from e

        # Build storage options
        opts = storage_options.copy() if storage_options else {}

        # Handle endpoint_url shorthand
        if endpoint_url:
            opts["endpoint_url"] = endpoint_url

        super().__init__(
            protocol="s3",
            storage_options=opts,
            ignore_patterns=ignore_patterns or list(DEFAULT_IGNORE_PATTERNS),
            binary_extensions=binary_extensions or set(DEFAULT_BINARY_EXTENSIONS),
        )

        self._bucket = bucket
        self._prefix = prefix.strip("/")

    @property
    def bucket(self) -> str:
        """Get the S3 bucket name."""
        return self._bucket

    @property
    def prefix(self) -> str:
        """Get the S3 prefix (subdirectory)."""
        return self._prefix

    def _get_root_path(self) -> str:
        """Get the root path for enumeration.

        Returns:
            S3 path in format: bucket/prefix
        """
        if self._prefix:
            return f"{self._bucket}/{self._prefix}"
        return self._bucket

    async def list(self, root: str = "") -> AsyncIterator["SourceItem"]:
        """Enumerate objects in the S3 bucket.

        Args:
            root: Optional subdirectory within the bucket/prefix.
                If empty, uses the connector's bucket/prefix.

        Yields:
            SourceItem for each discovered object.

        Note:
            Objects are filtered using ignore_patterns.
            Binary extensions are not filtered here but marked appropriately.
        """
        # Determine enumeration root
        if root:
            # Combine with base path
            base = self._get_root_path()
            enum_root = f"{base}/{root.strip('/')}"
        else:
            enum_root = self._get_root_path()

        # Use parent's list implementation
        async for item in super().list(enum_root):
            yield item

    def _build_uri(self, path: str) -> str:
        """Build S3 URI from path.

        Args:
            path: Raw path from fsspec (bucket/key format).

        Returns:
            S3 URI in format: s3://bucket/key
        """
        return f"s3://{path}"

    def _uri_to_path(self, uri: str) -> str:
        """Extract path from S3 URI.

        Args:
            uri: S3 URI to parse.

        Returns:
            Path in bucket/key format.
        """
        if uri.startswith("s3://"):
            return uri[5:]  # Remove "s3://" prefix
        return uri


if TYPE_CHECKING:
    from agent_vault.connectors.types import SourceItem
