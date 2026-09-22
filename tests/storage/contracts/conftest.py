"""Fixtures for contract tests.

This module provides parameterized fixtures for testing multiple provider
implementations against the same contract tests.

Each provider is initialized, used for tests, and then cleaned up.

Supported providers:
- memory: In-memory provider (always available)
- lancedb: LanceDB file-based provider (always available)
- postgres: PostgreSQL with pgvector (requires running PostgreSQL)
- alloydb: AlloyDB with server-side embeddings (requires ALLOYDB_CONNECTION_STRING)

To run with PostgreSQL:
    docker-compose -f docker-compose.dev.yaml up -d
    pytest tests/storage/contracts/ -v

To run with AlloyDB:
    export ALLOYDB_CONNECTION_STRING="postgresql://user:pass@host:port/db"
    pytest tests/storage/contracts/ -v -m alloydb
"""

import os
import uuid

import pytest
import pytest_asyncio

from agentic_inquiry.config import Config, StorageConfig
from agentic_inquiry.storage.providers import InMemoryProvider, LanceDBProvider


def generate_project_id() -> str:
    """Generate a unique project ID for test isolation."""
    return f"contract_test_{uuid.uuid4().hex[:8]}"


# =============================================================================
# Configuration Fixtures
# =============================================================================


@pytest.fixture
def test_config(tmp_path):
    """Create test configuration with temporary storage."""
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


# =============================================================================
# Provider Fixtures - InMemory
# =============================================================================


@pytest_asyncio.fixture
async def memory_provider(project_id):
    """Create and initialize an in-memory provider."""
    provider = InMemoryProvider(project_id=project_id)
    await provider.initialize()
    yield provider
    await provider.close()


# =============================================================================
# Provider Fixtures - LanceDB
# =============================================================================


@pytest_asyncio.fixture
async def lancedb_provider(test_config, project_id):
    """Create and initialize a LanceDB provider."""
    provider = LanceDBProvider(
        config=test_config,
        project_id=project_id,
    )
    await provider.initialize()
    yield provider
    await provider.close()


# =============================================================================
# Provider Fixtures - PostgreSQL
# =============================================================================


def _get_postgres_url() -> str:
    """Get PostgreSQL connection URL from environment or default."""
    if url := os.environ.get("POSTGRES_URL"):
        return url

    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "dev")
    password = os.environ.get("POSTGRES_PASSWORD", "dev")
    database = os.environ.get("POSTGRES_DB", "agentic-inquiry")

    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


@pytest_asyncio.fixture
async def postgres_connection_manager():
    """Create a PostgresConnectionManager for contract testing.

    Skips tests if PostgreSQL is not available.
    """
    try:
        from agentic_inquiry.storage.providers.postgresql import PostgresConnectionManager
    except ImportError:
        pytest.skip("asyncpg not installed")
        return

    # Use unique table prefix for contract tests to avoid conflicts
    manager = PostgresConnectionManager(
        connection_string=_get_postgres_url(),
        table_prefix="ai_contract_",
        pool_size=5,
    )

    try:
        await manager.initialize()
    except Exception as e:
        pytest.skip(f"PostgreSQL not available: {e}")
        return

    yield manager

    await manager.close()


@pytest_asyncio.fixture
async def postgres_provider(postgres_connection_manager, project_id):
    """Create and initialize a PostgreSQL vector provider."""
    from agentic_inquiry.storage.providers.postgresql import PostgresVectorProvider

    provider = PostgresVectorProvider(
        connection_manager=postgres_connection_manager,
        project_id=project_id,
        embedding_dim=384,
    )
    await provider.initialize()
    yield provider
    await provider.close()


# =============================================================================
# Provider Fixtures - AlloyDB
# =============================================================================


def _get_alloydb_url() -> str | None:
    """Get AlloyDB connection URL from environment.

    Returns None if ALLOYDB_CONNECTION_STRING is not set.
    """
    return os.environ.get("ALLOYDB_CONNECTION_STRING")


@pytest_asyncio.fixture
async def alloydb_provider(project_id):
    """Create and initialize an AlloyDB vector provider.

    Skips tests if ALLOYDB_CONNECTION_STRING is not set.
    AlloyDB uses 768-dim server-side embeddings (text-embedding-005).
    """
    url = _get_alloydb_url()
    if not url:
        pytest.skip("ALLOYDB_CONNECTION_STRING not set")
        return

    try:
        from agentic_inquiry.storage.providers.postgresql import (
            PostgresConnectionManager,
            PostgresVectorProvider,
        )
    except ImportError:
        pytest.skip("asyncpg not installed")
        return

    prefix = f"ai_alloydb_ct_{project_id[:8]}_"
    manager = PostgresConnectionManager(
        connection_string=url,
        table_prefix=prefix,
        pool_size=5,
    )

    try:
        await manager.initialize()
    except Exception as e:
        pytest.skip(f"AlloyDB not available: {e}")
        return

    try:
        provider = PostgresVectorProvider(
            connection_manager=manager,
            project_id=project_id,
            embedding_dim=768,
        )
        await provider.initialize()
        yield provider
        await provider.close()
    finally:
        # Clean up test tables
        try:
            async with manager.acquire() as conn:
                result = await conn.fetch(
                    """
                    SELECT tablename FROM pg_tables
                    WHERE schemaname = 'public' AND tablename LIKE $1
                    """,
                    f"{prefix}%",
                )
                for row in result:
                    await conn.execute(
                        f'DROP TABLE IF EXISTS "{row["tablename"]}" CASCADE'
                    )
        except Exception:
            pass  # Ignore cleanup errors

        await manager.close()


# =============================================================================
# Parameterized Provider Fixture
# =============================================================================


def _collect_provider_params() -> list[str]:
    """Build parameterized provider list based on environment.

    Always includes memory and lancedb. Includes postgres and alloydb
    only when their connection env vars are set.
    """
    params = ["memory", "lancedb", "postgres"]
    if os.environ.get("ALLOYDB_CONNECTION_STRING"):
        params.append("alloydb")
    return params


@pytest.fixture(params=_collect_provider_params())
def provider_type(request):
    """Parameterized fixture for provider type."""
    return request.param


@pytest_asyncio.fixture
async def vector_provider(provider_type, test_config, project_id):
    """Create a parameterized vector provider.

    This fixture runs the same tests against multiple provider implementations.
    PostgreSQL tests will be skipped if the database is not available.
    AlloyDB tests will be skipped if ALLOYDB_CONNECTION_STRING is not set.
    """
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
            from agentic_inquiry.storage.providers.postgresql import (
                PostgresConnectionManager,
                PostgresVectorProvider,
            )
        except ImportError:
            pytest.skip("asyncpg not installed")
            return

        # Create connection manager
        manager = PostgresConnectionManager(
            connection_string=_get_postgres_url(),
            table_prefix=f"ai_ct_{project_id[:8]}_",  # Unique prefix per test
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
                    prefix = f"ai_ct_{project_id[:8]}_"
                    result = await conn.fetch(
                        """
                        SELECT tablename FROM pg_tables
                        WHERE schemaname = 'public' AND tablename LIKE $1
                        """,
                        f"{prefix}%",
                    )
                    for row in result:
                        await conn.execute(
                            f'DROP TABLE IF EXISTS "{row["tablename"]}" CASCADE'
                        )
            except Exception:
                pass  # Ignore cleanup errors

            await manager.close()

    elif provider_type == "alloydb":
        url = _get_alloydb_url()
        if not url:
            pytest.skip("ALLOYDB_CONNECTION_STRING not set")
            return

        try:
            from agentic_inquiry.storage.providers.postgresql import (
                PostgresConnectionManager,
                PostgresVectorProvider,
            )
        except ImportError:
            pytest.skip("asyncpg not installed")
            return

        prefix = f"ai_ct_alloy_{project_id[:8]}_"
        manager = PostgresConnectionManager(
            connection_string=url,
            table_prefix=prefix,
            pool_size=5,
        )

        try:
            await manager.initialize()
        except Exception as e:
            pytest.skip(f"AlloyDB not available: {e}")
            return

        try:
            provider = PostgresVectorProvider(
                connection_manager=manager,
                project_id=project_id,
                embedding_dim=768,
            )
            await provider.initialize()
            yield provider
            await provider.close()
        finally:
            try:
                async with manager.acquire() as conn:
                    result = await conn.fetch(
                        """
                        SELECT tablename FROM pg_tables
                        WHERE schemaname = 'public' AND tablename LIKE $1
                        """,
                        f"{prefix}%",
                    )
                    for row in result:
                        await conn.execute(
                            f'DROP TABLE IF EXISTS "{row["tablename"]}" CASCADE'
                        )
            except Exception:
                pass
            await manager.close()

    else:
        pytest.skip(f"Unknown provider type: {provider_type}")


# =============================================================================
# Test Data Factories
# =============================================================================


@pytest.fixture
def chunk_factory():
    """Factory for creating test DocumentChunks."""
    from agentic_inquiry.models.document_chunk import DocumentChunk

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
    from agentic_inquiry.models.graph_entity import EntityType, GraphEntity

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
    from agentic_inquiry.models.graph_relationship import (
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
