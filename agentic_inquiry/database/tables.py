"""Table management for LanceDB.

This module provides TableManager, which handles table creation, caching,
and index management.

Design reference: DES-S3-001 in .sessions/deep-architecture-review/009-design.md
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections import defaultdict
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Tuple

from agentic_inquiry.database.lancedb_schemas import (
    TABLE_CONFIGS,
    get_document_chunks_schema,
    get_graph_entities_schema,
    get_graph_relationships_schema,
    get_memory_episodic_schema,
)
from agentic_inquiry.storage.similarity import (
    DEFAULT_SIMILARITY_METRIC,
    lancedb_metric,
)

if TYPE_CHECKING:
    import lancedb
    from agentic_inquiry.database.connection import ConnectionManager

logger = logging.getLogger(__name__)

try:
    import pyarrow as pa
except ImportError:
    pa = None  # type: ignore[assignment]


def remove_legacy_fts_index(db_uri: Optional[str], table_name: str) -> None:
    """Delete a Tantivy-era FTS index directory left under a local table.

    Older installs created ``<table>.lance/_indices/fts`` with
    ``use_tantivy=True``. ``list_indices()`` never reports it, yet
    lancedb 0.38 refuses to create a native FTS index while it exists
    and 0.25 routes every FTS query to it, so rows written after the
    switch would be unsearchable. Removing it lets the native index be
    built; the index holds no row data.

    Only a directory that really sits under the local database root is
    removed: the path is canonicalized and prefix-checked, and a symlink
    at the index directory or its parent is refused, so a crafted
    checkout cannot point the delete outside the vault. A writer that
    can swap a component between the check and the delete already has
    write access to the dataset itself, which is the accepted boundary.
    """
    if not db_uri or "://" in db_uri:
        logger.debug(
            "Skipping legacy FTS index check for %s: no local database path",
            table_name,
        )
        return
    root = Path(db_uri).resolve()
    table_dir = root / f"{table_name}.lance"
    legacy = table_dir / "_indices" / "fts"
    if legacy.is_symlink() or legacy.parent.is_symlink() or table_dir.is_symlink():
        logger.error(
            "Refusing to remove legacy FTS index at %s: symlink in path", legacy
        )
        return
    if not legacy.is_dir():
        return
    if not legacy.resolve().is_relative_to(root):
        logger.error(
            "Refusing to remove legacy FTS index at %s: outside database root %s",
            legacy,
            root,
        )
        return
    logger.warning(
        "Removing legacy Tantivy FTS index at %s; a native index replaces it",
        legacy,
    )
    try:
        shutil.rmtree(legacy)
    except FileNotFoundError:
        # Another process opening the same table removed it first.
        return
    except OSError as e:
        logger.error("Could not remove legacy FTS index at %s: %s", legacy, e)


class TableManager:
    """Handles LanceDB table operations.

    This class manages table lifecycle including:
    - Table creation with proper schemas
    - Table caching for performance
    - Index creation and verification
    - Table cache invalidation

    Parameters
    ----------
    connection_manager:
        ConnectionManager instance for database access.
    table_configs:
        Mapping of table names to index configuration.

    Example:
        >>> conn_manager = ConnectionManager(uri="./data")
        >>> table_manager = TableManager(conn_manager)
        >>> table = await table_manager.get_table("document_chunks")
    """

    def __init__(
        self,
        connection_manager: "ConnectionManager",
        table_configs: Optional[Dict[str, Dict[str, Sequence[str]]]] = None,
        similarity_metric: str = DEFAULT_SIMILARITY_METRIC,
    ):
        self._conn_manager = connection_manager
        self._tables: Dict[str, "lancedb.table.Table"] = {}
        self._lock = asyncio.Lock()
        # One lock per table: every open/create, index creation, write,
        # compaction, and version cleanup on a table runs under it, so a
        # single process never issues two competing LanceDB commits on
        # the same dataset. Different tables proceed concurrently.
        self._table_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._table_configs = table_configs or TABLE_CONFIGS
        self._similarity_metric = lancedb_metric(similarity_metric)

    async def _run_sync(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Run a synchronous function in the executor."""
        return await self._conn_manager._run_sync(func, *args, **kwargs)

    def table_lock(self, table_name: str) -> asyncio.Lock:
        """Return the lock that serializes commits on ``table_name``.

        Callers hold it around a write or maintenance step only; the
        methods on this class that open or create a table take it
        themselves, so never call them while holding it.
        """
        return self._table_locks[table_name]

    async def _cached(self, table_name: str) -> Optional[Any]:
        async with self._lock:
            return self._tables.get(table_name)

    async def _cache(self, table_name: str, table: Any) -> None:
        async with self._lock:
            self._tables[table_name] = table

    async def _ensure_indexes(self, table_name: str, table: Any) -> None:
        """Create missing configured indexes; caller holds the table lock."""
        try:
            existing_indices = await self._run_sync(lambda: list(table.list_indices()))
        except (AttributeError, Exception):
            logger.warning(
                "Could not retrieve indices for table '%s'. "
                "Skipping index verification.",
                table_name,
                exc_info=True,
            )
            existing_indices = []

        await self._run_sync(
            self._ensure_indexes_sync, table_name, table, existing_indices
        )

    async def get_table(self, table_name: str) -> Optional[Any]:
        """Get a table by name, opening it if needed.

        Args:
            table_name: Name of the table to get

        Returns:
            LanceDB table or None if not found
        """
        table = await self._cached(table_name)
        if table is not None:
            return table

        async with self.table_lock(table_name):
            table = await self._cached(table_name)
            if table is not None:
                return table

            db = await self._conn_manager.get_connection()
            try:
                table = await self._run_sync(db.open_table, table_name)
            except Exception:
                return None

            await self._cache(table_name, table)
            await self._ensure_indexes(table_name, table)
            return table

    async def create_table_from_schema(self, table_name: str, schema: Any) -> Any:
        """Open ``table_name`` or create it empty from ``schema``.

        Used by memory adapters so ``initialize()`` leaves a real table on
        disk even when no rows have been written yet.
        """
        existing = await self.get_table(table_name)
        if existing is not None:
            return existing

        async with self.table_lock(table_name):
            cached = await self._cached(table_name)
            if cached is not None:
                return cached

            db = await self._conn_manager.get_connection()
            try:
                table = await self._run_sync(db.open_table, table_name)
            except Exception:
                table = await self._run_sync(
                    partial(
                        db.create_table,
                        table_name,
                        schema=schema,
                        exist_ok=True,
                    )
                )
            await self._cache(table_name, table)
            return table

    async def get_or_create_table(
        self,
        table_name: str,
        rows: List[Dict[str, Any]],
    ) -> Tuple[Any, bool]:
        """Get a table or create it if it doesn't exist.

        Args:
            table_name: Name of the table
            rows: Initial rows for table creation (used for schema inference)

        Returns:
            Tuple of (table, created) where created is True if table was
            created with ``rows`` as its initial data. When another
            manager creates the table first, this returns (table, False)
            so the caller writes ``rows`` itself instead of losing them.
        """
        table = await self._cached(table_name)
        if table is not None:
            return table, False

        async with self.table_lock(table_name):
            table = await self._cached(table_name)
            if table is not None:
                return table, False

            db = await self._conn_manager.get_connection()
            try:
                table = await self._run_sync(db.open_table, table_name)
                created = False
            except Exception:
                schema = None
                if pa is not None and rows:
                    vector_dims = len(rows[0].get("vector", []))
                    schema = self._get_schema_for_table(table_name, rows, vector_dims)
                try:
                    table = await self._run_sync(
                        partial(db.create_table, table_name, data=rows, schema=schema)
                    )
                    created = True
                except Exception as create_error:
                    # Either another connection created the table first (its
                    # rows are on disk, ours are not, so report not-created)
                    # or the create failed outright; only the open tells.
                    try:
                        table = await self._run_sync(db.open_table, table_name)
                    except Exception:
                        raise create_error
                    logger.warning(
                        "Table %s was created concurrently; the caller writes its "
                        "rows itself (create reported: %s)",
                        table_name,
                        create_error,
                    )
                    created = False

            await self._cache(table_name, table)
            await self._ensure_indexes(table_name, table)
            return table, created

    def _get_schema_for_table(
        self,
        table_name: str,
        rows: List[Dict[str, Any]],
        vector_dims: int,
    ) -> Optional[Any]:
        """Get the PyArrow schema for a table.

        Args:
            table_name: Name of the table
            rows: Sample rows for dimension inference
            vector_dims: Default vector dimensions

        Returns:
            PyArrow schema or None
        """
        if table_name == "document_chunks":
            return get_document_chunks_schema(vector_dims)
        elif table_name == "graph_entities":
            return get_graph_entities_schema(vector_dims)
        elif table_name == "graph_relationships":
            return get_graph_relationships_schema(vector_dims)
        elif table_name == "memory_episodic_medium":
            content_dims = len(rows[0].get("vector", [])) if rows else 384
            summary_dims = len(rows[0].get("summary_vector", [])) if rows else 128
            return get_memory_episodic_schema(content_dims, summary_dims)
        return None

    def _ensure_indexes_sync(
        self,
        table_name: str,
        table: "lancedb.table.Table",
        existing_indices: List[Any],
    ) -> None:
        """Ensure indexes exist for configured columns.

        Args:
            table_name: Name of the table
            table: LanceDB table object
            existing_indices: List of existing indices
        """
        config = self._table_configs.get(table_name)
        if not config:
            return

        existing_columns: Dict[tuple[str, ...], bool] = {
            tuple(getattr(index, "columns", []) or []): True
            for index in existing_indices
        }

        for column in config.get("vector_columns", []):
            if not column:
                continue
            key = (column,)
            if key in existing_columns:
                continue
            try:
                table.create_index(
                    metric=self._similarity_metric,
                    vector_column_name=column,
                    index_type="IVF_FLAT",
                    replace=False,
                )
                existing_columns[key] = True
                logger.info("Created vector index on %s.%s", table_name, column)
            except Exception as e:
                logger.warning(
                    "Failed to create vector index on %s.%s: %s",
                    table_name,
                    column,
                    e,
                )
                continue

        # Handle single-column FTS indexes
        for column in config.get("fts_columns", []):
            if not column:
                continue
            key = (column,)
            if key in existing_columns:
                continue
            try:
                remove_legacy_fts_index(self._conn_manager.uri, table_name)
                table.create_fts_index(column, replace=False)
                existing_columns[key] = True
                logger.info("Created FTS index on %s.%s", table_name, column)
            except Exception as e:
                logger.warning(
                    "Failed to create FTS index on %s.%s: %s",
                    table_name,
                    column,
                    e,
                )
                continue

    def _rebuild_fts_indexes_sync(
        self,
        table_name: str,
        table: "lancedb.table.Table",
    ) -> int:
        """Rebuild FTS indexes for a table with replace=True.

        Native FTS queries already scan rows written after the index was
        built; rebuilding folds those rows into the index so bulk-loaded
        tables query at index speed again.

        Args:
            table_name: Name of the table
            table: LanceDB table object

        Returns:
            Number of FTS indexes rebuilt
        """
        config = self._table_configs.get(table_name)
        if not config:
            return 0

        rebuilt_count = 0

        # Rebuild single-column FTS indexes
        for column in config.get("fts_columns", []):
            if not column:
                continue
            try:
                remove_legacy_fts_index(self._conn_manager.uri, table_name)
                table.create_fts_index(column, replace=True)
                logger.info("Rebuilt FTS index on %s.%s", table_name, column)
                rebuilt_count += 1
            except Exception as e:
                logger.warning(
                    "Failed to rebuild FTS index on %s.%s: %s",
                    table_name,
                    column,
                    e,
                )

        return rebuilt_count

    async def rebuild_fts_indexes(self, table_name: str) -> int:
        """Rebuild FTS indexes for a table asynchronously.

        A performance step after bulk writes: native FTS already scans
        rows written after the index was built.

        Args:
            table_name: Name of the table

        Returns:
            Number of FTS indexes rebuilt
        """
        table = self._tables.get(table_name)
        if table is None:
            logger.warning(
                "Cannot rebuild FTS indexes: table '%s' not found in cache", table_name
            )
            return 0

        async with self.table_lock(table_name):
            return await self._run_sync(
                self._rebuild_fts_indexes_sync, table_name, table
            )

    async def invalidate_cache(self, table_name: Optional[str] = None) -> None:
        """Invalidate cached table references.

        Args:
            table_name: Specific table to invalidate, or None for all

        Example:
            >>> await table_manager.invalidate_cache("document_chunks")
            >>> # Or clear all
            >>> await table_manager.invalidate_cache()
        """
        async with self._lock:
            if table_name:
                if table_name in self._tables:
                    del self._tables[table_name]
                    logger.debug("Invalidated cache for table: %s", table_name)
            else:
                self._tables.clear()
                logger.debug("Invalidated all table caches")

    async def list_tables(self) -> List[str]:
        """List all tables in the database.

        Returns:
            List of table names
        """
        db = await self._conn_manager.get_connection()
        if db is None:
            return []
        return await self._run_sync(db.table_names)

    def is_stale_table_error(self, error: Exception) -> bool:
        """Check if an error indicates a stale table reference.

        Args:
            error: Exception to check

        Returns:
            True if error indicates stale table data
        """
        error_str = str(error).lower()
        # LanceDB file not found errors
        if "not found" in error_str and ".lance" in error_str:
            return True
        # LanceDB IO errors on missing files
        if "lancedb" in error_str and "io" in error_str:
            return True
        return False

    def get_cached_table(self, table_name: str) -> Optional[Any]:
        """Get a cached table reference without async.

        Args:
            table_name: Name of the table

        Returns:
            Cached table or None
        """
        return self._tables.get(table_name)

    def get_table_configs(self) -> Dict[str, Dict[str, Sequence[str]]]:
        """Get the table configuration dictionary.

        Returns:
            Table configuration mapping
        """
        return self._table_configs
