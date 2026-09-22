"""Tests for connector data types.

Tests cover:
- SourceItem creation and properties
- SourceContent creation and methods
- URI parsing and conventions
- Hash computation
"""
from __future__ import annotations

from datetime import datetime

import pytest

pytestmark = pytest.mark.unit

from agent_vault.connectors.types import (
    SourceContent,
    SourceItem,
    compute_content_hash,
)


class TestSourceItem:
    """Tests for SourceItem dataclass."""

    def test_create_minimal(self) -> None:
        """Create SourceItem with only required field."""
        item = SourceItem(uri="/path/to/file.py")
        assert item.uri == "/path/to/file.py"
        assert item.content_hash is None
        assert item.modified_at is None
        assert item.size is None
        assert item.content_type is None
        assert item.metadata == {}

    def test_create_full(self) -> None:
        """Create SourceItem with all fields."""
        now = datetime.now()
        item = SourceItem(
            uri="/path/to/file.py",
            content_hash="abc123",
            modified_at=now,
            size=1024,
            content_type="text/x-python",
            metadata={"custom": "value"},
        )
        assert item.uri == "/path/to/file.py"
        assert item.content_hash == "abc123"
        assert item.modified_at == now
        assert item.size == 1024
        assert item.content_type == "text/x-python"
        assert item.metadata == {"custom": "value"}

    def test_empty_uri_raises(self) -> None:
        """Empty URI should raise ValueError."""
        with pytest.raises(ValueError, match="uri cannot be empty"):
            SourceItem(uri="")

    def test_is_local_filesystem(self) -> None:
        """Local filesystem paths detected correctly."""
        item = SourceItem(uri="/path/to/file.py")
        assert item.is_local is True
        assert item.protocol == "file"

    def test_is_local_s3(self) -> None:
        """S3 URIs detected as non-local."""
        item = SourceItem(uri="s3://bucket/key/file.py")
        assert item.is_local is False
        assert item.protocol == "s3"

    def test_is_local_gcs(self) -> None:
        """GCS URIs detected as non-local."""
        item = SourceItem(uri="gcs://bucket/object/file.py")
        assert item.is_local is False
        assert item.protocol == "gcs"

    def test_is_local_github(self) -> None:
        """GitHub URIs detected as non-local."""
        item = SourceItem(uri="github://org/repo/path@sha")
        assert item.is_local is False
        assert item.protocol == "github"

    def test_path_extraction_local(self) -> None:
        """Path extraction from local URI."""
        item = SourceItem(uri="/path/to/file.py")
        assert item.path == "/path/to/file.py"

    def test_path_extraction_s3(self) -> None:
        """Path extraction from S3 URI."""
        item = SourceItem(uri="s3://bucket/key/file.py")
        assert item.path == "bucket/key/file.py"

    def test_with_hash(self) -> None:
        """with_hash returns new item with updated hash."""
        item = SourceItem(uri="/path/to/file.py", size=100)
        updated = item.with_hash("newhash")

        assert updated.content_hash == "newhash"
        assert updated.uri == item.uri
        assert updated.size == item.size
        # Original unchanged
        assert item.content_hash is None

    def test_frozen(self) -> None:
        """SourceItem is immutable."""
        item = SourceItem(uri="/path/to/file.py")
        with pytest.raises(AttributeError):
            item.uri = "/other/path"  # type: ignore[misc]


class TestSourceContent:
    """Tests for SourceContent dataclass."""

    def test_create_text_content(self) -> None:
        """Create text content with encoding."""
        content = SourceContent(
            data=b"hello world",
            encoding="utf-8",
            metadata={"uri": "/path/to/file.txt"},
        )
        assert content.data == b"hello world"
        assert content.encoding == "utf-8"
        assert content.metadata == {"uri": "/path/to/file.txt"}

    def test_create_binary_content(self) -> None:
        """Create binary content without encoding."""
        content = SourceContent(
            data=b"\x00\x01\x02",
            encoding=None,
            metadata={},
        )
        assert content.data == b"\x00\x01\x02"
        assert content.encoding is None

    def test_text_property(self) -> None:
        """text property decodes content."""
        content = SourceContent(data=b"hello", encoding="utf-8")
        assert content.text == "hello"

    def test_text_property_unicode(self) -> None:
        """text property handles unicode."""
        content = SourceContent(data="héllo wörld".encode("utf-8"), encoding="utf-8")
        assert content.text == "héllo wörld"

    def test_text_property_binary_raises(self) -> None:
        """text property raises for binary content."""
        content = SourceContent(data=b"\x00\x01", encoding=None)
        with pytest.raises(ValueError, match="Cannot decode binary content"):
            _ = content.text

    def test_is_binary_true(self) -> None:
        """is_binary returns True for binary content."""
        content = SourceContent(data=b"\x00", encoding=None)
        assert content.is_binary is True

    def test_is_binary_false(self) -> None:
        """is_binary returns False for text content."""
        content = SourceContent(data=b"text", encoding="utf-8")
        assert content.is_binary is False

    def test_size_property(self) -> None:
        """size property returns data length."""
        content = SourceContent(data=b"12345", encoding="utf-8")
        assert content.size == 5

    def test_frozen(self) -> None:
        """SourceContent is immutable."""
        content = SourceContent(data=b"test", encoding="utf-8")
        with pytest.raises(AttributeError):
            content.data = b"other"  # type: ignore[misc]


class TestComputeContentHash:
    """Tests for compute_content_hash function."""

    def test_sha256_default(self) -> None:
        """Default algorithm is SHA256."""
        result = compute_content_hash(b"hello world")
        # Known SHA256 hash of "hello world"
        expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
        assert result == expected

    def test_md5(self) -> None:
        """MD5 algorithm works."""
        result = compute_content_hash(b"hello world", algorithm="md5")
        # Known MD5 hash of "hello world"
        expected = "5eb63bbbe01eeed093cb22bb8f5acdc3"
        assert result == expected

    def test_empty_content(self) -> None:
        """Empty content produces valid hash."""
        result = compute_content_hash(b"")
        # SHA256 of empty string
        expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert result == expected

    def test_deterministic(self) -> None:
        """Same content produces same hash."""
        data = b"test content"
        hash1 = compute_content_hash(data)
        hash2 = compute_content_hash(data)
        assert hash1 == hash2

    def test_different_content_different_hash(self) -> None:
        """Different content produces different hash."""
        hash1 = compute_content_hash(b"content1")
        hash2 = compute_content_hash(b"content2")
        assert hash1 != hash2
