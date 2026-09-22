import pytest
from unittest.mock import MagicMock, AsyncMock
from agent_vault.storage.factory import create_provider
from agent_vault.storage.providers.postgresql import PostgreSQLProvider

@pytest.mark.asyncio
async def test_create_postgresql_provider():
    # Mock config
    config = MagicMock()
    config.embeddings.default_dimensions = 384
    config.storage.postgresql.connection_string = "postgresql://user:pass@localhost/db"
    
    with pytest.MonkeyPatch.context() as mp:
        # Mock connection manager and sub-providers
        mock_conn = MagicMock()
        mock_conn.initialize = AsyncMock()
        mock_conn.table_prefix = "agv_"
        mock_conn.similarity_metric = "cosine"
        
        # Patch both possible entry points for connection manager creation
        mp.setattr("agent_vault.storage.providers.postgresql.PostgresConnectionManager.from_config", 
                   lambda *args, **kwargs: mock_conn)
        mp.setattr("agent_vault.storage.providers.postgresql.PostgresConnectionManager.__init__", 
                   lambda *args, **kwargs: None)
        
        # Mock initialization of sub-providers to avoid real DB calls
        mp.setattr("agent_vault.storage.providers.postgresql.PostgresVectorProvider.initialize", AsyncMock())
        mp.setattr("agent_vault.storage.providers.postgresql.PostgresGraphProvider.initialize", AsyncMock())

        provider = await create_provider("postgresql", config, "test_project")
        
        assert isinstance(provider, PostgreSQLProvider)
        assert provider._project_id == "test_project"

@pytest.mark.asyncio
async def test_postgresql_provider_delegation():
    # Setup provider with mocked components
    config = MagicMock()
    config.embeddings.default_dimensions = 384
    
    mock_conn = MagicMock()
    mock_conn.initialize = AsyncMock()
    mock_conn.table_prefix = "agv_"
    mock_conn.similarity_metric = "cosine"

    provider = PostgreSQLProvider(config, "test_project", connection_manager=mock_conn)
    
    # Mock sub-providers
    provider._vector_provider = MagicMock()
    provider._vector_provider.vector_search = AsyncMock(return_value=[])
    
    provider._graph_provider = MagicMock()
    provider._graph_provider.get_entity = AsyncMock(return_value=None)
    
    # Test delegation
    await provider.vector_search([0.1]*384, limit=5)
    provider._vector_provider.vector_search.assert_called_once()
    
    await provider.get_entity("e1", "test_project")
    provider._graph_provider.get_entity.assert_called_once_with("e1", "test_project")
