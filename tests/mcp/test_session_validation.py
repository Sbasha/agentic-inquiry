"""
Tests for enhanced create_session() validation.

Tests project_id validation, normalization warnings, and mismatch warnings.
"""

import pytest

pytestmark = pytest.mark.unit
import logging
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

from agentic_inquiry.mcp.tools.session import create_session


@pytest.fixture
def mcp_services():
    """Create mock services for testing."""
    session_manager = AsyncMock()
    mock_db_manager = AsyncMock()
    event_system = AsyncMock()
    config = MagicMock()
    
    # Mock server configuration
    server_config = {
        "default_project_id": "default_project",
        "server_name": "Agentic Inquiry MCP Server",
        "server_version": "1.0.0",
        "server_description": "Intelligent search and knowledge management"
    }
    
    # Mock successful session creation
    async def mock_create_session(project_id, description=None):
        return {
            "session_id": "test-session-123",
            "project_id": project_id,
            "status": "ready",
            "created_at": datetime.now().isoformat(),
            "last_active": datetime.now().isoformat(),
            "statistics": {
                "total_chunks": 0,
                "total_files": 0,
                "total_entities": 0,
                "index_health": "empty"
            },
            "guidance": "Project is ready",
            "next_steps": ["Index content with add_knowledge()"]
        }
    
    session_manager.create_session = mock_create_session
    
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


class TestCreateSessionValidation:
    """Tests for create_session() validation enhancements."""
    
    @pytest.mark.asyncio
    async def test_create_session_with_valid_project_id(self, mcp_services):
        """Test creating session with valid project_id formats."""
        # Test various valid formats
        valid_ids = [
            "my-project",
            "project_123",
            "my_project",
            "Project-With-Hyphens",
            "project123",
            "a"  # Single character
        ]
        
        for project_id in valid_ids:
            result = await create_session(mcp_services, project_id=project_id)
            
            # Should succeed
            assert "session_id" in result
            assert "error" not in result
            # Project ID should be normalized to lowercase
            assert result["project_id"] == project_id.lower()
    
    @pytest.mark.asyncio
    async def test_create_session_with_invalid_project_id_characters(self, mcp_services):
        """Test creating session with invalid characters in project_id."""
        # Test invalid characters
        invalid_ids = [
            "invalid project",  # Space
            "project!",  # Special char
            "project@123",  # @ symbol
            "project#tag",  # # symbol
            "project/path",  # Slash
        ]
        
        for project_id in invalid_ids:
            result = await create_session(mcp_services, project_id=project_id)
            
            # Should return validation error
            assert "error" in result
            assert "error_code" in result
            assert result["error_code"] == "INVALID_PROJECT_ID"
            assert "suggestion" in result
            assert "get_server_info()" in result["suggestion"]
            assert "examples" in result
    
    @pytest.mark.asyncio
    async def test_create_session_with_empty_project_id(self, mcp_services):
        """Test creating session with empty project_id."""
        result = await create_session(mcp_services, project_id="")
        
        # Should return validation error
        assert "error" in result
        assert "error_code" in result
        assert result["error_code"] == "INVALID_PROJECT_ID"
        assert "cannot be empty" in result["error"].lower()
    
    @pytest.mark.asyncio
    async def test_create_session_with_too_long_project_id(self, mcp_services):
        """Test creating session with project_id exceeding 64 characters."""
        # Create a project_id with 65 characters
        long_id = "a" * 65
        result = await create_session(mcp_services, project_id=long_id)
        
        # Should return validation error
        assert "error" in result
        assert "error_code" in result
        assert result["error_code"] == "INVALID_PROJECT_ID"
        assert "maximum length" in result["error"].lower()
        assert "64" in result["error"]
    
    @pytest.mark.asyncio
    async def test_create_session_normalization_warning(self, mcp_services, caplog):
        """Test that uppercase project_id is normalized with warning."""
        # Use uppercase project_id
        with caplog.at_level(logging.WARNING):
            result = await create_session(mcp_services, project_id="MyProject")
        
        # Should succeed with normalized ID
        assert "session_id" in result
        assert result["project_id"] == "myproject"
        
        # Should log warning about normalization
        assert any("normalized" in record.message.lower() for record in caplog.records)
        assert any("MyProject" in record.message for record in caplog.records)
        assert any("myproject" in record.message for record in caplog.records)
    
    @pytest.mark.asyncio
    async def test_create_session_mismatch_warning(self, mcp_services):
        """Test warning when project differs from server default."""
        # Use different project than default
        result = await create_session(mcp_services, project_id="different_project")
        
        # Should succeed but include warning
        assert "session_id" in result
        assert "warning" in result
        assert "message" in result["warning"]
        assert "default_project" in result["warning"]["message"]
        assert "different_project" in result["warning"]["message"]
        assert "suggestion" in result["warning"]
        assert "get_server_info()" in result["warning"]["suggestion"]
    
    @pytest.mark.asyncio
    async def test_create_session_no_mismatch_warning_for_default(self, mcp_services):
        """Test no warning when using server default project."""
        # Use server default project
        result = await create_session(mcp_services, project_id="default_project")
        
        # Should succeed without warning
        assert "session_id" in result
        assert "warning" not in result
    
    @pytest.mark.asyncio
    async def test_create_session_error_message_includes_get_server_info(self, mcp_services):
        """Test that error messages suggest calling get_server_info()."""
        # Test with invalid project_id
        result = await create_session(mcp_services, project_id="invalid project!")
        
        # Error should suggest get_server_info()
        assert "error" in result
        assert "suggestion" in result
        assert "get_server_info()" in result["suggestion"]
    
    @pytest.mark.asyncio
    async def test_create_session_validation_examples_in_error(self, mcp_services):
        """Test that validation errors include examples of valid formats."""
        result = await create_session(mcp_services, project_id="invalid project!")
        
        # Should include examples
        assert "examples" in result
        assert isinstance(result["examples"], list)
        assert len(result["examples"]) > 0
        # Examples should be valid formats
        for example in result["examples"]:
            assert "-" in example or "_" in example or example.isalnum()
    
    @pytest.mark.asyncio
    async def test_create_session_successful_with_valid_project_id(self, mcp_services):
        """Test successful session creation with valid project_id."""
        result = await create_session(
            mcp_services,
            project_id="my-project",
            description="Test session"
        )
        
        # Should succeed
        assert "session_id" in result
        assert result["project_id"] == "my-project"
        assert "error" not in result
        assert "status" in result
        assert "statistics" in result
    
    @pytest.mark.asyncio
    async def test_create_session_validation_before_creation(self, mcp_services):
        """Test that validation happens before session creation."""
        # Mock session manager to track if it was called
        call_count = 0
        
        async def mock_create_session(project_id, description=None):
            nonlocal call_count
            call_count += 1
            return {"session_id": "test-123", "project_id": project_id}
        
        mcp_services["session_manager"].create_session = mock_create_session
        
        # Try with invalid project_id
        result = await create_session(mcp_services, project_id="invalid project!")
        
        # Should return error without calling session manager
        assert "error" in result
        assert call_count == 0  # Session manager should not be called
    
    @pytest.mark.asyncio
    async def test_create_session_events_emitted(self, mcp_services):
        """Test that events are emitted for session creation."""
        await create_session(mcp_services, project_id="test-project")
        
        # Verify events were emitted
        event_system = mcp_services["event_system"]
        assert event_system.emit.called
        
        # Check for started and completed events
        calls = event_system.emit.call_args_list
        event_types = [call[0][0] for call in calls]
        assert "mcp.tool.started" in event_types
        assert "mcp.tool.completed" in event_types
    
    @pytest.mark.asyncio
    async def test_create_session_no_server_config(self, mcp_services):
        """Test behavior when server_config is not available."""
        # Remove server_config
        del mcp_services["server_config"]
        
        # Should still work without mismatch warnings
        result = await create_session(mcp_services, project_id="test-project")
        
        # Should succeed
        assert "session_id" in result
        assert "warning" not in result
    
    @pytest.mark.asyncio
    async def test_create_session_mixed_case_normalization(self, mcp_services, caplog):
        """Test normalization of mixed case project_id."""
        with caplog.at_level(logging.WARNING):
            result = await create_session(mcp_services, project_id="My-Project_123")
        
        # Should normalize to lowercase
        assert result["project_id"] == "my-project_123"
        
        # Should log warning
        assert any("normalized" in record.message.lower() for record in caplog.records)
    
    @pytest.mark.asyncio
    async def test_create_session_boundary_length(self, mcp_services):
        """Test project_id at boundary lengths."""
        # Test at exactly 64 characters (should succeed)
        valid_64 = "a" * 64
        result = await create_session(mcp_services, project_id=valid_64)
        assert "session_id" in result
        assert "error" not in result
        
        # Test at 65 characters (should fail)
        invalid_65 = "a" * 65
        result = await create_session(mcp_services, project_id=invalid_65)
        assert "error" in result
        assert result["error_code"] == "INVALID_PROJECT_ID"
    
    @pytest.mark.asyncio
    async def test_create_session_with_description(self, mcp_services):
        """Test creating session with description."""
        result = await create_session(
            mcp_services,
            project_id="test-project",
            description="Working on authentication feature"
        )
        
        # Should succeed
        assert "session_id" in result
        assert "error" not in result
    
    @pytest.mark.asyncio
    async def test_create_session_error_handling(self, mcp_services):
        """Test error handling when session creation fails."""
        # Make session manager raise an exception
        async def mock_create_error(project_id, description=None):
            raise Exception("Database connection failed")
        
        mcp_services["session_manager"].create_session = mock_create_error
        
        # Should handle error gracefully
        result = await create_session(mcp_services, project_id="test-project")
        
        # Should return error with suggestion
        assert "error" in result
        assert "suggestion" in result
        assert "get_server_info()" in result["suggestion"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
