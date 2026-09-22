"""Dimension-immutability tests for PostgresGraphProvider.

The graph provider stores entity embeddings in ``pgvector`` columns whose
dimension is fixed at ``CREATE TABLE`` time. If the configured
``embedding_dim`` diverges from what's already persisted, we want to fail
fast during ``initialize()`` with a clear :class:`SchemaMismatchError`
rather than surface an opaque pgvector type error at first upsert.

These tests mock asyncpg and assert that the tracker is consulted *before*
any ``CREATE TABLE`` DDL is issued, and that a mismatch aborts init.
"""

from __future__ import annotations

from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit

from agent_vault.storage.errors import SchemaMismatchError


def _make_connection_manager():
    """Build a PostgresConnectionManager mock that can back the provider."""
    manager = MagicMock()
    manager.table_prefix = "agv_test_"
    manager.similarity_metric = "cosine"
    manager.initialize = AsyncMock()
    manager.ensure_extension = AsyncMock()

    executed: List[str] = []

    async def execute(stmt, *args):
        executed.append(str(stmt))
        return None

    manager.execute = AsyncMock(side_effect=execute)
    manager._executed = executed  # type: ignore[attr-defined]

    mock_conn = AsyncMock()
    manager.acquire = MagicMock()
    manager.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    manager.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    manager._mock_conn = mock_conn  # type: ignore[attr-defined]
    return manager


@pytest.mark.asyncio
async def test_initialize_raises_on_dimension_mismatch():
    from agent_vault.storage.providers.postgresql.graph import PostgresGraphProvider

    manager = _make_connection_manager()
    # pg_attribute returns 768 for the existing column, configured is 1536.
    manager._mock_conn.fetchval = AsyncMock(return_value=768)

    provider = PostgresGraphProvider(
        connection_manager=manager,
        project_id="proj",
        embedding_dim=1536,
    )

    with pytest.raises(SchemaMismatchError) as exc_info:
        await provider.initialize()

    message = str(exc_info.value)
    assert "1536" in message
    assert "768" in message
    # Check must happen before any CREATE TABLE is dispatched.
    assert not any("CREATE TABLE" in stmt.upper() for stmt in manager._executed), (
        "Provider must abort before issuing DDL"
    )


@pytest.mark.asyncio
async def test_initialize_proceeds_when_dimensions_match():
    from agent_vault.storage.providers.postgresql.graph import PostgresGraphProvider

    manager = _make_connection_manager()
    manager._mock_conn.fetchval = AsyncMock(return_value=384)

    provider = PostgresGraphProvider(
        connection_manager=manager,
        project_id="proj",
        embedding_dim=384,
    )

    await provider.initialize()

    assert provider._initialized is True
    # After the check passes, DDL for the *exact* prefix-qualified entities
    # table must have been issued. Matching on the concrete table name (not
    # a substring like "ENTITIES") avoids false positives against e.g. FK
    # references or index names that happen to mention "entities".
    entities_create = f"CREATE TABLE IF NOT EXISTS {provider._entities_table} "
    assert any(
        entities_create in stmt for stmt in manager._executed
    ), f"Expected CREATE TABLE for {provider._entities_table} in: {manager._executed}"


@pytest.mark.asyncio
async def test_initialize_proceeds_when_table_absent():
    """No existing column -> fetchval returns None -> no mismatch raised."""
    from agent_vault.storage.providers.postgresql.graph import PostgresGraphProvider

    manager = _make_connection_manager()
    manager._mock_conn.fetchval = AsyncMock(return_value=None)

    provider = PostgresGraphProvider(
        connection_manager=manager,
        project_id="proj",
        embedding_dim=768,
    )

    await provider.initialize()
    assert provider._initialized is True


@pytest.mark.asyncio
async def test_initialize_checks_entity_embeddings_table_in_server_side_mode():
    """Server-side strategy persists entity_embeddings; it must also be validated."""
    from agent_vault.storage.providers.postgresql.adapter import AlloyDBAdapter
    from agent_vault.storage.providers.postgresql.graph import PostgresGraphProvider

    manager = _make_connection_manager()
    manager._mock_conn.fetchval = AsyncMock(return_value=384)

    provider = PostgresGraphProvider(
        connection_manager=manager,
        project_id="proj",
        embedding_dim=384,
        embedding_strategy="server_side",
        embedding_model="text-embedding-005",
        adapter=AlloyDBAdapter(),
    )

    checked_tables = provider._dim_checked_tables()
    assert any("entities" in t for t in checked_tables)
    assert any("entity_embeddings" in t for t in checked_tables), (
        "server_side mode must include entity_embeddings table in the dim check"
    )
