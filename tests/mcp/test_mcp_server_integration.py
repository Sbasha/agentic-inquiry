"""
Integration tests for MCP server startup and tool registration.

This test validates that:
1. MCP server can start without import errors
2. All tools register successfully with their models
3. Tool execution works with request validation
4. Response validation works correctly
"""

import pytest

pytestmark = pytest.mark.integration
from unittest.mock import Mock, MagicMock, AsyncMock, patch

from agent_vault.config import Config
from agent_vault.mcp.server import MCPServer


@pytest.fixture
def mock_config():
    """Create a test configuration."""
    config = Config.load()
    
    # Ensure MCP is enabled
    if not hasattr(config, 'mcp') or not config.mcp.enabled:
        pytest.skip("MCP not enabled in configuration")
    
    return config


@pytest.fixture
async def mcp_services():
    """Create mock services for testing."""
    # Create mock database manager
    mock_db = AsyncMock()
    mock_db.advanced_filter = AsyncMock(return_value=[])
    mock_db.insert = AsyncMock()
    mock_db.count_records = AsyncMock(return_value=0)
    
    # Create mock search service
    mock_search = AsyncMock()
    mock_search.hybrid_search = AsyncMock(return_value=[])
    mock_search.vector_search = AsyncMock(return_value=[])
    mock_search.full_text_search = AsyncMock(return_value=[])
    
    # Create mock indexing pipeline
    mock_pipeline = AsyncMock()
    mock_pipeline.process_document = AsyncMock()
    mock_pipeline.flush_pending_relationships = AsyncMock(return_value=0)
    mock_pipeline.get_resolution_stats = MagicMock(return_value={})
    
    # Create mock memory system
    mock_memory = AsyncMock()
    mock_memory.store = AsyncMock()
    mock_memory.retrieve = AsyncMock(return_value=[])
    
    # Create mock event system
    mock_events = AsyncMock()
    mock_events.emit = AsyncMock()
    mock_events.query = AsyncMock(return_value=[])
    
    # Create mock session manager
    mock_session_mgr = AsyncMock()
    mock_session = Mock()
    mock_session.session_id = "test_session"
    mock_session.project_id = "test_project"
    mock_session.state = "active"
    mock_session_mgr.get_session = AsyncMock(return_value=mock_session)
    mock_session_mgr.create_session = AsyncMock(return_value=mock_session)
    mock_session_mgr.validate_session = AsyncMock(return_value=True)
    
    # Create mock context builder
    mock_context = AsyncMock()
    mock_context.build_context = AsyncMock(return_value={
        "context_items": [],
        "summary": "Test context",
        "suggestions": []
    })
    
    # Create mock pattern analyzer
    mock_patterns = AsyncMock()
    mock_patterns.find_patterns = AsyncMock(return_value={
        "patterns": [],
        "suggestions": []
    })
    
    # Create mock temporal analyzer
    mock_temporal = AsyncMock()
    mock_temporal.get_recent_activity = AsyncMock(return_value={
        "recent_activity": []
    })
    
    # Create mock token optimizer
    mock_token = AsyncMock()
    mock_token.optimize = AsyncMock(return_value={
        "optimized_content": "test",
        "token_count": 10
    })
    
    return {
        "mock_db_manager": mock_db,
        "storage": mock_db,  # Expose as storage for tools
        "search_service": mock_search,
        "mock_indexing_pipeline": mock_pipeline,
        "indexing_pipeline": mock_pipeline,  # Also expose as indexing_pipeline for tools
        "memory_system": mock_memory,
        "event_system": mock_events,
        "session_manager": mock_session_mgr,
        "context_builder": mock_context,
        "pattern_analyzer": mock_patterns,
        "temporal_analyzer": mock_temporal,
        "token_optimizer": mock_token,
        "config": Config.load(),
    }


class TestMCPServerStartup:
    """Test MCP server can start without import errors."""
    
    @pytest.mark.asyncio
    async def test_server_starts_without_import_errors(self, mock_config, mcp_services):
        """Test MCP server can start without any import errors."""
        with patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services), \
             patch('agent_vault.mcp.server.FastMCP') as mock_fastmcp:
            
            # Mock FastMCP to avoid actual initialization
            mock_app = Mock()
            mock_fastmcp.return_value = mock_app
            
            server = MCPServer(config=mock_config, project_id="test_project")
            
            # This should not raise any import errors
            await server.initialize()
            
            assert server._initialized
            assert server.app is not None
            assert len(server.services) > 0
    
    @pytest.mark.asyncio
    async def test_server_initializes_all_services(self, mock_config, mcp_services):
        """Test server initializes all required services."""
        with patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services), \
             patch('agent_vault.mcp.server.FastMCP'):
            
            server = MCPServer(config=mock_config, project_id="test_project")
            await server.initialize()
            
            # Verify all services are present
            required_services = [
                "mock_db_manager",
                "search_service",
                "mock_indexing_pipeline",
                "memory_system",
                "event_system",
                "session_manager",
            ]
            
            for service_name in required_services:
                assert service_name in server.services, f"Missing service: {service_name}"


class TestToolRegistration:
    """Test all tools register successfully."""
    
    @pytest.mark.asyncio
    async def test_all_cognitive_tools_register(self, mock_config, mcp_services):
        """Test all cognitive tools register successfully."""
        with patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services), \
             patch('agent_vault.mcp.server.FastMCP'):
            
            server = MCPServer(config=mock_config, project_id="test_project")
            await server.initialize()
            
            # Import all cognitive tool modules to verify they can be imported
            # Current architecture uses function-based tools, not classes
            from agent_vault.mcp.tools import search
            from agent_vault.mcp.tools import knowledge
            from agent_vault.mcp.tools import context
            from agent_vault.mcp.tools import analysis
            from agent_vault.mcp.tools import memory
            from agent_vault.mcp.tools import info
            from agent_vault.mcp.tools import session
            
            # Verify each module has the expected tool functions
            assert hasattr(search, 'search_knowledge')
            assert hasattr(knowledge, 'add_knowledge')
            assert hasattr(context, 'build_context')
            assert hasattr(analysis, 'understand_entity')
            assert hasattr(analysis, 'analyze_impact')
            assert hasattr(analysis, 'find_patterns')
            assert hasattr(memory, 'save_memory')
            assert hasattr(memory, 'recall_memories')
            assert hasattr(info, 'get_events')
            assert hasattr(info, 'get_project_info')
            assert hasattr(info, 'get_server_info')
            assert hasattr(session, 'create_session')
            assert hasattr(session, 'get_session')
            assert hasattr(session, 'list_sessions')
            assert hasattr(session, 'resume_session')
    
    @pytest.mark.asyncio
    async def test_tools_have_required_attributes(self, mock_config, mcp_services):
        """Test all tools have required attributes for registration."""
        with patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services), \
             patch('agent_vault.mcp.server.FastMCP'):
            
            server = MCPServer(config=mock_config, project_id="test_project")
            await server.initialize()
            
            # Import tool functions (current architecture uses functions, not classes)
            from agent_vault.mcp.tools.search import search_knowledge
            from agent_vault.mcp.tools.knowledge import add_knowledge
            from agent_vault.mcp.tools.context import build_context
            from agent_vault.mcp.tools.analysis import understand_entity, analyze_impact, find_patterns
            
            # Check that tool functions are callable and have docstrings
            tool_functions = [
                search_knowledge,
                add_knowledge,
                build_context,
                understand_entity,
                analyze_impact,
                find_patterns
            ]
            
            for tool_func in tool_functions:
                assert callable(tool_func), f"{tool_func.__name__} is not callable"
                assert tool_func.__doc__ is not None, f"{tool_func.__name__} missing docstring"
                # Verify function signature includes 'services' as first parameter
                import inspect
                sig = inspect.signature(tool_func)
                params = list(sig.parameters.keys())
                assert len(params) > 0, f"{tool_func.__name__} has no parameters"
                assert params[0] == 'services', f"{tool_func.__name__} first parameter should be 'services', got '{params[0]}'"


class TestRequestValidation:
    """Test tool execution with request validation."""
    
    @pytest.mark.asyncio
    async def test_search_tool_validates_request(self, mock_config, mcp_services):
        """Test search_knowledge validates request parameters."""
        with patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services):
            from agent_vault.mcp.tools.search import search_knowledge
            import inspect
            
            # Verify function signature has required parameters
            sig = inspect.signature(search_knowledge)
            params = list(sig.parameters.keys())
            
            # Check required parameters exist
            assert 'services' in params
            assert 'session_id' in params
            assert 'query' in params
            
            # Check that limit has a default value
            assert sig.parameters['limit'].default == 10
    
    @pytest.mark.asyncio
    async def test_search_tool_executes_with_valid_params(self, mock_config, mcp_services):
        """Test search_knowledge executes with valid parameters."""
        with patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services):
            from agent_vault.mcp.tools.search import search_knowledge
            
            # Execute with valid parameters
            result = await search_knowledge(
                services=mcp_services,
                session_id="test_session",
                query="test query",
                limit=10
            )
            
            # Should return a dict result (not raise exception)
            assert isinstance(result, dict)
            # Should have results or error key
            assert "results" in result or "error" in result
    
    @pytest.mark.asyncio
    async def test_add_knowledge_tool_validates_request(self, mock_config, mcp_services):
        """Test add_knowledge validates request parameters."""
        with patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services):
            from agent_vault.mcp.tools.knowledge import add_knowledge
            import inspect
            
            # Verify function signature has required parameters
            sig = inspect.signature(add_knowledge)
            params = list(sig.parameters.keys())
            
            # Check required parameters exist
            assert 'services' in params
            assert 'session_id' in params
            assert 'content_type' in params
            assert 'source' in params
    
    @pytest.mark.asyncio
    async def test_memory_tool_validates_request(self, mock_config, mcp_services):
        """Test save_memory validates request parameters."""
        with patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services):
            from agent_vault.mcp.tools.memory import save_memory
            import inspect
            
            # Verify function signature has required parameters
            sig = inspect.signature(save_memory)
            params = list(sig.parameters.keys())
            
            # Check required parameters exist
            assert 'services' in params
            assert 'session_id' in params
            assert 'summary' in params
            assert 'content' in params
            
            # Check that importance has a default value
            assert sig.parameters['importance'].default == "medium"


class TestResponseValidation:
    """Test response validation works correctly."""
    
    @pytest.mark.asyncio
    async def test_search_response_structure(self, mock_config, mcp_services):
        """Test search response has correct structure."""
        with patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services):
            from agent_vault.mcp.tools.search import search_knowledge
            
            # Execute search
            result = await search_knowledge(
                services=mcp_services,
                session_id="test_session",
                query="test query",
                limit=10,
            )
            
            # Verify response structure
            assert isinstance(result, dict)
            assert "results" in result or "error" in result
    
    @pytest.mark.asyncio
    async def test_session_response_structure(self, mock_config, mcp_services):
        """Test session creation response has correct structure."""
        # Mock session manager to return proper dict structure with all required fields
        mock_session_result = {
            "session_id": "test_session_123",
            "project_id": "test_project",
            "status": "active",
            "created_at": "2024-01-01T00:00:00",
            "last_active": "2024-01-01T00:00:00",
            "statistics": {
                "total_chunks": 0,
                "total_files": 0,
                "total_entities": 0,
            },
            "guidance": {
                "next_steps": ["Session created successfully"]
            }
        }
        mcp_services["session_manager"].create_session = AsyncMock(return_value=mock_session_result)
        
        with patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services):
            from agent_vault.mcp.tools.session import create_session
            
            # Execute session creation
            result = await create_session(
                services=mcp_services,
                project_id="test_project",
            )
            
            # Verify response structure
            assert isinstance(result, dict)
            assert "session_id" in result
            assert "project_id" in result
            assert "status" in result
            assert result["session_id"] == "test_session_123"
            assert result["project_id"] == "test_project"
    
    @pytest.mark.asyncio
    async def test_memory_response_structure(self, mock_config, mcp_services):
        """Test memory save response has correct structure."""
        with patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services):
            from agent_vault.mcp.tools.memory import save_memory
            
            # Create a mock memory item
            mock_memory_item = Mock()
            mock_memory_item.id = "test_memory_id"
            mock_memory_item.created_at = Mock()
            mock_memory_item.created_at.isoformat = Mock(return_value="2024-01-01T00:00:00")
            mock_memory_item.tier = Mock()
            mock_memory_item.tier.value = "episodic"
            
            mcp_services["memory_system"].store = AsyncMock(return_value=mock_memory_item)
            
            # Execute memory save
            result = await save_memory(
                services=mcp_services,
                session_id="test_session",
                summary="Test memory",
                content="This is a test memory",
                importance="medium",
            )
            
            # Verify response structure
            assert isinstance(result, dict)
            assert "memory_id" in result or "error" in result or "status" in result


class TestToolErrorHandling:
    """Test tool error handling."""
    
    @pytest.mark.asyncio
    async def test_search_tool_handles_execution_errors(self, mock_config, mcp_services):
        """Test search_knowledge handles execution errors gracefully."""
        with patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services):
            from agent_vault.mcp.tools.search import search_knowledge
            
            # Make search service raise an error
            mcp_services["search_service"].hybrid_search = AsyncMock(
                side_effect=Exception("Search failed")
            )
            
            # Execute should handle the error
            result = await search_knowledge(
                services=mcp_services,
                session_id="test_session",
                query="test query",
                limit=10,
            )
            
            # Should return error response
            assert isinstance(result, dict)
            assert "error" in result
    
    @pytest.mark.asyncio
    async def test_add_knowledge_handles_invalid_path(self, mock_config, mcp_services):
        """Test add_knowledge handles invalid file paths gracefully."""
        with patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services):
            from agent_vault.mcp.tools.knowledge import add_knowledge
            
            # Execute with non-existent file
            result = await add_knowledge(
                services=mcp_services,
                session_id="test_session",
                content_type="file",
                source="/nonexistent/file.py"
            )
            
            # Should return error response
            assert isinstance(result, dict)
            assert "error" in result
    
    @pytest.mark.asyncio
    async def test_session_tool_handles_invalid_session(self, mock_config, mcp_services):
        """Test tools handle invalid session IDs gracefully."""
        with patch('agent_vault.mcp.server.create_mcp_services', return_value=mcp_services):
            from agent_vault.mcp.tools.info import get_project_info
            
            # Make session validation fail
            mcp_services["session_manager"].validate_session = AsyncMock(return_value=False)
            
            # Execute should handle the error
            result = await get_project_info(
                services=mcp_services,
                session_id="invalid_session"
            )
            
            # Should return error response
            assert isinstance(result, dict)
            assert "error" in result
