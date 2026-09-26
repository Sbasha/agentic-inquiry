"""Storage facade - unified interface for storage operations.

This module provides the StorageFacade class that composes vector,
graph, events, and file tracker providers into a single, simple
interface for internal services (SearchService, IndexingPipeline,
MemorySystem).

The facade:
- Composes all four storage providers (vector, graph, events, file_tracker)
- Provides simplified API for common operations
- Handles provider lifecycle (init/close)
- Supports capability detection for optional features
- Uses named backend configurations for flexible deployment

Phase 6: GCP Connectors implementation - Updated to support pluggable backends.
"""
from __future__ import annotations

import dataclasses
import logging
import warnings
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Union, cast, Literal

# Import capability checks
from agentic_inquiry.storage.protocols.vector import (
    has_fts,
    has_graph_ranking,
    has_hybrid_search,
    has_vector_search,
)

# Import canonical TransactionError from storage exceptions
from agentic_inquiry.storage.exceptions import TransactionError

if TYPE_CHECKING:
    from agentic_inquiry.config import Config
    from agentic_inquiry.database.lancedb_manager import LanceDBManager
    from agentic_inquiry.database.results import SearchResult
    from agentic_inquiry.models.document_chunk import DocumentChunk
    from agentic_inquiry.models.graph_entity import GraphEntity
    from agentic_inquiry.models.graph_relationship import GraphRelationship
    from agentic_inquiry.storage.capabilities import ProviderCapabilities
    from agentic_inquiry.storage.protocols.vector import VectorStorageProtocol
    from agentic_inquiry.storage.protocols.graph import GraphStorageProtocol
    from agentic_inquiry.storage.protocols.events import EventStorageProtocol
    from agentic_inquiry.storage.protocols.file_tracker import FileTrackerProtocol
    from agentic_inquiry.storage.pool import BackendPoolManager

logger = logging.getLogger(__name__)


class StorageFacade:
    """Unified facade for storage operations.

    StorageFacade composes vector and graph storage providers into a
    single interface, simplifying access for internal services. It
    handles provider lifecycle and provides capability detection.

    This class is the primary entry point for storage operations in
    Agentic Inquiry. Services should depend on StorageFacade rather than
    directly on providers.

    Example:
        # Create from config (recommended)
        storage = await StorageFacade.from_config(config, "my_project")

        # Vector operations
        results = await storage.vector_search(query_vector, limit=10)
        await storage.upsert_chunks(chunks)

        # Graph operations
        await storage.upsert_entities(entities)
        entities = await storage.get_entities_by_type("function")

        # Lifecycle
        await storage.close()

    Attributes:
        config: Configuration instance
        project_id: Project ID for data isolation
        _vector_provider: Vector storage provider instance
        _graph_provider: Graph storage provider instance
    """

    def __init__(
        self,
        config: "Config",
        project_id: str,
        vector_provider: "VectorStorageProtocol",
        graph_provider: "GraphStorageProtocol",
        events_provider: Optional["EventStorageProtocol"] = None,
        file_tracker_provider: Optional["FileTrackerProtocol"] = None,
        pool_manager: Optional["BackendPoolManager"] = None,
        backend_type: str = "lancedb",
        graph_backend_type: Optional[str] = None,
    ) -> None:
        """Initialize storage facade with providers.

        Args:
            config: Configuration instance
            project_id: Project ID for data isolation
            vector_provider: Provider for vector operations
            graph_provider: Provider for graph operations
            events_provider: Optional provider for event operations
            file_tracker_provider: Optional provider for file tracking
            pool_manager: Optional connection pool manager for shared connections
            backend_type: The vector-role backend type (lancedb, postgresql,
                etc.). Retained as the "primary" type because most callers use
                it to route search behaviour, which is a vector-side concern.
            graph_backend_type: The graph-role backend type. May differ from
                ``backend_type`` in mixed deployments (e.g. vector=LanceDB +
                graph=Postgres). Defaults to ``backend_type`` when omitted,
                preserving the legacy single-backend assumption.
        """
        self._config = config
        self._project_id = project_id
        self._vector_provider = vector_provider
        self._graph_provider = graph_provider
        self._events_provider = events_provider
        self._file_tracker_provider = file_tracker_provider
        self._pool_manager = pool_manager
        self._backend_type = backend_type
        self._graph_backend_type = graph_backend_type or backend_type
        self._initialized = False

    @staticmethod
    def _to_dict(obj: Any) -> Dict[str, Any]:
        """Convert an object to a dict, handling dataclasses, Pydantic models,
        asyncpg Records, and plain dicts.
        """
        if isinstance(obj, dict):
            return obj
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
            return dataclasses.asdict(obj)
        # asyncpg.Record and similar mapping types
        if hasattr(obj, "keys"):
            return dict(obj)
        return vars(obj)

    @classmethod
    async def from_config(
        cls,
        config: "Config",
        project_id: str,
        provider_name: str = "",
    ) -> "StorageFacade":
        """Create facade from configuration.

        Requires the registry-based config shape: ``config.storage.backends``
        must be a dict of named backend configs with
        ``config.storage.vector_backend`` / ``config.storage.graph_backend``
        naming the active roles. ``ai setup`` emits this shape; the legacy
        single-``storage.backend``-string path was removed so the graph and
        vector roles can be served by genuinely different backends (for
        example Postgres + LanceDB today, or planned pairings like Neptune
        + OpenSearch) without one provider pretending to implement both
        protocols.

        Args:
            config: Configuration instance.
            project_id: Project ID for data isolation.
            provider_name: Retained for signature compatibility with
                external callers — ignored. Kept to avoid breaking users
                who were passing it explicitly before.

        Returns:
            Initialized StorageFacade instance.

        Raises:
            ConfigurationError: If ``config.storage.backends`` is not set.
            BackendResolutionError: If backend configuration is invalid.
            ConnectionError: If provider initialization fails.
        """
        from agentic_inquiry.exceptions import ConfigurationError
        from agentic_inquiry.storage.pool import BackendPoolManager
        from agentic_inquiry.storage.registry import (
            BackendResolutionError,
            create_provider,
            resolve_backend,
        )

        # ``provider_name`` is accepted for signature stability but no longer
        # influences backend resolution. Emit BOTH a ``DeprecationWarning``
        # (so external test suites running with ``-W error::DeprecationWarning``
        # notice) AND a log warning (so it's visible in production logs
        # where warnings filters may be silenced).
        if provider_name:
            deprecation_message = (
                f"StorageFacade.from_config(provider_name={provider_name!r}) "
                "is ignored; storage backends are now resolved exclusively "
                "through config.storage.backends / vector_backend / "
                "graph_backend. Run `ai setup` to update your config if needed."
            )
            warnings.warn(deprecation_message, DeprecationWarning, stacklevel=2)
            logger.warning("%s", deprecation_message)

        storage_config = config.storage

        # ``not backends`` catches both ``None`` (unset) and ``{}`` (explicitly
        # empty). The target shape is always the registry one — legacy
        # single-provider dispatch inside this method is gone.
        #
        # Programmatic callers (test fixtures, internal scripts) often still
        # build ``StorageConfig(backend="lancedb")`` without populating
        # ``backends`` / role pointers. For those we auto-migrate the legacy
        # shape into an equivalent registry config plus a ``DeprecationWarning``
        # — the registry path is still what actually executes, so the PR's
        # architectural goal (kill same-provider-both-roles fallback inside
        # facade.py) holds. Only truly empty configs still fail loud with the
        # ``ai setup`` pointer.
        if not storage_config.backends:
            legacy_backend = getattr(storage_config, "backend", "") or ""
            if legacy_backend:
                migration_message = (
                    f"StorageConfig(backend={legacy_backend!r}) without "
                    "`backends` is deprecated; synthesizing the registry "
                    "config on the fly. Populate `storage.backends` plus "
                    "`vector_backend` / `graph_backend` pointers (see "
                    "`ai setup` output) to silence this warning."
                )
                warnings.warn(migration_message, DeprecationWarning, stacklevel=2)
                logger.warning("%s", migration_message)

                # Synthesize a registry-shaped config. ``database_path`` is
                # only added for file-based backends (lancedb / sqlite) that
                # actually consume it — memory / postgresql / etc. reject it.
                _FILE_BASED_TYPES = {"lancedb", "sqlite"}

                def _file_backed_cfg(backend_type: str, path: str) -> Dict[str, Any]:
                    cfg: Dict[str, Any] = {"type": backend_type}
                    if backend_type in _FILE_BASED_TYPES:
                        cfg["database_path"] = path
                    return cfg

                synthesized_backends: Dict[str, Dict[str, Any]] = {
                    legacy_backend: _file_backed_cfg(
                        legacy_backend,
                        str(storage_config.get_lancedb_path()),
                    )
                }
                # Optional roles default to separate sqlite backends in
                # StorageConfig; keep that shape so events / file_tracker
                # resolve the same way they did before.
                event_backend_type = storage_config.event_store_backend or "sqlite"
                synthesized_backends.setdefault(
                    "events_store",
                    _file_backed_cfg(
                        event_backend_type,
                        str(storage_config.get_event_store_path()),
                    ),
                )
                tracker_backend_type = storage_config.file_tracker_backend or "sqlite"
                synthesized_backends.setdefault(
                    "file_tracker",
                    _file_backed_cfg(
                        tracker_backend_type,
                        str(storage_config.get_file_tracker_path()),
                    ),
                )
                storage_config = dataclasses.replace(
                    storage_config,
                    backends=synthesized_backends,
                    vector_backend=legacy_backend,
                    graph_backend=legacy_backend,
                    events_backend="events_store",
                    file_tracker_backend_v2="file_tracker",
                )
            else:
                raise ConfigurationError(
                    "No storage backends configured. Run `ai setup` to "
                    "generate a config, or populate `storage.backends` with at "
                    "least one named backend plus `storage.vector_backend` / "
                    "`storage.graph_backend` pointers. The legacy single-"
                    "`storage.backend` shape is no longer supported."
                )

        pool_manager: Optional["BackendPoolManager"] = None

        # Pooled backend types — keep aligned with ``BackendPoolManager._create_pool``
        # (pool.py handles these via asyncpg / Spanner / Cloud SQL pools).
        # Note: the allocated ``BackendPoolManager`` is **not currently wired
        # through to providers** — ``storage.registry.create_provider`` never
        # passes ``pool_manager`` to providers on either dispatch path
        # (sync ``from_config`` receives only the backend-config dict +
        # ``project_id``; direct ``__init__`` explicitly strips it). Each
        # provider still creates its own connection. ``type`` behaves
        # differently: it stays in the dict on the sync ``from_config``
        # path because Postgres-family providers dispatch on it to pick an
        # adapter, and only gets stripped on the direct ``__init__`` path
        # where constructors don't accept it. The pool manager is scaffolding
        # for a follow-up that plumbs it into provider construction; today
        # its only effect is centralised close-all on facade teardown.
        # Allocation is kept so that follow-up can hook in without changing
        # this surface.
        # Tracked: https://github.com/sbasha/agentic_inquiry/issues/131
        pooled_backend_types: tuple[str, ...] = ()
        needs_pool = False
        for role_str in ["vector", "graph", "events", "file_tracker"]:
            try:
                role = cast(
                    Literal["vector", "graph", "events", "file_tracker"],
                    role_str,
                )
                _, backend_config = resolve_backend(storage_config, role)
                if backend_config.get("type") in pooled_backend_types:
                    needs_pool = True
                    break
            except BackendResolutionError:
                continue  # Role not configured, skip

        if needs_pool:
            pool_manager = BackendPoolManager()

        # Create providers for each role
        try:
            vector_provider = create_provider(
                storage_config,
                "vector",
                project_id=project_id,
                pool_manager=pool_manager,
                config=config,
            )
        except BackendResolutionError as e:
            logger.error("Failed to resolve vector backend: %s", e)
            raise

        try:
            graph_provider = create_provider(
                storage_config,
                "graph",
                project_id=project_id,
                pool_manager=pool_manager,
                config=config,
            )
        except BackendResolutionError as e:
            logger.error("Failed to resolve graph backend: %s", e)
            raise

        # Optional providers
        events_provider = None
        try:
            events_provider = create_provider(
                storage_config,
                "events",
                project_id=project_id,
                pool_manager=pool_manager,
                config=config,
            )
        except BackendResolutionError:
            logger.debug("No events backend configured, skipping")

        file_tracker_provider = None
        try:
            file_tracker_provider = create_provider(
                storage_config,
                "file_tracker",
                project_id=project_id,
                pool_manager=pool_manager,
                config=config,
            )
        except BackendResolutionError:
            logger.debug("No file_tracker backend configured, skipping")

        # Detect backend type per role. ``_backend_type`` stays vector-derived
        # so existing callers routing on ``get_backend_type()`` (search
        # services, persistence backends — see agentic_inquiry/mcp/tools/search.py,
        # agentic_inquiry/mcp/services/context_builder.py) keep the
        # vector-store-centric semantics they already depend on.
        # ``_graph_backend_type`` is tracked separately so mixed deployments
        # (e.g. LanceDB vectors + Postgres graph) can surface a pg-compatible
        # graph via ``get_connection_manager`` even though the vector side is
        # not pg-compatible.
        _, vector_backend_config = resolve_backend(storage_config, "vector")
        detected_backend_type = vector_backend_config.get("type", "lancedb")
        try:
            _, graph_backend_config = resolve_backend(storage_config, "graph")
            graph_backend_type = graph_backend_config.get("type", detected_backend_type)
        except BackendResolutionError:
            graph_backend_type = detected_backend_type

        facade = cls(
            config=config,
            project_id=project_id,
            vector_provider=vector_provider,
            graph_provider=graph_provider,
            events_provider=events_provider,
            file_tracker_provider=file_tracker_provider,
            pool_manager=pool_manager,
            backend_type=detected_backend_type,
            graph_backend_type=graph_backend_type,
        )

        await facade.initialize()
        return facade

    async def initialize(self) -> None:
        """Initialize all providers.

        This method is idempotent - calling it multiple times
        has the same effect as calling it once.
        """
        if self._initialized:
            return

        logger.info("Initializing StorageFacade for project %s", self._project_id)

        await self._vector_provider.initialize()

        # Only initialize graph provider if different from vector provider
        if self._graph_provider is not self._vector_provider:
            await self._graph_provider.initialize()

        # Initialize optional providers if configured
        if self._events_provider:
            await self._events_provider.initialize()

        if self._file_tracker_provider:
            await self._file_tracker_provider.initialize()

        self._initialized = True

    async def generate_embeddings(self) -> Dict[str, Any]:
        """Generate server-side embeddings for chunks and entities.

        Delegates to the vector and graph providers' generate_embeddings()
        methods. Only meaningful for server-side embedding backends (AlloyDB).

        Returns:
            Combined diagnostics from both providers.
        """
        results: Dict[str, Any] = {}

        if hasattr(self._vector_provider, "generate_embeddings"):
            logger.info("Generating server-side chunk embeddings...")
            results["chunks"] = await self._vector_provider.generate_embeddings()

        if hasattr(self._graph_provider, "generate_embeddings"):
            logger.info("Generating server-side entity embeddings...")
            results["entities"] = await self._graph_provider.generate_embeddings()

        return results

    async def close(self) -> None:
        """Close all providers and release resources.

        This method should be called during graceful shutdown.
        It is idempotent.
        """
        if not self._initialized:
            return

        logger.info("Closing StorageFacade for project %s", self._project_id)

        await self._vector_provider.close()

        # Only close graph provider if different from vector provider
        if self._graph_provider is not self._vector_provider:
            await self._graph_provider.close()

        # Close optional providers if configured
        if self._events_provider:
            await self._events_provider.close()

        if self._file_tracker_provider:
            await self._file_tracker_provider.close()

        # Close pool manager if configured. Use ``close_all()`` rather than
        # ``close(self._backend_type)``: pool keys are backend *names* (e.g.
        # ``"primary"``) from ``storage.backends``, not backend *types* (e.g.
        # ``"postgresql"``). Passing the type silently found no match and
        # leaked any registered pools. ``close_all`` is idempotent and is the
        # right shape whether or not any pool was actually registered.
        if self._pool_manager:
            await self._pool_manager.close_all()

        self._initialized = False

    # =========================================================================
    # Transaction Management (FR-2, AC-4, AC-5)
    # =========================================================================

    def transaction(self, timeout: Optional[float] = None):
        """Create a transaction context for atomic multi-provider operations.

        This method implements FR-2.1: Cross-provider transaction atomicity.
        It creates a TransactionCoordinator that manages BEGIN/COMMIT/ROLLBACK
        across both VectorProvider and GraphProvider.

        Usage:
            >>> async with storage.transaction() as txn:
            ...     await txn.store_chunks(chunks)
            ...     await txn.store_relationships(relationships)
            ...     # Auto-commits on success, rolls back on exception

        Args:
            timeout: Connection acquisition timeout in seconds. If None, uses
                config.storage.backend_timeouts.transaction_timeout (default: 30.0)

        Returns:
            Async context manager yielding TransactionCoordinator

        Raises:
            TransactionError: If providers don't support transactions
            PoolExhaustedError: If connection pool is exhausted

        Example:
            >>> # Atomic multi-provider operation
            >>> async with storage.transaction() as txn:
            ...     await txn.store_chunks([chunk1, chunk2])
            ...     await txn.store_relationships([rel1, rel2])
            ...
            >>> # Automatic rollback on failure (AC-4, AC-5)
            >>> try:
            ...     async with storage.transaction() as txn:
            ...         await txn.store_chunks(chunks)
            ...         raise ValueError("Simulated failure")
            ... except ValueError:
            ...     pass  # Transaction rolled back automatically
        """
        # Resolve timeout from config if not provided
        if timeout is None:
            timeout = self._config.storage.backend_timeouts.transaction_timeout

        raise TransactionError(
            f"Vector provider {type(self._vector_provider).__name__} does not support "
            "transactions. The local LanceDB, SQLite and in-memory providers "
            "commit per operation; a transactional external provider must implement "
            "the TransactionalProvider protocol."
        )

    async def vector_search(
        self,
        query_vector: List[float],
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> List["SearchResult"]:
        """Search for similar documents by vector.

        Args:
            query_vector: Query embedding vector
            limit: Maximum number of results
            filters: Optional field-based filters
            project_id: Optional project ID override. If None, uses facade's default.

        Returns:
            List of SearchResult objects sorted by similarity
        """
        effective_project_id = project_id if project_id is not None else self._project_id
        return await self._vector_provider.vector_search(
            query_vector=query_vector,
            limit=limit,
            filters=filters,
            project_id=effective_project_id,
        )

    async def hybrid_search(
        self,
        query_vector: List[float],
        query_text: str,
        limit: int = 10,
        vector_weight: float = 0.7,
    ) -> List["SearchResult"]:
        """Search using both vector and text.

        Args:
            query_vector: Query embedding vector
            query_text: Query text for FTS
            limit: Maximum number of results
            vector_weight: Weight for vector results (0.0-1.0)

        Returns:
            List of SearchResult objects sorted by combined score
        """
        return await self._vector_provider.hybrid_search(
            query_vector=query_vector,
            query_text=query_text,
            limit=limit,
            vector_weight=vector_weight,
            project_id=self._project_id,
        )

    async def fts_search(
        self,
        query: str,
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> List["SearchResult"]:
        """Search using full-text search.

        Args:
            query: Query text
            limit: Maximum number of results
            filters: Optional field-based filters
            project_id: Optional project ID override. If None, uses facade's default.

        Returns:
            List of SearchResult objects sorted by relevance
        """
        effective_project_id = project_id if project_id is not None else self._project_id
        return await self._vector_provider.fts_search(
            query=query,
            limit=limit,
            filters=filters,
            project_id=effective_project_id,
        )

    async def upsert_chunks(
        self,
        chunks: Sequence["DocumentChunk"],
    ) -> int:
        """Insert or update document chunks.

        Args:
            chunks: Document chunks to store (with vectors)

        Returns:
            Number of chunks upserted
        """
        if not chunks:
            return 0

        # Use the chunk's project_id for storage - this ensures chunks are
        # stored under their intended project rather than the facade's default.
        # All chunks in a batch should have the same project_id.
        chunk_project_id = chunks[0].project_id if chunks[0].project_id else self._project_id

        return await self._vector_provider.upsert_chunks(
            chunks=chunks,
            project_id=chunk_project_id,
        )

    async def add_document_chunks(
        self,
        chunks: Sequence["DocumentChunk"],
        project_id: Optional[str] = None,
        ensure_commit: bool = True,
    ) -> int:
        """Add document chunks (compatibility wrapper for upsert_chunks).

        This method provides backward compatibility for code that calls
        add_document_chunks (like IndexingPipeline and other indexers).

        Args:
            chunks: Document chunks to store (with vectors)
            project_id: Optional project ID (ignored - chunk's project_id is used)
            ensure_commit: Whether to ensure commit after add (no-op for this wrapper)

        Returns:
            Number of chunks added
        """
        return await self.upsert_chunks(chunks)

    async def get_chunks_by_file(
        self,
        file_path: str,
        project_id: Optional[str] = None,
    ) -> List["DocumentChunk"]:
        """Get all chunks from a specific file.

        Args:
            file_path: Path to the source file
            project_id: Optional project ID override

        Returns:
            List of DocumentChunk objects from the file
        """
        return await self._vector_provider.get_chunks_by_file(
            file_path=file_path,
            project_id=project_id or self._project_id,
        )

    async def delete_chunks_by_file(
        self,
        file_path: str,
        project_id: Optional[str] = None,
    ) -> int:
        """Delete all chunks from a specific file.

        Args:
            file_path: Path to the source file
            project_id: Optional project ID override

        Returns:
            Number of chunks deleted
        """
        return await self._vector_provider.delete_chunks_by_file(
            file_path=file_path,
            project_id=project_id or self._project_id,
        )

    async def delete_chunks_by_ids(
        self,
        chunk_ids: List[str],
        project_id: Optional[str] = None,
    ) -> int:
        """Delete document chunks by ID.

        Args:
            chunk_ids: IDs of chunks to delete
            project_id: Optional project ID override

        Returns:
            Number of chunks deleted
        """
        return await self._vector_provider.delete_chunks_by_ids(
            chunk_ids=chunk_ids,
            project_id=project_id or self._project_id,
        )

    async def count_chunks(
        self,
        filters: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Count document chunks matching filters.

        Args:
            filters: Optional field-based filters

        Returns:
            Number of matching chunks
        """
        return await self._vector_provider.count(
            filters=filters,
            project_id=self._project_id,
        )

    # =========================================================================
    # Graph Operations (delegated to graph_provider)
    # =========================================================================

    async def upsert_entities(
        self,
        entities: Sequence["GraphEntity"],
    ) -> int:
        """Insert or update graph entities.

        Args:
            entities: Entities to upsert

        Returns:
            Number of entities upserted
        """
        if not entities:
            return 0

        # Use the entity's project_id for storage - this ensures entities are
        # stored under their intended project rather than the facade's default.
        # All entities in a batch should have the same project_id.
        entity_project_id = entities[0].project_id if entities[0].project_id else self._project_id

        # Use configured batch_size for bulk operations
        # Note: batch_size logic is handled within the provider if applicable
        # batch_size = self._config.storage.batch_size if self._config else 1000

        return await self._graph_provider.upsert_entities(
            entities=entities,
            project_id=entity_project_id,
        )

    async def add_graph_entities(
        self,
        entities: Sequence["GraphEntity"],
    ) -> int:
        """Add graph entities (compatibility wrapper for upsert_entities).

        This method provides backward compatibility for code that calls
        add_graph_entities (like UnifiedCodeParser._register_entities).

        Args:
            entities: Entities to add

        Returns:
            Number of entities added
        """
        return await self.upsert_entities(entities)

    async def get_entity(
        self,
        entity_id: str,
    ) -> Optional["GraphEntity"]:
        """Retrieve an entity by ID.

        Args:
            entity_id: ID of the entity

        Returns:
            Entity if found, None otherwise
        """
        return await self._graph_provider.get_entity(
            entity_id=entity_id,
            project_id=self._project_id,
        )

    async def get_entities_by_file(
        self,
        file_path: str,
        project_id: Optional[str] = None,
    ) -> List["GraphEntity"]:
        """Get all entities from a specific file.

        Args:
            file_path: Path to the source file
            project_id: Optional project ID override

        Returns:
            List of entities from the file
        """
        return await self._graph_provider.get_entities_by_file(
            file_path=file_path,
            project_id=project_id or self._project_id,
        )

    async def get_entities_by_type(
        self,
        entity_type: str,
        limit: int = 100,
        project_id: Optional[str] = None,
    ) -> List["GraphEntity"]:
        """Get entities by type.

        Args:
            entity_type: Type of entities to retrieve
            limit: Maximum number of results
            project_id: Optional project ID override

        Returns:
            List of entities of the specified type
        """
        return await self._graph_provider.get_entities_by_type(
            entity_type=entity_type,
            project_id=project_id or self._project_id,
            limit=limit,
        )

    async def delete_entities_by_file(
        self,
        file_path: str,
        project_id: Optional[str] = None,
    ) -> int:
        """Delete all entities from a specific file.

        Args:
            file_path: Path to the source file
            project_id: Optional project ID override

        Returns:
            Number of entities deleted
        """
        return await self._graph_provider.delete_entities_by_file(
            file_path=file_path,
            project_id=project_id or self._project_id,
        )

    async def delete_entities_by_ids(
        self,
        entity_ids: List[str],
        project_id: Optional[str] = None,
    ) -> int:
        """Delete entities by their IDs.

        Args:
            entity_ids: IDs of entities to delete
            project_id: Optional project ID override

        Returns:
            Number of entities deleted
        """
        return await self._graph_provider.delete_entities_by_ids(
            entity_ids=entity_ids,
            project_id=project_id or self._project_id,
        )

    async def count_entities(
        self,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> int:
        """Count graph entities matching filters.

        Args:
            filters: Optional field-based filters
            project_id: Optional project ID override

        Returns:
            Number of matching entities
        """
        return await self._graph_provider.count_entities(
            filters=filters,
            project_id=project_id or self._project_id,
        )

    async def count_relationships(
        self,
        project_id: Optional[str] = None,
    ) -> int:
        """Count total graph relationships.

        Args:
            project_id: Optional project ID override

        Returns:
            Total number of relationships
        """
        counts = await self._graph_provider.count_relationships_by_type(
            project_id=project_id or self._project_id,
        )
        return sum(counts.values())

    async def upsert_relationships(
        self,
        relationships: Sequence["GraphRelationship"],
    ) -> int:
        """Insert or update graph relationships.

        Args:
            relationships: Relationships to upsert

        Returns:
            Number of relationships upserted
        """
        if not relationships:
            return 0

        # Use the relationship's project_id for storage - this ensures relationships are
        # stored under their intended project rather than the facade's default.
        # All relationships in a batch should have the same project_id.
        rel_project_id = relationships[0].project_id if relationships[0].project_id else self._project_id

        return await self._graph_provider.upsert_relationships(
            relationships=relationships,
            project_id=rel_project_id,
        )

    async def add_graph_relationships(
        self,
        relationships: Sequence["GraphRelationship"],
    ) -> int:
        """Add graph relationships (compatibility wrapper for upsert_relationships).

        This method provides backward compatibility for code that calls
        add_graph_relationships (like GraphBuilder and other graph constructors).

        Args:
            relationships: Relationships to add

        Returns:
            Number of relationships added
        """
        return await self.upsert_relationships(relationships)

    async def get_relationships_by_entity(
        self,
        entity_id: str,
        direction: str = "both",
        relationship_types: Optional[List[str]] = None,
    ) -> List["GraphRelationship"]:
        """Get relationships for an entity.

        Args:
            entity_id: ID of the entity
            direction: "outgoing", "incoming", or "both"
            relationship_types: Optional filter by type

        Returns:
            List of relationships
        """
        return await self._graph_provider.get_relationships_by_entity(
            entity_id=entity_id,
            direction=direction,
            relationship_types=relationship_types,
            project_id=self._project_id,
        )

    async def delete_relationships_by_file(
        self,
        file_path: str,
    ) -> int:
        """Delete all relationships from a specific file.

        Args:
            file_path: Path to the source file

        Returns:
            Number of relationships deleted
        """
        return await self._graph_provider.delete_relationships_by_file(
            file_path=file_path,
            project_id=self._project_id,
        )

    async def delete_relationships_by_entity(
        self,
        entity_id: str,
    ) -> int:
        """Delete all relationships for an entity.

        Args:
            entity_id: Entity to delete relationships for

        Returns:
            Number of relationships deleted
        """
        return await self._graph_provider.delete_relationships_by_entity(
            entity_id=entity_id,
            project_id=self._project_id,
        )

    async def delete_graph_relationships(
        self,
        relationship_ids: List[str],
        project_id: Optional[str] = None,
    ) -> int:
        """Delete graph relationships by IDs.

        Provides backward-compatible interface for indexing operations.

        Args:
            relationship_ids: List of relationship IDs to delete
            project_id: Optional project ID

        Returns:
            Number of relationships deleted
        """
        if not relationship_ids:
            return 0

        effective_project_id = project_id or self._project_id

        # Use graph provider's delete method if available
        if hasattr(self._graph_provider, "delete_relationships_by_ids"):
            return await self._graph_provider.delete_relationships_by_ids(
                relationship_ids=relationship_ids,
                project_id=effective_project_id,
            )

        # Fallback: delete one by one using entity-based deletion
        deleted = 0
        for rel_id in relationship_ids:
            try:
                # Get relationship to find source entity
                rels = await self.query_relationships(
                    filters={"id": rel_id},
                    limit=1,
                    project_id=effective_project_id,
                )
                if rels:
                    # Delete by source entity - this may delete more than intended
                    # but it's the best we can do without direct ID-based deletion
                    await self._graph_provider.delete_relationships_by_entity(
                        entity_id=rels[0].source_id,
                        project_id=effective_project_id,
                    )
                    deleted += 1
            except Exception as e:
                logger.warning("Failed to delete relationship %s: %s", rel_id, e)
        return deleted

    async def delete_document_chunks(
        self,
        chunk_ids: List[str],
        project_id: Optional[str] = None,
    ) -> int:
        """Delete document chunks by IDs.

        Alias for delete_chunks_by_ids for backward compatibility.

        Args:
            chunk_ids: List of chunk IDs to delete
            project_id: Optional project ID

        Returns:
            Number of chunks deleted
        """
        effective_project_id = project_id or self._project_id
        return await self.delete_chunks_by_ids(
            chunk_ids=chunk_ids,
            project_id=effective_project_id,
        )

    async def delete_graph_entities(
        self,
        entity_ids: List[str],
        project_id: Optional[str] = None,
    ) -> int:
        """Delete graph entities by IDs.

        Alias for delete_entities_by_ids for backward compatibility.

        Args:
            entity_ids: List of entity IDs to delete
            project_id: Optional project ID

        Returns:
            Number of entities deleted
        """
        effective_project_id = project_id or self._project_id
        return await self.delete_entities_by_ids(
            entity_ids=entity_ids,
            project_id=effective_project_id,
        )

    async def get_neighbors(
        self,
        entity_id: str,
        direction: str = "both",
        depth: int = 1,
        relationship_types: Optional[List[str]] = None,
    ) -> List["GraphEntity"]:
        """Get neighboring entities.

        Args:
            entity_id: Starting entity ID
            direction: "outgoing", "incoming", or "both"
            depth: How many hops to traverse
            relationship_types: Optional filter by relationship types

        Returns:
            List of neighboring entities
        """
        return await self._graph_provider.get_neighbors(
            entity_id=entity_id,
            direction=direction,
            depth=depth,
            relationship_types=relationship_types,
            project_id=self._project_id,
        )

    async def traverse(
        self,
        start_entity_id: str,
        max_depth: int = 2,
        relationship_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Traverse the graph from a starting entity.

        Args:
            start_entity_id: Starting entity ID
            max_depth: Maximum traversal depth
            relationship_types: Types of relationships to follow

        Returns:
            Dict with entities, relationships, and traversal info
        """
        return await self._graph_provider.traverse(
            start_entity_id=start_entity_id,
            max_depth=max_depth,
            relationship_types=relationship_types,
            project_id=self._project_id,
        )

    async def query_entities(
        self,
        filters: Dict[str, Any],
        limit: int = 100,
        offset: int = 0,
        project_id: Optional[str] = None,
    ) -> List["GraphEntity"]:
        """Query entities with filters.

        Args:
            filters: Filter conditions
            limit: Maximum number of results
            offset: Number of results to skip
            project_id: Optional project ID override

        Returns:
            List of matching GraphEntity objects
        """
        return await self._graph_provider.query_entities(
            filters=filters,
            project_id=project_id or self._project_id,
            limit=limit,
            offset=offset,
        )

    async def entity_vector_search(
        self,
        query_vector: Union[str, List[float]],
        limit: int = 50,
        entity_type: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> List["GraphEntity"]:
        """Search entities by vector similarity.

        Routed to the **vector** provider (the op moved off
        ``GraphStorageProtocol`` because it's a vector-space concern even
        though the entity rows are structurally graph-owned). Works across
        all backends that implement ``VectorStorageProtocol`` — the only
        fallback is for a custom provider that genuinely cannot serve
        entity vector search, in which case an empty list is returned.

        Args:
            query_vector: Query embedding vector (list of floats) or a raw
                ``str`` query for backends with server-side embedding
                (AlloyDB, RDS server-side). Mirrors the protocol's
                ``Union[str, List[float]]`` contract.
            limit: Maximum number of results. Default is 50.
            entity_type: Optional filter by entity type.
            project_id: Optional override (uses facade's project_id if None).

        Returns:
            List of :class:`GraphEntity` objects ranked by similarity (most
            similar first). Each entity has a ``_distance`` attribute with
            the raw distance value.
        """
        effective_project_id = project_id or self._project_id

        if hasattr(self._vector_provider, "entity_vector_search"):
            return await self._vector_provider.entity_vector_search(
                query_vector=query_vector,
                project_id=effective_project_id,
                limit=limit,
                entity_type=entity_type,
            )

        logger.debug(
            "Vector provider %s does not support entity_vector_search, returning empty",
            type(self._vector_provider).__name__,
        )
        return []

    async def query_relationships(
        self,
        filters: Dict[str, Any],
        limit: int = 100,
        offset: int = 0,
        project_id: Optional[str] = None,
    ) -> List["GraphRelationship"]:
        """Query relationships with filters.

        Args:
            filters: Filter conditions
            limit: Maximum number of results
            offset: Number of results to skip
            project_id: Optional project ID override

        Returns:
            List of matching GraphRelationship objects
        """
        return await self._graph_provider.query_relationships(
            filters=filters,
            project_id=project_id or self._project_id,
            limit=limit,
            offset=offset,
        )

    async def count_relationships_by_type(
        self,
        project_id: Optional[str] = None,
    ) -> Dict[str, int]:
        """Count relationships grouped by relationship type.

        Args:
            project_id: Optional override (uses facade's project_id if None)

        Returns:
            Dictionary mapping relationship type to count
        """
        effective_project_id = project_id or self._project_id
        return await self._graph_provider.count_relationships_by_type(
            project_id=effective_project_id,
        )

    # =========================================================================
    # Legacy LanceDBManager Methods (for MCP tool compatibility)
    # =========================================================================

    async def count_records(
        self,
        table_name: str,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> int:
        """Count records in a table.

        .. deprecated::
            Use count_chunks() for chunk counts or provider.count() directly.
            This method will be removed in a future version.

        Args:
            table_name: Name of the table to count
            filters: Optional filter conditions
            project_id: Project ID to filter by

        Returns:
            Count of matching records
        """
        import warnings

        warnings.warn(
            "count_records is deprecated. Use count_chunks() or provider.count() directly.",
            DeprecationWarning,
            stacklevel=2,
        )

        effective_project_id = project_id or self._project_id

        # For chunks table, use protocol method
        if table_name in ("chunks", "document_chunks"):
            return await self._vector_provider.count(
                filters=filters,
                project_id=effective_project_id,
            )

        # For graph_entities table, use protocol method
        if table_name == "graph_entities":
            return await self._graph_provider.count_entities(
                filters=filters,
                project_id=effective_project_id,
            )

        # For graph_relationships table, use query_relationships with count
        if table_name == "graph_relationships":
            # GraphStorageProtocol doesn't have count_relationships, so query and count
            max_limit = self._config.storage.max_query_limit if self._config else 100000
            relationships = await self._graph_provider.query_relationships(
                filters=filters or {},
                limit=max_limit,
                project_id=effective_project_id,
            )
            return len(relationships)

        # Route other graph tables to graph_provider if _db_manager available
        if table_name.startswith("graph_"):
            if hasattr(self._graph_provider, "_db_manager"):
                db_manager = self._graph_provider._db_manager
            else:
                raise NotImplementedError(
                    f"count_records for table '{table_name}' not supported by "
                    f"{type(self._graph_provider).__name__}. Graph provider has no _db_manager."
                )
        elif hasattr(self._vector_provider, "_db_manager"):
            db_manager = self._vector_provider._db_manager
        else:
            raise NotImplementedError(
                f"count_records for table '{table_name}' not supported by "
                f"{type(self._vector_provider).__name__}. Use provider.count() for chunks."
            )

        return await db_manager.count_records(
            table_name=table_name,
            filters=filters,
            project_id=effective_project_id,
        )

    async def advanced_filter(
        self,
        table_name: str,
        filters: Optional[Union[Dict[str, Any], Any]] = None,
        limit: Optional[int] = 100,
        project_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query with advanced filtering.

        .. deprecated::
            Use provider.query() directly.
            This method will be removed in a future version.

        Args:
            table_name: Name of the table to query
            filters: Filter conditions (dict or Filter AST)
            limit: Maximum number of results
            project_id: Project ID to filter by

        Returns:
            List of matching records as dicts
        """
        import warnings

        warnings.warn(
            "advanced_filter is deprecated. Use provider.query() directly.",
            DeprecationWarning,
            stacklevel=2,
        )

        effective_project_id = project_id or self._project_id

        # For chunks table, use protocol method and convert to dicts
        # Handle both "chunks" (legacy) and "document_chunks" (canonical) table names
        if table_name in ("chunks", "document_chunks"):
            chunks = await self._vector_provider.query(
                filters=filters or {},
                limit=limit or 100,
                project_id=effective_project_id,
            )
            # Convert DocumentChunk objects to dicts
            return [self._to_dict(chunk) for chunk in chunks]

        # For graph_entities table, use protocol method
        if table_name == "graph_entities":
            entities = await self._graph_provider.query_entities(
                filters=filters or {},
                limit=limit or 100,
                project_id=effective_project_id,
            )
            return [self._to_dict(entity) for entity in entities]

        # For graph_relationships table, use protocol method
        if table_name == "graph_relationships":
            relationships = await self._graph_provider.query_relationships(
                filters=filters or {},
                limit=limit or 100,
                project_id=effective_project_id,
            )
            return [self._to_dict(rel) for rel in relationships]

        # Fallback to _db_manager for other tables (LanceDB-specific)
        if table_name.startswith("graph_"):
            if hasattr(self._graph_provider, "_db_manager"):
                db_manager = self._graph_provider._db_manager
            else:
                raise NotImplementedError(
                    f"advanced_filter for table '{table_name}' not supported by "
                    f"{type(self._graph_provider).__name__}. Use query_entities() or query_relationships()."
                )
        elif hasattr(self._vector_provider, "_db_manager"):
            db_manager = self._vector_provider._db_manager
        else:
            raise NotImplementedError(
                f"advanced_filter for table '{table_name}' not supported by "
                f"{type(self._vector_provider).__name__}. Use provider.query() for chunks."
            )

        return await db_manager.advanced_filter(
            table_name=table_name,
            filters=filters,
            limit=limit,
            project_id=effective_project_id,
        )

    async def query_raw(
        self,
        table_name: str,
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        project_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Query raw records from a table.

        Provides backward-compatible interface for indexing operations.
        Routes queries to the appropriate provider based on table name.

        Args:
            table_name: Name of the table to query
            filters: Optional filter conditions
            limit: Maximum number of results
            project_id: Project ID to filter by

        Returns:
            List of matching records as dicts
        """
        effective_project_id = project_id or self._project_id

        # Route to appropriate provider based on table name
        if table_name == "document_chunks":
            # Use get_chunks_by_file if filtering by file_path
            if filters and "file_path" in filters:
                chunks = await self.get_chunks_by_file(
                    file_path=filters["file_path"],
                    project_id=effective_project_id,
                )
                return [
                    chunk.model_dump() if hasattr(chunk, "model_dump") else vars(chunk)
                    for chunk in chunks
                ]
            # Otherwise use query method
            chunks = await self._vector_provider.query(
                filters=filters or {},
                limit=limit or 1000,
                project_id=effective_project_id,
            )
            return [
                chunk.model_dump() if hasattr(chunk, "model_dump") else vars(chunk)
                for chunk in chunks
            ]

        elif table_name == "graph_entities":
            # Helper function for converting entities
            def entity_to_dict(e):
                if isinstance(e, dict):
                    return e
                if hasattr(e, "to_dict"):
                    return e.to_dict()
                if hasattr(e, "model_dump"):
                    return e.model_dump()
                # Fallback for dataclasses with slots
                from dataclasses import fields, is_dataclass
                if is_dataclass(e):
                    return {f.name: getattr(e, f.name) for f in fields(e)}
                return vars(e)

            # Use get_entities_by_file if filtering by file_path
            if filters and "file_path" in filters:
                entities = await self.get_entities_by_file(
                    file_path=filters["file_path"],
                    project_id=effective_project_id,
                )
                return [entity_to_dict(e) for e in entities]
            # Query all entities
            entities = await self.query_entities(
                filters=filters or {},
                limit=limit or 10000,
                project_id=effective_project_id,
            )
            return [entity_to_dict(e) for e in entities]

        elif table_name == "graph_relationships":
            # Query all relationships
            relationships = await self.query_relationships(
                filters=filters or {},
                limit=limit or 10000,
                project_id=effective_project_id,
            )

            # Convert relationships to dicts
            def rel_to_dict(r):
                if isinstance(r, dict):
                    return r
                if hasattr(r, "to_dict"):
                    return r.to_dict()
                if hasattr(r, "model_dump"):
                    return r.model_dump()
                # Fallback for dataclasses with slots
                from dataclasses import fields, is_dataclass
                if is_dataclass(r):
                    return {f.name: getattr(r, f.name) for f in fields(r)}
                return vars(r)

            return [rel_to_dict(r) for r in relationships]

        else:
            # Fall back to advanced_filter for unknown tables
            logger.warning(
                "query_raw called for unknown table '%s', using advanced_filter",
                table_name
            )
            return await self.advanced_filter(
                table_name=table_name,
                filters=filters,
                limit=limit,
                project_id=effective_project_id,
            )

    async def run_maintenance(
        self,
        project_id: Optional[str] = None,
        table_names: Optional[List[str]] = None,
        cleanup_older_than: timedelta = timedelta(minutes=5),
    ) -> Dict[str, Any]:
        """Run database maintenance on all providers.

        Delegates to each provider's run_maintenance() method if available,
        then aggregates results into a unified format.

        Args:
            project_id: Optional project scope.
            table_names: List of table names to maintain. If None, maintains
                        all standard tables.
            cleanup_older_than: Only remove versions older than this duration.
                              Default is 5 minutes.

        Returns:
            Maintenance results with keys:
            - compaction: Aggregated compaction results from all providers
            - cleanup: Aggregated cleanup results from all providers
            - summary: Overall summary with total fragments_reduced and versions_removed
            - providers: Per-provider breakdown (for debugging)
        """
        provider_results: Dict[str, Any] = {}
        aggregated_compaction: Dict[str, Any] = {}
        aggregated_cleanup: Dict[str, Any] = {}
        total_fragments_reduced = 0
        total_versions_removed = 0

        effective_project_id = project_id or self._project_id

        # Vector provider maintenance
        if hasattr(self._vector_provider, "run_maintenance"):
            try:
                # Try with full parameters
                try:
                    result = await self._vector_provider.run_maintenance(
                        project_id=effective_project_id,
                    )
                except TypeError:
                    # Fallback for older signatures or backend-specific params
                    # Some backends might take table_names/cleanup_older_than instead of project_id
                    # But per protocol, it should take project_id.
                    # We will try passing just project_id first.
                    # If that fails, maybe it takes no args?
                    result = await self._vector_provider.run_maintenance()

                provider_results["vector"] = result

                # Aggregate results
                if "compaction" in result:
                    aggregated_compaction.update(result["compaction"])
                if "cleanup" in result:
                    aggregated_cleanup.update(result["cleanup"])
                if "summary" in result:
                    total_fragments_reduced += result["summary"].get(
                        "fragments_reduced", 0
                    )
                    total_versions_removed += result["summary"].get(
                        "versions_removed", 0
                    )
            except Exception as e:
                provider_results["vector"] = {"error": str(e)}
        elif hasattr(self._vector_provider, "_db_manager"):
            # Legacy LanceDB fallback
            db_manager = self._vector_provider._db_manager
            result = await db_manager.run_maintenance(
                table_names=table_names,
                cleanup_older_than=cleanup_older_than,
            )
            provider_results["vector"] = result
            if "compaction" in result:
                aggregated_compaction.update(result["compaction"])
            if "cleanup" in result:
                aggregated_cleanup.update(result["cleanup"])
            if "summary" in result:
                total_fragments_reduced += result["summary"].get("fragments_reduced", 0)
                total_versions_removed += result["summary"].get("versions_removed", 0)

        # Graph provider maintenance (only if different from vector)
        if self._graph_provider is not self._vector_provider:
            if hasattr(self._graph_provider, "run_maintenance"):
                try:
                    result = await self._graph_provider.run_maintenance()
                    provider_results["graph"] = result
                    # Aggregate if graph provider returns similar structure
                    if "compaction" in result:
                        for k, v in result["compaction"].items():
                            aggregated_compaction[f"graph_{k}"] = v
                    if "cleanup" in result:
                        for k, v in result["cleanup"].items():
                            aggregated_cleanup[f"graph_{k}"] = v
                except Exception as e:
                    provider_results["graph"] = {"error": str(e)}

        # Events provider maintenance
        if self._events_provider and hasattr(self._events_provider, "run_maintenance"):
            try:
                result = await self._events_provider.run_maintenance()
                provider_results["events"] = result
            except Exception as e:
                provider_results["events"] = {"error": str(e)}

        # File tracker doesn't typically need maintenance, but check anyway
        if self._file_tracker_provider and hasattr(
            self._file_tracker_provider, "run_maintenance"
        ):
            try:
                result = await self._file_tracker_provider.run_maintenance()
                provider_results["file_tracker"] = result
            except Exception as e:
                provider_results["file_tracker"] = {"error": str(e)}

        return {
            "compaction": aggregated_compaction,
            "cleanup": aggregated_cleanup,
            "summary": {
                "fragments_reduced": total_fragments_reduced,
                "versions_removed": total_versions_removed,
            },
            "providers": provider_results,
        }

    # =========================================================================
    # Properties
    # =========================================================================

    @property
    def project_id(self) -> str:
        """Get the project ID."""
        return self._project_id

    @property
    def is_initialized(self) -> bool:
        """Check if facade is initialized."""
        return self._initialized

    @property
    def vector_provider(self) -> "VectorStorageProtocol":
        """Access the underlying vector storage provider.

        Use this when you need low-level operations not exposed by the
        facade (e.g., query_raw, list_tables, query_across_projects).

        Note: Prefer facade methods when possible for consistency and
        future backend portability.

        Returns:
            The vector storage provider instance.
        """
        return self._vector_provider

    @property
    def graph_provider(self) -> "GraphStorageProtocol":
        """Access the underlying graph storage provider.

        Use this when you need low-level operations not exposed by the
        facade (e.g., query_entities, query_relationships).

        Note: Prefer facade methods when possible for consistency and
        future backend portability.

        Returns:
            The graph storage provider instance.
        """
        return self._graph_provider

    @property
    def events_provider(self) -> Optional["EventStorageProtocol"]:
        """Access the underlying events storage provider.

        Use this when you need direct access to event storage operations
        not exposed by the facade.

        Returns:
            The events storage provider instance, or None if not configured.
        """
        return self._events_provider

    @property
    def file_tracker_provider(self) -> Optional["FileTrackerProtocol"]:
        """Access the underlying file tracker provider.

        Use this when you need direct access to file tracking operations
        not exposed by the facade.

        Returns:
            The file tracker provider instance, or None if not configured.
        """
        return self._file_tracker_provider

    @property
    def pool_manager(self) -> Optional["BackendPoolManager"]:
        """Access the connection pool manager.

        Returns:
            The pool manager instance, or None if not configured.
        """
        return self._pool_manager

    def get_backend_type(self) -> str:
        """Get the storage backend type.

        Returns the backend type string (e.g., "lancedb", "postgresql", "cloudsql").
        This can be used to check which backend is active before calling
        backend-specific methods like get_db_manager().

        Returns:
            The backend type string.

        Example:
            >>> if storage.get_backend_type() == "lancedb":
            ...     db_manager = storage.get_db_manager()
            ...     # Use LanceDB-specific features
        """
        return self._backend_type

    def get_capabilities(self) -> "ProviderCapabilities":
        """Get the capabilities of the active storage backend.

        Returns a ProviderCapabilities object that describes what this backend
        supports (embedding strategy, proxy requirements, etc.). Use this
        instead of checking get_backend_type() strings directly.

        Returns:
            ProviderCapabilities for the active backend.

        Example:
            >>> caps = storage.get_capabilities()
            >>> if caps.uses_server_side_embedding:
            ...     # Skip local embedding generation
            ...     pass
        """
        from agentic_inquiry.storage.capabilities import get_capabilities_for_backend

        return get_capabilities_for_backend(self._backend_type)

    def get_connection_manager(self) -> Any:
        """Get the connection manager for PostgreSQL-compatible backends.

        Returns the connection manager from whichever role (vector or graph)
        is backed by a PostgreSQL-compatible backend. In mixed deployments
        (e.g. vector=LanceDB + graph=Postgres) the graph-side pg connection
        is what memory adapters and onboarding use, so routing off a single
        facade-wide backend type string would miss it. Returns ``None`` only
        when neither role is pg-compatible.

        Returns:
            Connection manager instance or None if no role is pg-compatible.

        Example:
            >>> caps = storage.get_capabilities()
            >>> if caps.is_postgresql_compatible:
            ...     conn_manager = storage.get_connection_manager()
        """
        from agentic_inquiry.storage.capabilities import get_capabilities_for_backend

        vector_caps = get_capabilities_for_backend(self._backend_type)
        graph_caps = get_capabilities_for_backend(self._graph_backend_type)

        # Probe the role(s) whose backend is pg-compatible, in vector-first
        # order since single-backend deployments (most common case) hit the
        # vector provider first and short-circuit.
        if vector_caps.is_postgresql_compatible and self._vector_provider is not None:
            if hasattr(self._vector_provider, "_conn"):
                return self._vector_provider._conn
            if hasattr(self._vector_provider, "_connection_manager"):
                return self._vector_provider._connection_manager

        if graph_caps.is_postgresql_compatible and self._graph_provider is not None:
            if hasattr(self._graph_provider, "_conn"):
                return self._graph_provider._conn
            if hasattr(self._graph_provider, "_connection_manager"):
                return self._graph_provider._connection_manager

        return None

    # =========================================================================
    # Capability Checks
    # =========================================================================

    def supports_vector_search(self) -> bool:
        """Check if the storage backend supports vector search.

        Returns:
            True if vector search is available.
        """
        return has_vector_search(self._vector_provider)

    def supports_fts(self) -> bool:
        """Check if the storage backend supports full-text search.

        Returns:
            True if FTS is available.
        """
        return has_fts(self._vector_provider)

    def supports_hybrid_search(self) -> bool:
        """Check if the storage backend supports native hybrid search.

        Returns:
            True if hybrid search is available.
        """
        return has_hybrid_search(self._vector_provider)

    def supports_graph_ranking(self) -> bool:
        """Check if the storage backend supports graph-based ranking.

        Returns:
            True if graph ranking is available.
        """
        return has_graph_ranking(self._vector_provider)

    async def has_graph_ranking_data(self, table: str = "document_chunks") -> bool:
        """Check if graph ranking data is available for a table.

        This is a runtime check for whether ranking signals have been
        computed, not a capability check.

        Args:
            table: Logical table name to check

        Returns:
            True if graph ranking data is available.
        """
        # Check if vector provider has the method
        if hasattr(self._vector_provider, "has_graph_ranking"):
            return await self._vector_provider.has_graph_ranking(table)
        # Check underlying manager for graph_ranking_available
        if hasattr(self._vector_provider, "_manager"):
            manager = self._vector_provider._manager
            if hasattr(manager, "graph_ranking_available"):
                return await manager.graph_ranking_available()
        if hasattr(self._vector_provider, "_connection_manager"):
            db_manager = self._vector_provider._connection_manager.db_manager
            if hasattr(db_manager, "graph_ranking_available"):
                return await db_manager.graph_ranking_available()
        return False

    # =========================================================================
    # Low-Level Query Operations (for GraphSearchService compatibility)
    # =========================================================================

    async def list_tables(self) -> List[str]:
        """List all tables in the storage backend.

        This method provides a unified way to discover available tables
        across different backend implementations.

        Returns:
            List of table names available in the storage.
        """
        # Try vector provider first (usually has comprehensive table list)
        if hasattr(self._vector_provider, "list_tables"):
            return await self._vector_provider.list_tables()
        # Try underlying managers
        if hasattr(self._vector_provider, "_manager"):
            return await self._vector_provider._manager.list_tables()
        if hasattr(self._vector_provider, "_connection_manager"):
            return await self._vector_provider._connection_manager.db_manager.list_tables()
        # Fallback: return standard table set
        logger.warning("list_tables not supported by provider, returning default table list")
        return ["document_chunks", "graph_entities", "graph_relationships"]

    async def vector_search_raw(
        self,
        table: str,
        vector: List[float],
        vector_column: str = "vector",
        limit: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Perform raw vector search on a specific table.

        This is a low-level method for cases where the standard vector_search
        on document_chunks is not sufficient (e.g., searching graph_entities).

        Args:
            table: Table name to search
            vector: Query vector
            vector_column: Name of the vector column
            limit: Maximum results to return
            filters: Optional filters to apply
            project_id: Project ID to filter by

        Returns:
            List of matching records as dicts
        """
        effective_project_id = project_id or self._project_id

        # For standard document_chunks, use facade's vector_search
        if table == "document_chunks":
            results = await self.vector_search(
                query_vector=vector,
                limit=limit,
                filters=filters,
                project_id=effective_project_id,
            )
            return [
                r.model_dump() if hasattr(r, "model_dump") else vars(r)
                for r in results
            ]

        # For other tables, try provider methods
        if hasattr(self._vector_provider, "vector_search_raw"):
            return await self._vector_provider.vector_search_raw(
                table=table,
                vector=vector,
                vector_column=vector_column,
                limit=limit,
                filters=filters,
                project_id=effective_project_id,
            )
        if hasattr(self._vector_provider, "_manager"):
            manager = self._vector_provider._manager
            if hasattr(manager, "vector_search"):
                results = await manager.vector_search(
                    table_name=table,
                    query_vector=vector,
                    limit=limit,
                    filters=filters,
                    project_id=effective_project_id,
                )
                return [
                    r.model_dump() if hasattr(r, "model_dump") else (r if isinstance(r, dict) else vars(r))
                    for r in results
                ]
        if hasattr(self._vector_provider, "_connection_manager"):
            db_manager = self._vector_provider._connection_manager.db_manager
            if hasattr(db_manager, "vector_search"):
                results = await db_manager.vector_search(
                    table_name=table,
                    query_vector=vector,
                    limit=limit,
                    filters=filters,
                    project_id=effective_project_id,
                )
                return [
                    r.model_dump() if hasattr(r, "model_dump") else (r if isinstance(r, dict) else vars(r))
                    for r in results
                ]

        raise NotImplementedError(
            f"vector_search_raw for table '{table}' not supported by "
            f"{type(self._vector_provider).__name__}"
        )

    async def query_across_projects(
        self,
        table_name: str,
        project_ids: List[str],
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Query records across multiple projects.

        This method provides cross-project querying capability for multi-tenant
        scenarios where data needs to be aggregated from multiple projects.

        Args:
            table_name: Table to query
            project_ids: List of project IDs to query across
            filters: Optional filters to apply
            limit: Maximum results to return

        Returns:
            List of matching records with project_id annotations
        """
        # Default limit if not provided
        effective_limit = limit or 100

        # Try provider method directly
        if hasattr(self._vector_provider, "query_across_projects"):
            return await self._vector_provider.query_across_projects(
                table_name=table_name,
                project_ids=project_ids,
                filters=filters,
                limit=effective_limit,
            )
        if hasattr(self._vector_provider, "_manager"):
            manager = self._vector_provider._manager
            if hasattr(manager, "query_across_projects"):
                return await manager.query_across_projects(
                    table_name=table_name,
                    project_ids=project_ids,
                    filters=filters,
                    limit=effective_limit,
                )
        if hasattr(self._vector_provider, "_connection_manager"):
            db_manager = self._vector_provider._connection_manager.db_manager
            if hasattr(db_manager, "query_across_projects"):
                return await db_manager.query_across_projects(
                    table_name=table_name,
                    project_ids=project_ids,
                    filters=filters,
                    limit=effective_limit,
                )

        # Fallback: query each project individually and merge
        logger.warning(
            "query_across_projects not natively supported, using fallback implementation"
        )
        all_results = []
        for pid in project_ids:
            results = await self.query_raw(
                table_name=table_name,
                filters=filters,
                limit=effective_limit,
                project_id=pid,
            )
            # Annotate with project_id
            for r in results:
                r["_project_id"] = pid
            all_results.extend(results)

        # Apply overall limit if specified
        if len(all_results) > effective_limit:
            all_results = all_results[:effective_limit]

        return all_results

    # =========================================================================
    # Legacy Compatibility
    # =========================================================================

    def get_db_manager(self) -> "LanceDBManager":
        """Get the underlying LanceDBManager for legacy compatibility.

        DEPRECATED: Use StorageFacade methods directly. This is provided
        for migration purposes and will be removed in a future version.

        Returns:
            The underlying LanceDBManager instance.

        Raises:
            AttributeError: If the provider doesn't have a db_manager.
        """
        # Emit deprecation warning only once per process
        if not getattr(self, "_db_manager_warning_emitted", False):
            import warnings

            warnings.warn(
                "get_db_manager() is deprecated. Use StorageFacade methods directly.",
                DeprecationWarning,
                stacklevel=2,
            )
            self._db_manager_warning_emitted = True
        # Support various provider implementations:
        # - LanceDBAdapter: uses _manager
        # - LanceDBProvider: uses _connection_manager.db_manager
        # - LanceDBVectorProvider: uses _connection_manager.db_manager
        # - Legacy providers: use _db_manager
        provider = self._vector_provider
        if hasattr(provider, "_manager"):
            return provider._manager
        elif hasattr(provider, "_connection_manager"):
            # LanceDBProvider and LanceDBVectorProvider
            return provider._connection_manager.db_manager
        elif hasattr(provider, "_db_manager"):
            return provider._db_manager
        else:
            raise AttributeError(
                f"Provider {type(provider).__name__} has no _manager, _connection_manager, or _db_manager attribute"
            )


__all__ = ["StorageFacade"]
