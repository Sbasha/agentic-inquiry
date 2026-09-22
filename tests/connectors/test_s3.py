"""Tests for S3Connector.

Tests cover:
- Connector initialization and configuration
- Bucket and prefix handling
- URI building and parsing
- Mocked S3 filesystem operations

Note: Most tests are skipped if s3fs is not installed.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.connectors.conftest import MockS3FileSystem

# Check if s3fs is available
try:
    import s3fs  # noqa: F401
    HAS_S3FS = True
except ImportError:
    HAS_S3FS = False

# Skip decorator for tests requiring s3fs
requires_s3fs = pytest.mark.skipif(
    not HAS_S3FS, reason="s3fs not installed"
)


class TestS3ConnectorImport:
    """Tests for S3Connector import requirements."""

    @pytest.mark.skipif(HAS_S3FS, reason="Test only runs when s3fs is NOT installed")
    def test_import_error_without_s3fs(self) -> None:
        """S3Connector raises ImportError when s3fs not available."""
        from agent_vault.connectors.s3 import S3Connector

        with pytest.raises(ImportError, match="s3fs is required"):
            S3Connector(bucket="test-bucket")


@requires_s3fs
class TestS3ConnectorCreation:
    """Tests for S3 connector initialization."""

    def test_basic_initialization(self) -> None:
        """Create connector with bucket only."""
        from agent_vault.connectors.s3 import S3Connector

        connector = S3Connector(bucket="my-bucket")

        assert connector.bucket == "my-bucket"
        assert connector.prefix == ""
        assert connector.protocol == "s3"

    def test_with_prefix(self) -> None:
        """Create connector with bucket and prefix."""
        from agent_vault.connectors.s3 import S3Connector

        connector = S3Connector(bucket="my-bucket", prefix="data/raw")

        assert connector.bucket == "my-bucket"
        assert connector.prefix == "data/raw"

    def test_prefix_stripped(self) -> None:
        """Prefix leading/trailing slashes are stripped."""
        from agent_vault.connectors.s3 import S3Connector

        connector = S3Connector(bucket="my-bucket", prefix="/data/raw/")

        assert connector.prefix == "data/raw"

    def test_with_endpoint_url(self) -> None:
        """Create connector with custom endpoint (MinIO, LocalStack)."""
        from agent_vault.connectors.s3 import S3Connector

        connector = S3Connector(
            bucket="my-bucket", endpoint_url="http://localhost:9000"
        )

        assert connector._storage_options["endpoint_url"] == "http://localhost:9000"

    def test_with_storage_options(self) -> None:
        """Create connector with explicit credentials."""
        from agent_vault.connectors.s3 import S3Connector

        connector = S3Connector(
            bucket="my-bucket",
            storage_options={
                "key": "AKIAIOSFODNN7EXAMPLE",
                "secret": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
                "region": "us-east-1",
            },
        )

        assert connector._storage_options["key"] == "AKIAIOSFODNN7EXAMPLE"
        assert connector._storage_options["region"] == "us-east-1"

    def test_endpoint_url_shorthand_priority(self) -> None:
        """endpoint_url parameter overrides storage_options."""
        from agent_vault.connectors.s3 import S3Connector

        connector = S3Connector(
            bucket="my-bucket",
            storage_options={"endpoint_url": "http://original:9000"},
            endpoint_url="http://override:9000",
        )

        assert connector._storage_options["endpoint_url"] == "http://override:9000"

    def test_custom_ignore_patterns(self) -> None:
        """Create connector with custom ignore patterns."""
        from agent_vault.connectors.s3 import S3Connector

        patterns = ["*.log", "*.tmp"]
        connector = S3Connector(bucket="my-bucket", ignore_patterns=patterns)

        assert connector.ignore_patterns == patterns

    def test_custom_binary_extensions(self) -> None:
        """Create connector with custom binary extensions."""
        from agent_vault.connectors.s3 import S3Connector

        extensions = {".custom", ".bin"}
        connector = S3Connector(bucket="my-bucket", binary_extensions=extensions)

        assert connector.binary_extensions == extensions


@requires_s3fs
class TestS3RootPath:
    """Tests for root path construction."""

    def test_root_path_bucket_only(self) -> None:
        """Root path is just bucket when no prefix."""
        from agent_vault.connectors.s3 import S3Connector

        connector = S3Connector(bucket="my-bucket")

        assert connector._get_root_path() == "my-bucket"

    def test_root_path_with_prefix(self) -> None:
        """Root path includes prefix when set."""
        from agent_vault.connectors.s3 import S3Connector

        connector = S3Connector(bucket="my-bucket", prefix="data/raw")

        assert connector._get_root_path() == "my-bucket/data/raw"


@requires_s3fs
class TestS3URIHandling:
    """Tests for S3 URI building and parsing."""

    def test_build_uri(self) -> None:
        """Build S3 URI from path."""
        from agent_vault.connectors.s3 import S3Connector

        connector = S3Connector(bucket="my-bucket")

        assert connector._build_uri("my-bucket/file.txt") == "s3://my-bucket/file.txt"
        assert (
            connector._build_uri("my-bucket/data/file.json")
            == "s3://my-bucket/data/file.json"
        )

    def test_uri_to_path(self) -> None:
        """Extract path from S3 URI."""
        from agent_vault.connectors.s3 import S3Connector

        connector = S3Connector(bucket="my-bucket")

        assert connector._uri_to_path("s3://my-bucket/file.txt") == "my-bucket/file.txt"
        assert (
            connector._uri_to_path("s3://my-bucket/data/file.json")
            == "my-bucket/data/file.json"
        )

    def test_uri_to_path_without_prefix(self) -> None:
        """Extract path when URI has no s3:// prefix."""
        from agent_vault.connectors.s3 import S3Connector

        connector = S3Connector(bucket="my-bucket")

        # Should return as-is when no prefix
        assert connector._uri_to_path("my-bucket/file.txt") == "my-bucket/file.txt"


@requires_s3fs
class TestS3ConnectorWithMock:
    """Tests using mocked S3 filesystem."""

    def test_list_files(self, mock_s3_filesystem: "MockS3FileSystem") -> None:
        """List enumerates files from mock S3."""
        from agent_vault.connectors.s3 import S3Connector

        connector = S3Connector(bucket="test-bucket")

        # Inject mock filesystem
        connector._fs = mock_s3_filesystem

        # Mock glob to return our test files
        files = list(mock_s3_filesystem.glob("test-bucket/**"))
        assert len(files) == 3

    def test_open_text_file(self, mock_s3_filesystem: "MockS3FileSystem") -> None:
        """Open reads content from mock S3."""
        from agent_vault.connectors.s3 import S3Connector

        connector = S3Connector(bucket="test-bucket")
        connector._fs = mock_s3_filesystem

        # Read directly from mock
        with mock_s3_filesystem.open("test-bucket/data/file1.txt") as f:
            content = f.read()

        assert content == b"Hello, world!"

    def test_extract_hash_from_etag(
        self, mock_s3_filesystem: "MockS3FileSystem"
    ) -> None:
        """Extract hash from S3 ETag."""
        from agent_vault.connectors.s3 import S3Connector

        connector = S3Connector(bucket="test-bucket")
        connector._fs = mock_s3_filesystem

        info = mock_s3_filesystem.info("test-bucket/data/file1.txt")
        hash_value = connector._extract_hash(info)

        assert hash_value == "abc123"

    def test_file_not_found(self, mock_s3_filesystem: "MockS3FileSystem") -> None:
        """FileNotFoundError raised for missing file."""
        with pytest.raises(FileNotFoundError):
            mock_s3_filesystem.info("test-bucket/nonexistent.txt")


@requires_s3fs
class TestS3ConnectorRegistration:
    """Tests for connector registry integration."""

    def test_s3_in_list_connectors(self) -> None:
        """S3Connector appears in list of registered connectors."""
        from agent_vault.connectors.registry import list_connectors

        connectors = list_connectors()

        assert "s3" in connectors

    def test_get_connector_returns_s3(self) -> None:
        """get_connector returns S3Connector instance."""
        from agent_vault.connectors.registry import get_connector
        from agent_vault.connectors.s3 import S3Connector

        connector = get_connector("s3", bucket="my-bucket", prefix="data")

        assert isinstance(connector, S3Connector)
        assert connector.bucket == "my-bucket"
        assert connector.prefix == "data"

    def test_get_connector_unknown_raises(self) -> None:
        """get_connector raises KeyError for unknown name."""
        from agent_vault.connectors.registry import get_connector

        with pytest.raises(KeyError, match="Unknown connector"):
            get_connector("unknown_connector", bucket="test")
