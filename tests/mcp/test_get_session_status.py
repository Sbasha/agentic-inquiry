"""
Integration tests for get_session status field - Task 8.1.

Tests that get_session returns the status field correctly.
"""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import AsyncMock, MagicMock

from agentic_inquiry.mcp.tools.session import create_session, get_session
from agentic_inquiry.mcp.models.session import Session


@pytest.fixture
def mcp_services():
    """Create mock services for testing."""
    session_manager = AsyncMock()
    mock_db_manager = AsyncMock()
    event_system = AsyncMock()
    config = MagicMock()

    # Mock server configuration
    server_config = {
        "default_project_id": "test_project",
        "server_name": "Agentic Inquiry MCP Server",
        "server_version": "1.0.0",
    }

    # Store sessions in memory for testing
    sessions = {}

    # Mock session creation
    async def mock_create_session(project_id, description=None):
        session_id = f"test-session-{len(sessions)}"
        session = Session(
            session_id=session_id,
            project_id=project_id,
            description=description,
            status="active",
        )
        sessions[session_id] = session

        return {
            "session_id": session_id,
            "project_id": project_id,
            "status": "ready",
            "state": "active",
            "created_at": session.created_at.isoformat(),
            "last_active": session.last_active.isoformat(),
            "statistics": {
                "total_chunks": 0,
                "total_files": 0,
                "total_entities": 0,
                "index_health": "empty",
            },
            "guidance": "Project is ready",
            "next_steps": ["Index content with add_knowledge()"],
        }

    # Mock session validation
    async def mock_validate_session(session_id):
        return session_id in sessions

    # Mock session retrieval
    async def mock_get_session(session_id, include_history=False):
        if session_id in sessions:
            return sessions[session_id]
        return None

    # Mock session update
    async def mock_update_session(session):
        sessions[session.session_id] = session

    session_manager.create_session = mock_create_session
    session_manager.validate_session = mock_validate_session
    session_manager.get_session = mock_get_session
    session_manager.update_session = mock_update_session

    # Mock event system
    event_system.emit = AsyncMock()

    return {
        "session_manager": session_manager,
        "mock_db_manager": mock_db_manager,
        "storage": mock_db_manager,  # Expose as storage for tools
        "event_system": event_system,
        "config": config,
        "server_config": server_config,
    }


class TestGetSessionStatus:
    """Tests for get_session status field - Task 8.1."""

    @pytest.mark.asyncio
    async def test_get_session_includes_status_field(self, mcp_services):
        """Test that get_session returns status field."""
        # Create a session
        create_result = await create_session(
            mcp_services, project_id="test_project", description="Test session"
        )
        session_id = create_result["session_id"]

        # Get the session
        result = await get_session(
            mcp_services, session_id=session_id, include_history=True
        )

        # Verify status field exists
        assert "status" in result
        assert isinstance(result["status"], str)

    @pytest.mark.asyncio
    async def test_get_session_status_is_active(self, mcp_services):
        """Test that newly created session has active status."""
        # Create a session
        create_result = await create_session(mcp_services, project_id="test_project")
        session_id = create_result["session_id"]

        # Get the session
        result = await get_session(mcp_services, session_id=session_id)

        # Verify status is active
        assert result["status"] == "active"

    @pytest.mark.asyncio
    async def test_get_session_status_values(self, mcp_services):
        """Test get_session returns correct status values (active, expired, closed)."""
        # Create a session
        create_result = await create_session(mcp_services, project_id="test_project")
        session_id = create_result["session_id"]

        # Get the session - should be active
        result = await get_session(mcp_services, session_id=session_id)
        assert result["status"] == "active"

        # Mark session as expired
        session_manager = mcp_services["session_manager"]
        session = await session_manager.get_session(session_id)
        session.mark_expired()
        await session_manager.update_session(session)

        # Get the session again - should be expired
        result = await get_session(mcp_services, session_id=session_id)
        assert result["status"] == "expired"

    @pytest.mark.asyncio
    async def test_get_session_status_in_valid_values(self, mcp_services):
        """Test that status is one of the valid values."""
        # Create a session
        create_result = await create_session(mcp_services, project_id="test_project")
        session_id = create_result["session_id"]

        # Get the session
        result = await get_session(mcp_services, session_id=session_id)

        # Verify status is one of the valid values
        valid_statuses = ["active", "expired", "closed"]
        assert result["status"] in valid_statuses

    @pytest.mark.asyncio
    async def test_get_session_includes_activity_log(self, mcp_services):
        """Test that get_session returns activity_log field."""
        # Create a session
        create_result = await create_session(mcp_services, project_id="test_project")
        session_id = create_result["session_id"]

        # Get the session
        result = await get_session(
            mcp_services, session_id=session_id, include_history=True
        )

        # Verify activity_log field exists
        assert "activity_log" in result
        assert isinstance(result["activity_log"], list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
