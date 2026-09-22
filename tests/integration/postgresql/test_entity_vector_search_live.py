"""Live-Postgres test that ``entity_vector_search`` works on the vector provider.

The contract tests in ``tests/storage/contracts`` parametrize over the
standard ``vector_provider`` fixture, which for Postgres yields a
``PostgresVectorProvider`` alone (no ``upsert_entities``). That covers
memory and LanceDB but skips Postgres because seeding requires the
graph provider.

This test constructs both providers over a shared
``PostgresConnectionManager`` — mirroring how production wires them via
``StorageFacade`` — so the full round-trip (graph provider writes, vector
provider reads via its new ``entity_vector_search``) is exercised
against real pgvector.
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = [pytest.mark.postgres, pytest.mark.integration]


def _postgres_url() -> str:
    if url := os.environ.get("POSTGRES_URL"):
        return url
    return (
        f"postgresql://{os.environ.get('POSTGRES_USER', 'dev')}:"
        f"{os.environ.get('POSTGRES_PASSWORD', 'dev')}@"
        f"{os.environ.get('POSTGRES_HOST', 'localhost')}:"
        f"{os.environ.get('POSTGRES_PORT', '5432')}/"
        f"{os.environ.get('POSTGRES_DB', 'agent-vault')}"
    )


def _orthogonal(dim: int = 384) -> tuple[list[float], list[float]]:
    return [1.0] + [0.0] * (dim - 1), [0.0, 1.0] + [0.0] * (dim - 2)


@pytest.mark.asyncio
async def test_postgres_entity_vector_search_end_to_end(entity_factory):
    try:
        from agent_vault.storage.providers.postgresql import (
            PostgresConnectionManager,
            PostgresGraphProvider,
            PostgresVectorProvider,
        )
    except ImportError:
        pytest.skip("asyncpg not installed")

    prefix = f"agv_evs_{uuid.uuid4().hex[:8]}_"
    project_id = f"proj_{uuid.uuid4().hex[:8]}"

    manager = PostgresConnectionManager(
        connection_string=_postgres_url(),
        table_prefix=prefix,
        pool_size=2,
    )

    try:
        await manager.initialize()
    except Exception as exc:  # pragma: no cover - skip when db down
        try:
            await manager.close()
        except Exception:
            # best-effort cleanup
            pass
        pytest.skip(f"PostgreSQL not available: {exc}")

    try:
        graph = PostgresGraphProvider(
            connection_manager=manager,
            project_id=project_id,
            embedding_dim=384,
        )
        vector = PostgresVectorProvider(
            connection_manager=manager,
            project_id=project_id,
            embedding_dim=384,
        )
        await graph.initialize()
        await vector.initialize()

        axis0, axis1 = _orthogonal()
        auth_fn = entity_factory(
            "auth_fn", project_id, name="authenticate", entity_type="function", vector=axis0
        )
        other_fn = entity_factory(
            "other_fn", project_id, name="unrelated", entity_type="function", vector=axis1
        )
        auth_cls = entity_factory(
            "auth_cls", project_id, name="AuthCtrl", entity_type="class", vector=axis0
        )
        await graph.upsert_entities([auth_fn, other_fn, auth_cls], project_id)

        # 1. Ranks the axis-aligned match ahead of the orthogonal one.
        results = await vector.entity_vector_search(
            query_vector=axis0,
            project_id=project_id,
            limit=10,
        )
        ids = [e.id for e in results]
        assert "auth_fn" in ids
        assert "other_fn" in ids
        assert ids.index("auth_fn") < ids.index("other_fn")

        # 2. entity_type filter applies.
        class_only = await vector.entity_vector_search(
            query_vector=axis0,
            project_id=project_id,
            limit=10,
            entity_type="class",
        )
        class_ids = {e.id for e in class_only}
        assert class_ids == {"auth_cls"}

        # 3. Project isolation — a different project_id returns nothing.
        other = await vector.entity_vector_search(
            query_vector=axis0,
            project_id="nonexistent_project",
            limit=10,
        )
        assert other == []

        # 4. _distance annotated.
        for entity in results:
            assert hasattr(entity, "_distance")
            assert isinstance(entity._distance, (int, float))

    finally:
        async with manager.acquire() as conn:
            # ``prefix`` contains underscores and LIKE treats ``_`` as a
            # single-character wildcard. Without an explicit ESCAPE the
            # pattern would match — and drop — unrelated tables whose
            # names happen to fit the wildcard. Use ``\`` as the escape
            # char and escape any LIKE metacharacters in the prefix.
            escaped_prefix = (
                prefix.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            rows = await conn.fetch(
                """
                SELECT tablename FROM pg_tables
                WHERE schemaname = 'public'
                  AND tablename LIKE $1 ESCAPE '\\'
                """,
                f"{escaped_prefix}%",
            )
            for row in rows:
                await conn.execute(
                    f'DROP TABLE IF EXISTS "{row["tablename"]}" CASCADE'
                )
        await manager.close()
