"""Unit tests for RDS vector support via PostgresVectorProvider and RDSAdapter.

These tests verify the DSN construction, capabilities, embedding generation
logic, and server-side search SQL for the AWS RDS support using the unified
PostgresVectorProvider and RDSAdapter.

Run with: pytest tests/storage/providers/test_rds_vector_provider.py -v
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_vault.storage.providers.postgresql.vector import PostgresVectorProvider
from agent_vault.storage.providers.postgresql.adapter import RDSAdapter

# Mark all tests in this module as unit tests
pytestmark = [pytest.mark.unit]


# =============================================================================
# Mock helpers
# =============================================================================


class MockRecord(dict):
    """Mock asyncpg.Record that supports both dict and attribute access."""

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError:
            raise AttributeError(f"'MockRecord' has no attribute '{key}'")

    def get(self, key: str, default: Any = None) -> Any:
        return super().get(key, default)


def make_record(**kwargs) -> MockRecord:
    """Create a mock record with the given fields."""
    return MockRecord(kwargs)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def mock_schema_tracker():
    """Mock SchemaVersionTracker to avoid dimension mismatch errors in unit tests."""
    with patch("agent_vault.storage.providers.postgresql.schema_tracker.SchemaVersionTracker") as mock_cls:
        mock_instance = mock_cls.return_value
        mock_instance.ensure_meta_table = AsyncMock()
        mock_instance.detect_dimension_mismatch = AsyncMock(return_value=None)
        yield mock_instance


@pytest.fixture
def mock_conn_manager():
    """Create a mock PostgresConnectionManager for RDS tests."""
    manager = MagicMock()
    manager.connection_string = "postgresql://user:pass@mydb.cluster.us-east-1.rds.amazonaws.com/agv"
    manager.table_prefix = "agv_test_"
    manager.similarity_metric = "cosine"
    manager.is_initialized = True
    manager._initialized = True

    manager.initialize = AsyncMock()
    manager.close = AsyncMock()
    manager.execute = AsyncMock(return_value="OK")
    manager.fetch = AsyncMock(return_value=[])
    manager.fetchrow = AsyncMock(return_value=None)
    manager.fetchval = AsyncMock(return_value=None)
    manager.executemany = AsyncMock()
    manager.ensure_extension = AsyncMock()

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value="OK")
    mock_conn.executemany = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_conn.fetchrow = AsyncMock(return_value=None)
    mock_conn.fetchval = AsyncMock(return_value=None)

    mock_txn_ctx = AsyncMock()
    mock_txn_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_txn_ctx.__aexit__ = AsyncMock(return_value=None)
    manager.transaction = MagicMock(return_value=mock_txn_ctx)

    return manager


@pytest.fixture
def rds_provider_local(mock_conn_manager):
    """PostgresVectorProvider with RDSAdapter in local embedding mode."""
    provider = PostgresVectorProvider(
        connection_manager=mock_conn_manager,
        project_id="test-project",
        embedding_dim=384,
        embedding_strategy="local",
        adapter=RDSAdapter(),
    )
    provider._initialized = True
    return provider


@pytest.fixture
def rds_provider_server_side(mock_conn_manager):
    """PostgresVectorProvider with RDSAdapter in server-side embedding mode."""
    provider = PostgresVectorProvider(
        connection_manager=mock_conn_manager,
        project_id="test-project",
        embedding_dim=1024,
        embedding_strategy="server_side",
        embedding_model="amazon.titan-embed-text-v2:0",
        adapter=RDSAdapter(),
    )
    provider._initialized = True
    return provider


# =============================================================================
# DSN Construction
# =============================================================================


class TestRDSDSNConstruction:
    """Tests for _build_rds_dsn() — RDS-specific DSN building."""

    def test_builds_dsn_with_host_not_localhost(self):
        """DSN must use the RDS host, not 127.0.0.1."""
        dsn = PostgresVectorProvider._build_rds_dsn(
            {
                "host": "mydb.abc123.us-east-1.rds.amazonaws.com",
                "user": "agv_user",
                "password": "secret",
                "port": 5432,
                "database": "agent-vault",
            }
        )

        from urllib.parse import urlparse
        parsed = urlparse(dsn)
        assert parsed.hostname == "mydb.abc123.us-east-1.rds.amazonaws.com"
        assert parsed.hostname != "127.0.0.1"

    def test_dsn_includes_ssl_require_by_default(self):
        """SSL mode should default to 'require' for RDS security."""
        dsn = PostgresVectorProvider._build_rds_dsn(
            {
                "host": "mydb.us-east-1.rds.amazonaws.com",
                "user": "u",
                "password": "p",
                "database": "db",
            }
        )

        assert "sslmode=require" in dsn

    def test_dsn_url_encodes_special_chars_in_password(self):
        """Password with special characters must be URL-encoded."""
        dsn = PostgresVectorProvider._build_rds_dsn(
            {
                "host": "mydb.us-east-1.rds.amazonaws.com",
                "user": "u",
                "password": "p@$$w0rd!",
                "database": "db",
            }
        )

        # '@' must be encoded to avoid DSN ambiguity
        assert "p%40" in dsn


# =============================================================================
# Capabilities
# =============================================================================


class TestRDSCapabilities:
    """Tests for provider capabilities with RDSAdapter."""

    def test_local_mode_reports_local_embedding(self, rds_provider_local):
        """Local embedding mode should report EmbeddingStrategy.LOCAL."""
        from agent_vault.storage.capabilities import EmbeddingStrategy

        caps = rds_provider_local.capabilities

        assert caps.embedding_strategy == EmbeddingStrategy.LOCAL
        assert caps.backend_type == "rds"
        assert caps.embedding_dimensions == 384

    def test_server_side_mode_reports_server_side_embedding(self, rds_provider_server_side):
        """Server-side mode should report EmbeddingStrategy.SERVER_SIDE."""
        from agent_vault.storage.capabilities import EmbeddingStrategy

        caps = rds_provider_server_side.capabilities

        assert caps.embedding_strategy == EmbeddingStrategy.SERVER_SIDE
        assert caps.backend_type == "rds"
        assert caps.embedding_dimensions == 1024
        assert caps.embedding_model == "amazon.titan-embed-text-v2:0"


# =============================================================================
# Initialization
# =============================================================================


class TestRDSInitialization:
    """Tests for initialization with RDSAdapter."""

    async def test_initialize_server_side_creates_embed_function(self, mock_conn_manager):
        """Server-side init should create the agv_embed() SQL function."""
        provider = PostgresVectorProvider(
            connection_manager=mock_conn_manager,
            project_id="test-project",
            embedding_dim=1024,
            embedding_strategy="server_side",
            embedding_model="amazon.titan-embed-text-v2:0",
            adapter=RDSAdapter(),
        )

        await provider.initialize()

        # Check that ensure_extension was called for aws_ml
        extension_calls = [c.args[0] for c in mock_conn_manager.ensure_extension.call_args_list]
        assert "aws_ml" in extension_calls

        # Check that the agv_embed function was created
        execute_calls = [str(c) for c in mock_conn_manager.execute.call_args_list]
        assert any("agv_embed" in c for c in execute_calls)
        assert any("aws_bedrock.invoke_model" in c for c in execute_calls)


# =============================================================================
# Search
# =============================================================================


class TestRDSVectorSearch:
    """Tests for vector search behavior with RDSAdapter."""

    async def test_server_side_vector_search_with_text_uses_agv_embed(
        self, rds_provider_server_side, mock_conn_manager
    ):
        """When server_side mode and a string query is passed, agv_embed() is used via CTE."""
        mock_conn_manager.fetch.return_value = []

        await rds_provider_server_side.vector_search("find auth logic", limit=5)

        call_args = mock_conn_manager.fetch.call_args
        sql = call_args.args[0]
        assert "WITH query_vec AS" in sql
        assert "agv_embed(" in sql
        assert "amazon.titan-embed-text-v2:0" in sql

    async def test_local_vector_search_uses_precomputed_vector(
        self, rds_provider_local, mock_conn_manager
    ):
        """Local mode uses the pre-computed vector, not agv_embed()."""
        mock_conn_manager.fetch.return_value = []

        query_vec = [0.1] * 384
        await rds_provider_local.vector_search(query_vec, limit=5)

        call_args = mock_conn_manager.fetch.call_args
        sql = call_args.args[0]
        assert "agv_embed" not in sql
        assert "<=>" in sql


# =============================================================================
# Embedding Generation
# =============================================================================


class TestRDSEmbeddingGeneration:
    """Tests for generate_embeddings() with RDSAdapter."""

    async def test_fallback_embed_rows_uses_agv_embed(
        self, rds_provider_server_side, mock_conn_manager
    ):
        """_fallback_embed_rows() must use agv_embed() via adapter SQL."""
        mock_conn_manager.fetch.return_value = [
            make_record(chunk_id="c1"),
        ]
        mock_conn_manager.execute.return_value = "UPDATE 1"

        await rds_provider_server_side._fallback_embed_rows(
            "agv_test_v_chunk_embeddings", "amazon.titan-embed-text-v2:0"
        )

        execute_calls = [str(c) for c in mock_conn_manager.execute.call_args_list]
        assert any("agv_embed" in c for c in execute_calls)
        assert not any("embedding('" in c for c in execute_calls)


# =============================================================================
# Registry
# =============================================================================


class TestRDSRegistry:
    """Tests verifying the registry routes RDS correctly."""

    def test_registry_routes_rds_vector_to_postgres_provider(self):
        """rds/vector role now maps to PostgresVectorProvider (with adapter)."""
        from agent_vault.storage.registry import get_provider_class

        cls = get_provider_class("rds", "vector")

        assert cls.__name__ == "PostgresVectorProvider"
