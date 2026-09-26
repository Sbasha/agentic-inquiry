"""Production LanceDB manager backed by the real LanceDB Python client.

This module provides LanceDBManager, which implements the DatabaseProtocol
interface for async database operations with project-based data isolation.

The manager delegates to focused components:
- ConnectionManager: Connection lifecycle (connect, close, reconnect)
- TableManager: Table operations (get, create, cache, indexes)
- LanceDBQueryBuilder: Query execution (vector, FTS, hybrid search)
- LanceDBSchemaManager: Schema validation and integrity checks

Design reference: DES-S3-001 in .sessions/deep-architecture-review/009-design.md
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from contextlib import asynccontextmanager
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Union,
)

if TYPE_CHECKING:
    from agentic_inquiry.database.filters import Filter, FilterInput

from agentic_inquiry.database.filters.dict_translator import format_in_clause
from agentic_inquiry.models.document_chunk import BRANCH_INDEXING_FIELDS

logger = logging.getLogger(__name__)


def _is_retryable_lancedb_error(exc: BaseException) -> bool:
    """Return True if a LanceDB write error is labeled retryable.

    Matches the database's own "Retryable commit conflict" wording on
    the exception and its ``__cause__`` chain.
    """
    text = str(exc).lower()
    if "commit conflict" in text or "retryable" in text:
        return True
    cause = getattr(exc, "__cause__", None)
    if cause is not None and cause is not exc:
        return _is_retryable_lancedb_error(cause)
    return False


def _collapse_duplicate_merge_keys(
    rows: List[Dict[str, Any]],
    key_column: Union[str, List[str]],
) -> tuple[List[Dict[str, Any]], int]:
    """Keep the last row for each merge key.

    LanceDB ``merge_insert`` fails closed when the source batch repeats a
    join key. Collapse here so the writer logs the drop instead of the
    database silently refusing the batch.

    Returns:
        A pair of (deduplicated rows in first-seen key order, number of
        rows dropped).
    """
    key_names = [key_column] if isinstance(key_column, str) else list(key_column)
    collapsed: Dict[tuple[Any, ...], Dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(name) for name in key_names)
        collapsed[key] = row
    dropped = len(rows) - len(collapsed)
    return list(collapsed.values()), dropped


async def _retry_lancedb_write(operation: Callable[[], Awaitable[None]]) -> None:
    """Run a LanceDB write with capped backoff on retryable conflicts."""
    from agentic_inquiry.utils.retry import RetryPolicy

    policy = RetryPolicy(
        max_attempts=5,
        base_delay=0.1,
        max_delay=2.0,
        jitter=True,
    )
    last_exc: Optional[Exception] = None
    for attempt in range(policy.max_attempts):
        try:
            await operation()
            return
        except Exception as e:
            last_exc = e
            if not _is_retryable_lancedb_error(e) or attempt >= policy.max_attempts - 1:
                raise
            delay = policy.calculate_delay(attempt)
            logger.warning(
                "LanceDB write failed (attempt %d/%d), retrying in %.2fs: %s",
                attempt + 1,
                policy.max_attempts,
                delay,
                e,
            )
            await asyncio.sleep(delay)
    if last_exc is not None:
        raise last_exc


# ``Table.optimize`` always prunes versions older than its window; this
# window means "prune nothing" for a compaction-only pass.
_NO_VERSION_CLEANUP = timedelta(days=365 * 100)

try:  # pragma: no cover - exercised indirectly in integration tests
    import lancedb
except ImportError:  # pragma: no cover - surfaced during runtime usage
    lancedb = None  # type: ignore[assignment]

from agentic_inquiry.config import Config  # noqa: E402 - after optional dependency handling
from agentic_inquiry.constants import CURRENT_PROJECT_ID  # noqa: E402
from agentic_inquiry.database.connection import ConnectionManager  # noqa: E402
from agentic_inquiry.database.lancedb_schemas import (  # noqa: E402
    FORBIDDEN_FIELD_ALIASES,
    REQUIRED_FIELDS,
    TABLE_CONFIGS,
)
from agentic_inquiry.database.tables import TableManager  # noqa: E402
from agentic_inquiry.exceptions import StorageError  # noqa: E402
from agentic_inquiry.storage.similarity import DEFAULT_SIMILARITY_METRIC  # noqa: E402


def _resolve_similarity_metric_from_config(config: Any) -> str:
    """Resolve the similarity metric from the active vector backend config.

    Falls back to ``DEFAULT_SIMILARITY_METRIC`` when the named-backend config
    is absent or the active entry does not override the metric. This helper
    does not validate the returned metric name; if a configured value is
    unknown, downstream LanceDB components may raise (for example when
    converting it via ``lancedb_metric()``).
    """
    backends = getattr(config.storage, "backends", None)
    if not backends:
        return DEFAULT_SIMILARITY_METRIC
    backend_name = getattr(config.storage, "vector_backend", None) or "default"
    backend_cfg = backends.get(backend_name)
    if not isinstance(backend_cfg, dict):
        return DEFAULT_SIMILARITY_METRIC
    return backend_cfg.get("similarity_metric", DEFAULT_SIMILARITY_METRIC)


def _resolve_embedding_dim_from_config(config: Any) -> Optional[int]:
    """Resolve the expected embedding dim from config for dim-immutability checks.

    Resolution order:

    1. Active named-backend config (``config.storage.backends[vector_backend]
       .embedding_dim``) — per-backend overrides win, matching how backends
       are routed elsewhere (see ``_resolve_similarity_metric_from_config``).
       Without this fallback a per-backend override of ``embedding_dim`` would
       silently bypass dim validation — the exact scenario this check exists
       to prevent.
    2. Global ``config.embeddings.default_dimensions`` — the runtime source
       of truth for embedding-production dim.
    3. ``None`` — schema manager skips the check. Legacy configs with neither
       field stay backward-compatible.
    """
    backends = getattr(getattr(config, "storage", None), "backends", None)
    if backends:
        backend_name = getattr(config.storage, "vector_backend", None) or "default"
        backend_cfg = backends.get(backend_name)
        if isinstance(backend_cfg, dict):
            dim = backend_cfg.get("embedding_dim")
            if isinstance(dim, int) and dim > 0:
                return dim

    embeddings_cfg = getattr(config, "embeddings", None)
    if embeddings_cfg is None:
        return None
    dim = getattr(embeddings_cfg, "default_dimensions", None)
    if isinstance(dim, int) and dim > 0:
        return dim
    return None


class LanceDBManager:
    """Asynchronous helper that wraps LanceDB table operations.

    Implements DatabaseProtocol for dependency injection and testing.

    Parameters
    ----------
    uri:
        Path or URI pointing at a LanceDB store. Optional when injecting a
        connection or connection factory directly, or when using config.
    config:
        Config instance for storage configuration. When provided, uses
        config.storage.get_lancedb_path() for path resolution.
    project_id:
        Project identifier for data isolation. Takes precedence over
        config.storage.default_project_id if both are provided.
    connection:
        Pre-created LanceDB connection instance. When supplied the manager will
        reuse the object and never attempt to create directories or call
        :func:`lancedb.connect`.
    connection_factory:
        Callable that yields a LanceDB connection. Useful for remote URIs where
        directory creation must be avoided or when more advanced connection
        options are required.
    table_configs:
        Mapping of table names to index configuration. When omitted the module
        level :data:`TABLE_CONFIGS` is used. Provide overrides when your LanceDB
        schema diverges from the defaults.

    Note:
        This class implements DatabaseProtocol, providing async methods for
        database operations with project-based data isolation.
    """

    def __init__(
        self,
        uri: Optional[str] = None,
        *,
        config: Optional[Any] = None,
        project_id: Optional[str] = None,
        connection: Optional["lancedb.DBConnection"] = None,
        connection_factory: Optional[Callable[[], "lancedb.DBConnection"]] = None,
        table_configs: Optional[Dict[str, Dict[str, Sequence[str]]]] = None,
        similarity_metric: str = DEFAULT_SIMILARITY_METRIC,
        embedding_dim: Optional[int] = None,
    ):
        # Extract URI from config if provided
        if config is not None:
            if uri is None:
                uri = str(config.storage.get_lancedb_path())
            # Note: Directory creation is handled by LanceDBConnectionManager.initialize()
            # following the lifecycle protocol where backends own their resource setup

        # Set project_id (explicit parameter takes precedence over config)
        self._project_id: Optional[str]
        if project_id is not None:
            self._project_id = project_id
        elif config is not None and config.storage.default_project_id is not None:
            self._project_id = config.storage.default_project_id
        else:
            self._project_id = None

        # Determine if we need to prepare local path
        prepare_local_path = (
            connection is None
            and connection_factory is None
            and uri is not None
            and "://" not in uri
        )

        # Initialize connection manager (handles connection lifecycle)
        self._conn_manager = ConnectionManager(
            uri=uri,
            connection=connection,
            connection_factory=connection_factory,
            prepare_local_path=prepare_local_path,
        )

        # Store for backward compatibility (some code may access these directly)
        self.uri = uri
        self._table_configs = table_configs or TABLE_CONFIGS

        self._similarity_metric = similarity_metric

        # Initialize table manager (handles table operations)
        self._table_manager = TableManager(
            connection_manager=self._conn_manager,
            table_configs=self._table_configs,
            similarity_metric=self._similarity_metric,
        )

        # Import metrics tracker
        from agentic_inquiry.metrics import get_metrics_tracker

        self._metrics = get_metrics_tracker()

        # Initialize query builder and schema manager
        from agentic_inquiry.database.query_builder import LanceDBQueryBuilder
        from agentic_inquiry.database.schema_manager import LanceDBSchemaManager

        self._query_builder = LanceDBQueryBuilder(
            get_table_fn=self._get_table_async,
            run_sync_fn=self._run_sync,
            project_id=self._project_id,
            invalidate_cache_fn=self.invalidate_table_cache,
        )

        self._schema_manager = LanceDBSchemaManager(
            ensure_db_fn=self._conn_manager._ensure_db_sync,
            run_sync_fn=self._run_sync,
            tables=self._table_manager._tables,
            table_configs=self._table_configs,
            similarity_metric=self._similarity_metric,
            embedding_dim=embedding_dim,
            table_lock=self._table_manager.table_lock,
            db_uri=self._conn_manager.uri,
        )

    def get_metrics(self) -> Dict[str, Any]:
        """Get database manager metrics.

        Returns:
            Dictionary containing latency metrics for database operations
        """
        return {
            "latency_metrics": self._metrics.get_all_metrics(),
        }

    def _validate_record(
        self, table_name: str, record: Dict[str, Any], strict: bool = True
    ) -> None:
        """Validate a record against schema requirements before write.

        This validation catches field name inconsistencies at write time
        rather than allowing them to propagate and require fallback patterns.

        Args:
            table_name: Name of the target table
            record: Dictionary to validate
            strict: If True, raise error on forbidden fields; if False, log warning

        Raises:
            ValueError: If record contains forbidden field aliases or missing required fields
        """
        # Check for forbidden field aliases (common mistakes)
        for forbidden, correct in FORBIDDEN_FIELD_ALIASES.items():
            if forbidden in record:
                msg = (
                    f"Field '{forbidden}' is not allowed in {table_name}. "
                    f"Use '{correct}' instead. This is a schema consistency error."
                )
                if strict:
                    raise ValueError(msg)
                else:
                    logger.warning(msg)

        # Check for required fields
        if table_name in REQUIRED_FIELDS:
            required = REQUIRED_FIELDS[table_name]
            missing = [f for f in required if f not in record]
            if missing:
                raise ValueError(
                    f"Missing required fields for {table_name}: {missing}. "
                    f"Required fields are: {required}"
                )

    @classmethod
    def from_config(
        cls,
        config: Optional[Config] = None,
        project_id: Optional[str] = None,
    ) -> "LanceDBManager":
        """Create LanceDBManager from configuration.

        Args:
            config: Optional Config instance. If None, loads default configuration.
            project_id: Optional project ID for data isolation. If provided,
                tables will be scoped to this project.

        Returns:
            LanceDBManager instance configured from settings

        Example:
            >>> from agentic_inquiry.config import Config
            >>> config = Config.load()
            >>> manager = LanceDBManager.from_config(config, project_id="my-project")

            >>> # Or load default config
            >>> manager = LanceDBManager.from_config()
        """
        if config is None:
            config = Config.load()

        similarity_metric = _resolve_similarity_metric_from_config(config)
        embedding_dim = _resolve_embedding_dim_from_config(config)

        return cls(
            config=config,
            project_id=project_id,
            similarity_metric=similarity_metric,
            embedding_dim=embedding_dim,
            table_configs=TABLE_CONFIGS,  # Use default table configs
        )

    async def connect(self) -> "LanceDBManager":
        """Open a connection to the LanceDB database."""
        await self._conn_manager.connect()
        return self

    async def close(self) -> None:
        """Close the database connection and clean up resources.

        This method closes the database connection and clears cached tables.
        It should be called when the manager is no longer needed to free
        resources properly.

        Example:
            >>> manager = LanceDBManager(uri="./data")
            >>> await manager.connect()
            >>> # ... use manager ...
            >>> await manager.close()

            >>> # Or use as async context manager
            >>> async with LanceDBManager(uri="./data") as manager:
            ...     # ... use manager ...
            ...     pass  # Automatically closed
        """
        # Clear table cache
        await self._table_manager.invalidate_cache()
        # Close connection
        await self._conn_manager.close()

    async def __aenter__(self) -> "LanceDBManager":
        """Async context manager entry.

        Returns:
            Self after connecting to the database
        """
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        """Async context manager exit.

        Closes the connection when exiting the context.
        """
        await self.close()

    def is_connected(self) -> bool:
        """Check if the database connection is active.

        Returns:
            True if connected, False otherwise
        """
        return self._conn_manager.is_connected()

    async def invalidate_table_cache(self, table_name: Optional[str] = None) -> None:
        """Invalidate cached table references.

        Call this when table data may have changed externally (e.g., data files
        deleted) to force re-opening the table on next access.

        Args:
            table_name: Specific table to invalidate, or None to clear all tables

        Example:
            >>> manager = LanceDBManager(uri="./data")
            >>> # After external data change
            >>> await manager.invalidate_table_cache("document_chunks")
            >>> # Or clear all
            >>> await manager.invalidate_table_cache()
        """
        await self._table_manager.invalidate_cache(table_name)

    def _is_stale_table_error(self, error: Exception) -> bool:
        """Check if an error indicates a stale table reference.

        LanceDB raises errors when cached table references point to
        deleted or moved data files. This method detects such errors.

        Args:
            error: Exception to check

        Returns:
            True if error indicates stale table data
        """
        return self._table_manager.is_stale_table_error(error)

    async def reconnect(self) -> None:
        """Reconnect to the database.

        This method closes the existing connection and creates a new one.
        Useful for recovering from connection errors or refreshing stale
        connections.

        Example:
            >>> manager = LanceDBManager(uri="./data")
            >>> await manager.connect()
            >>> # ... connection error occurs ...
            >>> await manager.reconnect()
        """
        # Clear table cache before reconnecting
        await self._table_manager.invalidate_cache()
        # Reconnect via connection manager
        await self._conn_manager.reconnect()

    async def health_check(self) -> bool:
        """Check if the database connection is healthy.

        Attempts to list tables to verify the connection is working.

        Returns:
            True if connection is healthy, False otherwise
        """
        if not self.is_connected():
            return False

        try:
            # Try to list tables as a health check
            await self._table_manager.list_tables()
            return True
        except Exception as e:
            logger.warning("Database health check failed: %s", e, exc_info=True)
            return False

    async def validate_database_integrity(self) -> Dict[str, Any]:
        """Validate database integrity and return status.

        Returns:
            Dictionary with validation results including:
            - valid: Overall validity status
            - tables: Per-table validation results
            - errors: List of validation errors
        """
        return await self._schema_manager.validate_database_integrity()

    async def create_tables_and_indexes(self) -> None:
        """Asynchronously ensure the database exists and indexes are registered."""
        await self._schema_manager.create_tables_and_indexes()

    async def add_document_chunks(
        self,
        chunks: List[Any],
        project_id: str = CURRENT_PROJECT_ID,
        ensure_commit: bool = True,
    ) -> None:
        """Add or update document chunks in the database.

        This method performs upsert behavior: updates existing chunks
        (matched by ID) and inserts new ones.

        Args:
            chunks: List of document chunks to add/update
            project_id: Project identifier for data isolation. Note that chunks
                       already contain project_id in their data, so this parameter
                       is primarily for protocol compliance.
            ensure_commit: Accepted for interface compatibility. LanceDB commits
                the write before this call returns; nothing further runs.
        """
        with self._metrics.track_latency("db.add_document_chunks"):
            await self._upsert_rows(
                "document_chunks", chunks, key_column="id", ensure_commit=ensure_commit
            )

    async def rebuild_fts_indexes(self, table_name: str = "document_chunks") -> int:
        """Rebuild FTS indexes for a table.

        Native FTS queries already scan rows written after the index was
        built. Call this after bulk writes so those rows are folded into
        the index and queries run at index speed.

        Args:
            table_name: Name of the table (default: document_chunks)

        Returns:
            Number of FTS indexes rebuilt
        """
        with self._metrics.track_latency("db.rebuild_fts_indexes"):
            return await self._table_manager.rebuild_fts_indexes(table_name)

    async def add_graph_entities(
        self,
        entities: List[Any],
        project_id: str = CURRENT_PROJECT_ID,
        ensure_commit: bool = True,
    ) -> None:
        """Add or update graph entities in the database.

        This method performs upsert behavior: updates existing entities
        (matched by ID and project_id) and inserts new ones.

        Args:
            entities: List of graph entities to add/update
            project_id: Project identifier for data isolation. Note that entities
                       already contain project_id in their data, so this parameter
                       is primarily for protocol compliance.
            ensure_commit: Accepted for interface compatibility. LanceDB commits
                the write before this call returns; nothing further runs.
        """
        with self._metrics.track_latency("db.add_graph_entities"):
            # Use composite key [id, project_id] for proper project isolation
            await self._upsert_rows(
                "graph_entities",
                entities,
                key_column=["id", "project_id"],
                ensure_commit=ensure_commit,
            )

    async def add_graph_relationships(
        self,
        relationships: List[Any],
        project_id: str = CURRENT_PROJECT_ID,
        ensure_commit: bool = True,
    ) -> None:
        """Add or update graph relationships in the database.

        This method performs upsert behavior: updates existing relationships
        (matched by ID) and inserts new ones.

        Args:
            relationships: List of graph relationships to add/update
            project_id: Project identifier for data isolation. Note that relationships
                       already contain project_id in their data, so this parameter
                       is primarily for protocol compliance.
            ensure_commit: Accepted for interface compatibility. LanceDB commits
                the write before this call returns; nothing further runs.
        """
        logger.info(
            "Writing %d relationships to table graph_relationships", len(relationships)
        )
        with self._metrics.track_latency("db.add_graph_relationships"):
            # Use composite key [id, project_id] for proper project isolation
            await self._upsert_rows(
                "graph_relationships",
                relationships,
                key_column=["id", "project_id"],
                ensure_commit=ensure_commit,
            )

    async def graph_ranking_available(self) -> bool:
        """Return ``True`` when graph entities provide ranking metadata."""

        sample = await self.advanced_filter("graph_entities", limit=5)
        return any(
            entity.get("has_ranking_signals") or entity.get("pagerank") is not None
            for entity in sample
        )

    async def delete_document_chunks(self, ids: List[str]) -> None:
        await self._delete_rows("document_chunks", ids)

    async def delete_graph_entities(self, ids: List[str]) -> None:
        await self._delete_rows("graph_entities", ids)

    async def delete_graph_relationships(self, ids: List[str]) -> None:
        await self._delete_rows("graph_relationships", ids)

    async def vector_search(
        self,
        table_name: str,
        query_vector: List[float],
        vector_column_name: str,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> List[Dict[str, Any]]:
        """Perform vector similarity search.

        Args:
            table_name: Name of the table to search
            query_vector: Query vector for similarity search
            vector_column_name: Name of the vector column
            limit: Maximum number of results
            filters: Optional additional filters
            project_id: Project ID to filter by. Use CURRENT_PROJECT_ID for configured project,
                       specific ID for single project, or None for all projects.

        Returns:
            List of matching records
        """
        with self._metrics.track_latency("db.vector_search"):
            if query_vector is None or len(query_vector) == 0:
                return await self.advanced_filter(
                    table_name, filters=filters, limit=limit, project_id=project_id
                )

            return await self._query_builder.vector_search(
                table_name=table_name,
                query_vector=query_vector,
                vector_column_name=vector_column_name,
                limit=limit,
                filters=filters,
                project_id=project_id,
            )

    async def fts_search(
        self,
        table_name: str,
        query: str,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> List[Dict[str, Any]]:
        """Perform full-text search.

        Args:
            table_name: Name of the table to search
            query: Search query string
            limit: Maximum number of results
            filters: Optional additional filters
            project_id: Project ID to filter by. Use CURRENT_PROJECT_ID for configured project,
                       specific ID for single project, or None for all projects.

        Returns:
            List of matching records
        """
        with self._metrics.track_latency("db.fts_search"):
            if not query:
                return await self.advanced_filter(
                    table_name, filters=filters, limit=limit, project_id=project_id
                )

            return await self._query_builder.fts_search(
                table_name=table_name,
                query=query,
                limit=limit,
                filters=filters,
                project_id=project_id,
            )

    async def hybrid_search(
        self,
        table_name: str,
        query: str,
        query_vector: List[float],
        vector_column_name: str,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
        reranker: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """Perform hybrid search combining vector and FTS.

        Args:
            table_name: Name of the table to search
            query: Search query string
            query_vector: Query vector for similarity search
            vector_column_name: Name of the vector column
            limit: Maximum number of results
            filters: Optional additional filters
            project_id: Project ID to filter by
            reranker: Optional reranker for result fusion

        Returns:
            List of matching records
        """
        with self._metrics.track_latency("db.hybrid_search"):
            return await self._query_builder.hybrid_search(
                table_name=table_name,
                query=query,
                query_vector=query_vector,
                vector_column_name=vector_column_name,
                limit=limit,
                filters=filters,
                project_id=project_id,
                reranker=reranker,
            )

    async def advanced_filter(
        self,
        table_name: str,
        filters: Optional[Union[Dict[str, Any], "Filter"]] = None,
        limit: Optional[int] = 100,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> List[Dict[str, Any]]:
        """Query with advanced filtering.

        Args:
            table_name: Name of the table to query
            filters: Filter conditions (dict or Filter AST)
            limit: Maximum number of results
            project_id: Project ID to filter by

        Returns:
            List of matching records
        """
        with self._metrics.track_latency("db.advanced_filter"):
            return await self._query_builder.advanced_filter(
                table_name=table_name,
                filters=filters,
                limit=limit if limit is not None else 100,
                project_id=project_id,
            )

    async def query_raw(
        self,
        table_name: str,
        filters: Optional[Union[Dict[str, Any], "Filter"]] = None,
        limit: int = 100,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> List[Dict[str, Any]]:
        """Query returning raw dictionaries.

        Alias for advanced_filter that provides a consistent interface
        for components that need dict results.

        Args:
            table_name: Name of the table to query
            filters: Filter conditions (dict or Filter AST)
            limit: Maximum number of results
            project_id: Project ID to filter by

        Returns:
            List of matching records as dictionaries
        """
        return await self.advanced_filter(
            table_name=table_name,
            filters=filters,
            limit=limit,
            project_id=project_id,
        )

    async def query_entities(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> List[Dict[str, Any]]:
        """Query graph entities.

        Args:
            filters: Optional filter conditions
            limit: Maximum number of results
            project_id: Project ID to filter by

        Returns:
            List of matching graph entities
        """
        with self._metrics.track_latency("db.query_entities"):
            return await self._query_builder.query_entities(
                filters=filters,
                limit=limit,
                project_id=project_id,
            )

    async def query_relationships(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> List[Dict[str, Any]]:
        """Query graph relationships.

        Args:
            filters: Optional filter conditions
            limit: Maximum number of results
            project_id: Project ID to filter by

        Returns:
            List of matching graph relationships
        """
        with self._metrics.track_latency("db.query_relationships"):
            return await self._query_builder.query_relationships(
                filters=filters,
                limit=limit,
                project_id=project_id,
            )

    async def list_tables(self) -> List[str]:
        """List all tables in the database.

        Returns:
            List of table names
        """
        return await self._table_manager.list_tables()

    async def get_graph_entities(
        self, project_id: str, limit: Optional[int] = None
    ) -> List[Any]:
        """Get all graph entities for a project.

        Args:
            project_id: Project ID to filter by
            limit: Optional limit on number of entities to return

        Returns:
            List of GraphEntity objects
        """
        from agentic_inquiry.models.graph_entity import GraphEntity

        # Query entities for the project
        results = await self.query_entities(
            filters={"project_id": project_id},
            limit=limit or 10000,
            project_id=project_id,
        )

        # Convert dict results to GraphEntity objects
        entities = []
        for result in results:
            try:
                entity = GraphEntity(
                    id=result["id"],
                    name=result["name"],
                    type=result["type"],
                    file_path=result["file_path"],
                    doc_id=result["doc_id"],
                    project_id=result["project_id"],
                    vector=result.get("vector", []),
                    pagerank=result.get("pagerank", 0.0),
                )
                entities.append(entity)
            except (KeyError, TypeError) as e:
                logger.warning("Failed to convert entity result to GraphEntity: %s", e)
                continue

        return entities

    async def get_graph_relationships(
        self, project_id: str, limit: Optional[int] = None
    ) -> List[Any]:
        """Get all graph relationships for a project.

        Args:
            project_id: Project ID to filter by
            limit: Optional limit on number of relationships to return

        Returns:
            List of GraphRelationship objects
        """
        from agentic_inquiry.models.graph_relationship import GraphRelationship

        # Query relationships for the project
        results = await self.query_relationships(
            filters={"project_id": project_id},
            limit=limit or 10000,
            project_id=project_id,
        )

        # Convert dict results to GraphRelationship objects
        relationships = []
        for result in results:
            try:
                relationship = GraphRelationship(
                    id=result["id"],
                    source_id=result["source_id"],
                    target_id=result["target_id"],
                    type=result["type"],
                    project_id=result["project_id"],
                    vector=result.get("vector", []),
                )
                relationships.append(relationship)
            except (KeyError, TypeError) as e:
                logger.warning(
                    "Failed to convert relationship result to GraphRelationship: %s", e
                )
                continue

        return relationships

    async def upsert(
        self,
        table_name: str,
        data: List[Dict[str, Any]],
        key_field: str = "id",
    ) -> None:
        """Insert or update records in a table.

        Checks if records exist by key_field and updates if found, inserts if not.

        Args:
            table_name: Name of the table to upsert into
            data: List of records to upsert
            key_field: Field name to use for uniqueness check (default: "id")

        Performance Notes:
            - This method checks existence for each record individually
            - For large batches, consider using batch operations if available
            - Empty data list is handled gracefully (no-op)

        Examples:
            # Upsert sessions
            await db.upsert(
                table_name="mcp_sessions",
                data=[{
                    "id": "session_123",
                    "session_id": "session_123",
                    "project_id": "proj_1",
                    "state": "active"
                }],
                key_field="session_id"
            )

            # Upsert multiple entities
            await db.upsert(
                table_name="graph_entities",
                data=[
                    {"id": "e1", "name": "Foo", "type": "class"},
                    {"id": "e2", "name": "Bar", "type": "function"}
                ]
            )
        """
        if not data:
            return

        # Separate records into updates and inserts
        to_insert = []
        to_delete_ids = []

        for record in data:
            key_value = record.get(key_field)
            if not key_value:
                # No key value, treat as insert
                to_insert.append(record)
                continue

            # Check if record exists
            existing = await self.advanced_filter(
                table_name=table_name,
                filters={key_field: key_value},
                limit=1,
                project_id=None,  # Don't filter by project for existence check
            )

            if existing:
                # Record exists - mark for deletion and re-insert
                # Use the 'id' field for deletion (standard primary key)
                existing_id = existing[0].get("id")
                if existing_id:
                    to_delete_ids.append(existing_id)
                to_insert.append(record)
            else:
                # Record doesn't exist, insert it
                to_insert.append(record)

        # Delete existing records first
        if to_delete_ids:
            await self._delete_rows(table_name=table_name, ids=to_delete_ids)

        # Insert all records (both new and updated)
        if to_insert:
            await self._add_rows(table_name=table_name, items=to_insert)

    async def delete_by_ids(
        self,
        table_name: str,
        ids: List[str],
    ) -> None:
        """Delete records from a table by their IDs.

        Public API for deleting records. Used by memory layers and other
        components that need to remove specific records by ID.

        Args:
            table_name: Name of the table to delete from
            ids: List of record IDs to delete

        Notes:
            - Empty ids list is handled gracefully (no-op)
            - Non-existent IDs are silently ignored
            - Uses the 'id' field for deletion (standard primary key)

        Examples:
            # Delete single memory item
            await db.delete_by_ids("semantic_memory", ["mem_123"])

            # Delete multiple items
            await db.delete_by_ids("episodic_memory", ["mem_1", "mem_2", "mem_3"])
        """
        await self._delete_rows(table_name=table_name, ids=ids)

    async def update_by_ids(
        self,
        table_name: str,
        ids: List[str],
        values: Dict[str, Any],
    ) -> int:
        """Set columns on the rows with the given IDs in one commit.

        Only the named columns change and no row is deleted or inserted, so
        concurrent writers that touch other columns of the same row cannot
        overwrite each other or leave a duplicate row behind.

        Args:
            table_name: Name of the table to update
            ids: IDs of the rows to update
            values: Column name to new value

        Returns:
            Number of rows updated (0 when the table or IDs do not exist)
        """
        if not ids or not values:
            return 0

        table = await self._get_table_async(table_name)
        if table is None:
            return 0

        clause = format_in_clause("id", ids)
        if clause is None:
            return 0

        rows_updated = 0

        async def _do_write() -> None:
            nonlocal rows_updated
            result = await self._run_sync(lambda: table.update(where=clause, values=values))
            rows_updated = result.rows_updated

        async with self._locked(table_name):
            await _retry_lancedb_write(_do_write)
        return rows_updated

    async def add_rows(
        self,
        table_name: str,
        items: List[Dict[str, Any]],
    ) -> None:
        """Add rows to a table, creating the table if it doesn't exist.

        Public API for adding records. Used by memory layers and other
        components that need to insert new records.

        Args:
            table_name: Name of the table to add rows to
            items: List of records to add (as dictionaries)

        Notes:
            - Empty items list is handled gracefully (no-op)
            - Table is created on first write with inferred schema
            - For update operations, use upsert() instead

        Examples:
            # Add memory items
            await db.add_rows("semantic_memory", [
                {"id": "mem_1", "content": "fact 1", "vector": [0.1, 0.2, ...]},
                {"id": "mem_2", "content": "fact 2", "vector": [0.3, 0.4, ...]}
            ])
        """
        await self._add_rows(table_name=table_name, items=items)

    async def count_records(
        self,
        table_name: str,
        filters: "Optional[FilterInput]" = None,
        project_id: Optional[str] = None,
    ) -> int:
        """Count records in a table efficiently without loading all data.

        This method provides an optimized way to count records that match
        specific criteria without loading the full dataset into memory.
        It's significantly faster than loading all records and counting them,
        especially for large tables.

        Performance Notes:
            - Uses pandas for efficient counting when available
            - Falls back to loading records if pandas is not installed
            - Applies filters at the database level
            - Suitable for tables with millions of records

        Args:
            table_name: Name of the table to count records in
            filters: Optional filter expressions to apply before counting.
                    Same format as advanced_filter() method.
            project_id: Optional project ID to filter by. If provided,
                       adds project_id filter automatically.

        Returns:
            Integer count of matching records

        Raises:
            ValueError: If table doesn't exist
            Exception: If count operation fails

        Example:
            >>> # Count all chunks in a project
            >>> count = await db_manager.count_records(
            ...     "document_chunks",
            ...     filters={"project_id": "my-project"}
            ... )
            >>> print(f"Total chunks: {count}")

            >>> # Count entities of a specific type
            >>> count = await db_manager.count_records(
            ...     "graph_entities",
            ...     filters={"type": "function"},
            ...     project_id="my-project"
            ... )
        """
        with self._metrics.track_latency(f"db.count_records.{table_name}"):
            try:
                # Get table
                table = await self._get_table_async(table_name)

                # Handle case where table doesn't exist yet (no data written)
                if table is None:
                    logger.debug(
                        "Table %s doesn't exist yet, returning count 0", table_name
                    )
                    return 0

                # Build filter expression
                filter_expr = None
                if filters or project_id:
                    # Filter can be a dict (legacy shape) or a Filter AST. For
                    # AST inputs combine via ``and_(eq("project_id", ...), …)``
                    # so the project-scope clause runs through the canonical
                    # SQL-escaping path (translate_filter doubles single
                    # quotes) instead of being hand-interpolated.
                    from agentic_inquiry.database.filters import Filter, and_, eq

                    if isinstance(filters, Filter):
                        combined_ast: Filter = (
                            and_(eq("project_id", project_id), filters)
                            if project_id
                            else filters
                        )
                        filter_expr = self._filters_to_expression(combined_ast)
                    else:
                        combined_filters = filters.copy() if filters else {}
                        if project_id:
                            combined_filters = (
                                self._add_project_filter(combined_filters, project_id)
                                or {}
                            )
                        if combined_filters:
                            filter_expr = self._filters_to_expression(combined_filters)

                # Try to use pandas for efficient counting
                try:
                    import pandas as pd  # noqa: F401 - import needed for .to_pandas()

                    # Execute count query using pandas
                    if filter_expr:
                        # Count with filters - use count_rows with filter for efficiency
                        # Note: table.count_rows(filter_expr) is more efficient than
                        # loading all records into pandas and counting them
                        count = await asyncio.to_thread(
                            lambda: table.count_rows(filter=filter_expr)
                        )
                    else:
                        # Count all records - use LanceDB's count_rows for best performance
                        count = await asyncio.to_thread(lambda: table.count_rows())

                    logger.debug(
                        "Counted %d records in %s (filters=%s, project_id=%s)",
                        count,
                        table_name,
                        bool(filters),
                        project_id,
                    )

                    return count

                except ImportError:
                    # Pandas not available, use fallback
                    logger.warning(
                        "pandas not installed, using fallback counting method. "
                        "Install pandas for better performance: uv add pandas"
                    )

                    # Fallback: load records and count them
                    # This is slower but works without pandas
                    results = await self.advanced_filter(
                        table_name=table_name,
                        filters=filters,
                        limit=None,  # Load all matching records
                        project_id=project_id,
                    )
                    count = len(results)

                    logger.debug(
                        "Counted %d records in %s using fallback (filters=%s, project_id=%s)",
                        count,
                        table_name,
                        bool(filters),
                        project_id,
                    )

                    return count

            except Exception as e:
                logger.error("Error counting records in %s: %s", table_name, e)
                raise

    async def query_across_projects(
        self,
        table_name: str,
        filters: Dict[str, Any],
        limit: int = 100,
        project_ids: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Query across projects with optional project filtering.

        Args:
            table_name: Name of the table to query
            filters: Filter conditions
            limit: Maximum number of results
            project_ids: Optional list of project IDs to filter by.
                         If None, queries all projects.

        Returns:
            List of matching records
        """
        # Add project_id filter if specific projects requested
        if project_ids:
            filters = dict(filters) if filters else {}
            filters["project_id"] = project_ids

        with self._metrics.track_latency("db.query_across_projects"):
            return await self._query_builder.query_across_projects(
                table_name=table_name,
                filters=filters,
                limit=limit,
            )

    async def vector_search_across_projects(
        self,
        table_name: str,
        query_vector: List[float],
        vector_column_name: str,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Perform vector search across all projects.

        Args:
            table_name: Name of the table to search
            query_vector: Query embedding vector
            vector_column_name: Name of the vector column
            limit: Maximum number of results
            filters: Optional filters to apply

        Returns:
            List of matching records
        """
        with self._metrics.track_latency("db.vector_search_across_projects"):
            return await self._query_builder.vector_search_across_projects(
                table_name=table_name,
                query_vector=query_vector,
                vector_column_name=vector_column_name,
                limit=limit,
                filters=filters,
            )

    async def fts_search_across_projects(
        self,
        table_name: str,
        query: str,
        limit: int,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Perform FTS search across all projects.

        Args:
            table_name: Name of the table to search
            query: Search query string
            limit: Maximum number of results
            filters: Optional filters to apply

        Returns:
            List of matching records
        """
        with self._metrics.track_latency("db.fts_search_across_projects"):
            return await self._query_builder.fts_search_across_projects(
                table_name=table_name,
                query=query,
                limit=limit,
                filters=filters,
            )

    async def _add_rows(
        self, table_name: str, items: Iterable[Any], ensure_commit: bool = True
    ) -> None:
        """Add rows to a table with optional commit guarantee.

        Args:
            table_name: Name of the table
            items: Items to add
            ensure_commit: Accepted for interface compatibility. LanceDB commits
                the write before this call returns; nothing further runs.

        Raises:
            StorageError: If database operation fails with suggested remediation
        """
        from agentic_inquiry.exceptions import StorageError

        try:
            rows = [self._normalise_item(item) for item in items]
            if not rows:
                return

            # Validate records against schema requirements before write
            for row in rows:
                self._validate_record(table_name, row)

            table, created = await self._get_or_create_table(table_name, rows)
            if created:
                return

            async def _do_write() -> None:
                await self._run_sync(lambda: table.add(rows))

            async with self._locked(table_name):
                await _retry_lancedb_write(_do_write)

        except Exception as e:
            # Provide helpful error message with operation context
            error_msg = (
                f"Database operation failed: add_rows to table '{table_name}'. "
                f"Error: {str(e)}"
            )

            # Add specific suggestions based on error type
            if "table" in str(e).lower() and "not found" in str(e).lower():
                error_msg += (
                    "\n\nSuggestion: Table may not exist or may have been deleted. "
                    "Try recreating the table or check database initialization."
                )
            elif "schema" in str(e).lower() or "column" in str(e).lower():
                error_msg += (
                    "\n\nSuggestion: Data schema may not match table schema. "
                    "Verify that all required fields are present and have correct types."
                )
            elif "permission" in str(e).lower() or "access" in str(e).lower():
                error_msg += (
                    "\n\nSuggestion: Check database file permissions and ensure "
                    "the process has write access to the storage directory."
                )
            elif "disk" in str(e).lower() or "space" in str(e).lower():
                error_msg += (
                    "\n\nSuggestion: Check available disk space. "
                    "The database may need more storage space."
                )
            else:
                error_msg += (
                    "\n\nSuggestion: Check database connection and ensure "
                    "the storage directory is accessible and writable."
                )

            raise StorageError(error_msg) from e

    async def _upsert_rows(
        self,
        table_name: str,
        items: Iterable[Any],
        key_column: Union[str, List[str]] = "id",
        ensure_commit: bool = True,
    ) -> None:
        """Upsert rows to a table using merge_insert.

        This method performs true upsert behavior: updates existing rows
        and inserts new ones based on the key column(s).

        Args:
            table_name: Name of the table
            items: Items to upsert
            key_column: Column(s) to use for matching existing rows (default: "id").
                       Can be a string for single column or list of strings for
                       composite key (e.g., ["id", "project_id"]).
            ensure_commit: Accepted for interface compatibility. LanceDB commits
                the write before this call returns; nothing further runs.

        Raises:
            StorageError: If database operation fails with suggested remediation
        """
        from agentic_inquiry.exceptions import StorageError

        try:
            rows = [self._normalise_item(item) for item in items]
            if not rows:
                return

            # Strip branch-indexing fields not yet in LanceDB schema
            for row in rows:
                for field in BRANCH_INDEXING_FIELDS:
                    row.pop(field, None)

            # Validate records against schema requirements before write
            for row in rows:
                self._validate_record(table_name, row)

            rows, collapsed = _collapse_duplicate_merge_keys(rows, key_column)
            if collapsed:
                logger.info(
                    "Collapsed %d duplicate merge-key row(s) before upsert into %s",
                    collapsed,
                    table_name,
                )

            table, created = await self._get_or_create_table(table_name, rows)
            if created:
                # Table was just created with the data, no need to upsert
                return

            def _do_upsert() -> None:
                (
                    table.merge_insert(key_column)
                    .when_matched_update_all()
                    .when_not_matched_insert_all()
                    .execute(rows)
                )

            async def _do_write() -> None:
                await self._run_sync(_do_upsert)

            async with self._locked(table_name):
                await _retry_lancedb_write(_do_write)

        except Exception as e:
            # Provide helpful error message with operation context
            error_msg = (
                f"Database operation failed: upsert_rows to table '{table_name}'. "
                f"Error: {str(e)}"
            )

            if "table" in str(e).lower() and "not found" in str(e).lower():
                error_msg += (
                    "\n\nSuggestion: Table may not exist or may have been deleted. "
                    "Try recreating the table or check database initialization."
                )
            elif "schema" in str(e).lower() or "column" in str(e).lower():
                error_msg += (
                    "\n\nSuggestion: Data schema may not match table schema. "
                    "Verify that all required fields are present and have correct types."
                )
            else:
                error_msg += (
                    "\n\nSuggestion: Check database connection and ensure "
                    "the storage directory is accessible and writable."
                )

            raise StorageError(error_msg) from e

    async def _delete_rows(self, table_name: str, ids: List[str]) -> None:
        if not ids:
            return

        table = await self._get_table_async(table_name)
        if table is None:
            return

        clause = format_in_clause("id", ids)
        if clause is None:
            return
        async with self._locked(table_name):
            await self._run_sync(lambda: table.delete(clause))

    async def get_table(self, table_name: str) -> Optional[Any]:
        """Open a table by name, or ``None`` if it doesn't exist yet.

        The provider-level ``entity_vector_search`` / relationship
        traversal paths both need direct table handles — this is the
        public entry point. Earlier code used a ``get_table`` call that
        didn't actually exist on the manager (so those call sites were
        latent bugs); promoting this method closes the mismatch.
        """
        return await self._table_manager.get_table(table_name)

    async def create_table_from_schema(self, table_name: str, schema: Any) -> None:
        """Create ``table_name`` from ``schema`` when it does not already exist."""
        await self._table_manager.create_table_from_schema(table_name, schema)

    # Kept as an alias so internal callers that predate the public
    # ``get_table`` don't need updating in lockstep. New code should
    # prefer the public form.
    _get_table_async = get_table

    async def _get_or_create_table(
        self,
        table_name: str,
        rows: List[Dict[str, Any]],
    ) -> tuple[Any, bool]:
        """Get a table or create it if it doesn't exist.

        Delegates to TableManager for table operations.

        Args:
            table_name: Name of the table
            rows: Initial rows for table creation (used for schema inference)

        Returns:
            Tuple of (table, created) where created is True if table was created
        """
        return await self._table_manager.get_or_create_table(table_name, rows)

    # Connection and index methods are now handled by ConnectionManager and TableManager.
    # The following methods are kept as thin wrappers for backward compatibility with
    # code that depends on these internal methods (query_builder, schema_manager).

    def _add_project_filter(
        self,
        filters: Optional[Dict[str, Any]],
        project_id: Optional[str] = CURRENT_PROJECT_ID,
    ) -> Optional[Dict[str, Any]]:
        """Add project_id filter to existing filters.

        Args:
            filters: Existing filter dictionary
            project_id: Project ID to filter by. Use CURRENT_PROJECT_ID for configured project,
                       specific ID for single project, or None for all projects.

        Returns:
            Updated filters dictionary with project_id filter added
        """
        # If project_id is None, search all projects (no filter)
        if project_id is None:
            return filters

        # If project_id is CURRENT_PROJECT_ID, use the configured project_id
        if project_id == CURRENT_PROJECT_ID:
            if self._project_id is None:
                # No project_id configured, don't filter
                return filters
            project_id = self._project_id

        # Add project_id filter
        project_filter = {"project_id": project_id}

        if filters is None:
            return project_filter

        # Merge with existing filters
        return {**filters, **project_filter}

    def _filters_to_expression(self, filters: "Optional[FilterInput]") -> Optional[str]:
        """Convert dict filters or a Filter AST to a LanceDB SQL expression.

        Delegates through :class:`LanceDBFilterAdapter` so both legacy dicts
        and the canonical AST share the same backend translation path. A
        ``None`` or empty input yields ``None`` (caller short-circuits the
        WHERE clause).
        """
        from agentic_inquiry.database.filters import LanceDBFilterAdapter

        return LanceDBFilterAdapter().translate(filters)

    def _normalise_item(self, item: Any) -> Dict[str, Any]:
        if hasattr(item, "to_dict"):
            return dict(item.to_dict())
        if hasattr(item, "model_dump"):
            return dict(item.model_dump())
        if isinstance(item, dict):
            return dict(item)
        raise TypeError("Unsupported item type for LanceDB insertion")

    async def _run_sync(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Run a synchronous function in the LanceDB executor.

        Delegates to ConnectionManager for executor management.
        """
        return await self._conn_manager._run_sync(func, *args, **kwargs)

    @asynccontextmanager
    async def _locked(self, table_name: str) -> AsyncIterator[None]:
        """Hold the per-table commit lock, timing the wait separately.

        ``db.table_lock_wait`` in the metrics separates queueing behind
        another commit from the cost of the commit itself.
        """
        lock = self._table_manager.table_lock(table_name)
        with self._metrics.track_latency("db.table_lock_wait"):
            await lock.acquire()
        try:
            yield
        finally:
            lock.release()

    async def compact_tables(
        self,
        table_names: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Compact table files to merge small fragments into larger ones.

        LanceDB creates new data files for every write operation. Over time,
        this leads to thousands of small files, degrading query performance.
        This method runs ``Table.optimize`` with a far-future cleanup window,
        which merges fragments and folds unindexed rows into the indexes
        without pruning versions.

        Note: This improves query performance but does NOT reclaim disk space.
        Call cleanup_old_versions() after compaction to free disk space.

        Args:
            table_names: List of table names to compact. If None, compacts all
                        standard tables (document_chunks, graph_entities,
                        graph_relationships).

        Returns:
            Dict mapping table names to compaction results with keys:
            - fragments_before: Number of fragments before compaction (if available)
            - fragments_after: Number of fragments after compaction (if available)
            - status: 'success', 'skipped', or 'error'
            - error: Error message if status is 'error'
        """
        if table_names is None:
            table_names = list(TABLE_CONFIGS.keys())

        results: Dict[str, Dict[str, Any]] = {}

        def _get_fragment_count(t: Any) -> Optional[int]:
            """Get fragment count using available API methods."""
            # Try different API methods for fragment counting
            if hasattr(t, "list_fragments"):
                try:
                    return len(t.list_fragments())
                except Exception:
                    pass
            if hasattr(t, "count_fragments"):
                try:
                    return t.count_fragments()
                except Exception:
                    pass
            # ``Table.stats()`` returns a dict on lancedb 0.25 and 0.38.
            if hasattr(t, "stats"):
                try:
                    stats = t.stats()
                    if isinstance(stats, dict):
                        return stats["fragment_stats"]["num_fragments"]
                    if hasattr(stats, "num_fragments"):
                        return stats.num_fragments
                except Exception:
                    pass
            return None

        for table_name in table_names:
            try:
                table = await self._get_table_async(table_name)
                if table is None:
                    results[table_name] = {
                        "status": "skipped",
                        "reason": "table does not exist",
                    }
                    continue

                # Counts are read under the same lock as the optimize so
                # concurrent writers cannot skew before/after.
                async with self._locked(table_name):
                    fragments_before = await self._run_sync(
                        lambda t=table: _get_fragment_count(t)
                    )
                    if fragments_before is not None:
                        logger.info(
                            "Compacting table %s (%d fragments)",
                            table_name,
                            fragments_before,
                        )
                    else:
                        logger.info("Compacting table %s", table_name)

                    # ``Table.optimize`` is the only compaction entry point
                    # that works without pylance on lancedb >= 0.26; it also
                    # folds unindexed rows into the indexes. A far-future
                    # cleanup window keeps this step from pruning versions.
                    await self._run_sync(
                        lambda t=table: t.optimize(
                            cleanup_older_than=_NO_VERSION_CLEANUP
                        )
                    )
                    fragments_after = await self._run_sync(
                        lambda t=table: _get_fragment_count(t)
                    )

                result_data: Dict[str, Any] = {"status": "success"}
                if fragments_before is not None:
                    result_data["fragments_before"] = fragments_before
                if fragments_after is not None:
                    result_data["fragments_after"] = fragments_after

                results[table_name] = result_data

                if fragments_before is not None and fragments_after is not None:
                    logger.info(
                        "Compacted table %s: %d → %d fragments",
                        table_name,
                        fragments_before,
                        fragments_after,
                    )
                else:
                    logger.info("Compacted table %s successfully", table_name)

            except Exception as e:
                logger.error("Failed to compact table %s: %s", table_name, e)
                results[table_name] = {
                    "status": "error",
                    "error": str(e),
                }

        return results

    async def compact_table(
        self,
        table_name: str,
        cleanup_older_than: timedelta = timedelta(minutes=5),
    ) -> Dict[str, Any]:
        """Compact a single table and remove its old versions.

        Convenience wrapper around compact_tables() + cleanup_old_versions()
        for operating on one table at a time.  The caller does not need to
        know the correct ordering (compact first, then cleanup).

        Args:
            table_name: Name of the LanceDB table to compact.
            cleanup_older_than: Only remove versions older than this duration.
                Default is 5 minutes.

        Returns:
            Dict with keys:
            - compaction: per-table result from compact_tables()
            - cleanup: per-table result from cleanup_old_versions(), or None
              if compaction failed
            - success: True when both steps succeeded without errors
        """
        compaction_results = await self.compact_tables([table_name])
        compact_result = compaction_results.get(table_name, {})

        cleanup_result = None
        if compact_result.get("status") == "success":
            cleanup_results = await self.cleanup_old_versions(
                [table_name],
                older_than=cleanup_older_than,
            )
            cleanup_result = cleanup_results.get(table_name)

        success = compact_result.get("status") == "success" and (
            cleanup_result is None or cleanup_result.get("status") != "error"
        )
        return {
            "compaction": compact_result,
            "cleanup": cleanup_result,
            "success": success,
        }

    async def cleanup_old_versions(
        self,
        table_names: Optional[List[str]] = None,
        older_than: timedelta = timedelta(minutes=5),
        delete_unverified: bool = False,
    ) -> Dict[str, Dict[str, Any]]:
        """Remove old table versions to reclaim disk space.

        LanceDB uses MVCC (Multi-Version Concurrency Control), creating new
        versions on every write. Old versions are kept for time-travel queries.
        This method runs ``Table.optimize`` with the given window, which also
        compacts fragments and refreshes indexes before pruning, so data from
        old files is merged into new files before those files go away.

        Args:
            table_names: List of table names to clean up. If None, cleans all
                        standard tables.
            older_than: Only remove versions older than this duration.
                       Default is 5 minutes. Use a larger value if you need
                       rollback capability for longer periods.

        Returns:
            Dict mapping table names to cleanup results with keys:
            - versions_before: Number of versions before cleanup
            - versions_after: Number of versions after cleanup
            - status: 'success', 'skipped', or 'error'
            - error: Error message if status is 'error'
        """
        if table_names is None:
            table_names = list(TABLE_CONFIGS.keys())

        results: Dict[str, Dict[str, Any]] = {}

        for table_name in table_names:
            try:
                table = await self._get_table_async(table_name)
                if table is None:
                    results[table_name] = {
                        "status": "skipped",
                        "reason": "table does not exist",
                    }
                    continue

                async with self._locked(table_name):
                    versions_before = await self._run_sync(
                        lambda t=table: len(t.list_versions())
                    )
                    logger.info(
                        "Cleaning up old versions for table %s (%d versions, older_than=%s)",
                        table_name,
                        versions_before,
                        older_than,
                    )
                    # ``Table.optimize`` compacts, refreshes indexes, and
                    # prunes versions older than the window in one call.
                    await self._run_sync(
                        lambda t=table, d=older_than, unverified=delete_unverified: t.optimize(
                            cleanup_older_than=d,
                            delete_unverified=unverified,
                        )
                    )
                    versions_after = await self._run_sync(
                        lambda t=table: len(t.list_versions())
                    )

                results[table_name] = {
                    "status": "success",
                    "versions_before": versions_before,
                    "versions_after": versions_after,
                }
                logger.info(
                    "Cleaned up table %s: %d → %d versions",
                    table_name,
                    versions_before,
                    versions_after,
                )

            except Exception as e:
                logger.error(
                    "Failed to cleanup old versions for table %s: %s",
                    table_name,
                    e,
                )
                results[table_name] = {
                    "status": "error",
                    "error": str(e),
                }

        return results

    async def get_table_statistics(
        self,
        table_names: Optional[List[str]] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Get storage statistics for tables.

        Returns size, version count, and fragment count for specified tables.
        This is useful for monitoring storage usage and planning maintenance.

        Args:
            table_names: List of table names to get stats for. If None, gets stats
                        for all standard tables (document_chunks, graph_entities,
                        graph_relationships).

        Returns:
            Dict mapping table names to statistics with keys:
            - size_bytes: Estimated size in bytes (if available)
            - version_count: Number of MVCC versions
            - fragment_count: Number of data fragments (if available)
            - status: 'success', 'skipped', or 'error'
            - error: Error message if status is 'error'

        Example:
            >>> stats = await manager.get_table_statistics()
            >>> for table, data in stats.items():
            ...     print(f"{table}: {data['size_bytes']} bytes, {data['version_count']} versions")
        """
        if table_names is None:
            table_names = list(TABLE_CONFIGS.keys())

        results: Dict[str, Dict[str, Any]] = {}

        def _get_fragment_count(t: Any) -> Optional[int]:
            """Get fragment count using available API methods."""
            # Try different API methods for fragment counting
            if hasattr(t, "list_fragments"):
                try:
                    return len(t.list_fragments())
                except Exception:
                    pass
            if hasattr(t, "count_fragments"):
                try:
                    return t.count_fragments()
                except Exception:
                    pass
            # ``Table.stats()`` returns a dict on lancedb 0.25 and 0.38.
            if hasattr(t, "stats"):
                try:
                    stats = t.stats()
                    if isinstance(stats, dict):
                        return stats["fragment_stats"]["num_fragments"]
                    if hasattr(stats, "num_fragments"):
                        return stats.num_fragments
                except Exception:
                    pass
            return None

        def _get_size_bytes(t: Any) -> Optional[int]:
            """Get table size in bytes if available."""
            # Try to get size from table stats
            if hasattr(t, "stats"):
                try:
                    stats = t.stats()
                    # LanceDB stats may have num_rows or other size indicators
                    # but not always direct size. Return None if unavailable.
                    if hasattr(stats, "index_size"):
                        return stats.index_size
                except Exception:
                    pass
            return None

        for table_name in table_names:
            try:
                table = await self._get_table_async(table_name)
                if table is None:
                    results[table_name] = {
                        "status": "skipped",
                        "reason": "table does not exist",
                    }
                    continue

                # Get version count
                version_count = await self._run_sync(
                    lambda t=table: len(t.list_versions())
                )

                # Get fragment count (may be None if API unavailable)
                fragment_count = await self._run_sync(
                    lambda t=table: _get_fragment_count(t)
                )

                # Get size in bytes (may be None if unavailable)
                size_bytes = await self._run_sync(lambda t=table: _get_size_bytes(t))

                result_data: Dict[str, Any] = {
                    "status": "success",
                    "version_count": version_count,
                }

                if fragment_count is not None:
                    result_data["fragment_count"] = fragment_count

                if size_bytes is not None:
                    result_data["size_bytes"] = size_bytes

                results[table_name] = result_data

            except Exception as e:
                logger.error("Failed to get statistics for table %s: %s", table_name, e)
                results[table_name] = {
                    "status": "error",
                    "error": str(e),
                }

        return results

    async def run_maintenance(
        self,
        table_names: Optional[List[str]] = None,
        cleanup_older_than: timedelta = timedelta(minutes=5),
    ) -> Dict[str, Any]:
        """Run full maintenance: compact files then cleanup old versions.

        This is the recommended way to manage LanceDB storage. It:
        1. Compacts small files into larger ones (improves query performance)
        2. Removes old versions (reclaims disk space)

        Should be called after bulk indexing operations or periodically
        (e.g., daily) for active databases.

        IDEMPOTENT & SAFE: This operation is safe to call multiple times.
        Re-running after completion or interruption will not corrupt data.
        If compaction fails, cleanup is blocked to prevent data loss
        (FR-2.5, NFR-2.1, NFR-2.3).

        Args:
            table_names: List of table names to maintain. If None, maintains
                        all standard tables.
            cleanup_older_than: Only remove versions older than this duration.
                              Default is 5 minutes.

        Returns:
            Dict with keys:
            - compaction: Results from compact_tables()
            - cleanup: Results from cleanup_old_versions() or None if blocked
            - summary: Overall summary with total space stats
            - compact_success: Whether all compactions succeeded
            - cleanup_success: Whether all cleanups succeeded
            - interrupted: Whether operation was interrupted
        """
        logger.info("Starting database maintenance")

        # Step 1: Compact files (MUST run first - FR-2.5)
        compaction_results = await self.compact_tables(table_names)

        # Step 2: Determine which tables can be safely cleaned up (NFR-2.3)
        # Only clean up tables that successfully compacted to prevent data loss
        tables_to_cleanup = [
            table_name
            for table_name, result in compaction_results.items()
            if result.get("status") == "success"
        ]

        # Track overall success states
        compact_success = all(
            r.get("status") != "error" for r in compaction_results.values()
        )
        cleanup_success = False
        interrupted = False

        # Step 3: Cleanup old versions (only for successfully compacted tables)
        cleanup_results: Dict[str, Any] = {}
        if tables_to_cleanup:
            try:
                cleanup_results = await self.cleanup_old_versions(
                    tables_to_cleanup,
                    older_than=cleanup_older_than,
                )
                cleanup_success = all(
                    r.get("status") != "error" for r in cleanup_results.values()
                )
            except Exception as e:
                logger.error("Cleanup interrupted: %s", e)
                interrupted = True
                cleanup_results = {
                    "status": "error",
                    "error": str(e),
                }

        # Step 4: Mark tables that failed compaction as blocked from cleanup
        for table_name, compact_result in compaction_results.items():
            if (
                compact_result.get("status") == "error"
                and table_name not in cleanup_results
            ):
                cleanup_results[table_name] = {
                    "status": "blocked",
                    "reason": "compaction_failed",
                }
                logger.info(
                    "Cleanup blocked for table %s: compaction failed (FR-2.5, NFR-2.3)",
                    table_name,
                )

        # Build summary
        total_fragments_reduced = sum(
            r.get("fragments_before", 0) - r.get("fragments_after", 0)
            for r in compaction_results.values()
            if r.get("status") == "success"
        )

        # Calculate versions removed (only if cleanup ran successfully)
        total_versions_removed = 0
        if cleanup_results and isinstance(cleanup_results, dict):
            if cleanup_results.get("status") != "blocked":
                # ``Table.optimize`` commits new versions while it prunes,
                # so the difference can be negative; report growth as zero
                # removed rather than a negative count.
                total_versions_removed = sum(
                    max(r.get("versions_before", 0) - r.get("versions_after", 0), 0)
                    for r in cleanup_results.values()
                    if isinstance(r, dict) and r.get("status") == "success"
                )

        logger.info(
            "Maintenance complete: reduced %d fragments, removed %d versions, "
            "compact_success=%s, cleanup_success=%s, interrupted=%s",
            total_fragments_reduced,
            total_versions_removed,
            compact_success,
            cleanup_success,
            interrupted,
        )

        return {
            "compaction": compaction_results,
            "cleanup": cleanup_results,
            "summary": {
                "fragments_reduced": total_fragments_reduced,
                "versions_removed": total_versions_removed,
            },
            "compact_success": compact_success,
            "cleanup_success": cleanup_success,
            "interrupted": interrupted,
        }


class SyncLanceDBManager:
    """Synchronous facade over :class:`LanceDBManager`.

    The adapter owns a private event loop so codebases that are not asyncio aware
    can still leverage the asynchronous implementation. Any coroutine method on
    the wrapped manager is exposed as a blocking counterpart while synchronous
    helpers (such as :meth:`create_sync_table_and_indexes`) are forwarded
    directly.
    """

    def __init__(
        self,
        *args: Any,
        manager: Optional[LanceDBManager] = None,
        **kwargs: Any,
    ) -> None:
        if manager is not None and (args or kwargs):
            raise StorageError(
                "Provide either an existing 'manager' instance or constructor arguments."
            )

        self._loop = asyncio.new_event_loop()
        self._manager = manager or LanceDBManager(*args, **kwargs)

    def __enter__(self) -> "SyncLanceDBManager":
        return self

    def __exit__(
        self, exc_type: Optional[type], exc: Optional[BaseException], tb: Optional[Any]
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the private event loop used for executing coroutines."""

        if not self._loop.is_closed():
            self._loop.close()

    def _run(self, awaitable: Any) -> Any:
        if self._loop.is_closed():
            raise StorageError("The SyncLanceDBManager event loop has been closed.")
        return self._loop.run_until_complete(awaitable)

    def __getattr__(self, item: str):
        attr = getattr(self._manager, item)
        if asyncio.iscoroutinefunction(attr):

            def wrapper(*args, **kwargs):
                return self._run(attr(*args, **kwargs))

            setattr(self, item, wrapper)
            return wrapper
        return attr

    @property
    def async_manager(self) -> LanceDBManager:
        """Expose the underlying asynchronous manager instance."""

        return self._manager

    def __del__(self) -> None:  # pragma: no cover - defensive cleanup
        try:
            self.close()
        except Exception:
            pass
