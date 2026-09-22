"""Pytest fixtures for storage integration tests.

These fixtures provide PostgreSQL connections for integration tests.
Tests using these fixtures should be marked with @pytest.mark.postgres.

Usage:
    docker-compose -f docker-compose.dev.yaml up -d
    pytest -m postgres tests/storage/
"""

import os
import uuid

import pytest
import pytest_asyncio


def _get_postgres_url() -> str:
    """Get PostgreSQL connection URL from environment or default."""
    # Allow override via environment variable
    if url := os.environ.get("POSTGRES_URL"):
        return url

    # Default for docker-compose.dev.yaml
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "dev")
    password = os.environ.get("POSTGRES_PASSWORD", "dev")
    database = os.environ.get("POSTGRES_DB", "agent-vault")

    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


@pytest.fixture(scope="session")
def integration_postgres_url() -> str:
    """Get PostgreSQL connection URL."""
    return _get_postgres_url()


@pytest.fixture
async def postgres_connection_manager(integration_postgres_url: str):
    """Create a PostgresConnectionManager for testing.

    Yields:
        PostgresConnectionManager: Initialized connection manager
    """
    try:
        from agent_vault.storage.providers.postgresql import PostgresConnectionManager
    except ImportError:
        pytest.skip("asyncpg not installed")

    manager = PostgresConnectionManager(
        connection_string=integration_postgres_url,
        table_prefix="agv_test_",
        pool_size=5,
    )

    try:
        await manager.initialize()
    except Exception as e:
        pytest.skip(f"PostgreSQL not available: {e}")

    yield manager

    await manager.close()


@pytest.fixture
async def clean_postgres_tables(postgres_connection_manager):
    """Clean up test tables before and after tests.

    This fixture drops and recreates test tables to ensure
    a clean state for each test.
    """
    # Tables created by PostgreSQL providers with test prefix
    test_tables = [
        "agv_test_v_chunks",
        "agv_test_v_chunks_fts",
        "agv_test_g_entities",
        "agv_test_g_relationships",
        "agv_test_e_events",
        "agv_test_f_file_hashes",
    ]

    # Clean up before test using connection manager's acquire context manager
    async with postgres_connection_manager.acquire() as conn:
        for table in test_tables:
            await conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")

    yield

    # Clean up after test
    async with postgres_connection_manager.acquire() as conn:
        for table in test_tables:
            await conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


# =============================================================================
# Re-export fixtures from contracts/conftest.py for project isolation tests
# =============================================================================


def generate_project_id() -> str:
    """Generate a unique project ID for test isolation."""
    return f"test_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def test_config(tmp_path):
    """Create test configuration with temporary storage."""
    from agent_vault.config import Config, StorageConfig

    storage_config = StorageConfig(
        root=str(tmp_path / "storage"),
    )
    config = Config(storage=storage_config)
    config.storage.default_project_id = generate_project_id()
    return config


@pytest.fixture
def project_id():
    """Generate unique project ID for each test."""
    return generate_project_id()


@pytest_asyncio.fixture
async def vector_provider(provider_type, test_config, project_id):
    """Create a parameterized vector provider for testing.

    This fixture runs tests against multiple provider implementations.
    PostgreSQL tests will be skipped if the database is not available.
    """
    from agent_vault.storage.providers import InMemoryProvider, LanceDBProvider

    if provider_type == "memory":
        provider = InMemoryProvider(project_id=project_id)
        await provider.initialize()
        yield provider
        await provider.close()

    elif provider_type == "lancedb":
        provider = LanceDBProvider(config=test_config, project_id=project_id)
        await provider.initialize()
        yield provider
        await provider.close()

    elif provider_type == "postgres":
        # Check if asyncpg is available
        try:
            from agent_vault.storage.providers.postgresql import (
                PostgresConnectionManager,
                PostgresVectorProvider,
            )
        except ImportError:
            pytest.skip("asyncpg not installed")
            return

        # Create connection manager
        manager = PostgresConnectionManager(
            connection_string=_get_postgres_url(),
            table_prefix=f"agv_iso_{project_id[:8]}_",  # Unique prefix per test
            pool_size=5,
        )

        try:
            await manager.initialize()
        except Exception as e:
            pytest.skip(f"PostgreSQL not available: {e}")
            return

        try:
            provider = PostgresVectorProvider(
                connection_manager=manager,
                project_id=project_id,
                embedding_dim=384,
            )
            await provider.initialize()
            yield provider
            await provider.close()
        finally:
            # Clean up tables before closing manager
            try:
                async with manager.acquire() as conn:
                    # Drop all tables with this test's prefix
                    prefix = f"agv_iso_{project_id[:8]}_"
                    result = await conn.fetch(
                        """
                        SELECT tablename FROM pg_tables
                        WHERE schemaname = 'public' AND tablename LIKE $1
                        """,
                        f"{prefix}%",
                    )
                    for row in result:
                        await conn.execute(f'DROP TABLE IF EXISTS "{row["tablename"]}" CASCADE')
            except Exception:
                pass  # Ignore cleanup errors

            await manager.close()

    else:
        pytest.skip(f"Unknown provider type: {provider_type}")


@pytest.fixture(params=["memory", "lancedb", "postgres"])
def provider_type(request):
    """Parameterized fixture for provider type."""
    return request.param


@pytest.fixture
def chunk_factory():
    """Factory for creating test DocumentChunks."""
    from agent_vault.models.document_chunk import DocumentChunk

    def _create_chunk(
        chunk_id: str = None,
        project_id: str = "test",
        file_path: str = "/test/file.py",
        content: str = "test content",
        content_type: str = "CODE",
        vector: list = None,
    ):
        if chunk_id is None:
            chunk_id = f"chunk_{uuid.uuid4().hex[:8]}"
        if vector is None:
            vector = [0.1] * 384

        return DocumentChunk(
            id=chunk_id,
            doc_id=f"doc_{chunk_id}",
            project_id=project_id,
            file_path=file_path,
            content=content,
            fts_text=content,  # Use content as FTS text
            content_type=content_type,
            vector=vector,
            line_start=1,
            line_end=10,
            language="python",
        )

    return _create_chunk


@pytest.fixture
def entity_factory():
    """Factory for creating test GraphEntities."""
    from agent_vault.models.graph_entity import EntityType, GraphEntity

    def _create_entity(
        entity_id: str = None,
        project_id: str = "test",
        name: str = "test_entity",
        entity_type: str = EntityType.CODE_FUNCTION.value,
        file_path: str = "/test/file.py",
        vector: list = None,
    ):
        if entity_id is None:
            entity_id = f"entity_{uuid.uuid4().hex[:8]}"
        if vector is None:
            vector = [0.1] * 384

        return GraphEntity(
            id=entity_id,
            project_id=project_id,
            name=name,
            type=entity_type,
            file_path=file_path,
            doc_id=f"doc_{entity_id}",
            vector=vector,
        )

    return _create_entity


@pytest.fixture
def relationship_factory():
    """Factory for creating test GraphRelationships."""
    from agent_vault.models.graph_relationship import (
        GraphRelationship,
        RelationshipType,
    )

    def _create_relationship(
        rel_id: str = None,
        project_id: str = "test",
        source_id: str = "source",
        target_id: str = "target",
        rel_type: str = RelationshipType.CALLS.value,
        vector: list = None,
    ):
        if rel_id is None:
            rel_id = f"rel_{uuid.uuid4().hex[:8]}"
        if vector is None:
            vector = [0.1] * 384

        return GraphRelationship(
            id=rel_id,
            project_id=project_id,
            source_id=source_id,
            target_id=target_id,
            type=rel_type,
            vector=vector,
        )

    return _create_relationship
