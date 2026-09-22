"""Tests for ContextBuilder registration in service factory.

This module tests that the ContextBuilder service is properly registered
in the MCP service factory and can be created with all dependencies.
"""

import pytest

pytestmark = pytest.mark.integration

from agent_vault.config import Config
from agent_vault.mcp.factories import create_mcp_services
from agent_vault.mcp.services.context_builder import ContextBuilder


@pytest.mark.asyncio
async def test_context_builder_registered_in_factory(mock_config):
    """Test that ContextBuilder is registered in service factory."""
    # Create services
    services = await create_mcp_services(mock_config, "test_project")
    
    # Verify context_builder is in services
    assert "context_builder" in services
    assert services["context_builder"] is not None
    assert isinstance(services["context_builder"], ContextBuilder)


@pytest.mark.asyncio
async def test_context_builder_has_all_dependencies(mock_config):
    """Test that ContextBuilder receives all required dependencies."""
    # Create services
    services = await create_mcp_services(mock_config, "test_project")
    
    context_builder = services["context_builder"]
    
    # Verify all dependencies are set and have expected types
    from agent_vault.search.service import SearchService
    from agent_vault.memory.system import MemorySystem
    from agent_vault.database.lancedb_manager import LanceDBManager
    from agent_vault.mcp.services.session_manager import SessionManager
    from agent_vault.mcp.services.token_optimizer import TokenOptimizer

    assert context_builder.search is not None
    assert isinstance(context_builder.search, SearchService)
    assert context_builder.memory is not None
    assert isinstance(context_builder.memory, MemorySystem)
    assert context_builder.db is not None
    assert isinstance(context_builder.db, LanceDBManager)
    assert context_builder.session_manager is not None
    assert isinstance(context_builder.session_manager, SessionManager)
    assert context_builder.config is not None
    assert isinstance(context_builder.config, Config)
    assert context_builder.token_optimizer is not None
    assert isinstance(context_builder.token_optimizer, TokenOptimizer)


@pytest.mark.asyncio
async def test_context_builder_dependencies_are_correct_types(mock_config):
    """Test that ContextBuilder dependencies are correct types."""
    from agent_vault.search.service import SearchService
    from agent_vault.memory.system import MemorySystem
    from agent_vault.database.lancedb_manager import LanceDBManager
    from agent_vault.mcp.services.session_manager import SessionManager
    from agent_vault.mcp.services.token_optimizer import TokenOptimizer
    
    # Create services
    services = await create_mcp_services(mock_config, "test_project")
    
    context_builder = services["context_builder"]
    
    # Verify dependency types
    assert isinstance(context_builder.search, SearchService)
    assert isinstance(context_builder.memory, MemorySystem)
    assert isinstance(context_builder.db, LanceDBManager)
    assert isinstance(context_builder.session_manager, SessionManager)
    assert isinstance(context_builder.config, Config)
    assert isinstance(context_builder.token_optimizer, TokenOptimizer)


@pytest.mark.asyncio
async def test_context_builder_can_be_used_after_creation(mock_config):
    """Test that ContextBuilder can be used after creation from factory."""
    # Create services
    services = await create_mcp_services(mock_config, "test_project")
    
    context_builder = services["context_builder"]
    session_manager = services["session_manager"]
    
    # Create a test session
    session = await session_manager.create_session(
        project_id="test_project",
        description="Test session"
    )
    session_id = session["session_id"]
    
    # Try to build context (should not raise errors)
    result = await context_builder.build_context(
        query="test query",
        session_id=session_id,
        focus="all",
        depth="focused",
        max_tokens=1000
    )
    
    # Verify result structure
    assert "context" in result
    assert "summary" in result
    assert "suggestions" in result
    assert "token_usage" in result
    
    # Verify context structure
    assert "code" in result["context"]
    assert "documentation" in result["context"]
    assert "memories" in result["context"]
    assert "relationships" in result["context"]


@pytest.mark.asyncio
async def test_all_context_builder_dependencies_created_before_builder(mock_config):
    """Test that all dependencies are created before ContextBuilder."""
    # Create services
    services = await create_mcp_services(mock_config, "test_project")
    
    # Verify all required services exist
    required_services = [
        "search_service",
        "memory_system",
        "storage",  # StorageFacade (was db_manager)
        "session_manager",
        "config"
    ]
    
    for service_name in required_services:
        assert service_name in services, f"Required service {service_name} not found"
        assert services[service_name] is not None, f"Service {service_name} is None"
    
    # Verify context_builder exists
    assert "context_builder" in services
    assert services["context_builder"] is not None
