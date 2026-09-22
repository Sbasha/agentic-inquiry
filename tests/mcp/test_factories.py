"""Tests for MCP service factories.

This module tests:
- Service factory creation
- Dependency injection
- Service wiring

Mocking Strategy:
-----------------
This test suite follows a "mock only external dependencies" approach:

REAL IMPLEMENTATIONS (no mocking):
- Config objects: Use real Config with test values for accuracy
- Simple utilities: TokenOptimizer, MCPCacheManager (no I/O, pure logic)
- Data classes: All model objects and dataclasses

MOCKED COMPONENTS (with justification):
- StorageFacade: Requires database initialization (mocked for unit tests, real for integration)
- EventSystem: Async lifecycle complexity (start/stop)
- EmbeddingService: May load ML models (expensive)
- MemorySystem: Depends on storage and event system
- MCP Services: SessionManager, EntityResolver, etc. (depend on storage)
  These are tested in their own unit test files with appropriate isolation

This approach ensures:
1. Tests catch real config validation issues
2. Pure logic is exercised (not mocked away)
3. External I/O and expensive operations remain isolated
4. Tests run fast while maintaining high confidence
"""

import pytest

pytestmark = pytest.mark.unit
from unittest.mock import Mock, patch, AsyncMock

from agent_vault.config import Config
from agent_vault.mcp.factories import create_mcp_services
from agent_vault.mcp.services.token_optimizer import TokenOptimizer
from agent_vault.mcp.utils.cache import MCPCacheManager


@pytest.fixture
def real_config(integration_config):
    """Create a real configuration for factory tests.

    Uses integration_config fixture which provides a complete,
    schema-valid Config object. This catches real configuration
    validation issues that Mock objects would hide.

    JUSTIFICATION: Real Config objects reveal:
    - Missing required configuration fields
    - Type mismatches in service initialization
    - Config schema violations
    """
    # Add MCP server configuration required by factory
    from agent_vault.config import MCPConfig, MCPServerConfig

    integration_config.mcp = MCPConfig(
        server=MCPServerConfig(
            name="Agent-Vault Test",
            version="1.0.0",
            description="Test MCP Server"
        )
    )

    return integration_config


class TestCreateMCPServices:
    """Test create_mcp_services factory function."""

    @patch('agent_vault.mcp.factories.StorageFacade')
    @patch('agent_vault.mcp.factories.SearchService')
    @patch('agent_vault.mcp.factories.IndexingPipeline')
    @patch('agent_vault.embeddings.service.EmbeddingService')
    @patch('agent_vault.mcp.factories.MemorySystem')
    @patch('agent_vault.events.system.EventSystem')
    @patch('agent_vault.mcp.factories.SessionManager')
    @patch('agent_vault.mcp.factories.EntityResolver')
    @patch('agent_vault.mcp.factories.ImpactAnalyzer')
    @patch('agent_vault.mcp.factories.ContextBuilder')
    @patch('agent_vault.mcp.factories.PatternAnalyzer')
    @patch('agent_vault.mcp.factories.TemporalAnalyzer')
    @patch('agent_vault.mcp.factories.embedding_registry')
    @patch('agent_vault.mcp.factories.LanceDBMemoryAdapter')
    async def test_creates_all_services(
        self,
        mock_memory_adapter,
        mock_embedding_registry,
        mock_temporal_analyzer,
        mock_pattern_analyzer,
        mock_context_builder,
        mock_impact_analyzer,
        mock_entity_resolver,
        mock_session_manager,
        mock_event_system_class,
        mock_memory_system,
        mock_embedding_service,
        mock_indexing_pipeline,
        mock_search_service,
        mock_storage_facade,
        real_config
    ):
        """Test factory creates all required services.

        MOCKED: External I/O services (storage, database, events)
        REAL: Config, TokenOptimizer, MCPCacheManager

        This test verifies the factory creates and wires all services correctly
        while using real config to catch schema issues.
        """
        # Configure embedding registry
        mock_embedding_registry._default_configured = True

        # Mock: Storage - requires database initialization
        storage = Mock()
        storage.close = AsyncMock()
        storage.get_backend_type = Mock(return_value="lancedb")
        db_manager = Mock()
        storage.get_db_manager = Mock(return_value=db_manager)

        # Mock: Core services that depend on storage
        search_service = Mock()
        indexing_pipeline = Mock()
        embedding_service = Mock()

        # Mock: Memory system - depends on storage and event system
        memory_system = Mock()
        memory_system.initialize = AsyncMock()

        # Mock: Event system - async lifecycle complexity
        event_system = Mock()
        event_system.start = AsyncMock()
        event_system.stop = AsyncMock()

        # Mock: MCP services - tested in their own unit test files
        session_manager = Mock()
        entity_resolver = Mock()
        impact_analyzer = Mock()
        context_builder = Mock()
        pattern_analyzer = Mock()
        temporal_analyzer = Mock()

        # Configure mocks to return instances
        mock_storage_facade.from_config = AsyncMock(return_value=storage)
        mock_search_service.return_value = search_service
        mock_indexing_pipeline.return_value = indexing_pipeline
        mock_embedding_service.return_value = embedding_service
        mock_memory_system.return_value = memory_system
        mock_event_system_class.from_config = AsyncMock(return_value=event_system)
        mock_session_manager.return_value = session_manager
        mock_entity_resolver.return_value = entity_resolver
        mock_impact_analyzer.return_value = impact_analyzer
        mock_context_builder.return_value = context_builder
        mock_pattern_analyzer.return_value = pattern_analyzer
        mock_temporal_analyzer.return_value = temporal_analyzer

        # Create services
        services = await create_mcp_services(real_config, "test_project")

        # Verify all services are present
        assert "config" in services
        assert "storage" in services
        assert "search_service" in services
        assert "indexing_pipeline" in services
        assert "memory_system" in services
        assert "event_system" in services
        assert "embedding_service" in services
        assert "session_manager" in services
        assert "entity_resolver" in services
        assert "impact_analyzer" in services
        assert "context_builder" in services
        assert "pattern_analyzer" in services
        assert "temporal_analyzer" in services
        assert "token_optimizer" in services
        assert "cache_manager" in services

        # Verify correct instances
        assert services["config"] is real_config
        assert services["storage"] == storage
        assert services["search_service"] == search_service
        assert services["indexing_pipeline"] == indexing_pipeline
        assert services["memory_system"] == memory_system
        assert services["event_system"] == event_system
        assert services["embedding_service"] == embedding_service
        assert services["session_manager"] == session_manager
        assert services["entity_resolver"] == entity_resolver
        assert services["impact_analyzer"] == impact_analyzer
        assert services["context_builder"] == context_builder
        assert services["pattern_analyzer"] == pattern_analyzer
        assert services["temporal_analyzer"] == temporal_analyzer

        # Verify REAL implementations are used (not mocks)
        assert isinstance(services["token_optimizer"], TokenOptimizer)
        assert isinstance(services["cache_manager"], MCPCacheManager)

    @patch('agent_vault.mcp.factories.StorageFacade')
    @patch('agent_vault.mcp.factories.SearchService')
    @patch('agent_vault.mcp.factories.IndexingPipeline')
    @patch('agent_vault.embeddings.service.EmbeddingService')
    @patch('agent_vault.mcp.factories.MemorySystem')
    @patch('agent_vault.mcp.factories.LanceDBMemoryAdapter')
    @patch('agent_vault.events.system.EventSystem')
    @patch('agent_vault.mcp.factories.SessionManager')
    @patch('agent_vault.mcp.factories.EntityResolver')
    @patch('agent_vault.mcp.factories.ImpactAnalyzer')
    @patch('agent_vault.mcp.factories.ContextBuilder')
    @patch('agent_vault.mcp.factories.PatternAnalyzer')
    @patch('agent_vault.mcp.factories.TemporalAnalyzer')
    @patch('agent_vault.mcp.factories.embedding_registry')
    async def test_passes_correct_dependencies(
        self,
        mock_embedding_registry,
        mock_temporal_analyzer,
        mock_pattern_analyzer,
        mock_context_builder,
        mock_impact_analyzer,
        mock_entity_resolver,
        mock_session_manager,
        mock_event_system_class,
        mock_memory_adapter,
        mock_memory_system,
        mock_embedding_service,
        mock_indexing_pipeline,
        mock_search_service,
        mock_storage_facade,
        real_config
    ):
        """Test factory passes correct dependencies to services.

        MOCKED: External I/O services
        REAL: Config, TokenOptimizer, MCPCacheManager

        This test verifies dependency injection works correctly,
        catching parameter mismatches that Mock objects might hide.
        """
        # Configure embedding registry
        mock_embedding_registry._default_configured = True

        # Mock: Storage and database
        storage = Mock()
        storage.close = AsyncMock()
        storage.get_backend_type = Mock(return_value="lancedb")
        db_manager = Mock()
        storage.get_db_manager = Mock(return_value=db_manager)

        # Mock: Core services
        search_service = Mock()
        embedding_service = Mock()
        embedding_service.start_background_warmup = Mock()
        memory_system = Mock()
        memory_system.initialize = AsyncMock()
        event_system = Mock()
        event_system.start = AsyncMock()
        event_system.stop = AsyncMock()
        session_manager = Mock()
        entity_resolver = Mock()

        # Create mock memory adapters
        episodic_adapter = Mock()
        semantic_adapter = Mock()
        mock_memory_adapter.side_effect = [episodic_adapter, semantic_adapter]

        # Configure mock returns
        mock_storage_facade.from_config = AsyncMock(return_value=storage)
        mock_search_service.return_value = search_service
        mock_embedding_service.return_value = embedding_service
        mock_memory_system.return_value = memory_system
        mock_event_system_class.from_config = AsyncMock(return_value=event_system)
        mock_session_manager.return_value = session_manager
        mock_entity_resolver.return_value = entity_resolver

        # Create services
        services = await create_mcp_services(real_config, "test_project")

        # Verify StorageFacade was created with correct args
        mock_storage_facade.from_config.assert_called_once_with(real_config, "test_project")

        # Verify EventSystem was created and started
        mock_event_system_class.from_config.assert_called_once_with(real_config, "test_project")
        event_system.start.assert_called_once()

        # Verify SearchService receives correct dependencies
        mock_search_service.assert_called_once_with(
            storage=storage,
            config=real_config,
            event_system=event_system,
            project_id="test_project"
        )

        mock_indexing_pipeline.assert_called_once()
        call_kwargs = mock_indexing_pipeline.call_args.kwargs
        assert call_kwargs["db_manager"] == storage
        assert call_kwargs["config"] == real_config
        assert call_kwargs["project_id"] == "test_project"
        assert call_kwargs["event_system"] == event_system
        # capabilities is injected from Phase 1 centralization
        assert "capabilities" in call_kwargs

        # Verify embedding service was created with real config
        mock_embedding_service.assert_called_once_with(config=real_config)

        # Verify memory adapters were created with correct parameters
        assert mock_memory_adapter.call_count == 2
        calls = mock_memory_adapter.call_args_list
        # First call: episodic adapter
        assert calls[0].kwargs['manager'] == db_manager
        assert calls[0].kwargs['table_name'] == 'memory_episodic'
        assert calls[0].kwargs['embedding_dims'] == real_config.embeddings.default_dimensions
        # Second call: semantic adapter
        assert calls[1].kwargs['manager'] == db_manager
        assert calls[1].kwargs['table_name'] == 'memory_semantic'
        assert calls[1].kwargs['embedding_dims'] == real_config.embeddings.default_dimensions

        # Verify memory system was created with correct dependencies
        mock_memory_system.assert_called_once_with(
            config=real_config,
            embedding_service=embedding_service,
            event_system=event_system,
            episodic_storage=episodic_adapter,
            semantic_storage=semantic_adapter,
        )

        # Verify MCP services were created with correct dependencies
        mock_session_manager.assert_called_once_with(
            db_manager=storage,
            config=real_config,
            event_system=event_system
        )

        mock_context_builder.assert_called_once_with(
            search_service=search_service,
            memory_system=memory_system,
            db_manager=storage,
            session_manager=session_manager,
            config=real_config,
            event_system=event_system
        )

        mock_pattern_analyzer.assert_called_once_with(
            search_service=search_service,
            db_manager=storage,
            embedding_service=embedding_service
        )

        mock_temporal_analyzer.assert_called_once_with(
            db_manager=storage,
            config=real_config
        )

        # Verify REAL implementations were created correctly
        assert isinstance(services["token_optimizer"], TokenOptimizer)
        assert isinstance(services["cache_manager"], MCPCacheManager)

    @patch('agent_vault.mcp.factories.StorageFacade')
    @patch('agent_vault.mcp.factories.embedding_registry')
    async def test_propagates_creation_errors(
        self,
        mock_embedding_registry,
        mock_storage_facade,
        real_config
    ):
        """Test factory propagates service creation errors.

        MOCKED: Only StorageFacade (minimal mocking for error testing)
        REAL: Config
        """
        # Configure embedding registry
        mock_embedding_registry._default_configured = True

        # Make storage creation fail
        mock_storage_facade.from_config = AsyncMock(side_effect=Exception("Storage creation failed"))

        # Should propagate the error
        with pytest.raises(Exception, match="Storage creation failed"):
            await create_mcp_services(real_config, "test_project")

    @patch('agent_vault.mcp.factories.StorageFacade')
    @patch('agent_vault.mcp.factories.SearchService')
    @patch('agent_vault.mcp.factories.IndexingPipeline')
    @patch('agent_vault.embeddings.service.EmbeddingService')
    @patch('agent_vault.mcp.factories.MemorySystem')
    @patch('agent_vault.events.system.EventSystem')
    @patch('agent_vault.mcp.factories.SessionManager')
    @patch('agent_vault.mcp.factories.EntityResolver')
    @patch('agent_vault.mcp.factories.ImpactAnalyzer')
    @patch('agent_vault.mcp.factories.ContextBuilder')
    @patch('agent_vault.mcp.factories.PatternAnalyzer')
    @patch('agent_vault.mcp.factories.TemporalAnalyzer')
    @patch('agent_vault.mcp.factories.embedding_registry')
    async def test_config_accessible_in_services(
        self,
        mock_embedding_registry,
        mock_temporal_analyzer,
        mock_pattern_analyzer,
        mock_context_builder,
        mock_impact_analyzer,
        mock_entity_resolver,
        mock_session_manager,
        mock_event_system_class,
        mock_memory_system,
        mock_embedding_service,
        mock_indexing_pipeline,
        mock_search_service,
        mock_storage_facade,
        real_config
    ):
        """Test that config is accessible via services dictionary.

        Uses REAL config to verify actual Config object behavior,
        not just Mock object behavior.
        """
        # Configure embedding registry
        mock_embedding_registry._default_configured = True

        # Mock storage and event system
        storage = Mock()
        storage.close = AsyncMock()
        mock_storage_facade.from_config = AsyncMock(return_value=storage)

        memory_system = Mock()
        memory_system.initialize = AsyncMock()
        mock_memory_system.return_value = memory_system

        event_system = Mock()
        event_system.start = AsyncMock()
        event_system.stop = AsyncMock()
        mock_event_system_class.from_config = AsyncMock(return_value=event_system)

        # Create services
        services = await create_mcp_services(real_config, "test_project")

        # Verify config is in services dictionary
        assert "config" in services

        # Verify config is the actual Config object (not a mock)
        config = services["config"]
        assert config is real_config
        assert isinstance(config, Config)

        # Verify config is the first entry in the dictionary
        first_key = next(iter(services.keys()))
        assert first_key == "config"

    @patch('agent_vault.mcp.factories.StorageFacade')
    @patch('agent_vault.mcp.factories.SearchService')
    @patch('agent_vault.mcp.factories.IndexingPipeline')
    @patch('agent_vault.embeddings.service.EmbeddingService')
    @patch('agent_vault.mcp.factories.MemorySystem')
    @patch('agent_vault.events.system.EventSystem')
    @patch('agent_vault.mcp.factories.SessionManager')
    @patch('agent_vault.mcp.factories.EntityResolver')
    @patch('agent_vault.mcp.factories.ImpactAnalyzer')
    @patch('agent_vault.mcp.factories.ContextBuilder')
    @patch('agent_vault.mcp.factories.PatternAnalyzer')
    @patch('agent_vault.mcp.factories.TemporalAnalyzer')
    @patch('agent_vault.mcp.factories.embedding_registry')
    async def test_server_config_created_correctly(
        self,
        mock_embedding_registry,
        mock_temporal_analyzer,
        mock_pattern_analyzer,
        mock_context_builder,
        mock_impact_analyzer,
        mock_entity_resolver,
        mock_session_manager,
        mock_event_system_class,
        mock_memory_system,
        mock_embedding_service,
        mock_indexing_pipeline,
        mock_search_service,
        mock_storage_facade,
        real_config
    ):
        """Test that server_config is created with correct values from config.

        Uses REAL config to test actual config value extraction,
        verifying the factory correctly reads from Config schema.
        """
        # Configure embedding registry
        mock_embedding_registry._default_configured = True

        # Mock storage and services
        storage = Mock()
        storage.close = AsyncMock()
        mock_storage_facade.from_config = AsyncMock(return_value=storage)

        memory_system = Mock()
        memory_system.initialize = AsyncMock()
        mock_memory_system.return_value = memory_system

        event_system = Mock()
        event_system.start = AsyncMock()
        event_system.stop = AsyncMock()
        mock_event_system_class.from_config = AsyncMock(return_value=event_system)

        # Create services
        services = await create_mcp_services(real_config, "test_project")

        # Verify server_config exists
        assert "server_config" in services

        # Verify server_config has all required fields
        server_config = services["server_config"]
        assert "default_project_id" in server_config
        assert "server_name" in server_config
        assert "server_version" in server_config
        assert "server_description" in server_config

        # Verify values match REAL configuration
        assert server_config["default_project_id"] == "test_project"
        assert server_config["server_name"] == real_config.mcp.server.name
        assert server_config["server_version"] == real_config.mcp.server.version
        assert server_config["server_description"] == real_config.mcp.server.description

    @patch('agent_vault.mcp.factories.StorageFacade')
    @patch('agent_vault.mcp.factories.SearchService')
    @patch('agent_vault.mcp.factories.IndexingPipeline')
    @patch('agent_vault.embeddings.service.EmbeddingService')
    @patch('agent_vault.mcp.factories.MemorySystem')
    @patch('agent_vault.events.system.EventSystem')
    @patch('agent_vault.mcp.factories.SessionManager')
    @patch('agent_vault.mcp.factories.EntityResolver')
    @patch('agent_vault.mcp.factories.ImpactAnalyzer')
    @patch('agent_vault.mcp.factories.ContextBuilder')
    @patch('agent_vault.mcp.factories.PatternAnalyzer')
    @patch('agent_vault.mcp.factories.TemporalAnalyzer')
    @patch('agent_vault.mcp.factories.embedding_registry')
    async def test_server_config_accessible_in_services_dict(
        self,
        mock_embedding_registry,
        mock_temporal_analyzer,
        mock_pattern_analyzer,
        mock_context_builder,
        mock_impact_analyzer,
        mock_entity_resolver,
        mock_session_manager,
        mock_event_system_class,
        mock_memory_system,
        mock_embedding_service,
        mock_indexing_pipeline,
        mock_search_service,
        mock_storage_facade,
        real_config
    ):
        """Test that server_config is accessible in services dict."""
        # Configure embedding registry
        mock_embedding_registry._default_configured = True

        # Mock storage and services
        storage = Mock()
        storage.close = AsyncMock()
        mock_storage_facade.from_config = AsyncMock(return_value=storage)

        memory_system = Mock()
        memory_system.initialize = AsyncMock()
        mock_memory_system.return_value = memory_system

        event_system = Mock()
        event_system.start = AsyncMock()
        event_system.stop = AsyncMock()
        mock_event_system_class.from_config = AsyncMock(return_value=event_system)

        # Create services
        services = await create_mcp_services(real_config, "my_project")

        # Verify server_config is accessible without KeyError
        server_config = services["server_config"]

        # Verify it's a dictionary
        assert isinstance(server_config, dict)

        # Verify it has the expected structure
        assert len(server_config) == 4
        assert all(key in server_config for key in [
            "default_project_id", "server_name", "server_version", "server_description"
        ])

    @patch('agent_vault.mcp.factories.StorageFacade')
    @patch('agent_vault.mcp.factories.SearchService')
    @patch('agent_vault.mcp.factories.IndexingPipeline')
    @patch('agent_vault.embeddings.service.EmbeddingService')
    @patch('agent_vault.mcp.factories.MemorySystem')
    @patch('agent_vault.events.system.EventSystem')
    @patch('agent_vault.mcp.factories.SessionManager')
    @patch('agent_vault.mcp.factories.EntityResolver')
    @patch('agent_vault.mcp.factories.ImpactAnalyzer')
    @patch('agent_vault.mcp.factories.ContextBuilder')
    @patch('agent_vault.mcp.factories.PatternAnalyzer')
    @patch('agent_vault.mcp.factories.TemporalAnalyzer')
    @patch('agent_vault.mcp.factories.embedding_registry')
    async def test_event_system_initialization(
        self,
        mock_embedding_registry,
        mock_temporal_analyzer,
        mock_pattern_analyzer,
        mock_context_builder,
        mock_impact_analyzer,
        mock_entity_resolver,
        mock_session_manager,
        mock_event_system_class,
        mock_memory_system,
        mock_embedding_service,
        mock_indexing_pipeline,
        mock_search_service,
        mock_storage_facade,
        real_config
    ):
        """Test that EventSystem is created and started correctly.

        MOCKED: EventSystem (async lifecycle complexity)
        REAL: Config
        """
        # Configure embedding registry
        mock_embedding_registry._default_configured = True

        # Mock storage
        storage = Mock()
        storage.close = AsyncMock()
        mock_storage_facade.from_config = AsyncMock(return_value=storage)

        # Mock event system
        event_system = Mock()
        event_system.start = AsyncMock()
        event_system.stop = AsyncMock()
        mock_event_system_class.from_config = AsyncMock(return_value=event_system)

        # Mock memory system
        memory_system = Mock()
        memory_system.initialize = AsyncMock()
        mock_memory_system.return_value = memory_system

        # Create services
        services = await create_mcp_services(real_config, "test_project")

        # Verify EventSystem.from_config was called with REAL config
        mock_event_system_class.from_config.assert_called_once_with(real_config, "test_project")

        # Verify EventSystem.start() was called
        event_system.start.assert_called_once()

        # Verify event_system is in services
        assert "event_system" in services
        assert services["event_system"] == event_system

    @patch('agent_vault.mcp.factories.StorageFacade')
    @patch('agent_vault.events.system.EventSystem')
    @patch('agent_vault.mcp.factories.embedding_registry')
    async def test_event_system_initialization_failure(
        self,
        mock_embedding_registry,
        mock_event_system_class,
        mock_storage_facade,
        real_config
    ):
        """Test that EventSystem initialization failure is handled correctly.

        MOCKED: Minimal (EventSystem, StorageFacade)
        REAL: Config
        """
        # Configure embedding registry
        mock_embedding_registry._default_configured = True

        # Mock storage
        storage = Mock()
        storage.close = AsyncMock()
        mock_storage_facade.from_config = AsyncMock(return_value=storage)

        # Mock event system to fail on start
        event_system = Mock()
        event_system.start = AsyncMock(side_effect=Exception("EventSystem start failed"))
        mock_event_system_class.from_config = AsyncMock(return_value=event_system)

        # Should propagate the error and clean up storage
        with pytest.raises(Exception, match="EventSystem start failed"):
            await create_mcp_services(real_config, "test_project")

        # Verify storage.close() was called for cleanup
        storage.close.assert_called_once()


class TestRealImplementations:
    """Test that factory uses real implementations for pure logic components.

    These tests verify that the factory creates actual instances of
    TokenOptimizer and MCPCacheManager rather than requiring mocks.
    This ensures the pure logic is exercised in tests.
    """

    @patch('agent_vault.mcp.factories.StorageFacade')
    @patch('agent_vault.mcp.factories.SearchService')
    @patch('agent_vault.mcp.factories.IndexingPipeline')
    @patch('agent_vault.embeddings.service.EmbeddingService')
    @patch('agent_vault.mcp.factories.MemorySystem')
    @patch('agent_vault.events.system.EventSystem')
    @patch('agent_vault.mcp.factories.SessionManager')
    @patch('agent_vault.mcp.factories.EntityResolver')
    @patch('agent_vault.mcp.factories.ImpactAnalyzer')
    @patch('agent_vault.mcp.factories.ContextBuilder')
    @patch('agent_vault.mcp.factories.PatternAnalyzer')
    @patch('agent_vault.mcp.factories.TemporalAnalyzer')
    @patch('agent_vault.mcp.factories.embedding_registry')
    async def test_token_optimizer_is_real_implementation(
        self,
        mock_embedding_registry,
        mock_temporal_analyzer,
        mock_pattern_analyzer,
        mock_context_builder,
        mock_impact_analyzer,
        mock_entity_resolver,
        mock_session_manager,
        mock_event_system_class,
        mock_memory_system,
        mock_embedding_service,
        mock_indexing_pipeline,
        mock_search_service,
        mock_storage_facade,
        real_config
    ):
        """Test that TokenOptimizer is a real instance with working functionality."""
        mock_embedding_registry._default_configured = True

        # Mock only external I/O
        storage = Mock()
        storage.close = AsyncMock()
        mock_storage_facade.from_config = AsyncMock(return_value=storage)

        memory_system = Mock()
        memory_system.initialize = AsyncMock()
        mock_memory_system.return_value = memory_system

        event_system = Mock()
        event_system.start = AsyncMock()
        event_system.stop = AsyncMock()
        mock_event_system_class.from_config = AsyncMock(return_value=event_system)

        # Create services
        services = await create_mcp_services(real_config, "test_project")

        # Verify token_optimizer is a real TokenOptimizer instance
        token_optimizer = services["token_optimizer"]
        assert isinstance(token_optimizer, TokenOptimizer)

        # Verify it has real functionality (not a mock)
        assert hasattr(token_optimizer, 'truncate_to_tokens')
        assert hasattr(token_optimizer, 'create_snippet')
        assert hasattr(token_optimizer, 'estimate_tokens')

        # Test actual functionality works
        snippet = token_optimizer.create_snippet("This is a test string", max_tokens=5)
        assert isinstance(snippet, str)
        assert len(snippet) > 0

    @patch('agent_vault.mcp.factories.StorageFacade')
    @patch('agent_vault.mcp.factories.SearchService')
    @patch('agent_vault.mcp.factories.IndexingPipeline')
    @patch('agent_vault.embeddings.service.EmbeddingService')
    @patch('agent_vault.mcp.factories.MemorySystem')
    @patch('agent_vault.events.system.EventSystem')
    @patch('agent_vault.mcp.factories.SessionManager')
    @patch('agent_vault.mcp.factories.EntityResolver')
    @patch('agent_vault.mcp.factories.ImpactAnalyzer')
    @patch('agent_vault.mcp.factories.ContextBuilder')
    @patch('agent_vault.mcp.factories.PatternAnalyzer')
    @patch('agent_vault.mcp.factories.TemporalAnalyzer')
    @patch('agent_vault.mcp.factories.embedding_registry')
    async def test_cache_manager_is_real_implementation(
        self,
        mock_embedding_registry,
        mock_temporal_analyzer,
        mock_pattern_analyzer,
        mock_context_builder,
        mock_impact_analyzer,
        mock_entity_resolver,
        mock_session_manager,
        mock_event_system_class,
        mock_memory_system,
        mock_embedding_service,
        mock_indexing_pipeline,
        mock_search_service,
        mock_storage_facade,
        real_config
    ):
        """Test that MCPCacheManager is a real instance with working functionality."""
        mock_embedding_registry._default_configured = True

        # Mock only external I/O
        storage = Mock()
        storage.close = AsyncMock()
        mock_storage_facade.from_config = AsyncMock(return_value=storage)

        memory_system = Mock()
        memory_system.initialize = AsyncMock()
        mock_memory_system.return_value = memory_system

        event_system = Mock()
        event_system.start = AsyncMock()
        event_system.stop = AsyncMock()
        mock_event_system_class.from_config = AsyncMock(return_value=event_system)

        # Create services
        services = await create_mcp_services(real_config, "test_project")

        # Verify cache_manager is a real MCPCacheManager instance
        cache_manager = services["cache_manager"]
        assert isinstance(cache_manager, MCPCacheManager)

        # Verify it has real functionality (not a mock)
        assert hasattr(cache_manager, 'get')
        assert hasattr(cache_manager, 'set')
        assert hasattr(cache_manager, 'invalidate')
        assert hasattr(cache_manager, 'get_stats')

        # Test actual functionality works
        cache_manager.set("test_key", "test_value")
        assert cache_manager.get("test_key") == "test_value"

        stats = cache_manager.get_stats()
        assert isinstance(stats, dict)
        assert "hits" in stats
        assert "misses" in stats


class TestIntegrationFactoryWithRealStorage:
    """Integration tests using real implementations where possible.

    These tests use real implementations to verify the factory works
    with actual objects rather than mocks. This catches integration
    issues that unit tests with mocks would miss.

    NOTE: Full integration tests with real StorageFacade should be in
    tests/integration/ directory. These tests focus on verifying that
    real utility classes work correctly in the factory context.
    """

    @pytest.mark.integration
    @patch('agent_vault.mcp.factories.StorageFacade')
    @patch('agent_vault.mcp.factories.SearchService')
    @patch('agent_vault.mcp.factories.IndexingPipeline')
    @patch('agent_vault.embeddings.service.EmbeddingService')
    @patch('agent_vault.mcp.factories.MemorySystem')
    @patch('agent_vault.events.system.EventSystem')
    @patch('agent_vault.mcp.factories.SessionManager')
    @patch('agent_vault.mcp.factories.EntityResolver')
    @patch('agent_vault.mcp.factories.ImpactAnalyzer')
    @patch('agent_vault.mcp.factories.ContextBuilder')
    @patch('agent_vault.mcp.factories.PatternAnalyzer')
    @patch('agent_vault.mcp.factories.TemporalAnalyzer')
    @patch('agent_vault.mcp.factories.embedding_registry')
    async def test_factory_creates_working_real_utilities(
        self,
        mock_embedding_registry,
        mock_temporal_analyzer,
        mock_pattern_analyzer,
        mock_context_builder,
        mock_impact_analyzer,
        mock_entity_resolver,
        mock_session_manager,
        mock_event_system_class,
        mock_memory_system,
        mock_embedding_service,
        mock_indexing_pipeline,
        mock_search_service,
        mock_storage_facade,
        real_config
    ):
        """Test that factory creates working real utility instances.

        REAL: Config, TokenOptimizer, MCPCacheManager (fully functional)
        MOCKED: I/O services (storage, events, etc.)

        This test verifies that real utility classes can be used
        together and function correctly in the service context.
        """
        mock_embedding_registry._default_configured = True

        # Mock external I/O
        storage = Mock()
        storage.close = AsyncMock()
        storage.get_backend_type = Mock(return_value="lancedb")
        mock_storage_facade.from_config = AsyncMock(return_value=storage)

        memory_system = Mock()
        memory_system.initialize = AsyncMock()
        mock_memory_system.return_value = memory_system

        event_system = Mock()
        event_system.start = AsyncMock()
        event_system.stop = AsyncMock()
        mock_event_system_class.from_config = AsyncMock(return_value=event_system)

        # Create services
        services = await create_mcp_services(real_config, "test_project")

        # Verify real utility instances are created and functional
        token_optimizer = services["token_optimizer"]
        cache_manager = services["cache_manager"]

        # Test TokenOptimizer functionality
        assert isinstance(token_optimizer, TokenOptimizer)
        test_text = "This is a long text that needs to be truncated to fit within token limits"
        snippet = token_optimizer.create_snippet(test_text, max_tokens=10)
        assert isinstance(snippet, str)
        assert len(snippet) < len(test_text)  # Should be truncated

        # Test MCPCacheManager functionality
        assert isinstance(cache_manager, MCPCacheManager)
        cache_manager.set("test_key", {"result": "test_value"})
        cached_value = cache_manager.get("test_key")
        assert cached_value == {"result": "test_value"}

        # Test cache statistics work
        stats = cache_manager.get_stats()
        assert stats["hits"] == 1
        assert stats["total_requests"] == 1

        # Test utilities work together (integration)
        # Simulate caching a truncated snippet
        long_content = "x" * 10000
        optimized_content = token_optimizer.truncate_to_tokens(long_content, max_tokens=100)
        cache_key = MCPCacheManager.generate_cache_key(
            tool_name="test_tool",
            session_id="test_session",
            query="test_query"
        )
        cache_manager.set(cache_key, optimized_content)

        # Verify cached optimized content is retrievable
        cached = cache_manager.get(cache_key)
        assert cached == optimized_content
        assert len(cached) < len(long_content)


class TestMCPServerShutdown:
    """Test MCPServer shutdown behavior."""

    async def test_shutdown_stops_event_system(self):
        """Test that shutdown calls event_system.stop()."""
        from agent_vault.mcp.server import MCPServer

        # Create mock services
        event_system = Mock()
        event_system.stop = AsyncMock()

        services = {
            "event_system": event_system,
            "storage": Mock()
        }

        # Create server with mock services
        server = MCPServer(config=Mock(), project_id="test")
        server.services = services
        server._initialized = True

        # Call shutdown
        await server.shutdown()

        # Verify event_system.stop() was called
        event_system.stop.assert_called_once()

        # Verify services were cleared
        assert len(server.services) == 0
        assert not server._initialized

    async def test_shutdown_handles_event_system_error(self):
        """Test that shutdown handles EventSystem.stop() errors gracefully."""
        from agent_vault.mcp.server import MCPServer

        # Create mock services with failing event system
        event_system = Mock()
        event_system.stop = AsyncMock(side_effect=Exception("Stop failed"))

        services = {
            "event_system": event_system,
            "storage": Mock()
        }

        # Create server with mock services
        server = MCPServer(config=Mock(), project_id="test")
        server.services = services
        server._initialized = True

        # Call shutdown - should not raise
        await server.shutdown()

        # Verify event_system.stop() was called
        event_system.stop.assert_called_once()

        # Verify services were still cleared despite error
        assert len(server.services) == 0
        assert not server._initialized

    async def test_shutdown_without_event_system(self):
        """Test that shutdown works when event_system is not in services."""
        from agent_vault.mcp.server import MCPServer

        # Create services without event_system
        services = {
            "storage": Mock()
        }

        # Create server with mock services
        server = MCPServer(config=Mock(), project_id="test")
        server.services = services
        server._initialized = True

        # Call shutdown - should not raise
        await server.shutdown()

        # Verify services were cleared
        assert len(server.services) == 0
        assert not server._initialized
