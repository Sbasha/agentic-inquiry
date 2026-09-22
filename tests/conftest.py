"""Pytest configuration helpers.

Fixture Naming Convention:
--------------------------
This file follows a strict naming convention for test fixtures to clearly
indicate their dependencies and usage:

1. **mock_*** - Fixtures using mocked or dummy dependencies
   - Example: mock_config, mock_db_manager, mock_embedding_registry
   - Use these for fast unit tests that don't need real implementations
   - These fixtures use in-memory databases, dummy embedders, etc.

2. **integration_*** - Fixtures using real dependencies  
   - Example: integration_config
   - Use these for integration tests that need real implementations
   - These fixtures may load actual models, connect to real services, etc.

3. **real_*** - Fixtures using real implementations (alternative to integration_*)
   - Example: real_embedder, real_db_manager, real_indexing_pipeline
   - Use these for end-to-end tests requiring actual model loading
   - These fixtures are typically session-scoped for performance

The naming convention helps developers quickly understand:
- Whether a test is a unit test (uses mock_*) or integration test (uses integration_*/real_*)
- What dependencies are being used
- Expected test execution speed and resource requirements
"""
from __future__ import annotations

import os
import sys
import warnings

import pytest
import pytest_asyncio

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


def pytest_configure(config):
    """Configure pytest with custom settings."""
    # Suppress expected sklearn convergence warnings in pattern analyzer tests
    warnings.filterwarnings(
        "ignore",
        category=Warning,
        message=".*Number of distinct clusters.*found smaller than n_clusters.*",
        module="sklearn.base"
    )

    # Suppress RuntimeWarnings about unawaited coroutines from mock cleanup
    # These occur during pytest's internal cleanup phase and are expected
    warnings.filterwarnings(
        "ignore",
        category=RuntimeWarning,
        message=".*coroutine.*was never awaited.*",
    )

    # Register custom markers
    config.addinivalue_line("markers", "smoke: critical path tests for quick validation")
    config.addinivalue_line("markers", "unit: unit tests (fast, no I/O)")
    config.addinivalue_line("markers", "integration: integration tests (component interactions)")
    config.addinivalue_line("markers", "e2e: end-to-end tests (real models)")
    config.addinivalue_line("markers", "golden: search quality regression tests")
    config.addinivalue_line("markers", "stress: concurrency and load tests")
    config.addinivalue_line("markers", "adapters: library assumption tests")
    config.addinivalue_line("markers", "slow: tests exceeding time budget")
    config.addinivalue_line("markers", "model: tests that load neural network models")
    config.addinivalue_line("markers", "postgres: PostgreSQL-specific tests (require Docker postgres)")
    config.addinivalue_line("markers", "contracts: storage provider contract tests")
    config.addinivalue_line("markers", "alloydb: AlloyDB-specific tests (require ALLOYDB_CONNECTION_STRING)")
    config.addinivalue_line(
        "markers",
        "cloud_smoke: smoke tests that hit live cloud endpoints "
        "(AWS RDS / Aurora / Bedrock, Azure Postgres / OpenAI, and "
        "S3 / GCS object storage via agv_SMOKE_S3_BUCKET / "
        "agv_SMOKE_GCS_BUCKET). Skipped by default; opt in with "
        "`-m cloud_smoke` and the appropriate credentials in the "
        "environment.",
    )


def pytest_collection_modifyitems(items):
    """Auto-tag tests based on directory structure.

    This hook automatically applies pytest markers to tests based on their
    directory location, eliminating the need for manual marker annotations.

    Directory -> Marker mapping:
    - tests/unit/       -> @pytest.mark.unit
    - tests/integration/ -> @pytest.mark.integration
    - tests/e2e/        -> @pytest.mark.e2e
    - tests/golden/     -> @pytest.mark.golden
    - tests/stress/     -> @pytest.mark.stress
    - tests/adapters/   -> @pytest.mark.adapters
    """
    for item in items:
        path = str(item.fspath)
        if "/unit/" in path:
            item.add_marker(pytest.mark.unit)
        elif "/integration/" in path:
            item.add_marker(pytest.mark.integration)
        elif "/e2e/" in path:
            item.add_marker(pytest.mark.e2e)
        elif "/golden/" in path:
            item.add_marker(pytest.mark.golden)
        elif "/stress/" in path:
            item.add_marker(pytest.mark.stress)
        elif "/adapters/" in path:
            item.add_marker(pytest.mark.adapters)


def pytest_sessionfinish(session, exitstatus):
    """Clean up all resources after test session completes.

    This ensures proper shutdown of:
    - agent-vault executors (LanceDB, embedding thread pools)
    - LanceDB old versions (prevents disk space bloat)
    - Any remaining asyncio resources
    - Stray non-daemon threads
    """
    import gc
    import threading
    import time

    # 1. Shutdown agent-vault executors (primary source of stuck threads)
    try:
        from agent_vault.executors import shutdown_executors
        shutdown_executors(wait=True, cancel_futures=True)
    except Exception:
        pass

    # 2. Clean up LanceDB old versions to prevent disk space bloat
    # Tests create thousands of versions; cleanup with aggressive timing
    # GUARD: Only run LanceDB cleanup if LanceDB was actually the backend
    # (skip for PostgreSQL/CloudSQL tests to avoid cross-backend contamination)
    try:
        from datetime import timedelta
        import lancedb
        import os

        # Check if a non-LanceDB backend was configured for this test session
        # If so, skip LanceDB cleanup to avoid touching data from other backends
        backend_env = os.environ.get("agv_STORAGE_BACKEND", "").lower()
        cloudsql_configured = bool(os.environ.get("CLOUDSQL_CONNECTION_NAME"))
        postgres_configured = bool(os.environ.get("POSTGRES_CONNECTION_STRING"))

        if backend_env in ("postgresql", "cloudsql", "postgres") or cloudsql_configured or postgres_configured:
            pass  # Skip LanceDB cleanup for non-LanceDB backends
        else:
            lancedb_path = ".agv/lancedb"
            if os.path.exists(lancedb_path):
                db = lancedb.connect(lancedb_path)
                for table_name in db.table_names():
                    try:
                        table = db.open_table(table_name)
                        # Compact fragments first
                        table.optimize.compact_files()
                        # Aggressive cleanup: 60 seconds (removes almost all test versions)
                        table.cleanup_old_versions(
                            older_than=timedelta(seconds=60),
                            delete_unverified=True
                        )
                    except Exception:
                        pass  # Ignore individual table errors
    except Exception:
        pass  # Ignore if lancedb not available or path doesn't exist

    # 3. Force garbage collection
    gc.collect()

    # 4. Shutdown any remaining ThreadPoolExecutors
    try:
        import concurrent.futures.thread
        for executor in list(concurrent.futures.thread._threads_queues.keys()):
            try:
                executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
        concurrent.futures.thread._threads_queues.clear()
    except Exception:
        pass

    # 5. Wait briefly for threads to clean up
    start = time.time()
    while time.time() - start < 3.0:
        non_daemon = [
            t for t in threading.enumerate()
            if t is not threading.main_thread()
            and not t.daemon
            and t.is_alive()
            and not t.name.startswith('pytest')
        ]
        if not non_daemon:
            break
        time.sleep(0.1)

    # 6. Force exit if threads still stuck (prevents hanging in CI)
    non_daemon = [
        t for t in threading.enumerate()
        if t is not threading.main_thread()
        and not t.daemon
        and t.is_alive()
    ]
    if non_daemon:
        import os
        # Don't print - just exit cleanly
        os._exit(exitstatus)


class _DummyEmbedder:
    """Dummy embedder for testing."""
    
    def generate(self, texts):
        """Generate dummy embeddings."""
        return [[0.1] * 384 for _ in texts]
    
    def ndims(self):
        """Return embedding dimensions."""
        return 384


@pytest.fixture(autouse=True)
def reset_cloud_detect_cache_global():
    """Reset the cloud detection cache before each test for isolation.

    detect_cloud_context() caches its result at module level so IMDS probes
    only run once per process. This is correct for production but breaks tests
    that mock different probe outcomes in different test cases.
    """
    try:
        import agent_vault.cli.cloud_detect as _cloud_detect_mod
        _cloud_detect_mod._cloud_context_cache = _cloud_detect_mod._UNSET
        yield
        _cloud_detect_mod._cloud_context_cache = _cloud_detect_mod._UNSET
    except ImportError:
        yield


@pytest.fixture(autouse=True)
def mock_metrics_reset():
    """Reset global metrics before and after each test for isolation."""
    from agent_vault.metrics import reset_metrics

    # Reset before test
    reset_metrics()
    yield
    # Reset after test
    reset_metrics()


@pytest.fixture(autouse=True)
def reset_embedding_registry():
    """Reset global embedding_registry before each test for isolation.

    The embedding_registry is a module-level singleton. Without reset,
    _default_configured persists across tests, causing non-deterministic
    behavior when tests modify the global state.
    """
    from agent_vault.embeddings.registry import embedding_registry

    # Reset before test
    embedding_registry.reset()
    yield
    # Reset after test (defensive, in case test modified state)
    embedding_registry.reset()


@pytest.fixture
def mock_config():
    """Provide a test configuration instance."""
    from agent_vault.config import Config
    return Config.load()


@pytest.fixture
def mock_temp_config(tmp_path):
    """Create a Config instance with temporary storage root.
    
    This fixture provides a Config object configured to use a temporary
    directory for all storage operations, ensuring test isolation.
    
    Args:
        tmp_path: pytest's tmp_path fixture providing a temporary directory
        
    Returns:
        Config instance with storage.root set to temporary directory
    """
    from agent_vault.config import Config, StorageConfig, CacheConfig, DocumentCacheConfig
    
    config = Config()
    config.storage = StorageConfig(root=str(tmp_path), default_project_id="test_default", backend="lancedb")
    # Add required cache configuration
    config.cache = CacheConfig(
        document_cache=DocumentCacheConfig(
            max_size=100,
            ttl_seconds=3600,
            eviction_policy="lru",
        )
    )
    return config


@pytest.fixture
def integration_config(tmp_path):
    """Provide a complete, schema-valid configuration for tests.
    
    This fixture creates a Config instance with all required properties
    per the configuration schema, ensuring tests don't fail due to
    missing required fields.
    
    Args:
        tmp_path: pytest's tmp_path fixture providing a temporary directory
        
    Returns:
        Config instance with all required schema properties
    """
    from agent_vault.config import (
        Config,
        StorageConfig,
        LanceDBConfig,
        FileTrackerConfig,
        DocumentCacheStorageConfig,
        CacheConfig,
        DocumentCacheConfig,
        SearchConfig,
        HybridSearchConfig,
        GraphSearchConfig,
        EmbeddingsConfig,
        SentenceTransformerConfig,
        ParsersConfig,
        ParserConfig,
        MemoryConfig,
        WorkingMemoryConfig,
        EpisodicMemoryConfig,
        SemanticMemoryConfig,
        ConsolidationConfig,
        RetrievalConfig,
        SummaryConfig,
        ConnectorsConfig,
        FileSystemConnectorConfig,
        RemoteConnectorCacheConfig,
    )

    config = Config()

    # Storage configuration (required)
    config.storage = StorageConfig(
        root=str(tmp_path),
        default_project_id="test_default",
        backend="lancedb",
        lancedb=LanceDBConfig(path="lancedb"),
        file_tracker=FileTrackerConfig(path="file_tracker.db"),
        document_cache=DocumentCacheStorageConfig(enabled=False, path="document_cache"),
    )
    
    # Cache configuration (required)
    config.cache = CacheConfig(
        document_cache=DocumentCacheConfig(
            max_size=100,
            ttl_seconds=3600,
            eviction_policy="lru",
        )
    )
    
    # Search configuration (required)
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
    
    # Embeddings configuration (required)
    config.embeddings = EmbeddingsConfig(
        default_provider="sentence_transformer",
        sentence_transformer=SentenceTransformerConfig(
            model_name="all-MiniLM-L6-v2",
            ndims=384,
        ),
    )
    
    # Parsers configuration (required)
    config.parsers = ParsersConfig(
        unified_code=ParserConfig(enabled=True, priority=100),
        document=ParserConfig(enabled=True, priority=50),
        fallback_text=ParserConfig(enabled=True, priority=0),
    )
    
    # Memory configuration (optional but commonly used)
    config.memory = MemoryConfig(
        working_memory=WorkingMemoryConfig(capacity=50, eviction_policy="lru"),
        episodic_memory=EpisodicMemoryConfig(
            capacity=1000, table_name="memory_episodic_medium"
        ),
        semantic_memory=SemanticMemoryConfig(
            capacity=500, table_name="memory_semantic_high"
        ),
        consolidation=ConsolidationConfig(
            enabled=True,
            interval_seconds=300,
            episodic_threshold=0.8,
            semantic_threshold=0.9,
        ),
        retrieval=RetrievalConfig(
            default_strategy="adaptive",
            cache_enabled=True,
            cache_ttl_seconds=300,
            cache_size=1000,
            ranking_weights={
                "relevance": 0.5,
                "recency": 0.3,
                "importance": 0.2
            },
        ),
        summary=SummaryConfig(auto_threshold=150),
    )

    # Connectors configuration (optional but commonly used)
    config.connectors = ConnectorsConfig(
        default_connector="filesystem",
        filesystem=FileSystemConnectorConfig(
            enabled=True,
            root=None,
            change_detection_enabled=True,
            watch_enabled=False,
        ),
        remote_cache=RemoteConnectorCacheConfig(
            enabled=True,
            path="connector_cache",
            max_size=0,
        ),
    )

    return config


@pytest_asyncio.fixture
async def mock_embedding_registry():
    """Create an embedding registry with dummy embedder.
    
    Returns:
        EmbeddingRegistry instance configured with a dummy embedder for testing
    """
    from agent_vault.embeddings.registry import EmbeddingRegistry
    
    return EmbeddingRegistry(default_embedder=_DummyEmbedder())


@pytest_asyncio.fixture
async def mock_event_system():
    """Create a mock event system for testing.

    This fixture provides a mock EventSystem that can be used in tests
    without requiring full event system infrastructure. The mock supports
    emit() calls but doesn't persist events.

    Yields:
        Mock EventSystem instance for use in tests
    """
    from unittest.mock import AsyncMock, MagicMock

    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    mock_es.start = AsyncMock()
    mock_es.stop = AsyncMock()
    mock_es.flush = AsyncMock()
    mock_es._started = False

    yield mock_es

    # Cleanup: ensure stop was called if start was called
    if mock_es.start.called and not mock_es.stop.called:
        await mock_es.stop()


@pytest_asyncio.fixture
async def mock_db_manager(mock_embedding_registry):
    """Create a temporary in-memory LanceDB manager.

    This fixture provides an in-memory database manager that is isolated
    from the real backend and automatically cleaned up after tests.

    Args:
        embedding_registry: The embedding registry fixture

    Returns:
        InMemoryLanceDBManager instance ready for use
    """
    from tests.helpers.async_utils import AsyncTestHelper
    from tests.utils.in_memory_lancedb_manager import InMemoryLanceDBManager

    manager = InMemoryLanceDBManager(uri="memory://test")
    await manager.create_tables_and_indexes()
    await manager.connect()
    yield manager

    # Cleanup: Clear tables to free memory
    async def cleanup_tables():
        async with manager._lock:
            manager._tables.clear()

    await AsyncTestHelper.ensure_cleanup(cleanup_tables())
    # Cleanup is automatic with in-memory database


@pytest_asyncio.fixture
async def mock_storage_facade(mock_db_manager, mock_temp_config):
    """Create a StorageFacade wrapping the mock db_manager.

    This fixture provides a StorageFacade instance that wraps the in-memory
    database manager. Services that require StorageFacade should use this
    fixture instead of mock_db_manager directly.

    The facade provides:
    - vector_provider: LanceDBAdapter wrapping the mock_db_manager
    - graph_provider: LanceDBAdapter wrapping the mock_db_manager
    - project_id: "test_project"

    Args:
        mock_db_manager: The in-memory database manager fixture
        mock_temp_config: The temporary config fixture

    Returns:
        StorageFacade instance ready for use in tests
    """
    from agent_vault.storage.facade import StorageFacade
    from agent_vault.database.adapters.lancedb_adapter import LanceDBAdapter

    # Create an adapter wrapping the in-memory manager
    adapter = LanceDBAdapter(mock_db_manager)

    # Create the facade with the adapter as both vector and graph provider
    facade = StorageFacade(
        config=mock_temp_config,
        project_id="test_project",
        vector_provider=adapter,
        graph_provider=adapter,
    )

    return facade


@pytest_asyncio.fixture
async def mock_indexing_pipeline(mock_db_manager, mock_temp_config, mock_embedding_registry, mock_event_system):
    """Create an IndexingPipeline instance with test configuration.

    This is the primary fixture for tests that need an IndexingPipeline.
    It automatically provides all required dependencies with proper test isolation.
    Each test gets a unique project_id for data isolation.

    Args:
        mock_db_manager: The database manager fixture
        mock_temp_config: The temporary config fixture
        mock_embedding_registry: The embedding registry fixture
        mock_event_system: The event system fixture

    Returns:
        IndexingPipeline instance ready for use in tests
    """
    from agent_vault.indexing.pipeline import IndexingPipeline
    import uuid

    # Generate unique project_id for test isolation
    project_id = f"test_{uuid.uuid4().hex[:8]}"

    return IndexingPipeline(
        db_manager=mock_db_manager,
        config=mock_temp_config,
        project_id=project_id,
        event_system=mock_event_system,
        registry=mock_embedding_registry
    )


def create_test_episodic_item(
    content: str,
    summary: str,
    context,
    importance: float = 0.7,
    event_type: str = "test",
    embedding = None,
    summary_embedding = None,
    **kwargs
):
    """Create a test episodic memory item with all required fields.
    
    This helper function simplifies creating episodic MemoryItem instances
    in tests by providing sensible defaults for all required fields.
    
    Args:
        content: The memory content
        summary: Brief summary of the content
        context: MemoryContext instance
        importance: Importance score (0.0-1.0), default 0.7
        event_type: Type of event, default "test"
        embedding: Content embedding vector (optional)
        summary_embedding: Summary embedding vector (optional)
        **kwargs: Additional fields to pass to MemoryItem constructor
        
    Returns:
        MemoryItem instance configured for episodic memory
    """
    import uuid
    from agent_vault.memory import MemoryItem, MemoryTier
    
    return MemoryItem(
        id=str(uuid.uuid4()),
        content=content,
        summary=summary,
        context=context,
        importance=importance,
        tier=MemoryTier.EPISODIC,
        creator_agent_id=context.agent_id,
        modifier_agent_id=context.agent_id,
        event_type=event_type,
        embedding=embedding,
        summary_embedding=summary_embedding,
        **kwargs
    )


def create_test_semantic_item(
    content: str,
    summary: str,
    context,
    importance: float = 0.8,
    subject: str | None = None,
    relationship: str | None = None,
    object: str | None = None,
    confidence: float = 0.9,
    embedding = None,
    summary_embedding = None,
    **kwargs
):
    """Create a test semantic memory item with all required fields.
    
    This helper function simplifies creating semantic MemoryItem instances
    in tests by providing sensible defaults for all required fields.
    
    Args:
        content: The memory content
        summary: Brief summary of the content
        context: MemoryContext instance
        importance: Importance score (0.0-1.0), default 0.8
        subject: Subject of the semantic triple (optional)
        relationship: Relationship type (optional)
        object: Object of the semantic triple (optional)
        confidence: Confidence score (0.0-1.0), default 0.9
        embedding: Content embedding vector (optional)
        summary_embedding: Summary embedding vector (optional)
        **kwargs: Additional fields to pass to MemoryItem constructor
        
    Returns:
        MemoryItem instance configured for semantic memory
    """
    import uuid
    from agent_vault.memory import MemoryItem, MemoryTier
    
    return MemoryItem(
        id=str(uuid.uuid4()),
        content=content,
        summary=summary,
        context=context,
        importance=importance,
        tier=MemoryTier.SEMANTIC,
        creator_agent_id=context.agent_id,
        modifier_agent_id=context.agent_id,
        subject=subject,
        relationship=relationship,
        object=object,
        confidence=confidence,
        embedding=embedding,
        summary_embedding=summary_embedding,
        **kwargs
    )
