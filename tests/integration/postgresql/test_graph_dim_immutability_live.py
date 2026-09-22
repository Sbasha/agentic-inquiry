"""Live-Postgres integration test for graph-provider dim immutability.

Validates end-to-end that once a ``*_g_entities`` table is persisted with a
given embedding dim, re-initializing a ``PostgresGraphProvider`` with a
different dim raises :class:`SchemaMismatchError` — before any DDL or
upsert has a chance to fail opaquely.

Requires a reachable Postgres with ``pgvector``. Skipped when unavailable.
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = [pytest.mark.postgres, pytest.mark.integration]


def _postgres_url() -> str:
    if url := os.environ.get("POSTGRES_URL"):
        return url
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "dev")
    password = os.environ.get("POSTGRES_PASSWORD", "dev")
    database = os.environ.get("POSTGRES_DB", "agent-vault")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


@pytest.mark.asyncio
async def test_graph_provider_raises_on_persisted_dim_mismatch():
    try:
        from agent_vault.storage.providers.postgresql import (
            PostgresConnectionManager,
        )
        from agent_vault.storage.providers.postgresql.graph import (
            PostgresGraphProvider,
        )
    except ImportError:
        pytest.skip("asyncpg not installed")

    from agent_vault.storage.errors import SchemaMismatchError

    prefix = f"agv_dimtest_{uuid.uuid4().hex[:8]}_"

    manager = PostgresConnectionManager(
        connection_string=_postgres_url(),
        table_prefix=prefix,
        pool_size=2,
    )

    try:
        await manager.initialize()
    except Exception as exc:  # pragma: no cover - skip when db down
        # initialize() can fail after partially starting the asyncpg pool;
        # close it before skipping to avoid leaked connections / warnings.
        try:
            await manager.close()
        except Exception:
            # Swallow cleanup errors: ``exc`` below is the real failure reason,
            # and we don't want a best-effort close to mask it.
            pass
        pytest.skip(f"PostgreSQL not available: {exc}")

    try:
        # First init: creates g_entities with embedding vector(384).
        first = PostgresGraphProvider(
            connection_manager=manager,
            project_id="proj_dim",
            embedding_dim=384,
        )
        await first.initialize()

        # Sanity: column exists with the expected width.
        async with manager.acquire() as conn:
            actual_dim = await conn.fetchval(
                """
                SELECT atttypmod
                FROM pg_attribute a
                JOIN pg_class c ON a.attrelid = c.oid
                WHERE c.relname = $1 AND a.attname = 'embedding'
                """,
                f"{prefix}g_entities",
            )
            assert actual_dim == 384

        # Second init with a different dim must fail fast.
        second = PostgresGraphProvider(
            connection_manager=manager,
            project_id="proj_dim",
            embedding_dim=768,
        )
        with pytest.raises(SchemaMismatchError) as exc_info:
            await second.initialize()

        rendered = str(exc_info.value)
        assert "384" in rendered
        assert "768" in rendered
        assert f"{prefix}g_entities" in rendered

    finally:
        # Drop any tables we created, including those from the aborted init.
        async with manager.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public' AND tablename LIKE $1
                """,
                f"{prefix}%",
            )
            for row in rows:
                await conn.execute(
                    f'DROP TABLE IF EXISTS "{row["tablename"]}" CASCADE'
                )
        await manager.close()
