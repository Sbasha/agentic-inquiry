"""Dimension-immutability tests for LanceDBSchemaManager.

LanceDB stores vector columns as PyArrow ``FixedSizeList`` fields whose
``list_size`` is the embedding dimension. That width is fixed at table
creation — writing vectors of a different length later surfaces as an
opaque arrow error. ``LanceDBSchemaManager`` validates existing tables
against the configured ``embedding_dim`` so we raise
:class:`SchemaMismatchError` with clear guidance instead.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Callable, Dict
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit

pa = pytest.importorskip("pyarrow")

from agent_vault.database.schema_manager import LanceDBSchemaManager
from agent_vault.storage.errors import SchemaMismatchError


def _make_fake_table(dim: int, column: str = "vector") -> Any:
    """Build a minimal object with ``.schema``, ``.list_indices``, ``.create_index``."""
    schema = pa.schema(
        [
            pa.field("id", pa.string()),
            pa.field(column, pa.list_(pa.float32(), dim)),
        ]
    )
    table = MagicMock()
    table.schema = schema
    table.list_indices = MagicMock(return_value=[])
    table.create_index = MagicMock()
    table.create_fts_index = MagicMock()
    return table


def _make_schema_manager(
    table: Any,
    embedding_dim: int,
    table_name: str = "document_chunks",
    vector_column: str = "vector",
) -> LanceDBSchemaManager:
    db = MagicMock()
    db.open_table = MagicMock(return_value=table)

    async def run_sync(fn: Callable, *args):  # noqa: ANN001 - test helper
        return fn(*args)

    tables: Dict[str, Any] = {}
    table_configs: Dict[str, Dict[str, Any]] = {
        table_name: {"vector_columns": (vector_column,)}
    }

    return LanceDBSchemaManager(
        ensure_db_fn=lambda: db,
        run_sync_fn=run_sync,
        tables=tables,
        table_configs=table_configs,
        table_lock=defaultdict(asyncio.Lock).__getitem__,
        embedding_dim=embedding_dim,
    )


@pytest.mark.asyncio
async def test_raises_when_existing_table_dim_mismatches_configured():
    table = _make_fake_table(dim=768)
    manager = _make_schema_manager(table=table, embedding_dim=384)

    with pytest.raises(SchemaMismatchError) as exc_info:
        await manager.create_tables_and_indexes()

    message = str(exc_info.value)
    assert "768" in message
    assert "384" in message
    assert "lancedb" in message.lower()


@pytest.mark.asyncio
async def test_proceeds_when_dim_matches():
    table = _make_fake_table(dim=384)
    manager = _make_schema_manager(table=table, embedding_dim=384)

    # Should not raise; index creation should be attempted.
    await manager.create_tables_and_indexes()
    table.create_index.assert_called()


@pytest.mark.asyncio
async def test_skips_check_when_embedding_dim_not_provided():
    """Existing call sites (tests, downstream code) don't always thread dim."""
    table = _make_fake_table(dim=768)
    manager = _make_schema_manager(table=table, embedding_dim=None)  # type: ignore[arg-type]
    # Should not raise even though table is 768 vs no configured dim.
    await manager.create_tables_and_indexes()


@pytest.mark.asyncio
async def test_skips_table_when_vector_column_missing():
    """Tables without the configured vector column are left alone."""
    schema = pa.schema([pa.field("id", pa.string())])  # no vector column
    table = MagicMock()
    table.schema = schema
    table.list_indices = MagicMock(return_value=[])
    table.create_index = MagicMock()
    table.create_fts_index = MagicMock()

    manager = _make_schema_manager(table=table, embedding_dim=384)
    await manager.create_tables_and_indexes()  # no raise


@pytest.mark.asyncio
async def test_tables_that_do_not_exist_yet_are_skipped_silently():
    """Before first write LanceDB has no table — skipping must not raise."""
    db = MagicMock()

    def open_table(name: str):
        raise FileNotFoundError(f"no such table: {name}")

    db.open_table = MagicMock(side_effect=open_table)

    async def run_sync(fn: Callable, *args):  # noqa: ANN001 - test helper
        return fn(*args)

    manager = LanceDBSchemaManager(
        ensure_db_fn=lambda: db,
        run_sync_fn=run_sync,
        tables={},
        table_configs={"document_chunks": {"vector_columns": ("vector",)}},
        table_lock=defaultdict(asyncio.Lock).__getitem__,
        embedding_dim=384,
    )
    await manager.create_tables_and_indexes()  # no raise
