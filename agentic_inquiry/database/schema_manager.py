"""Schema manager for LanceDB operations.

This module provides the LanceDBSchemaManager class for managing
database schemas, tables, and indexes.
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

from agentic_inquiry.database.tables import remove_legacy_fts_index
from agentic_inquiry.storage.errors import DimensionMismatch, SchemaMismatchError
from agentic_inquiry.storage.similarity import (
    DEFAULT_SIMILARITY_METRIC,
    lancedb_metric,
)

logger = logging.getLogger(__name__)


class LanceDBSchemaManager:
    """Manages LanceDB schemas, tables, and indexes.

    This class handles table creation, schema validation, and index management.
    It extracts schema-related logic from LanceDBManager to improve maintainability
    and adhere to Single Responsibility Principle.
    """

    def __init__(
        self,
        ensure_db_fn: Callable[[], Any],
        run_sync_fn: Callable[[Callable, ...], Any],  # type: ignore[misc]
        tables: Dict[str, Any],
        table_configs: Dict[str, Dict[str, Sequence[str]]],
        similarity_metric: str = DEFAULT_SIMILARITY_METRIC,
        embedding_dim: Optional[int] = None,
        *,
        table_lock: Callable[[str], Any],
        db_uri: Optional[str] = None,
    ):
        """Initialize schema manager.

        Args:
            ensure_db_fn: Function to ensure database exists
            run_sync_fn: Function to run sync operations in async context
            tables: Dictionary of table names to table objects
            table_configs: Table configuration dictionary
            similarity_metric: Canonical similarity metric name
                (``cosine``, ``l2``, ``dot``). Defaults to ``cosine``.
            embedding_dim: Expected vector dimension for immutability checks
                against existing tables. When ``None``, dim validation is
                skipped (e.g. for tests that don't care about persisted state).
            table_lock: Returns the per-table ``asyncio.Lock`` that serializes
                commits on a table; index creation runs under it so it never
                races a write.
            db_uri: Local database directory; used to locate and remove a
                legacy Tantivy FTS index. ``None`` skips that step.
        """
        self._ensure_db = ensure_db_fn
        self._table_lock = table_lock
        self._db_uri = db_uri
        self._run_sync = run_sync_fn
        self._tables = tables
        self._table_configs = table_configs
        self._similarity_metric = lancedb_metric(similarity_metric)
        self._embedding_dim = embedding_dim

    async def create_tables_and_indexes(self) -> None:
        """Asynchronously ensure the database exists and indexes are registered.

        Also validates that any existing table's vector column dimension matches
        the configured ``embedding_dim``. LanceDB fixes the vector width at
        table creation (FixedSizeList), so a mismatch would otherwise surface
        as an opaque arrow/schema error at first write. Raising
        :class:`SchemaMismatchError` here gives operators a clear signal.
        """
        db = await self._run_sync(self._ensure_db)  # type: ignore[call-arg]

        for table_name, config in self._table_configs.items():
            try:
                table = await self._run_sync(db.open_table, table_name)
            except Exception:  # table may not exist yet
                continue

            self._tables[table_name] = table

            # Dimension-mismatch detection against the configured embedding_dim.
            # Read the schema through _run_sync to stay off the event loop —
            # LanceDB usually caches schema after open, but some versions can
            # trigger lazy I/O on access.
            if self._embedding_dim is not None:
                try:
                    schema = await self._run_sync(lambda t=table: t.schema)
                except Exception:
                    logger.debug(
                        "Could not read schema for table '%s'; skipping dim check.",
                        table_name,
                        exc_info=True,
                    )
                else:
                    self._check_vector_dimensions(table_name, schema, config)

            # The index list is read under the same lock that guards index
            # creation, so a concurrent opener cannot create one in between.
            async with self._table_lock(table_name):
                try:
                    existing_indices = await self._run_sync(list, table.list_indices())
                except (AttributeError, Exception):
                    logger.warning(
                        "Could not retrieve indices for table '%s'. Skipping index verification.",
                        table_name,
                        exc_info=True,
                    )
                    existing_indices = []
                await self._run_sync(self._ensure_indexes_sync, table_name, table, existing_indices)  # type: ignore[call-arg]

    def _check_vector_dimensions(
        self,
        table_name: str,
        schema: Any,
        config: Dict[str, Sequence[str]],
    ) -> None:
        """Verify the persisted vector column dim matches ``embedding_dim``.

        LanceDB stores vectors as PyArrow ``FixedSizeList`` fields whose
        ``list_size`` is the dimension. Iterates each configured vector column
        on the supplied PyArrow ``schema`` and raises
        :class:`SchemaMismatchError` on mismatch.

        Tables that exist but don't yet have the vector column (e.g. created
        by a different writer, schema inferred without vectors) are skipped —
        they'll either error naturally at first write, or pick up the correct
        schema when the column is added.
        """
        # Defensive early-return rather than ``assert`` so the guard survives
        # ``python -O``. The happy path passes an int.
        if self._embedding_dim is None:
            return

        for column in config.get("vector_columns", []) or []:
            if not column:
                continue
            try:
                field = schema.field(column)
            except (KeyError, ValueError):
                continue

            actual_dim = getattr(field.type, "list_size", None)
            if actual_dim is None or actual_dim < 0:
                # Not a FixedSizeList, or size isn't known — nothing to check.
                continue

            if actual_dim != self._embedding_dim:
                mismatch = DimensionMismatch(
                    backend="lancedb",
                    table_name=table_name,
                    configured=self._embedding_dim,
                    actual=actual_dim,
                    column=column,
                    remediation=(
                        "Drop the LanceDB table directory and re-index, or "
                        "create a new table with the desired width."
                    ),
                )
                logger.error(str(mismatch))
                raise SchemaMismatchError(str(mismatch))

    async def validate_database_integrity(self) -> Dict[str, Any]:
        """Validate database integrity and return status.
        
        Returns:
            Dictionary with validation results including:
            - valid: Overall validity status
            - tables: Per-table validation results
            - errors: List of validation errors
        """
        results = {
            "valid": True,
            "tables": {},
            "errors": [],
        }

        # Check each configured table
        for table_name in self._table_configs:
            table_result = {
                "exists": False,
                "accessible": False,
                "has_indices": False,
                "errors": [],
            }

            try:
                # Check if table exists in our cache
                table = self._tables.get(table_name)
                if not table:
                    table_result["errors"].append(f"Table {table_name} not found in cache")  # type: ignore[attr-defined]
                    results["valid"] = False
                else:
                    table_result["exists"] = True

                    # Try to access table
                    try:
                        # Simple check - try to count records
                        await self._run_sync(table.count_rows)  # type: ignore[call-arg]
                        table_result["accessible"] = True
                    except Exception as e:
                        table_result["errors"].append(f"Table not accessible: {e}")  # type: ignore[attr-defined]
                        results["valid"] = False

                    # Check indices
                    try:
                        indices = await self._run_sync(list, table.list_indices())
                        table_result["has_indices"] = len(indices) > 0
                        table_result["index_count"] = len(indices)
                    except Exception as e:
                        table_result["errors"].append(f"Could not list indices: {e}")  # type: ignore[attr-defined]

            except Exception as e:
                table_result["errors"].append(f"Validation error: {e}")  # type: ignore[attr-defined]
                results["valid"] = False

            results["tables"][table_name] = table_result  # type: ignore[index]

        return results

    def _ensure_indexes_sync(
        self,
        table_name: str,
        table: Any,
        existing_indices: List[Any],
    ) -> None:
        """Ensure indexes exist for configured columns.
        
        Args:
            table_name: Name of the table
            table: LanceDB table object
            existing_indices: List of existing indices (retrieved in async context)
        """
        config = self._table_configs.get(table_name)
        if not config:
            return

        existing_columns = {
            tuple(getattr(index, "columns", []) or []): True
            for index in existing_indices
        }

        # Create vector indexes
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
                remove_legacy_fts_index(self._db_uri, table_name)
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
