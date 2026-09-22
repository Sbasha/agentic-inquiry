"""Unit guards for ``PostgresVectorProvider.entity_vector_search``.

Complements the cross-backend contract suite: here we assert shape-only
invariants (the ``TypeError`` raised when a ``str`` query_vector is
passed to a non-server-side provider) which don't need a live database
because the check fires before any I/O.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def local_embedding_provider():
    """Construct a ``PostgresVectorProvider`` wired for local embeddings.

    The TypeError guard runs before any async I/O, so we don't need a
    real connection — a minimal connection-manager mock is enough.
    """
    from agent_vault.storage.providers.postgresql.vector import (
        PostgresVectorProvider,
    )

    manager = MagicMock()
    manager.table_prefix = "agv_test_"
    manager.similarity_metric = "cosine"
    manager.initialize = AsyncMock()

    return PostgresVectorProvider(
        connection_manager=manager,
        project_id="proj",
        embedding_dim=384,
        embedding_strategy="local",
    )


@pytest.fixture
def server_side_provider():
    """Server-side provider needs an adapter that supports
    ``get_embedding_sql`` — default Postgres raises. Use the AlloyDB
    adapter, which does have server-side embeddings."""
    from agent_vault.storage.providers.postgresql.adapter import AlloyDBAdapter
    from agent_vault.storage.providers.postgresql.vector import (
        PostgresVectorProvider,
    )

    manager = MagicMock()
    manager.table_prefix = "agv_test_"
    manager.similarity_metric = "cosine"
    manager.initialize = AsyncMock()

    return PostgresVectorProvider(
        connection_manager=manager,
        project_id="proj",
        embedding_dim=768,
        embedding_strategy="server_side",
        embedding_model="text-embedding-005",
        adapter=AlloyDBAdapter(),
    )


class TestEntityVectorSearchTypeGuard:
    @pytest.mark.asyncio
    async def test_str_rejected_when_strategy_is_local(self, local_embedding_provider):
        """Without server-side embedding a ``str`` would fall through to
        ``','.join(str(v) for v in query_vector)`` and iterate character
        by character — the guard blocks that with a clear TypeError
        instead of producing nonsense SQL."""
        with pytest.raises(TypeError, match="server_side"):
            await local_embedding_provider.entity_vector_search(
                query_vector="not a vector",
                project_id="proj",
                limit=10,
            )

    @pytest.mark.asyncio
    async def test_str_accepted_when_strategy_is_server_side(
        self, server_side_provider
    ):
        """Under server-side embedding a ``str`` routes to the adapter's
        embedding function instead of raising. Don't actually run the
        query (no DB); just confirm the type guard doesn't trip."""
        # Stub the fetch so the method can complete without a real DB.
        server_side_provider._fetch = AsyncMock(return_value=[])

        result = await server_side_provider.entity_vector_search(
            query_vector="authenticate handler",
            project_id="proj",
            limit=5,
        )
        assert result == []
        server_side_provider._fetch.assert_awaited_once()


class TestEntityVectorSearchEmbeddingProjection:
    """Both server-side paths must project ``emb.embedding AS embedding``.

    Without that, ``row_to_entity`` reads ``row.get("embedding")`` as
    ``None`` and every returned ``GraphEntity`` ends up with ``vector=[]``
    — silently dropping the embedding data callers need for re-ranking
    or downstream vector math. The local path uses ``SELECT *`` so the
    column comes along for free, but the server-side branches enumerate
    columns explicitly and need to opt in.
    """

    @pytest.mark.asyncio
    async def test_server_side_text_query_projects_embedding(
        self, server_side_provider
    ):
        captured: list[str] = []

        async def capture(sql: str, *_params: Any) -> list:
            captured.append(sql)
            return []

        server_side_provider._fetch = capture

        await server_side_provider.entity_vector_search(
            query_vector="authenticate handler",
            project_id="proj",
            limit=5,
        )
        assert captured, "expected the server-side path to issue a query"
        assert "emb.embedding AS embedding" in captured[0]

    @pytest.mark.asyncio
    async def test_server_side_vector_query_projects_embedding(
        self, server_side_provider
    ):
        captured: list[str] = []

        async def capture(sql: str, *_params: Any) -> list:
            captured.append(sql)
            return []

        server_side_provider._fetch = capture

        await server_side_provider.entity_vector_search(
            query_vector=[0.1] * 768,
            project_id="proj",
            limit=5,
        )
        assert captured, "expected the server-side path to issue a query"
        assert "emb.embedding AS embedding" in captured[0]

    @pytest.mark.asyncio
    async def test_server_side_row_hydration_populates_vector(
        self, server_side_provider
    ):
        """End-to-end shape check: given a row that includes an
        ``embedding`` column, the returned ``GraphEntity.vector`` is
        populated with those floats (not the empty-list default that
        the pre-fix SELECT would have produced)."""
        row = {
            "id": "ent-1",
            "project_id": "proj",
            "file_path": "/foo.py",
            "name": "authenticate",
            "qualified_name": "auth.authenticate",
            "entity_type": "function",
            "start_line": 1,
            "end_line": 10,
            "metadata": {},
            "created_at": None,
            "updated_at": None,
            "embedding": [0.1, 0.2, 0.3],
            "_distance": 0.05,
        }
        server_side_provider._fetch = AsyncMock(return_value=[row])

        results = await server_side_provider.entity_vector_search(
            query_vector=[0.1] * 768,
            project_id="proj",
            limit=1,
        )
        assert len(results) == 1
        assert results[0].vector == [0.1, 0.2, 0.3]
        assert results[0]._distance == 0.05
