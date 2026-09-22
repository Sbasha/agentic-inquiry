"""Shared fixtures for connector tests."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Dict

import pytest


@pytest.fixture
def mock_temp_directory():
    """Create a temporary directory for testing.

    Yields:
        Path to the temporary directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_temp_project_structure(mock_temp_directory: Path) -> Path:
    """Create a realistic project directory structure.

    Creates:
        - src/ with Python files
        - docs/ with Markdown files
        - tests/ with test files
        - .git/ directory (should be ignored)
        - __pycache__/ directory (should be ignored)
        - README.md
        - pyproject.toml

    Returns:
        Path to the project root.
    """
    root = mock_temp_directory

    # Create directory structure
    (root / "src").mkdir()
    (root / "src" / "core").mkdir()
    (root / "docs").mkdir()
    (root / "tests").mkdir()
    (root / ".git").mkdir()
    (root / "__pycache__").mkdir()

    # Create source files
    (root / "src" / "__init__.py").write_text("")
    (root / "src" / "main.py").write_text('def main():\n    print("Hello")\n')
    (root / "src" / "core" / "__init__.py").write_text("")
    (root / "src" / "core" / "utils.py").write_text("def helper(): pass\n")

    # Create docs
    (root / "docs" / "README.md").write_text("# Documentation\n\nWelcome.")
    (root / "docs" / "api.md").write_text("# API Reference\n\n## Functions")

    # Create tests
    (root / "tests" / "__init__.py").write_text("")
    (root / "tests" / "test_main.py").write_text("def test_main(): pass\n")

    # Create root files
    (root / "README.md").write_text("# Test Project\n\nA test project.")
    (root / "pyproject.toml").write_text('[project]\nname = "test"')

    # Create files that should be ignored
    (root / ".git" / "config").write_text("[core]\nrepositoryformatversion = 0")
    (root / "__pycache__" / "main.cpython-310.pyc").write_bytes(b"\x00\x01\x02\x03")

    return root


@pytest.fixture
def mock_sample_binary_file(mock_temp_directory: Path) -> Path:
    """Create a sample binary file.

    Returns:
        Path to the binary file.
    """
    binary_file = mock_temp_directory / "data.bin"
    binary_file.write_bytes(b"\x00\x01\x02\x03\x04\x05\x06\x07")
    return binary_file


@pytest.fixture
def mock_sample_text_file(mock_temp_directory: Path) -> Path:
    """Create a sample text file.

    Returns:
        Path to the text file.
    """
    text_file = mock_temp_directory / "document.txt"
    text_file.write_text("Hello, world!\nThis is a test file.")
    return text_file


@pytest.fixture
def mock_mixed_content_directory(mock_temp_directory: Path) -> Path:
    """Create a directory with mixed content types.

    Contains:
        - Python source files
        - Binary files (images, compiled)
        - JSON configuration files
        - Markdown documentation

    Returns:
        Path to the directory.
    """
    root = mock_temp_directory / "mixed"
    root.mkdir()

    # Python files
    (root / "app.py").write_text('print("app")')
    (root / "config.py").write_text("DEBUG = True")

    # JSON files
    (root / "settings.json").write_text('{"key": "value"}')

    # Markdown files
    (root / "README.md").write_text("# README")

    # Binary files (simulated)
    (root / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "compiled.pyc").write_bytes(b"\x00\x01\x02\x03")

    # Nested directory
    (root / "subdir").mkdir()
    (root / "subdir" / "nested.py").write_text("x = 1")

    return root


class MockS3FileSystem:
    """Mock s3fs filesystem for testing without AWS credentials."""

    def __init__(self, files: Dict[str, bytes] | None = None) -> None:
        """Initialize with optional file mapping.

        Args:
            files: Dict mapping paths to content bytes.
        """
        self._files = files or {}
        self._info_cache: Dict[str, Dict] = {}

    def add_file(self, path: str, content: bytes, etag: str | None = None) -> None:
        """Add a file to the mock filesystem.

        Args:
            path: S3 path (bucket/key format).
            content: File content.
            etag: Optional ETag for the file.
        """
        self._files[path] = content
        self._info_cache[path] = {
            "size": len(content),
            "ETag": etag or f'"{hash(content)}"',
            "type": "file",
        }

    def glob(self, pattern: str) -> list[str]:
        """Glob matching for mock filesystem."""
        import fnmatch

        # Handle ** patterns
        if "**" in pattern:
            base = pattern.split("**")[0].rstrip("/")
            return [p for p in self._files.keys() if p.startswith(base)]
        return fnmatch.filter(self._files.keys(), pattern)

    def isfile(self, path: str) -> bool:
        """Check if path is a file."""
        return path in self._files

    def info(self, path: str) -> Dict:
        """Get file info."""
        if path not in self._files:
            raise FileNotFoundError(f"No such file: {path}")
        return self._info_cache.get(path, {"size": len(self._files[path])})

    def open(self, path: str, mode: str = "rb") -> "MockFileHandle":
        """Open a file."""
        if path not in self._files:
            raise FileNotFoundError(f"No such file: {path}")
        return MockFileHandle(self._files[path])


class MockFileHandle:
    """Mock file handle for reading."""

    def __init__(self, content: bytes) -> None:
        self._content = content

    def read(self) -> bytes:
        return self._content

    def __enter__(self) -> "MockFileHandle":
        return self

    def __exit__(self, *args) -> None:
        pass


@pytest.fixture
def mock_s3_filesystem() -> MockS3FileSystem:
    """Create a mock S3 filesystem with sample files.

    Contains:
        - test-bucket/data/file1.txt
        - test-bucket/data/file2.json
        - test-bucket/config/settings.yaml

    Returns:
        MockS3FileSystem instance.
    """
    fs = MockS3FileSystem()
    fs.add_file("test-bucket/data/file1.txt", b"Hello, world!", etag='"abc123"')
    fs.add_file("test-bucket/data/file2.json", b'{"key": "value"}', etag='"def456"')
    fs.add_file(
        "test-bucket/config/settings.yaml",
        b"database:\n  host: localhost",
        etag='"ghi789"',
    )
    return fs


class MockGCSFileSystem(MockS3FileSystem):
    """Mock gcsfs filesystem for testing without GCP credentials.

    Mirrors :class:`MockS3FileSystem` but exposes ``md5Hash`` in file info
    (the field gcsfs surfaces) rather than S3's ``ETag``, so connector hash
    extraction is exercised against GCS-shaped metadata.
    """

    def add_file(  # type: ignore[override]
        self, path: str, content: bytes, md5hash: str | None = None
    ) -> None:
        """Add a file to the mock filesystem.

        Args:
            path: GCS path (bucket/object format).
            content: File content.
            md5hash: Optional md5Hash for the file.
        """
        self._files[path] = content
        self._info_cache[path] = {
            "size": len(content),
            "md5Hash": md5hash or f"{hash(content)}",
            "type": "file",
        }


@pytest.fixture
def mock_gcs_filesystem() -> MockGCSFileSystem:
    """Create a mock GCS filesystem with sample files.

    Contains:
        - test-bucket/data/file1.txt
        - test-bucket/data/file2.json
        - test-bucket/config/settings.yaml

    Returns:
        MockGCSFileSystem instance.
    """
    fs = MockGCSFileSystem()
    fs.add_file("test-bucket/data/file1.txt", b"Hello, world!", md5hash="abc123")
    fs.add_file("test-bucket/data/file2.json", b'{"key": "value"}', md5hash="def456")
    fs.add_file(
        "test-bucket/config/settings.yaml",
        b"database:\n  host: localhost",
        md5hash="ghi789",
    )
    return fs
