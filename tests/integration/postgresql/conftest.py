"""Shared pytest fixtures for PostgreSQL integration tests.

This module provides common fixtures used across PostgreSQL integration tests
to reduce code duplication and ensure consistent test setup.

Fixtures:
    mock_connection_manager: Basic mock for PostgresConnectionManager
    mock_connection: AsyncMock for database connection with common methods
    mock_maintenance_service: PostgresMaintenanceService with mocked dependencies
    mock_vector_provider: Mock PostgresVectorProvider
    mock_graph_provider: Mock PostgresGraphProvider
"""

import pytest
from unittest.mock import AsyncMock, MagicMock
from typing import TYPE_CHECKING, Dict, Any

if TYPE_CHECKING:
    from agent_vault.storage.config import BackendConfig


@pytest.fixture
def mock_connection() -> AsyncMock:
    """Create a mock database connection with common methods.

    Returns:
        AsyncMock configured with execute, fetch, fetchrow, and fetchval methods.

    Example:
        def test_something(mock_connection):
            mock_connection.fetchrow.return_value = {"id": 1}
            result = await some_function(mock_connection)
    """
    connection = AsyncMock()
    connection.execute.return_value = None
    connection.fetch.return_value = []
    connection.fetchrow.return_value = None
    connection.fetchval.return_value = None
    return connection


@pytest.fixture
def mock_connection_manager(mock_connection: AsyncMock) -> MagicMock:
    """Create a mock PostgresConnectionManager.

    Args:
        mock_connection: The mock connection to return from acquire methods.

    Returns:
        MagicMock configured with acquire and release methods.

    Example:
        def test_maintenance(mock_connection_manager):
            service = PostgresMaintenanceService(mock_connection_manager)
            await service.run_maintenance("vacuum", "table")
    """
    manager = MagicMock()
    manager.acquire_for_transaction = AsyncMock(return_value=mock_connection)
    manager.release_transaction_connection = AsyncMock()
    manager.table_prefix = "agv_"
    manager._initialized = True
    return manager


@pytest.fixture
def vacuum_statistics() -> Dict[str, Any]:
    """Default vacuum statistics for testing.

    Returns:
        Dict with before/after vacuum statistics.
    """
    return {
        "before": {"n_dead_tup": 1234, "n_live_tup": 10000},
        "after": {"n_dead_tup": 0, "n_live_tup": 10000},
    }


@pytest.fixture
def mock_connection_with_vacuum_stats(
    mock_connection: AsyncMock, vacuum_statistics: Dict[str, Any]
) -> AsyncMock:
    """Mock connection configured for vacuum operation tests.

    Args:
        mock_connection: Base mock connection.
        vacuum_statistics: Statistics to return from fetchrow.

    Returns:
        AsyncMock configured for vacuum operation.
    """
    mock_connection.fetchrow.side_effect = [
        vacuum_statistics["before"],
        vacuum_statistics["after"],
    ]
    return mock_connection


@pytest.fixture
def mock_vector_provider() -> MagicMock:
    """Create a mock PostgresVectorProvider.

    Returns:
        MagicMock configured with common vector provider methods.
    """
    provider = MagicMock()
    provider.set_transaction_connection = MagicMock()
    provider.clear_transaction_connection = MagicMock()
    provider.store_chunks = AsyncMock(return_value=["chunk-1", "chunk-2"])
    provider.delete_chunks = AsyncMock(return_value=2)
    provider.delete_file = AsyncMock(return_value=5)
    provider._txn_connection = None
    return provider


@pytest.fixture
def mock_graph_provider() -> MagicMock:
    """Create a mock PostgresGraphProvider.

    Returns:
        MagicMock configured with common graph provider methods.
    """
    provider = MagicMock()
    provider.set_transaction_connection = MagicMock()
    provider.clear_transaction_connection = MagicMock()
    provider.store_relationships = AsyncMock(return_value=["rel-1", "rel-2"])
    provider.delete_relationships = AsyncMock(return_value=2)
    provider._txn_connection = None
    return provider


@pytest.fixture
def mock_schema_tracker() -> MagicMock:
    """Create a mock SchemaVersionTracker.

    Returns:
        MagicMock configured for schema tracking operations.
    """
    tracker = MagicMock()
    tracker.ensure_meta_table = AsyncMock()
    tracker.detect_dimension_mismatch = AsyncMock(return_value=None)
    tracker.increment_version = AsyncMock(return_value=2)
    tracker.acquire_migration_lock = AsyncMock(return_value=True)
    tracker.release_migration_lock = AsyncMock()
    return tracker


@pytest.fixture
def backend_config() -> "BackendConfig":
    """Create a test BackendConfig.

    Returns:
        BackendConfig instance for testing.
    """
    from agent_vault.storage.config import BackendConfig

    return BackendConfig(
        type="postgresql",
        connection_string="postgresql://test:test@localhost:5432/testdb",
        pool_size=5,
        max_overflow=2,
        table_prefix="test_",
    )


@pytest.fixture
def entity_factory():
    """Build a ``GraphEntity`` with test-sensible defaults.

    Mirrors the ``entity_factory`` fixture in ``tests/storage/contracts/``
    but scoped to this conftest chain — live-Postgres tests under
    ``tests/integration/postgresql/`` don't inherit the storage conftest.
    Kept here so any live test that needs to seed entities can share the
    same factory shape instead of inlining one per file.
    """
    from agent_vault.models.graph_entity import GraphEntity

    def _factory(
        entity_id: str,
        project_id: str,
        name: str = "test_entity",
        entity_type: str = "function",
        vector: list[float] | None = None,
        file_path: str | None = None,
    ) -> GraphEntity:
        return GraphEntity(
            id=entity_id,
            project_id=project_id,
            name=name,
            type=entity_type,
            file_path=file_path or f"/test/{entity_id}.py",
            doc_id=f"doc_{entity_id}",
            vector=vector or [0.1] * 384,
        )

    return _factory


@pytest.fixture
def index_rebuild_response() -> Dict[str, Any]:
    """Mock response for index rebuild operations.

    Returns:
        Dict simulating successful index rebuild.
    """
    return {
        "index_name": "agv_chunks_embedding_idx",
        "table_name": "agv_chunks",
        "index_size_before": "1024 MB",
        "index_size_after": "512 MB",
        "duration_seconds": 45.2,
    }
