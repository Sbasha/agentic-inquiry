"""Tests for GCSConnector.

Tests cover:
- Connector initialization and configuration
- Bucket and prefix handling
- URI building and parsing (``gcs://`` scheme)
- Mocked GCS filesystem operations (driving the connector, not the mock)
- Registry integration (``gcs`` registered at import time)

Note: Construction-dependent tests are skipped if gcsfs is not installed.
The registration tests do NOT require gcsfs — registration happens at import
time via the ``@register_connector`` decorator; the gcsfs check is only in
``GCSConnector.__init__``.
"""
from __future__ import annotations

import importlib.util

import pytest

pytestmark = pytest.mark.unit

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.connectors.conftest import MockGCSFileSystem

# Check if gcsfs is available (detect without importing for side effects)
HAS_GCSFS = importlib.util.find_spec("gcsfs") is not None

# Skip decorator for tests requiring gcsfs
requires_gcsfs = pytest.mark.skipif(not HAS_GCSFS, reason="gcsfs not installed")


class TestGCSConnectorImport:
    """Tests for GCSConnector import requirements."""

    @pytest.mark.skipif(HAS_GCSFS, reason="Test only runs when gcsfs is NOT installed")
    def test_import_error_without_gcsfs(self) -> None:
        """GCSConnector raises ImportError when gcsfs not available."""
        from agent_vault.connectors.gcs import GCSConnector

        with pytest.raises(ImportError, match="gcsfs is required"):
            GCSConnector(bucket="test-bucket")


@requires_gcsfs
class TestGCSConnectorCreation:
    """Tests for GCS connector initialization."""

    def test_basic_initialization(self) -> None:
        """Create connector with bucket only."""
        from agent_vault.connectors.gcs import GCSConnector

        connector = GCSConnector(bucket="my-bucket")

        assert connector.bucket == "my-bucket"
        assert connector.prefix == ""
        assert connector.protocol == "gcs"

    def test_with_prefix(self) -> None:
        """Create connector with bucket and prefix."""
        from agent_vault.connectors.gcs import GCSConnector

        connector = GCSConnector(bucket="my-bucket", prefix="data/raw")

        assert connector.bucket == "my-bucket"
        assert connector.prefix == "data/raw"

    def test_prefix_stripped(self) -> None:
        """Prefix leading/trailing slashes are stripped."""
        from agent_vault.connectors.gcs import GCSConnector

        connector = GCSConnector(bucket="my-bucket", prefix="/data/raw/")

        assert connector.prefix == "data/raw"

    def test_with_storage_options(self) -> None:
        """Create connector with explicit credentials/project."""
        from agent_vault.connectors.gcs import GCSConnector

        connector = GCSConnector(
            bucket="my-bucket",
            storage_options={"project": "my-project", "token": "google_default"},
        )

        assert connector._storage_options["project"] == "my-project"
        assert connector._storage_options["token"] == "google_default"

    def test_custom_ignore_patterns(self) -> None:
        """Create connector with custom ignore patterns."""
        from agent_vault.connectors.gcs import GCSConnector

        patterns = ["*.log", "*.tmp"]
        connector = GCSConnector(bucket="my-bucket", ignore_patterns=patterns)

        assert connector.ignore_patterns == patterns

    def test_custom_binary_extensions(self) -> None:
        """Create connector with custom binary extensions."""
        from agent_vault.connectors.gcs import GCSConnector

        extensions = {".custom", ".bin"}
        connector = GCSConnector(bucket="my-bucket", binary_extensions=extensions)

        assert connector.binary_extensions == extensions


@requires_gcsfs
class TestGCSRootPath:
    """Tests for root path construction."""

    def test_root_path_bucket_only(self) -> None:
        """Root path is just bucket when no prefix."""
        from agent_vault.connectors.gcs import GCSConnector

        connector = GCSConnector(bucket="my-bucket")

        assert connector._get_root_path() == "my-bucket"

    def test_root_path_with_prefix(self) -> None:
        """Root path includes prefix when set."""
        from agent_vault.connectors.gcs import GCSConnector

        connector = GCSConnector(bucket="my-bucket", prefix="data/raw")

        assert connector._get_root_path() == "my-bucket/data/raw"


@requires_gcsfs
class TestGCSURIHandling:
    """Tests for GCS URI building and parsing (``gcs://`` scheme)."""

    def test_build_uri(self) -> None:
        """Build GCS URI from path using the ``gcs://`` scheme."""
        from agent_vault.connectors.gcs import GCSConnector

        connector = GCSConnector(bucket="my-bucket")

        assert connector._build_uri("my-bucket/file.txt") == "gcs://my-bucket/file.txt"
        assert (
            connector._build_uri("my-bucket/data/file.json")
            == "gcs://my-bucket/data/file.json"
        )

    def test_uri_to_path(self) -> None:
        """Extract path from a ``gcs://`` URI (round-trips _build_uri)."""
        from agent_vault.connectors.gcs import GCSConnector

        connector = GCSConnector(bucket="my-bucket")

        assert (
            connector._uri_to_path("gcs://my-bucket/file.txt") == "my-bucket/file.txt"
        )
        assert (
            connector._uri_to_path("gcs://my-bucket/data/file.json")
            == "my-bucket/data/file.json"
        )

    def test_uri_to_path_without_prefix(self) -> None:
        """Extract path when URI has no gcs:// prefix (passthrough)."""
        from agent_vault.connectors.gcs import GCSConnector

        connector = GCSConnector(bucket="my-bucket")

        assert connector._uri_to_path("my-bucket/file.txt") == "my-bucket/file.txt"

    def test_uri_to_path_legacy_gs_scheme(self) -> None:
        """Legacy gs:// URIs still parse, for backward compatibility."""
        from agent_vault.connectors.gcs import GCSConnector

        connector = GCSConnector(bucket="my-bucket")

        assert (
            connector._uri_to_path("gs://my-bucket/file.txt") == "my-bucket/file.txt"
        )

    def test_uri_round_trips(self) -> None:
        """_uri_to_path(_build_uri(p)) == p for representative paths."""
        from agent_vault.connectors.gcs import GCSConnector

        connector = GCSConnector(bucket="my-bucket")

        for path in ("b/k", "my-bucket/data/file.json", "b/nested/deep/obj.md"):
            assert connector._uri_to_path(connector._build_uri(path)) == path


@requires_gcsfs
class TestGCSConnectorWithMock:
    """Tests that drive the connector against a mocked GCS filesystem.

    These assert on what the connector *yields* (SourceItem / SourceContent),
    not on the mock object directly.
    """

    async def test_list_yields_gcs_items(
        self, mock_gcs_filesystem: "MockGCSFileSystem"
    ) -> None:
        """connector.list() enumerates files and yields gcs:// SourceItems."""
        from agent_vault.connectors.gcs import GCSConnector

        connector = GCSConnector(bucket="test-bucket")
        connector._fs = mock_gcs_filesystem

        items = [item async for item in connector.list()]

        assert len(items) == 3
        # Every yielded item carries the gcs:// scheme and protocol "gcs".
        assert all(item.uri.startswith("gcs://") for item in items)
        assert all(item.protocol == "gcs" for item in items)
        # Hash is extracted from the GCS md5Hash field.
        uris = {item.uri: item.content_hash for item in items}
        assert uris["gcs://test-bucket/data/file1.txt"] == "abc123"

    async def test_open_reads_text_content(
        self, mock_gcs_filesystem: "MockGCSFileSystem"
    ) -> None:
        """connector.open() returns decoded SourceContent for a text item."""
        from agent_vault.connectors.gcs import GCSConnector
        from agent_vault.connectors.types import SourceItem

        connector = GCSConnector(bucket="test-bucket")
        connector._fs = mock_gcs_filesystem

        item = SourceItem(uri="gcs://test-bucket/data/file1.txt")
        content = await connector.open(item)

        assert content.data == b"Hello, world!"
        assert content.is_binary is False
        assert content.text == "Hello, world!"

    async def test_open_missing_raises(
        self, mock_gcs_filesystem: "MockGCSFileSystem"
    ) -> None:
        """connector.open() raises FileNotFoundError for a missing object."""
        from agent_vault.connectors.gcs import GCSConnector
        from agent_vault.connectors.types import SourceItem

        connector = GCSConnector(bucket="test-bucket")
        connector._fs = mock_gcs_filesystem

        item = SourceItem(uri="gcs://test-bucket/data/missing.txt")
        with pytest.raises(FileNotFoundError):
            await connector.open(item)

    # Note: md5Hash extraction is verified through the public surface by
    # test_list_yields_gcs_items (which asserts the hash on a yielded
    # SourceItem), so a white-box _extract_hash test is intentionally omitted.

    async def test_base64_md5hash_passed_through_verbatim(self) -> None:
        """A realistic base64 GCS md5Hash flows to content_hash unchanged.

        gcsfs surfaces ``md5Hash`` as a base64-encoded digest. The connector
        must not decode or reformat it — pin that contract so a future change
        to hash handling is caught in CI (not only behind opt-in cloud creds).
        """
        from tests.connectors.conftest import MockGCSFileSystem

        from agent_vault.connectors.gcs import GCSConnector

        b64 = "CY9rzUYh03PK3k6DJie09g=="  # base64-encoded MD5, as gcsfs returns
        fs = MockGCSFileSystem()
        fs.add_file("test-bucket/data/only.txt", b"payload", md5hash=b64)

        connector = GCSConnector(bucket="test-bucket")
        connector._fs = fs

        items = [item async for item in connector.list()]
        assert len(items) == 1
        assert items[0].content_hash == b64


class TestGCSConnectorRegistration:
    """Tests for connector registry integration.

    Registration is an import-time effect of ``_register_builtin_connectors``
    firing the ``@register_connector`` decorator. Because Python caches modules,
    the decorator only fires on first import — so a fresh interpreter is the
    only honest way to assert the production registration path (an in-process
    assertion is polluted by any sibling test that imports the gcs module).
    These run WITHOUT gcsfs: registration does not construct the connector.
    """

    def _fresh_import_connectors(self, code: str) -> None:
        """Run `code` in a fresh interpreter after importing the package.

        Raises CalledProcessError (failing the test) if the assertions inside
        the subprocess do not hold.
        """
        import subprocess
        import sys

        prog = "import agent_vault.connectors as c\n" + code
        try:
            result = subprocess.run(
                [sys.executable, "-c", prog],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except subprocess.TimeoutExpired as exc:
            pytest.fail(
                "fresh-interpreter import check timed out:\n"
                + str(exc.stderr or "")
            )
        if result.returncode != 0:
            pytest.fail(
                "fresh-interpreter import check failed:\n" + result.stderr
            )

    def test_fresh_import_registers_s3_and_gcs(self) -> None:
        """`import agent_vault.connectors` registers both cloud connectors.

        This is the core bug fix: before it, 'gcs' was never registered because
        nothing imported the gcs module at runtime.
        """
        self._fresh_import_connectors(
            "names = c.list_connectors()\n"
            "assert 'filesystem' in names, names\n"
            "assert 's3' in names, names\n"
            "assert 'gcs' in names, names\n"
        )

    def test_fresh_import_succeeds_without_cloud_libs(self) -> None:
        """Importing the package without s3fs/gcsfs succeeds; GCSConnector set.

        GCSConnector is exported (as None when gcsfs is absent), and 'gcs' is
        still registered (registration does not require the cloud lib).
        """
        self._fresh_import_connectors(
            "assert hasattr(c, 'GCSConnector'), 'GCSConnector not exported'\n"
            "assert 'gcs' in c.list_connectors()\n"
        )

    @requires_gcsfs
    def test_get_connector_returns_gcs(self) -> None:
        """get_connector('gcs', ...) returns a GCSConnector instance."""
        from agent_vault.connectors.gcs import GCSConnector
        from agent_vault.connectors.registry import (
            _register_builtin_connectors,
            get_connector,
        )

        # Ensure builtins are present even if a prior test reset the singleton.
        _register_builtin_connectors()
        connector = get_connector("gcs", bucket="my-bucket", prefix="data")

        assert isinstance(connector, GCSConnector)
        assert connector.bucket == "my-bucket"
        assert connector.prefix == "data"
