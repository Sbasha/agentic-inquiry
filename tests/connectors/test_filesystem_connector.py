"""Tests for filesystem connector.

Tests cover:
- FileSystemConnector creation and validation
- File enumeration with ignore patterns
- Content retrieval
- Path security (traversal prevention)
- Change detection
- Registry integration
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

from agent_vault.connectors import (
    FileSystemConnector,
    SourceItem,
    get_connector,
    has_change_detection,
    has_watch_capability,
    list_connectors,
)
from agent_vault.connectors.protocols import (
    ChangeDetectionCapability,
    ConnectorProtocol,
    WatchCapability,
)


@pytest.fixture
def temp_project():
    """Create a temporary project directory with test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # Create directory structure
        (root / "src").mkdir()
        (root / "src" / "module").mkdir()
        (root / "tests").mkdir()
        (root / ".git").mkdir()
        (root / "__pycache__").mkdir()

        # Create test files
        (root / "README.md").write_text("# Test Project")
        (root / "src" / "main.py").write_text("print('hello')")
        (root / "src" / "module" / "utils.py").write_text("def foo(): pass")
        (root / "tests" / "test_main.py").write_text("def test(): pass")
        (root / ".git" / "config").write_text("[core]")
        (root / "__pycache__" / "main.cpython-310.pyc").write_bytes(b"\x00\x01\x02")

        yield root


class TestFileSystemConnectorCreation:
    """Tests for connector creation and validation."""

    def test_create_with_existing_root(self, temp_project: Path) -> None:
        """Create connector with existing directory."""
        connector = FileSystemConnector(root=str(temp_project))
        # Use resolve() to handle macOS /var -> /private/var symlink
        assert connector.root_path == temp_project.resolve()

    def test_create_with_default_root(self) -> None:
        """Create connector with default (cwd) root."""
        connector = FileSystemConnector()
        assert connector.root_path == Path.cwd()

    def test_create_with_nonexistent_root(self) -> None:
        """Create connector with nonexistent directory raises."""
        with pytest.raises(FileNotFoundError):
            FileSystemConnector(root="/nonexistent/path")

    def test_create_with_file_as_root(self, temp_project: Path) -> None:
        """Create connector with file as root raises."""
        file_path = temp_project / "README.md"
        with pytest.raises(NotADirectoryError):
            FileSystemConnector(root=str(file_path))

    def test_implements_protocol(self, temp_project: Path) -> None:
        """Connector implements ConnectorProtocol."""
        connector = FileSystemConnector(root=str(temp_project))
        assert isinstance(connector, ConnectorProtocol)

    def test_implements_watch_capability(self, temp_project: Path) -> None:
        """Connector implements WatchCapability."""
        connector = FileSystemConnector(root=str(temp_project))
        assert isinstance(connector, WatchCapability)
        assert has_watch_capability(connector)

    def test_implements_change_detection(self, temp_project: Path) -> None:
        """Connector implements ChangeDetectionCapability."""
        connector = FileSystemConnector(root=str(temp_project))
        assert isinstance(connector, ChangeDetectionCapability)
        assert has_change_detection(connector)


class TestFileEnumeration:
    """Tests for file listing."""

    @pytest.mark.asyncio
    async def test_list_all_files(self, temp_project: Path) -> None:
        """List enumerates all non-ignored files."""
        connector = FileSystemConnector(root=str(temp_project))

        items = []
        async for item in connector.list():
            items.append(item)

        # Should find README.md, main.py, utils.py, test_main.py
        # Should NOT find .git/config, __pycache__/*.pyc
        uris = [item.uri for item in items]
        assert any("README.md" in uri for uri in uris)
        assert any("main.py" in uri for uri in uris)
        assert any("utils.py" in uri for uri in uris)
        assert any("test_main.py" in uri for uri in uris)
        assert not any(".git" in uri for uri in uris)
        assert not any("__pycache__" in uri for uri in uris)

    @pytest.mark.asyncio
    async def test_list_subdirectory(self, temp_project: Path) -> None:
        """List can enumerate a subdirectory."""
        connector = FileSystemConnector(root=str(temp_project))

        items = []
        async for item in connector.list(str(temp_project / "src")):
            items.append(item)

        # Should find main.py, utils.py
        uris = [item.uri for item in items]
        assert any("main.py" in uri for uri in uris)
        assert any("utils.py" in uri for uri in uris)
        assert not any("README.md" in uri for uri in uris)
        assert not any("test_main.py" in uri for uri in uris)

    @pytest.mark.asyncio
    async def test_items_have_hash(self, temp_project: Path) -> None:
        """Listed items have content hash."""
        connector = FileSystemConnector(root=str(temp_project))

        async for item in connector.list():
            assert item.content_hash is not None
            # SHA256 hash is 64 hex chars
            assert len(item.content_hash) == 64
            break

    @pytest.mark.asyncio
    async def test_items_have_size(self, temp_project: Path) -> None:
        """Listed items have file size."""
        connector = FileSystemConnector(root=str(temp_project))

        async for item in connector.list():
            if "README.md" in item.uri:
                assert item.size is not None
                assert item.size > 0
                break

    @pytest.mark.asyncio
    async def test_custom_ignore_patterns(self, temp_project: Path) -> None:
        """Custom ignore patterns are respected."""
        connector = FileSystemConnector(
            root=str(temp_project),
            ignore_patterns=["*.py", "*.md"],  # Ignore all Python and Markdown
        )

        items = []
        async for item in connector.list():
            items.append(item)

        # Should not find any .py or .md files
        # Note: Check for files ENDING with .py/.md, not containing
        # (e.g., .pyc contains .py substring but shouldn't be filtered by *.py)
        uris = [item.uri for item in items]
        assert not any(uri.endswith(".py") for uri in uris)
        assert not any(uri.endswith(".md") for uri in uris)


class TestContentRetrieval:
    """Tests for file content reading."""

    @pytest.mark.asyncio
    async def test_open_text_file(self, temp_project: Path) -> None:
        """Open returns text content for text files."""
        connector = FileSystemConnector(root=str(temp_project))

        async for item in connector.list():
            if "README.md" in item.uri:
                content = await connector.open(item)
                assert content.encoding == "utf-8"
                assert "# Test Project" in content.text
                break

    @pytest.mark.asyncio
    async def test_open_python_file(self, temp_project: Path) -> None:
        """Open returns content for Python files."""
        connector = FileSystemConnector(root=str(temp_project))

        async for item in connector.list():
            if "main.py" in item.uri:
                content = await connector.open(item)
                assert "print" in content.text
                break

    @pytest.mark.asyncio
    async def test_open_nonexistent_file(self, temp_project: Path) -> None:
        """Open raises for nonexistent file."""
        connector = FileSystemConnector(root=str(temp_project))
        item = SourceItem(uri=str(temp_project / "nonexistent.txt"))

        with pytest.raises(FileNotFoundError):
            await connector.open(item)


class TestPathSecurity:
    """Tests for path traversal prevention."""

    @pytest.mark.asyncio
    async def test_traversal_in_list_rejected(self, temp_project: Path) -> None:
        """Path traversal in list() is rejected."""
        connector = FileSystemConnector(root=str(temp_project / "src"))

        # Try to enumerate parent directory
        with pytest.raises(ValueError, match="escapes root"):
            async for _ in connector.list(str(temp_project)):
                pass

    @pytest.mark.asyncio
    async def test_traversal_in_open_rejected(self, temp_project: Path) -> None:
        """Path traversal in open() is rejected."""
        connector = FileSystemConnector(root=str(temp_project / "src"))

        # Try to open file outside root
        item = SourceItem(uri=str(temp_project / "README.md"))

        with pytest.raises(ValueError, match="escapes root"):
            await connector.open(item)

    @pytest.mark.asyncio
    async def test_dotdot_traversal_rejected(self, temp_project: Path) -> None:
        """.. traversal is rejected."""
        connector = FileSystemConnector(root=str(temp_project / "src"))

        # Try to use .. to escape
        escape_path = str(temp_project / "src" / ".." / "README.md")
        item = SourceItem(uri=escape_path)

        with pytest.raises(ValueError, match="escapes root"):
            await connector.open(item)


class TestChangeDetection:
    """Tests for change detection capability."""

    @pytest.mark.asyncio
    async def test_has_changed_new_file(self, temp_project: Path) -> None:
        """New files are detected as changed."""
        connector = FileSystemConnector(root=str(temp_project))

        async for item in connector.list():
            # First check - should be changed (never processed)
            assert await connector.has_changed(item) is True
            break

    @pytest.mark.asyncio
    async def test_has_changed_after_mark(self, temp_project: Path) -> None:
        """Marked files are not detected as changed."""
        connector = FileSystemConnector(root=str(temp_project))

        async for item in connector.list():
            # Mark as processed
            await connector.mark_processed(item)

            # Should not be changed
            assert await connector.has_changed(item) is False
            break

    @pytest.mark.asyncio
    async def test_has_changed_no_hash(self, temp_project: Path) -> None:
        """Items without hash are always considered changed."""
        connector = FileSystemConnector(root=str(temp_project))

        item = SourceItem(uri=str(temp_project / "README.md"))
        # No content_hash

        assert await connector.has_changed(item) is True


class TestRegistry:
    """Tests for connector registry integration."""

    def test_filesystem_registered(self) -> None:
        """FileSystemConnector is registered as 'filesystem'."""
        connectors = list_connectors()
        assert "filesystem" in connectors
        assert "file" in connectors  # Alias

    def test_get_filesystem_connector(self, temp_project: Path) -> None:
        """get_connector returns FileSystemConnector."""
        connector = get_connector("filesystem", root=str(temp_project))
        assert isinstance(connector, FileSystemConnector)

    def test_get_file_connector_alias(self, temp_project: Path) -> None:
        """get_connector('file') returns FileSystemConnector."""
        connector = get_connector("file", root=str(temp_project))
        assert isinstance(connector, FileSystemConnector)

    def test_get_unknown_connector_raises(self) -> None:
        """get_connector raises for unknown name."""
        with pytest.raises(KeyError, match="Unknown connector"):
            get_connector("unknown_connector")
