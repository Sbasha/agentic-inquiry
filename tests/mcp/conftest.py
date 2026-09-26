"""Shared fixtures for MCP tests.

This module provides standardized fixtures for MCP integration tests,
ensuring consistent service dictionary keys that match create_mcp_services().
"""

import pytest
from unittest.mock import AsyncMock, MagicMock


class _DummyEmbedder:
    """Dummy embedder for testing."""

    def generate(self, texts):
        """Generate dummy embeddings."""
        return [[0.1] * 384 for _ in texts]

    async def generate_async(self, texts):
        """Generate dummy embeddings asynchronously."""
        return self.generate(texts)

    def ndims(self):
        """Return embedding dimensions."""
        return 384


@pytest.fixture
async def mcp_services(tmp_path):
    """Create MCP services with correct key names matching create_mcp_services().

    This fixture provides a standardized services dictionary that matches
    the keys used by create_mcp_services() in agentic_inquiry/mcp/factories.py.

    Returns:
        dict: Services dictionary with keys:
            - config: Configuration object
            - storage: StorageFacade or compatible storage (InMemoryLanceDBManager)
            - search_service: Search service
            - indexing_pipeline: Indexing pipeline
            - memory_system: Memory system (mock)
            - event_system: Event system (mock)
            - session_manager: Session manager
            - test_session_id: Pre-created session ID for tests
    """
    from agentic_inquiry.config import (
        Config,
        StorageConfig,
        CacheConfig,
        DocumentCacheConfig,
        SearchConfig,
        HybridSearchConfig,
        GraphSearchConfig,
        EmbeddingsConfig,
        SentenceTransformerConfig,
        ParsersConfig,
        ParserConfig,
        ProgressConfig,
    )
    from tests.utils.in_memory_lancedb_manager import InMemoryLanceDBManager
    from agentic_inquiry.database.adapters.lancedb_adapter import LanceDBAdapter
    from agentic_inquiry.mcp.services.session_manager import SessionManager
    from agentic_inquiry.search.service import SearchService
    from agentic_inquiry.embeddings.registry import EmbeddingRegistry

    # Create config
    config = Config()
    config.storage = StorageConfig(
        root=str(tmp_path), default_project_id="test_default"
    )
    config.cache = CacheConfig(
        document_cache=DocumentCacheConfig(
            max_size=100,
            ttl_seconds=3600,
            eviction_policy="lru",
        )
    )
    config.search = SearchConfig(
        default_limit=10,
        max_limit=100,
        hybrid_search=HybridSearchConfig(
            vector_weight=0.7,
            fts_weight=0.3,
            rerank_by_graph=True,
            reranker_type="rrf",
            reranker_params={},
        ),
        graph_search=GraphSearchConfig(
            max_depth=3,
            relationship_types=["calls", "imports", "contains", "references"],
        ),
    )
    config.embeddings = EmbeddingsConfig(
        default_provider="sentence_transformer",
        sentence_transformer=SentenceTransformerConfig(
            model_name="all-MiniLM-L6-v2",
            ndims=384,
        ),
    )
    config.parsers = ParsersConfig(
        unified_code=ParserConfig(enabled=True, priority=100),
        document=ParserConfig(enabled=True, priority=50),
        fallback_text=ParserConfig(enabled=True, priority=0),
    )
    config.progress = ProgressConfig(enabled=False, emit_interval=10, min_duration=1.0)

    # Create real database manager with embedder
    db_manager = InMemoryLanceDBManager(uri="memory://test_integration")
    await db_manager.create_tables_and_indexes()
    await db_manager.connect()

    # Configure embedder for the database manager
    from agentic_inquiry.embeddings.registry import embedding_registry

    embedder = _DummyEmbedder()

    # Configure default embedder if not already configured
    if not embedding_registry._default_configured:
        embedding_registry.configure_default_embedder(embedder, ndims=384)

    # Also set it on the db_manager for backward compatibility
    registry = EmbeddingRegistry(default_embedder=embedder)
    db_manager.mock_embedding_registry = registry

    # Create mock event system
    event_system = AsyncMock()
    event_system.emit = AsyncMock()
    event_system.subscribe = MagicMock()

    # Create embedding service with the registry
    from agentic_inquiry.indexing.embedding_service import EmbeddingService

    embedding_service = EmbeddingService(registry=embedding_registry)

    # Create protocol-compliant vector and graph providers
    from agentic_inquiry.storage.providers.lancedb import (
        LanceDBVectorProvider,
        LanceDBGraphProvider,
    )
    from agentic_inquiry.storage.providers.lancedb.connection import (
        LanceDBConnectionManager,
    )

    # Create connection manager with the already-initialized db_manager
    connection_manager = LanceDBConnectionManager(
        config=config,
        project_id="test_integration_project",
        db_manager=db_manager,  # Pass pre-configured db_manager
    )
    # Mark as initialized since db_manager is already connected
    connection_manager._initialized = True

    vector_provider = LanceDBVectorProvider(connection_manager)
    graph_provider = LanceDBGraphProvider(connection_manager)

    # Also keep the adapter for backward compatibility in tests
    search_adapter = LanceDBAdapter(manager=db_manager, config=config)

    # Create StorageFacade for SearchService and SessionManager
    from agentic_inquiry.storage.facade import StorageFacade

    storage_facade = StorageFacade(
        config=config,
        project_id="test_integration_project",
        vector_provider=vector_provider,
        graph_provider=graph_provider,
    )

    # Create real session manager for proper event handling
    # Pass storage_facade which provides get_db_manager() method
    session_manager = SessionManager(db_manager=storage_facade, config=config)

    # Create a test session
    session_result = await session_manager.create_session(
        project_id="test_integration_project", description="Integration test session"
    )
    test_session_id = session_result["session_id"]

    # Create search service with StorageFacade
    search_service = SearchService(
        storage=storage_facade,
        config=config,
        event_system=event_system,
    )

    # Create mock memory system
    memory_system = AsyncMock()
    memory_system.retrieve = AsyncMock(return_value=[])
    memory_system.store = AsyncMock()

    # Create real indexing pipeline (not mock) for integration tests
    from agentic_inquiry.indexing.pipeline import IndexingPipeline

    indexing_pipeline = IndexingPipeline(
        db_manager=db_manager,
        config=config,
        project_id="test_integration_project",
        event_system=event_system,
    )

    # Return services dictionary with correct keys matching create_mcp_services()
    return {
        "config": config,
        "storage": storage_facade,  # StorageFacade - key matches factories.py output
        "db_manager": db_manager,  # Raw db_manager for tests that need direct access
        "search_adapter": search_adapter,  # LanceDBAdapter for SearchStorageProtocol
        "search_service": search_service,
        "indexing_pipeline": indexing_pipeline,
        "embedding_service": embedding_service,
        "memory_system": memory_system,
        "event_system": event_system,
        "session_manager": session_manager,
        "embedding_registry": registry,
        "test_session_id": test_session_id,
    }


@pytest.fixture
def mock_services_minimal():
    """Create minimal mock services for unit tests that don't need real components.

    This fixture is useful for testing error handling and validation logic
    where you don't need actual database or search functionality.
    """
    session_manager = AsyncMock()
    session_manager.validate_session = AsyncMock(return_value=True)
    session_manager.get_session = AsyncMock(
        return_value={
            "session_id": "test_session",
            "project_id": "test_project",
            "status": "active",
        }
    )

    db_manager = AsyncMock()
    db_manager.vector_search = AsyncMock(return_value=[])
    db_manager.fts_search = AsyncMock(return_value=[])

    search_service = AsyncMock()
    search_service.search = AsyncMock(return_value=[])
    search_service.hybrid_search = AsyncMock(return_value=[])

    event_system = AsyncMock()
    event_system.emit = AsyncMock()

    memory_system = AsyncMock()
    memory_system.retrieve = AsyncMock(return_value=[])

    config = MagicMock()
    config.search.default_limit = 10
    config.search.max_limit = 100

    return {
        "config": config,
        "storage": db_manager,
        "search_service": search_service,
        "indexing_pipeline": AsyncMock(),
        "memory_system": memory_system,
        "event_system": event_system,
        "session_manager": session_manager,
    }
