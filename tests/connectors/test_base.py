"""Tests for FsspecConnector base class.

Tests cover:
- Basic file enumeration
- Ignore pattern filtering
- Binary file detection
- Content reading
- URI building and parsing
- Hash extraction
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from agent_vault.connectors.base import (
    DEFAULT_BINARY_EXTENSIONS,
    DEFAULT_IGNORE_PATTERNS,
    FsspecConnector,
)
from agent_vault.connectors.protocols import ConnectorProtocol
from agent_vault.connectors.types import SourceItem


class TestFsspecConnectorCreation:
    """Tests for connector initialization."""

    def test_default_initialization(self) -> None:
        """Create connector with default options."""
        connector = FsspecConnector()

        assert connector.protocol == "file"
        assert connector.ignore_patterns == list(DEFAULT_IGNORE_PATTERNS)
        assert connector.binary_extensions == set(DEFAULT_BINARY_EXTENSIONS)

    def test_custom_protocol(self) -> None:
        """Create connector with custom protocol."""
        connector = FsspecConnector(protocol="memory")
        assert connector.protocol == "memory"

    def test_custom_ignore_patterns(self) -> None:
        """Create connector with custom ignore patterns."""
        patterns = ["*.log", "*.tmp"]
        connector = FsspecConnector(ignore_patterns=patterns)
        assert connector.ignore_patterns == patterns

    def test_custom_binary_extensions(self) -> None:
        """Create connector with custom binary extensions."""
        extensions = {".custom", ".bin"}
        connector = FsspecConnector(binary_extensions=extensions)
        assert connector.binary_extensions == extensions

    def test_storage_options(self) -> None:
        """Create connector with storage options."""
        options = {"key": "value", "anon": True}
        connector = FsspecConnector(storage_options=options)
        assert connector._storage_options == options

    def test_implements_protocol(self) -> None:
        """Connector implements ConnectorProtocol."""
        connector = FsspecConnector()
        assert isinstance(connector, ConnectorProtocol)

    def test_lazy_filesystem_init(self) -> None:
        """Filesystem is lazily initialized."""
        connector = FsspecConnector()

        # _fs should be None initially
        assert connector._fs is None

        # Accessing fs property initializes it
        fs = connector.fs
        assert fs is not None
        assert connector._fs is fs


class TestFileEnumeration:
    """Tests for file listing."""

    @pytest.mark.asyncio
    async def test_list_files(self, mock_temp_project_structure: Path) -> None:
        """List enumerates files in directory."""
        connector = FsspecConnector()

        items = []
        async for item in connector.list(str(mock_temp_project_structure)):
            items.append(item)

        # Should find multiple files
        assert len(items) >= 5

        # Check URIs
        uris = [item.uri for item in items]
        assert any("main.py" in uri for uri in uris)
        assert any("README.md" in uri for uri in uris)

    @pytest.mark.asyncio
    async def test_list_filters_ignored_patterns(
        self, mock_temp_project_structure: Path
    ) -> None:
        """List respects ignore patterns."""
        connector = FsspecConnector()

        items = []
        async for item in connector.list(str(mock_temp_project_structure)):
            items.append(item)

        uris = [item.uri for item in items]

        # .git and __pycache__ should be ignored
        assert not any(".git" in uri for uri in uris)
        assert not any("__pycache__" in uri for uri in uris)
        assert not any(".pyc" in uri for uri in uris)

    @pytest.mark.asyncio
    async def test_list_nonexistent_returns_empty(self, mock_temp_directory: Path) -> None:
        """List returns empty iterator for nonexistent directory."""
        connector = FsspecConnector()

        # fsspec's glob returns empty list for nonexistent paths
        items = []
        async for item in connector.list(str(mock_temp_directory / "nonexistent")):
            items.append(item)

        assert items == []

    @pytest.mark.asyncio
    async def test_items_have_content_type(
        self, mock_temp_project_structure: Path
    ) -> None:
        """Listed items have inferred content type."""
        connector = FsspecConnector()

        found_python = False
        async for item in connector.list(str(mock_temp_project_structure)):
            if item.uri.endswith(".py"):
                assert item.content_type == "text/x-python"
                found_python = True
                break

        assert found_python, "No Python file found in listing"

    @pytest.mark.asyncio
    async def test_items_have_size(self, mock_temp_project_structure: Path) -> None:
        """Listed items have size."""
        connector = FsspecConnector()

        async for item in connector.list(str(mock_temp_project_structure)):
            if item.uri.endswith(".py"):
                # Size should be set for real files
                assert item.size is not None
                break


class TestContentReading:
    """Tests for reading file content."""

    @pytest.mark.asyncio
    async def test_open_text_file(self, mock_sample_text_file: Path) -> None:
        """Open reads text file content."""
        connector = FsspecConnector()
        item = SourceItem(uri=str(mock_sample_text_file))

        content = await connector.open(item)

        assert content.encoding == "utf-8"
        assert "Hello, world!" in content.text
        assert content.metadata["uri"] == str(mock_sample_text_file)

    @pytest.mark.asyncio
    async def test_open_binary_file(self, mock_sample_binary_file: Path) -> None:
        """Open reads binary file as bytes."""
        connector = FsspecConnector()
        item = SourceItem(uri=str(mock_sample_binary_file))

        content = await connector.open(item)

        assert content.encoding is None
        assert content.data == b"\x00\x01\x02\x03\x04\x05\x06\x07"

    @pytest.mark.asyncio
    async def test_open_nonexistent_raises(self, mock_temp_directory: Path) -> None:
        """Open raises for nonexistent file."""
        connector = FsspecConnector()
        item = SourceItem(uri=str(mock_temp_directory / "missing.txt"))

        with pytest.raises(FileNotFoundError):
            await connector.open(item)

    @pytest.mark.asyncio
    async def test_compute_hash(self, mock_sample_text_file: Path) -> None:
        """Compute hash for file content."""
        connector = FsspecConnector()
        item = SourceItem(uri=str(mock_sample_text_file))

        hash_value = await connector.compute_hash(item)

        # SHA256 produces 64-char hex string
        assert len(hash_value) == 64
        assert all(c in "0123456789abcdef" for c in hash_value)


class TestIgnorePatterns:
    """Tests for ignore pattern matching."""

    def test_should_ignore_filename_match(self, mock_temp_directory: Path) -> None:
        """Ignore pattern matches filename."""
        connector = FsspecConnector(ignore_patterns=["*.pyc"])

        root = str(mock_temp_directory)
        assert connector._should_ignore(f"{root}/cache/module.pyc", root) is True
        assert connector._should_ignore(f"{root}/src/main.py", root) is False

    def test_should_ignore_directory_match(self, mock_temp_directory: Path) -> None:
        """Ignore pattern matches directory name."""
        connector = FsspecConnector(ignore_patterns=["__pycache__"])

        root = str(mock_temp_directory)
        assert (
            connector._should_ignore(f"{root}/__pycache__/module.pyc", root) is True
        )
        assert connector._should_ignore(f"{root}/src/main.py", root) is False

    def test_should_ignore_relative_path(self, mock_temp_directory: Path) -> None:
        """Ignore pattern matches relative path."""
        connector = FsspecConnector(ignore_patterns=["tests/*"])

        root = str(mock_temp_directory)
        assert connector._should_ignore(f"{root}/tests/test_main.py", root) is True
        assert connector._should_ignore(f"{root}/src/main.py", root) is False


class TestBinaryDetection:
    """Tests for binary file detection."""

    def test_is_binary_common_extensions(self) -> None:
        """Common binary extensions detected."""
        connector = FsspecConnector()

        assert connector._is_binary("/path/to/image.png") is True
        assert connector._is_binary("/path/to/archive.zip") is True
        assert connector._is_binary("/path/to/compiled.pyc") is True
        assert connector._is_binary("/path/to/library.dll") is True

    def test_is_binary_text_files(self) -> None:
        """Text files not detected as binary."""
        connector = FsspecConnector()

        assert connector._is_binary("/path/to/script.py") is False
        assert connector._is_binary("/path/to/README.md") is False
        assert connector._is_binary("/path/to/config.json") is False
        assert connector._is_binary("/path/to/style.css") is False

    def test_is_binary_case_insensitive(self) -> None:
        """Binary detection is case-insensitive."""
        connector = FsspecConnector()

        assert connector._is_binary("/path/to/IMAGE.PNG") is True
        assert connector._is_binary("/path/to/Archive.ZIP") is True

    def test_is_binary_custom_extensions(self) -> None:
        """Custom binary extensions work."""
        connector = FsspecConnector(binary_extensions={".custom", ".data"})

        assert connector._is_binary("/path/to/file.custom") is True
        assert connector._is_binary("/path/to/file.data") is True
        assert connector._is_binary("/path/to/file.png") is False


class TestURIHandling:
    """Tests for URI building and parsing."""

    def test_build_uri_local(self) -> None:
        """Local protocol returns path as-is."""
        connector = FsspecConnector(protocol="file")
        assert connector._build_uri("/path/to/file.py") == "/path/to/file.py"

    def test_build_uri_remote(self) -> None:
        """Remote protocol adds prefix."""
        connector = FsspecConnector(protocol="s3")
        assert connector._build_uri("bucket/file.py") == "s3://bucket/file.py"

    def test_uri_to_path_local(self) -> None:
        """Local URI parsed correctly."""
        connector = FsspecConnector(protocol="file")
        assert connector._uri_to_path("/path/to/file.py") == "/path/to/file.py"

    def test_uri_to_path_remote(self) -> None:
        """Remote URI parsed correctly."""
        connector = FsspecConnector(protocol="s3")
        assert connector._uri_to_path("s3://bucket/file.py") == "bucket/file.py"


class TestMetadataExtraction:
    """Tests for extracting metadata from fsspec info."""

    def test_extract_hash_etag(self) -> None:
        """Extract hash from ETag field."""
        connector = FsspecConnector()

        info = {"ETag": '"abc123"', "size": 100}
        assert connector._extract_hash(info) == "abc123"

    def test_extract_hash_md5(self) -> None:
        """Extract hash from md5Hash field."""
        connector = FsspecConnector()

        info = {"md5Hash": "def456", "size": 100}
        assert connector._extract_hash(info) == "def456"

    def test_extract_hash_missing(self) -> None:
        """Return None when no hash field."""
        connector = FsspecConnector()

        info = {"size": 100}
        assert connector._extract_hash(info) is None

    def test_extract_modified_at_mtime(self) -> None:
        """Extract modification time from mtime."""
        connector = FsspecConnector()

        info = {"mtime": 1234567890}
        assert connector._extract_modified_at(info) == 1234567890

    def test_extract_modified_at_last_modified(self) -> None:
        """Extract modification time from LastModified."""
        connector = FsspecConnector()

        info = {"LastModified": "2024-01-01T00:00:00Z"}
        assert connector._extract_modified_at(info) == "2024-01-01T00:00:00Z"

    def test_infer_content_type(self) -> None:
        """Infer MIME type from path."""
        connector = FsspecConnector()

        assert connector._infer_content_type("/path/to/file.py") == "text/x-python"
        assert connector._infer_content_type("/path/to/file.json") == "application/json"
        assert connector._infer_content_type("/path/to/file.md") == "text/markdown"
        assert connector._infer_content_type("/path/to/file.html") == "text/html"
