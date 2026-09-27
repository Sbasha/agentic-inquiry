"""Security tests for path validation in MCP tools.

This module tests that path validation is properly integrated into MCP tools
to prevent directory traversal attacks and unauthorized file access.
"""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock, patch

from agentic_inquiry.mcp.tools.knowledge import add_knowledge


class TestAddKnowledgePathSecurity:
    """Test path security in add_knowledge tool.

    These tests verify that path validation is properly integrated into the
    add_knowledge tool to prevent directory traversal attacks. The tests focus
    on the security validation layer that runs before any file operations.
    """

    @pytest.fixture
    def mcp_services(self):
        """Create minimal mock services for path validation testing.

        Note: These tests only need enough mocking to reach the path validation
        logic. The path validation happens early in add_knowledge() and returns
        immediately on security violations, so we don't need full service mocks.
        """
        from agentic_inquiry.config import Config

        # Create a minimal config
        config = Config()

        # Create session manager with async methods
        session_manager = MagicMock()
        session_manager.validate_session = AsyncMock(return_value=True)

        # Create a mock session object with project_id attribute
        mock_session = MagicMock()
        mock_session.project_id = "test_project"
        session_manager.get_session = AsyncMock(return_value=mock_session)

        return {
            "session_manager": session_manager,
            "event_system": AsyncMock(),
            "config": config,
            "mock_db_manager": MagicMock(),
            "storage": MagicMock(),  # Needed for service extraction at function start
        }

    @pytest.mark.asyncio
    async def test_directory_traversal_file_blocked(self, tmp_path, mcp_services):
        """Test that directory traversal attempts for files are blocked."""
        with patch("os.getcwd", return_value=str(tmp_path)):
            result = await add_knowledge(
                services=mcp_services,
                session_id="test_session",
                source="../../../etc/passwd",
                content_type="file",
            )

        assert result["status"] == "failed"
        assert result["error_type"] == "path_validation"
        assert "outside allowed directory" in result["error"]

    @pytest.mark.asyncio
    async def test_directory_traversal_directory_blocked(self, tmp_path, mcp_services):
        """Test that directory traversal attempts for directories are blocked."""
        with patch("os.getcwd", return_value=str(tmp_path)):
            result = await add_knowledge(
                services=mcp_services,
                session_id="test_session",
                source="../../../etc",
                content_type="directory",
            )

        assert result["status"] == "failed"
        assert result["error_type"] == "path_validation"
        assert "outside allowed directory" in result["error"]

    @pytest.mark.asyncio
    async def test_absolute_path_outside_project_blocked(self, tmp_path, mcp_services):
        """Test that absolute paths outside project are blocked."""
        with patch("os.getcwd", return_value=str(tmp_path)):
            result = await add_knowledge(
                services=mcp_services,
                session_id="test_session",
                source="/etc/passwd",
                content_type="file",
            )

        assert result["status"] == "failed"
        assert result["error_type"] == "path_validation"
        assert "outside allowed directory" in result["error"]

    @pytest.mark.asyncio
    async def test_symlink_traversal_blocked(self, tmp_path, mcp_services):
        """Test that symlinks pointing outside project are blocked."""
        # Create a directory outside the project
        outside_dir = tmp_path.parent / "outside"
        outside_dir.mkdir(exist_ok=True)
        outside_file = outside_dir / "secret.txt"
        outside_file.write_text("secret data")

        # Create a symlink inside the project pointing outside
        symlink = tmp_path / "link_to_secret"
        try:
            symlink.symlink_to(outside_file)
        except OSError:
            pytest.skip("Symlinks not supported on this system")

        with patch("os.getcwd", return_value=str(tmp_path)):
            result = await add_knowledge(
                services=mcp_services,
                session_id="test_session",
                source="link_to_secret",
                content_type="file",
            )

        assert result["status"] == "failed"
        assert result["error_type"] == "path_validation"
        assert "outside allowed directory" in result["error"]

    @pytest.mark.asyncio
    async def test_complex_traversal_sequence_blocked(self, tmp_path, mcp_services):
        """Test that complex directory traversal sequences are blocked."""
        # Create a subdirectory
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        with patch("os.getcwd", return_value=str(tmp_path)):
            result = await add_knowledge(
                services=mcp_services,
                session_id="test_session",
                source="subdir/../../etc/passwd",
                content_type="file",
            )

        assert result["status"] == "failed"
        assert result["error_type"] == "path_validation"
        assert "outside allowed directory" in result["error"]

    @pytest.mark.asyncio
    async def test_error_response_includes_troubleshooting(
        self, tmp_path, mcp_services
    ):
        """Test that path validation errors include troubleshooting information."""
        with patch("os.getcwd", return_value=str(tmp_path)):
            result = await add_knowledge(
                services=mcp_services,
                session_id="test_session",
                source="../../../etc/passwd",
                content_type="file",
            )

        assert result["status"] == "failed"
        assert result["error_type"] == "path_validation"
        assert "troubleshooting" in result
        assert "possible_causes" in result["troubleshooting"]
        assert "next_steps" in result["troubleshooting"]
        assert len(result["troubleshooting"]["possible_causes"]) > 0
        assert len(result["troubleshooting"]["next_steps"]) > 0
