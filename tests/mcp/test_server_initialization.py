"""Tests for MCP server initialization.

This module tests:
- Server creation and initialization
- Configuration loading
- Service creation
- Tool registration
- Lifecycle management
"""

import pytest

pytestmark = pytest.mark.unit

from unittest.mock import Mock, patch

from agent_vault.config import Config
from agent_vault.mcp.server import MCPServer


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    config = Mock(spec=Config)
    
    # MCP configuration
    config.mcp = Mock()
    config.mcp.enabled = True
    config.mcp.server = Mock()
    config.mcp.server.name = "Test MCP Server"
    config.mcp.server.version = "1.0.0"
    config.mcp.server.description = "Test server"
    
    config.mcp.tools = Mock()
    config.mcp.tools.cognitive = {"enabled": True}
    config.mcp.tools.direct_access = {"enabled": False}
    
    config.mcp.api = Mock()
    config.mcp.api.enabled = True
    config.mcp.api.host = "localhost"
    config.mcp.api.port = 8765
    
    return config


@pytest.fixture
def mcp_services():
    """Create mock services dictionary."""
    return {
        "mock_db_manager": Mock(),
        "search_service": Mock(),
        "mock_indexing_pipeline": Mock(),
        "memory_system": Mock(),
        "event_system": Mock(),
        "session_manager": Mock(),
        "context_builder": Mock(),
        "pattern_analyzer": Mock(),
        "temporal_analyzer": Mock(),
        "token_optimizer": Mock(),
    }


class TestMCPServerCreation:
    """Test MCP server creation."""
    
    def test_server_creation_with_config(self, mock_config):
        """Test server can be created with configuration."""
        server = MCPServer(config=mock_config, project_id="test_project")
        
        assert server.config == mock_config
        assert server.project_id == "test_project"
        assert server.app is None
        assert server.services == {}
        assert not server._initialized
    
    def test_server_creation_without_project_id(self, mock_config):
        """Test server can be created without project_id."""
        server = MCPServer(config=mock_config)
        
        assert server.config == mock_config
        assert server.project_id is None
        assert not server._initialized


class TestMCPServerInitialization:
    """Test MCP server initialization."""
    
    @pytest.mark.asyncio
    async def test_initialize_with_project_id(self, mock_config, mcp_services):
        """Test server initialization with project_id."""
        with patch('agent_vault.mcp.server.FastMCP') as mock_fastmcp, \
             patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services):
            
            server = MCPServer(config=mock_config, project_id="test_project")
            await server.initialize()
            
            # Verify FastMCP was created (uses 'instructions' parameter, not 'description')
            mock_fastmcp.assert_called_once_with(
                name="Test MCP Server",
                version="1.0.0",
                instructions="Test server"
            )
            
            # Verify services were created
            assert server.services == mcp_services
            assert server._initialized
    
    @pytest.mark.asyncio
    async def test_initialize_without_project_id_fails(self, mock_config):
        """Test initialization fails without project_id."""
        server = MCPServer(config=mock_config)
        
        with pytest.raises(ValueError, match="project_id must be provided"):
            await server.initialize()
    
    @pytest.mark.asyncio
    async def test_initialize_with_mcp_disabled_fails(self, mock_config):
        """Test initialization fails when MCP is disabled."""
        mock_config.mcp.enabled = False
        server = MCPServer(config=mock_config, project_id="test_project")
        
        with pytest.raises(RuntimeError, match="MCP is not enabled"):
            await server.initialize()
    
    @pytest.mark.asyncio
    async def test_initialize_idempotent(self, mock_config, mcp_services):
        """Test initialization is idempotent."""
        with patch('agent_vault.mcp.server.FastMCP'), \
             patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services):
            
            server = MCPServer(config=mock_config, project_id="test_project")
            
            # Initialize twice
            await server.initialize()
            await server.initialize()
            
            # Should only initialize once
            assert server._initialized
    
    @pytest.mark.asyncio
    async def test_initialize_with_direct_tools_enabled(self, mock_config, mcp_services):
        """Test initialization with direct access tools enabled."""
        mock_config.mcp.tools.direct_access = {"enabled": True}
        
        with patch('agent_vault.mcp.server.FastMCP'), \
             patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services):
            
            server = MCPServer(config=mock_config, project_id="test_project")
            await server.initialize()
            
            assert server._initialized


class TestServiceCreation:
    """Test service creation during initialization."""
    
    @pytest.mark.asyncio
    async def test_services_created_successfully(self, mock_config, mcp_services):
        """Test services are created successfully."""
        with patch('agent_vault.mcp.server.FastMCP'), \
             patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services) as mock_create:
            
            server = MCPServer(config=mock_config, project_id="test_project")
            await server.initialize()
            
            # Verify create_mcp_services was called
            mock_create.assert_called_once_with(
                config=mock_config,
                project_id="test_project"
            )
            
            # Verify services are stored
            assert server.services == mcp_services
    
    @pytest.mark.asyncio
    async def test_service_creation_failure_propagates(self, mock_config):
        """Test service creation failure propagates."""
        with patch('agent_vault.mcp.server.FastMCP'), \
             patch('agent_vault.mcp.server.create_mcp_services', side_effect=Exception("Service creation failed")):
            
            server = MCPServer(config=mock_config, project_id="test_project")
            
            with pytest.raises(Exception, match="Service creation failed"):
                await server.initialize()


class TestServerLifecycle:
    """Test server lifecycle management."""
    
    @pytest.mark.asyncio
    async def test_start_requires_initialization(self, mock_config):
        """Test start fails if not initialized."""
        server = MCPServer(config=mock_config, project_id="test_project")
        
        with pytest.raises(RuntimeError, match="must be initialized"):
            await server.start()
    
    @pytest.mark.asyncio
    async def test_start_after_initialization(self, mock_config, mcp_services):
        """Test server can start after initialization."""
        with patch('agent_vault.mcp.server.FastMCP'), \
             patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services):
            
            server = MCPServer(config=mock_config, project_id="test_project")
            await server.initialize()
            await server.start()
            
            # Should not raise
            assert server._initialized
    
    @pytest.mark.asyncio
    async def test_shutdown_cleans_up_services(self, mock_config, mcp_services):
        """Test shutdown cleans up services."""
        with patch('agent_vault.mcp.server.FastMCP'), \
             patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services):
            
            server = MCPServer(config=mock_config, project_id="test_project")
            await server.initialize()
            
            # Verify services exist
            assert len(server.services) > 0
            
            # Shutdown
            await server.shutdown()
            
            # Verify cleanup
            assert len(server.services) == 0
            assert not server._initialized
    
    @pytest.mark.asyncio
    async def test_shutdown_without_initialization(self, mock_config):
        """Test shutdown works even without initialization."""
        server = MCPServer(config=mock_config, project_id="test_project")

        # Should not raise
        await server.shutdown()

        assert not server._initialized

    @pytest.mark.asyncio
    async def test_shutdown_cancels_maintenance_task(self, mock_config, mcp_services):
        """Shutdown must cancel the background maintenance task so it does not
        keep ticking against torn-down dependencies. Regression for #169 review."""
        import asyncio

        async def _never_finishes():
            await asyncio.sleep(3600)

        task = asyncio.create_task(_never_finishes())
        services_with_task = {**mcp_services, "maintenance_task": task}

        with patch('agent_vault.mcp.server.FastMCP'), \
             patch('agent_vault.mcp.server.create_mcp_services', return_value=services_with_task):
            server = MCPServer(config=mock_config, project_id="test_project")
            await server.initialize()
            assert not task.done(), "task must still be running before shutdown"

            await server.shutdown()

            assert task.done(), "shutdown must complete the maintenance task"
            assert task.cancelled(), "shutdown must cancel (not let it finish naturally)"
            assert len(server.services) == 0


class TestGetApp:
    """Test getting FastMCP app instance."""
    
    @pytest.mark.asyncio
    async def test_get_app_after_initialization(self, mock_config, mcp_services):
        """Test get_app returns app after initialization."""
        with patch('agent_vault.mcp.server.FastMCP') as mock_fastmcp, \
             patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services):
            
            mock_app = Mock()
            mock_fastmcp.return_value = mock_app
            
            server = MCPServer(config=mock_config, project_id="test_project")
            await server.initialize()
            
            app = server.get_app()
            assert app == mock_app
    
    def test_get_app_before_initialization_fails(self, mock_config):
        """Test get_app fails before initialization."""
        server = MCPServer(config=mock_config, project_id="test_project")
        
        with pytest.raises(RuntimeError, match="must be initialized"):
            server.get_app()


class TestConfigurationHandling:
    """Test configuration handling."""
    
    @pytest.mark.asyncio
    async def test_uses_config_values(self, mock_config, mcp_services):
        """Test server uses configuration values."""
        with patch('agent_vault.mcp.server.FastMCP') as mock_fastmcp, \
             patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services):
            
            server = MCPServer(config=mock_config, project_id="test_project")
            await server.initialize()
            
            # Verify FastMCP was created with config values
            # Note: FastMCP uses 'instructions' parameter, not 'description'
            mock_fastmcp.assert_called_once_with(
                name=mock_config.mcp.server.name,
                version=mock_config.mcp.server.version,
                instructions=mock_config.mcp.server.description
            )
    
    @pytest.mark.asyncio
    async def test_project_id_override(self, mock_config, mcp_services):
        """Test project_id can be overridden in initialize."""
        with patch('agent_vault.mcp.server.FastMCP'), \
             patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services) as mock_create:
            
            server = MCPServer(config=mock_config, project_id="original_project")
            await server.initialize(project_id="override_project")
            
            # Verify override was used
            mock_create.assert_called_once_with(
                config=mock_config,
                project_id="override_project"
            )
            assert server.project_id == "override_project"
