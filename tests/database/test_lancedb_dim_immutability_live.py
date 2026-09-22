"""Live LanceDB test for embedding-dim immutability.

Opens a real LanceDB store on a tmp path, writes one row to lock in the
``document_chunks`` schema at a known dim, then spins up a fresh
``LanceDBManager`` configured with a different dim and asserts that
``create_tables_and_indexes()`` raises :class:`SchemaMismatchError`.

LanceDB is file-based, so this test runs in CI without external services.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

pa = pytest.importorskip("pyarrow")
lancedb = pytest.importorskip("lancedb")

from agent_vault.database.lancedb_manager import LanceDBManager
from agent_vault.database.lancedb_schemas import TABLE_CONFIGS
from agent_vault.storage.errors import SchemaMismatchError


def _seed_document_chunks(uri: str, dim: int) -> None:
    """Create a ``document_chunks`` table with the requested vector width."""
    schema = pa.schema(
        [
            pa.field("id", pa.string()),
            pa.field("vector", pa.list_(pa.float32(), dim)),
        ]
    )
    db = lancedb.connect(uri)
    table = db.create_table(
        "document_chunks",
        schema=schema,
        mode="overwrite",
    )
    # Must have at least one row so the schema is truly persisted.
    table.add([{"id": "seed", "vector": [0.0] * dim}])


@pytest.mark.asyncio
async def test_lancedb_manager_raises_when_configured_dim_differs(tmp_path):
    uri = str(tmp_path / "lancedb")

    _seed_document_chunks(uri, dim=384)

    # New manager configured with a DIFFERENT embedding_dim.
    manager = LanceDBManager(
        uri=uri,
        table_configs=TABLE_CONFIGS,
        embedding_dim=768,
    )
    await manager.connect()

    with pytest.raises(SchemaMismatchError) as exc_info:
        await manager.create_tables_and_indexes()

    message = str(exc_info.value)
    assert "384" in message
    assert "768" in message
    assert "document_chunks" in message

    await manager.close()


@pytest.mark.asyncio
async def test_lancedb_manager_accepts_matching_dim(tmp_path):
    uri = str(tmp_path / "lancedb")

    _seed_document_chunks(uri, dim=384)

    manager = LanceDBManager(
        uri=uri,
        table_configs=TABLE_CONFIGS,
        embedding_dim=384,
    )
    await manager.connect()

    # No raise; opening a matching table is the happy path.
    await manager.create_tables_and_indexes()

    await manager.close()


class TestResolveEmbeddingDimFromConfig:
    """Unit coverage for the resolver helper that `from_config` uses.

    The risk assessment called out that ``from_config`` is the entry point
    where a stale ``config.embeddings.default_dimensions`` now triggers a
    clear error instead of a confusing arrow crash. Cover the resolution
    order directly so a future refactor can't silently skip validation.
    """

    def _make_config(self, *, default_dimensions=None, backends=None, vector_backend=None):
        from types import SimpleNamespace

        embeddings = (
            SimpleNamespace(default_dimensions=default_dimensions)
            if default_dimensions is not None
            else None
        )
        storage = SimpleNamespace(
            backends=backends or {},
            vector_backend=vector_backend or "default",
        )
        return SimpleNamespace(embeddings=embeddings, storage=storage)

    def test_returns_none_when_no_config_fields_set(self):
        from agent_vault.database.lancedb_manager import (
            _resolve_embedding_dim_from_config,
        )

        cfg = self._make_config()
        assert _resolve_embedding_dim_from_config(cfg) is None

    def test_uses_embeddings_default_dimensions_as_fallback(self):
        from agent_vault.database.lancedb_manager import (
            _resolve_embedding_dim_from_config,
        )

        cfg = self._make_config(default_dimensions=768)
        assert _resolve_embedding_dim_from_config(cfg) == 768

    def test_per_backend_override_wins_over_embeddings_default(self):
        """#4 from the review — per-backend override must win so the
        validation actually fires on configs that set it."""
        from agent_vault.database.lancedb_manager import (
            _resolve_embedding_dim_from_config,
        )

        cfg = self._make_config(
            default_dimensions=384,
            vector_backend="lance",
            backends={"lance": {"embedding_dim": 1536}},
        )
        assert _resolve_embedding_dim_from_config(cfg) == 1536

    def test_ignores_non_positive_dims(self):
        from agent_vault.database.lancedb_manager import (
            _resolve_embedding_dim_from_config,
        )

        cfg = self._make_config(default_dimensions=0)
        assert _resolve_embedding_dim_from_config(cfg) is None
