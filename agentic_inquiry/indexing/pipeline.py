"""Indexing pipeline that materialises parser output into LanceDB tables."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import fields as dataclass_fields
from pathlib import Path
from types import TracebackType
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Type

from agentic_inquiry.database.transaction import Transaction
from agentic_inquiry.embeddings.registry import EmbeddingRegistry, embedding_registry
from agentic_inquiry.exceptions import SchemaValidationError
from agentic_inquiry.indexing.symbol_registry import SymbolRegistry
from agentic_inquiry.indexing.schema_processor import SchemaProcessor
from agentic_inquiry.models import DocumentChunk, GraphRelationship
from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk, ParserRelationship
from agentic_inquiry.cache import CacheProtocol, get_cache
from agentic_inquiry.watching import WatcherProtocol

# TYPE_CHECKING import to avoid circular dependency
from typing import TYPE_CHECKING, cast
if TYPE_CHECKING:
    from agentic_inquiry.indexing.relationship_resolver import RelationshipResolver
    from agentic_inquiry.indexing.models import IndexingResult
    from agentic_inquiry.connectors.protocols import ConnectorProtocol
    from agentic_inquiry.connectors.cache import ContentMaterializer
    from agentic_inquiry.storage.facade import StorageFacade
    from agentic_inquiry.storage.capabilities import ProviderCapabilities


from agentic_inquiry.indexing.document_processor import DocumentProcessor
from agentic_inquiry.indexing.embedding_service import EmbeddingService
from agentic_inquiry.indexing.graph_builder import GraphBuilderConfig
from agentic_inquiry.indexing.file_watch_manager import FileWatchManager
from agentic_inquiry.indexing.priority import (
    prioritize_files,
    get_fast_path_files,
)

from agentic_inquiry.events import EventSystem
from agentic_inquiry.events.context_managers import track_operation
from agentic_inquiry.mcp.utils.validation import validate_path
from agentic_inquiry.events.models import EventStatus
from agentic_inquiry.events.types import EventTypes
from agentic_inquiry.executors import get_embedding_executor
from agentic_inquiry.metrics import get_metrics_tracker

logger = logging.getLogger(__name__)


def _graph_write_indexing_error(exc: BaseException) -> Any:
    """Build an IndexingError for a failed graph-relationship write."""
    from agentic_inquiry.indexing.models import IndexingError

    return IndexingError(
        file_path="graph_relationships",
        error_type="GraphWriteError",
        error_message=str(exc),
        suggestion=(
            "Document chunks already written were left in place. "
            "Re-run ai index after the graph write succeeds."
        ),
    )


# Cache DocumentChunk field names for efficient lookup
_DOCUMENT_CHUNK_FIELDS: Optional[Set[str]] = None


def _get_document_chunk_fields() -> Set[str]:
    """Get the set of field names from DocumentChunk dataclass."""
    global _DOCUMENT_CHUNK_FIELDS
    if _DOCUMENT_CHUNK_FIELDS is None:
        _DOCUMENT_CHUNK_FIELDS = {f.name for f in dataclass_fields(DocumentChunk)}
    return _DOCUMENT_CHUNK_FIELDS


class IndexingPipeline:
    """Transform parsed documents into LanceDB rows.

    Supports multiple storage interfaces (in order of preference):
    1. StorageFacade: The unified storage interface (recommended)
    2. LanceDBAdapter: Direct adapter protocol interface
    3. LanceDBManager: Legacy interface (wrapped in adapter internally)

    This class supports the async context manager protocol for guaranteed
    resource cleanup. When used as a context manager, the file watcher
    (if active) will be automatically stopped on exit, even if an exception
    occurs.

    Example with StorageFacade (recommended):
        >>> storage = await StorageFacade.from_config(config, "my_project")
        >>> pipeline = IndexingPipeline(storage, config, "my_project")
        >>> await pipeline.process_document(doc)

    Example with legacy LanceDBManager:
        >>> async with IndexingPipeline.from_config(config) as pipeline:
        ...     await pipeline.process_document(doc)
        ... # Watcher automatically stopped on exit
    """

    def __init__(
        self,
        db_manager: Any,  # StorageFacade, LanceDBAdapter, or LanceDBManager
        config: Any,
        project_id: str,
        event_system: Optional[EventSystem] = None,
        *,
        registry: EmbeddingRegistry = embedding_registry,
        relationship_resolver: Optional["RelationshipResolver"] = None,
        cache_name: Optional[str] = None,
        watcher_name: Optional[str] = None,
        auto_watch: bool = False,
        max_concurrent: Optional[int] = None,
        project_root: Optional[str] = None,
        connector: Optional["ConnectorProtocol"] = None,
        content_materializer: Optional["ContentMaterializer"] = None,
        capabilities: Optional["ProviderCapabilities"] = None,
    ) -> None:
        """Initialize the indexing pipeline.

        Args:
            db_manager: Storage interface. Accepts (in order of preference):
                - StorageFacade: Unified storage interface (recommended)
                - LanceDBAdapter: Direct adapter protocol interface
                - LanceDBManager: Legacy interface (wrapped in adapter internally)
                Implements IndexingDatabaseProtocol (DES-S2-001): upsert_chunks,
                upsert_entities, upsert_relationships, delete_by_file.
            config: Configuration instance
            project_id: Project identifier for data isolation
            event_system: Optional EventSystem instance for event emission.
                          If None, indexing still works but no events are emitted.
            registry: Embedding registry for model management
            relationship_resolver: Optional relationship resolver instance
            cache_name: Optional cache name for parsed documents
            watcher_name: Optional watcher name for file watching
            auto_watch: Whether to automatically start file watching
            max_concurrent: Deprecated. Use config.indexing.processing_semaphore_limit instead.
            project_root: Optional project root directory for path validation.
                          Defaults to current working directory.
            connector: Optional connector for file discovery. If provided, uses
                connector.list() instead of direct filesystem access. Enables
                indexing from remote sources (S3, GCS, etc.).
            content_materializer: Optional materializer for remote content.
                Required for remote connectors to convert content to local paths
                for parser compatibility.
        """
        # Track if we have a StorageFacade
        self._storage_facade: Optional["StorageFacade"] = None

        # Normalize db_manager to an adapter for consistent interface.
        # All detection uses duck-typing (hasattr) to avoid runtime imports of
        # LanceDBAdapter/LanceDBManager outside the provider boundary (ADR-001).
        adapter: Any

        # Check for StorageFacade by attribute (duck typing to avoid circular import)
        # StorageFacade has _initialized as a bool, distinguishing from AsyncMock
        is_storage_facade = (
            hasattr(db_manager, "vector_provider")
            and hasattr(db_manager, "graph_provider")
            and isinstance(getattr(db_manager, "_initialized", None), bool)
        )

        if is_storage_facade:
            # StorageFacade detected - cast for type safety
            facade = cast("StorageFacade", db_manager)
            self._storage_facade = facade

            # Backend type is now irrelevant - StorageFacade provides unified access
            # to all backends through the protocol layer
            backend_type = facade.get_backend_type() if hasattr(facade, "get_backend_type") else "lancedb"
            logger.info("IndexingPipeline using backend: %s", backend_type)

            # For LanceDB, extract underlying manager for adapter compatibility.
            # Lazy import: only executed when LanceDB is the active backend (ADR-003).
            if backend_type == "lancedb" and hasattr(facade, "get_db_manager"):
                from agentic_inquiry.database.adapters.lancedb_adapter import LanceDBAdapter
                manager = facade.get_db_manager()
                adapter = LanceDBAdapter(manager, config)
                logger.debug(
                    "IndexingPipeline obtained LanceDBManager via get_db_manager()"
                )
            else:
                # Use StorageFacade directly - it implements IndexingStorageProtocol
                adapter = facade  # type: ignore[assignment]
                logger.info(
                    "IndexingPipeline using StorageFacade directly for backend: %s",
                    backend_type
                )
        elif hasattr(db_manager, "_manager") and hasattr(db_manager, "add_document_chunks"):
            # Quacks like LanceDBAdapter (has _manager and add_document_chunks) - use directly
            adapter = db_manager
            logger.debug("IndexingPipeline using provided LanceDBAdapter (duck-typed)")
        elif (
            hasattr(db_manager, "add_document_chunks")
            and hasattr(db_manager, "connect")
            and hasattr(db_manager, "_conn_manager")
        ):
            # Quacks like LanceDBManager (has _conn_manager, distinguishing it from test mocks).
            # Wrap in adapter lazily (ADR-003).
            from agentic_inquiry.database.adapters.lancedb_adapter import LanceDBAdapter
            adapter = LanceDBAdapter(db_manager, config)
            logger.debug("IndexingPipeline wrapped LanceDBManager in LanceDBAdapter (duck-typed)")
        else:
            # Unknown type - assume it implements the protocol (for testing with mocks)
            adapter = db_manager  # type: ignore[assignment]
            logger.warning(
                "IndexingPipeline received unknown db_manager type: %s. "
                "Assuming it implements IndexingStorageProtocol.",
                type(db_manager).__name__
            )

        self.db_manager = adapter
        self.config = config
        self.project_root = project_root if project_root is not None else str(Path.cwd())
        self.project_id = project_id
        self.event_system = event_system

        # Track backend type for embedding strategy decisions
        # AlloyDB uses server-side embeddings, so local embedding generation is skipped
        if hasattr(self, '_storage_facade') and self._storage_facade is not None:
            self._backend_type = self._storage_facade.get_backend_type() if hasattr(self._storage_facade, 'get_backend_type') else "lancedb"
        else:
            self._backend_type = "lancedb"

        # Resolve capabilities: prefer injected, fall back to derivation from backend_type
        if capabilities is not None:
            self._capabilities = capabilities
        else:
            from agentic_inquiry.storage.capabilities import get_capabilities_for_backend
            self._capabilities = get_capabilities_for_backend(self._backend_type)

        # Keep project_hash as alias for project_id for any internal code that uses it
        self.project_hash = self.project_id
        self._registry = registry
        
        # Document processor: handles document validation, normalization, and chunk transformation
        self.document_processor = DocumentProcessor(
            project_hash=self.project_hash,
            project_id=self.project_id
        )
        
        # Embedding service: handles embedding generation and configuration
        self.embedding_service = EmbeddingService(registry=registry)
        
        # Schema processor: unified validation, transformation, and sanitization
        self.schema_processor = SchemaProcessor(adapter)
        
        # Symbol registry service: manages symbol definitions with rich metadata for cross-file resolution
        self.symbol_registry = SymbolRegistry(self.project_root, self.project_hash)
        
        # Metrics tracker: track operation latencies and performance
        self._metrics = get_metrics_tracker()
        
        # Concurrency control: limit concurrent document processing
        import asyncio
        # Read from config, with backward compatibility for max_concurrent parameter
        if max_concurrent is not None:
            import warnings
            warnings.warn(
                "The max_concurrent parameter is deprecated. "
                "Use config.indexing.processing_semaphore_limit instead.",
                DeprecationWarning,
                stacklevel=2
            )
            semaphore_limit = max_concurrent
        else:
            semaphore_limit = config.indexing.processing_semaphore_limit
        
        self._processing_semaphore = asyncio.Semaphore(semaphore_limit)
        
        # Get embedding dimensions from config
        embedding_dimensions = getattr(config.embeddings, 'default_dimensions', 384)
        
        # Relationship resolver: handles import resolution using multiple strategies
        if relationship_resolver is None:
            # Create default RelationshipResolver if not provided
            from agentic_inquiry.indexing.relationship_resolver import RelationshipResolver
            relationship_resolver = RelationshipResolver(
                symbol_registry=self.symbol_registry,
                project_root=self.project_root,
                db_manager=adapter,
                embedding_dimensions=embedding_dimensions,
            )
        self.relationship_resolver = relationship_resolver
        
        # Graph builder: handles graph entity and relationship construction
        from agentic_inquiry.indexing.graph_builder import GraphBuilder
        self.graph_builder = GraphBuilder(
            db_manager=adapter,
            symbol_registry=self.symbol_registry,
            relationship_resolver=relationship_resolver,
            embedding_service=self.embedding_service,
            project_id=self.project_id,
            project_hash=self.project_hash,
            project_root=self.project_root,
            embedding_dimensions=embedding_dimensions,
            backend_type=self._backend_type,
            capabilities=self._capabilities,
        )
        
        # Pending relationships: now managed by GraphBuilder (accessed via property)
        # Resolution statistics from last flush
        self._last_resolution_stats: Optional[Dict[str, Any]] = None
        # Cache support: optional cache for parsed documents
        self.cache: Optional[CacheProtocol] = None
        if cache_name is not None:
            try:
                self.cache = get_cache(cache_name)
                logger.info("IndexingPipeline using cache: %s", cache_name)
            except (ValueError, KeyError) as e:
                logger.warning("Failed to get cache '%s': %s. Proceeding without cache.", cache_name, e, exc_info=True)
                self.cache = None

        # File watch manager: handles file watching for automatic re-indexing
        self._file_watch_manager = FileWatchManager(
            project_root=self.project_root,
            cache=self.cache
        )

        # Setup file watching if requested
        if watcher_name is not None and auto_watch:
            self._file_watch_manager.setup_file_watching(watcher_name)

        # Backwards-compatible properties for tests
        self._watcher_name = watcher_name

        # Connector support: optional connector for pluggable file discovery
        self.connector: Optional["ConnectorProtocol"] = connector
        self.content_materializer: Optional["ContentMaterializer"] = content_materializer

        # Validate connector/materializer configuration
        if connector is not None and content_materializer is None:
            logger.warning(
                "Connector provided without ContentMaterializer. "
                "Remote content will fail to parse."
            )

    @property
    def watcher(self) -> Optional[WatcherProtocol]:
        """Backwards-compatible property for accessing the file watcher.

        Returns:
            The active file watcher, or None if not watching
        """
        return self._file_watch_manager.watcher

    @watcher.setter
    def watcher(self, value: Optional[WatcherProtocol]) -> None:
        """Backwards-compatible setter for the file watcher.

        Args:
            value: The watcher to set
        """
        self._file_watch_manager.watcher = value

    @property
    def storage_facade(self) -> Optional["StorageFacade"]:
        """Access the underlying StorageFacade if available.

        Returns the StorageFacade if one was passed to the constructor,
        otherwise returns None. Use this property when you need access
        to the unified storage interface.

        Returns:
            StorageFacade if initialized with one, None otherwise.
        """
        return self._storage_facade

    async def __aenter__(self) -> "IndexingPipeline":
        """Async context manager entry.

        Returns:
            Self for use in the context manager block.
        """
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> bool:
        """Async context manager exit - ensures cleanup.

        This method guarantees that the file watcher is stopped when exiting
        the context, regardless of whether an exception occurred.

        Args:
            exc_type: Exception type if an exception was raised, None otherwise.
            exc_val: Exception instance if an exception was raised, None otherwise.
            exc_tb: Traceback if an exception was raised, None otherwise.

        Returns:
            False to allow exceptions to propagate after cleanup.
        """
        self.stop_watching()
        return False

    def _generate_operation_id(self) -> str:
        """Generate unique operation ID for tracking indexing operations.

        Uses UUID4 to generate a unique identifier that can be used to track
        indexing operations across events and status queries.

        Returns:
            Unique operation identifier string
        """
        import uuid
        return str(uuid.uuid4())

    async def _generate_server_side_embeddings(
        self, diagnostics: Dict[str, Any]
    ) -> None:
        """Local providers embed during indexing; nothing runs server side."""
        diagnostics.setdefault("server_side_embeddings", "not applicable")

    async def _count_null_embeddings(self) -> int:
        """Local providers store embeddings with each chunk, so none are pending."""
        return 0

    async def _poll_embedding_completion(
        self,
        poll_interval: float = 5.0,
        backoff_factor: float = 1.5,
        max_interval: float = 10.0,
        timeout: float = 900.0,
    ) -> None:
        """Poll until all embeddings are generated (no NULL embeddings remain).

        Uses exponential backoff to avoid excessive queries. Only meaningful
        for server-side embedding backends (AlloyDB).

        Args:
            poll_interval: Initial polling interval in seconds
            backoff_factor: Multiplier applied to interval after each poll
            max_interval: Maximum polling interval in seconds
            timeout: Maximum total wait time in seconds

        Raises:
            TimeoutError: If embeddings are not complete within timeout
        """
        if not self._capabilities.needs_embedding_polling:
            return

        start = time.time()
        interval = poll_interval

        while True:
            remaining = await self._count_null_embeddings()
            if remaining == 0:
                elapsed = time.time() - start
                logger.info(
                    "All embeddings complete after %.1f seconds", elapsed,
                )
                return

            elapsed = time.time() - start
            if elapsed >= timeout:
                logger.warning(
                    "Embedding polling timed out after %.1f seconds "
                    "with %d chunks still pending",
                    elapsed, remaining,
                )
                raise TimeoutError(
                    f"Embedding generation timed out after {elapsed:.0f}s "
                    f"with {remaining} chunks still pending"
                )

            logger.debug(
                "Embedding poll: %d chunks pending, waiting %.1fs "
                "(elapsed: %.1fs)",
                remaining, interval, elapsed,
            )
            await asyncio.sleep(interval)
            interval = min(interval * backoff_factor, max_interval)

    async def _discover_files(
        self,
        path: Path,
    ) -> List[Tuple[str, Optional[Any]]]:
        """Discover files to index, using connector if available.

        Args:
            path: Root path for file discovery.

        Returns:
            List of (local_path, source_item) tuples. source_item is None
            for direct filesystem access, or the SourceItem for connector access.
        """
        from agentic_inquiry.utils.ignore_handler import get_ignore_handler

        # If connector is provided, use it for discovery
        if self.connector is not None:
            from agentic_inquiry.connectors.protocols import ChangeDetectionCapability

            files: List[Tuple[str, Optional[Any]]] = []
            async for item in self.connector.list(str(path)):
                # Check change detection if available
                if isinstance(self.connector, ChangeDetectionCapability):
                    if not await self.connector.has_changed(item):
                        logger.debug("Skipping unchanged file: %s", item.uri)
                        continue

                # Materialize remote content to local path if needed
                if self.content_materializer is not None:
                    try:
                        local_path = await self.content_materializer.materialize(
                            self.connector, item
                        )
                    except Exception as e:
                        logger.warning("Failed to materialize %s: %s", item.uri, e)
                        continue
                else:
                    # No materializer - assume local path
                    local_path = item.uri

                files.append((local_path, item))

            logger.info(
                "File discovery via connector in %s: indexable=%d",
                path,
                len(files),
            )
            return files

        # Fallback: direct filesystem access (original behavior)
        binary_extensions = {
            '.mp3', '.mp4', '.wav', '.avi', '.mov', '.mkv',
            '.zip', '.tar', '.gz', '.rar', '.7z',
            '.exe', '.dll', '.so', '.dylib', '.bin',
            '.pyc', '.pyo', '.class', '.o', '.obj',
            '.woff', '.woff2', '.ttf', '.otf', '.eot'
        }
        ignore_handler = get_ignore_handler(str(path))

        # Track discovery statistics
        stats = {
            "total_found": 0,
            "ignored_by_pattern": 0,
            "ignored_as_binary": 0,
            "ignored_as_directory": 0,
            "indexable": 0,
        }
        ignored_files: List[str] = []  # For debug logging

        result: List[Tuple[str, Optional[Any]]] = []

        for f in path.rglob("*"):
            stats["total_found"] += 1

            if not f.is_file():
                stats["ignored_as_directory"] += 1
                continue

            if ignore_handler.is_ignored(str(f)):
                stats["ignored_by_pattern"] += 1
                try:
                    ignored_files.append(str(f.relative_to(path)))
                except ValueError:
                    ignored_files.append(str(f))
                logger.debug("Ignored by pattern: %s", f)
                continue

            if f.suffix.lower() in binary_extensions:
                stats["ignored_as_binary"] += 1
                logger.debug("Ignored as binary: %s (suffix: %s)", f, f.suffix)
                continue

            result.append((str(f), None))
            stats["indexable"] += 1

        # Always log discovery summary at INFO level
        logger.info(
            "File discovery in %s: total=%d, ignored_pattern=%d, ignored_binary=%d, indexable=%d",
            path,
            stats["total_found"],
            stats["ignored_by_pattern"],
            stats["ignored_as_binary"],
            stats["indexable"],
        )

        # Log ignored files at DEBUG level (first 10)
        if ignored_files and logger.isEnabledFor(logging.DEBUG):
            sample = ignored_files[:10]
            logger.debug(
                "Sample ignored files: %s%s",
                sample,
                f" (+{len(ignored_files) - 10} more)" if len(ignored_files) > 10 else "",
            )

        # Warn if nothing to index
        if not result:
            logger.warning(
                "No indexable files found in %s. "
                "Found %d files but all were ignored (pattern=%d, binary=%d). "
                "Check ignore patterns in .gitignore or DEFAULT_IGNORES.",
                path,
                stats["total_found"],
                stats["ignored_by_pattern"],
                stats["ignored_as_binary"],
            )

        return result

    async def _index_sync(
        self,
        path: Path,
        content_type: str,
        operation_id: str,
        timeout: int = 300,
        timeout_per_file: int = 5,
        base_timeout: int = 60
    ) -> "IndexingResult":
        """Synchronous indexing that waits for completion.
        
        This method blocks until all files are indexed and all writes are
        committed to the database. It ensures data is immediately queryable
        upon return.
        
        Args:
            path: Path to file or directory to index
            content_type: Type of content ("file", "directory", "text")
            operation_id: Unique operation identifier
            timeout: Fixed timeout in seconds (used if > 0, otherwise dynamic)
            timeout_per_file: Seconds allowed per file for dynamic timeout
            base_timeout: Base seconds for setup/flush in dynamic timeout
            
        Returns:
            IndexingResult with status="completed" and counts
            
        Raises:
            asyncio.TimeoutError: If indexing exceeds timeout
            Exception: If indexing fails
        """
        from agentic_inquiry.indexing.models import IndexingResult, IndexingError
        from agentic_inquiry.parsers import create_parser_chain

        # Emit started event
        if self.event_system:
            await self.event_system.emit(
                EventTypes.Indexing.STARTED,
                source="IndexingPipeline",
                operation_id=operation_id,
                path=str(path),
                content_type=content_type
            )
        
        # Track progress
        _indexing_start_time = time.time()
        chunks_created = 0
        entities_created = 0
        relationships_created = 0
        files_processed = 0
        files_discovered = 0
        errors: list[IndexingError] = []

        # Track fast-path progress (initialized for diagnostics)
        fast_path_count = 0
        fast_path_complete = False

        try:
            if content_type == "file":
                # Index single file
                files_discovered = 1
                local_path = str(path)
                source_item = None

                # Handle remote file via connector if available
                if self.connector is not None:
                    from agentic_inquiry.connectors.types import SourceItem
                    from agentic_inquiry.connectors.protocols import ChangeDetectionCapability

                    # Create a SourceItem for the single file
                    # Note: For single file indexing, we create a minimal SourceItem
                    source_item = SourceItem(uri=str(path))

                    # Check change detection if available
                    if isinstance(self.connector, ChangeDetectionCapability):
                        if not await self.connector.has_changed(source_item):
                            logger.info("Skipping unchanged file: %s", path)
                            return IndexingResult(
                                operation_id=operation_id,
                                status="completed",
                                chunks_created=0,
                                entities_created=0,
                                files_processed=0,
                                message="File unchanged, skipping"
                            )

                    # Materialize remote content to local path if needed
                    if self.content_materializer is not None:
                        try:
                            local_path = await self.content_materializer.materialize(
                                self.connector, source_item
                            )
                        except Exception as e:
                            logger.error("Failed to materialize %s: %s", path, e)
                            return IndexingResult(
                                operation_id=operation_id,
                                status="failed",
                                message=f"Failed to materialize remote content: {e}"
                            )

                chain = create_parser_chain(config=self.config)
                parsed_doc = await chain.parse(
                    local_path,
                    db_manager=self.db_manager,
                    embedding_service=self.embedding_service,
                    project_id=self.project_id
                )
                # Disable per-document flush during batch indexing for performance
                # Relationships will be flushed at the end of the batch operation
                await self.process_document(parsed_doc, flush_relationships=False)

                # Mark as processed for change detection
                if (
                    source_item is not None
                    and self.connector is not None
                    and isinstance(self.connector, ChangeDetectionCapability)
                ):
                    await self.connector.mark_processed(source_item)

                chunks_created = len(parsed_doc.chunks)
                entities_created = sum(len(chunk.symbols or []) for chunk in parsed_doc.chunks)
                files_processed = 1

                # Flush relationships and capture count
                try:
                    relationships_created = await self.flush_pending_relationships()
                except Exception as e:
                    logger.error("Graph relationship write failed: %s", e)
                    errors.append(_graph_write_indexing_error(e))

            elif content_type == "directory":
                # Discover files using connector or filesystem
                files = await self._discover_files(path)
                files_discovered = len(files)

                # Sort files by priority (fast-path files first)
                # Extract paths for prioritization, maintain source_item mapping
                file_paths = [Path(local_path) for local_path, _ in files]
                sorted_paths = prioritize_files(file_paths, path)

                # Create a mapping from path to source_item for efficient lookup
                path_to_source: Dict[str, Any] = {
                    local_path: source_item for local_path, source_item in files
                }

                # Rebuild files list in priority order
                files = [(str(p), path_to_source.get(str(p))) for p in sorted_paths]

                # Identify fast-path files for progress tracking
                fast_path_files = get_fast_path_files(file_paths, path)
                fast_path_set = {str(f) for f in fast_path_files}
                fast_path_count = len(fast_path_files)
                indexing_start_time = time.monotonic()

                # Calculate dynamic timeout
                if timeout <= 0 or timeout == 300:
                    dynamic_timeout = base_timeout + (len(files) * timeout_per_file)
                    effective_timeout = max(dynamic_timeout, 120)
                else:
                    effective_timeout = timeout

                # Index files with timeout — parallel processing with semaphore
                async def _do_indexing() -> None:
                    nonlocal chunks_created, entities_created, files_processed
                    nonlocal relationships_created, fast_path_complete, fast_path_count
                    from agentic_inquiry.connectors.protocols import ChangeDetectionCapability

                    processed_paths: Set[str] = set()
                    chain = create_parser_chain(config=self.config)
                    total_files = len(files)
                    _progress_lock = asyncio.Lock()

                    async def _process_single_file(
                        local_path: str, source_item: Any
                    ) -> None:
                        """Process a single file. Concurrency is limited by
                        self._processing_semaphore inside process_document()."""
                        nonlocal chunks_created, entities_created, files_processed
                        nonlocal fast_path_complete

                        try:
                            parsed_doc = await chain.parse(
                                local_path,
                                db_manager=self.db_manager,
                                embedding_service=self.embedding_service,
                                project_id=self.project_id
                            )
                            # Disable per-document flush during batch indexing for performance
                            # Relationships will be flushed at the end of the batch operation
                            await self.process_document(parsed_doc, flush_relationships=False)

                            # Update counters under lock for thread safety
                            async with _progress_lock:
                                chunks_created += len(parsed_doc.chunks)
                                entities_created += sum(len(chunk.symbols or []) for chunk in parsed_doc.chunks)
                                files_processed += 1
                                processed_paths.add(local_path)
                                current_processed = files_processed

                            # Mark as processed for change detection
                            if (
                                source_item is not None
                                and self.connector is not None
                                and isinstance(self.connector, ChangeDetectionCapability)
                            ):
                                await self.connector.mark_processed(source_item)

                            # Check if all fast-path files are complete
                            async with _progress_lock:
                                if (
                                    not fast_path_complete
                                    and fast_path_set
                                    and fast_path_set.issubset(processed_paths)
                                ):
                                    fast_path_complete = True
                                    elapsed = time.monotonic() - indexing_start_time
                                    if self.event_system:
                                        await self.event_system.emit(
                                            EventTypes.Indexing.FAST_PATH_COMPLETE,
                                            source="IndexingPipeline",
                                            operation_id=operation_id,
                                            files_indexed=[str(f) for f in fast_path_files],
                                            fast_path_count=len(fast_path_files),
                                            elapsed_seconds=round(elapsed, 3),
                                        )
                                    logger.info(
                                        "Fast-path indexing complete: %d files in %.2fs",
                                        len(fast_path_files),
                                        elapsed,
                                    )

                            # Emit progress periodically
                            should_emit_progress = (
                                total_files <= 100 or
                                current_processed % 10 == 0 or
                                current_processed == total_files
                            )

                            if self.event_system and should_emit_progress:
                                async with _progress_lock:
                                    await self.event_system.emit(
                                        EventTypes.Indexing.PROGRESS,
                                        source="IndexingPipeline",
                                        operation_id=operation_id,
                                        files_processed=files_processed,
                                        chunks_created=chunks_created,
                                        total_files=total_files,
                                        fast_path_complete=fast_path_complete,
                                    )

                            # Periodic maintenance to prevent LanceDB storage bloat
                            maintenance_interval = self.config.indexing.maintenance_interval_files
                            if (
                                maintenance_interval > 0
                                and current_processed > 0
                                and current_processed % maintenance_interval == 0
                            ):
                                try:
                                    maint_result = await self.db_manager.run_maintenance()
                                    logger.info(
                                        "Periodic maintenance at %d files: removed %d versions",
                                        current_processed,
                                        maint_result["summary"]["versions_removed"],
                                    )
                                except Exception as maint_err:
                                    logger.warning(
                                        "Periodic maintenance failed (non-fatal): %s",
                                        maint_err,
                                    )
                        except Exception as e:
                            logger.error("Failed to index file %s: %s", local_path, e)
                            errors.append(IndexingError(
                                file_path=local_path,
                                error_type=type(e).__name__,
                                error_message=str(e),
                                suggestion="Verify file is valid and accessible"
                            ))

                    # Process all files concurrently — _processing_semaphore
                    # inside process_document() limits actual concurrency
                    tasks = [
                        _process_single_file(local_path, source_item)
                        for local_path, source_item in files
                    ]
                    await asyncio.gather(*tasks)

                    # Flush relationships and capture count
                    try:
                        relationships_created = await self.flush_pending_relationships()
                    except Exception as e:
                        logger.error("Graph relationship write failed: %s", e)
                        errors.append(_graph_write_indexing_error(e))

                await asyncio.wait_for(_do_indexing(), timeout=effective_timeout)
            
            # Determine appropriate status based on results
            diagnostics: Dict[str, Any] = {
                "files_discovered": files_discovered,
                "files_processed": files_processed,
                "files_failed": len(errors),
                "fast_path_files": fast_path_count,
                "fast_path_complete": fast_path_complete,
            }

            if files_processed == 0:
                if files_discovered == 0:
                    status = "no_files_found"
                    message = (
                        f"No indexable files found in {path}. "
                        f"Check ignore patterns and file extensions."
                    )
                elif len(errors) == files_discovered:
                    status = "all_files_failed"
                    message = f"All {files_discovered} files failed to index. See errors for details."
                else:
                    status = "partial_failure"
                    message = f"Processed 0 of {files_discovered} files. {len(errors)} errors occurred."
            else:
                if errors:
                    status = "completed_with_errors"
                    message = (
                        f"Indexed {files_processed} file(s) with {len(errors)} error(s). "
                        f"Created {chunks_created} chunks."
                    )
                else:
                    status = "completed"
                    message = f"Successfully indexed {files_processed} file(s). Created {chunks_created} chunks."

            graph_errors = [err for err in errors if err.error_type == "GraphWriteError"]
            if graph_errors:
                message = (
                    f"{message} Graph relationship write failed: "
                    f"{graph_errors[0].error_message}"
                )

            # --- Split event emission: STORED -> embeddings -> READY ---
            storage_duration = time.time() - _indexing_start_time
            embedding_strategy = (
                "server_side" if self._capabilities.needs_embedding_polling
                else "local"
            )

            # Emit indexing.stored — chunks are written to storage
            if self.event_system:
                await self.event_system.emit(
                    EventTypes.Indexing.STORED,
                    source="IndexingPipeline",
                    operation_id=operation_id,
                    files_processed=files_processed,
                    chunks_created=chunks_created,
                    entities_created=entities_created,
                    relationships_created=relationships_created,
                    duration_seconds=storage_duration,
                    embedding_strategy=embedding_strategy,
                )

            # Generate server-side embeddings if backend supports it
            # On fresh tables: uses fast ai.initialize_embeddings() (~400/sec)
            # On tables with gaps: falls back to per-row embedding() (~25/sec)
            # Always runs for server-side backends to pick up any NULL embeddings
            embedding_duration: Optional[float] = None
            if self._capabilities.needs_embedding_polling:
                embed_start = time.time()
                try:
                    await self._generate_server_side_embeddings(diagnostics)
                except Exception as embed_err:
                    logger.warning(
                        "Post-indexing embedding generation failed (non-fatal): %s",
                        embed_err,
                    )
                    diagnostics["embedding_error"] = str(embed_err)

                # Poll until embeddings are complete (or timeout)
                try:
                    await self._poll_embedding_completion()
                except Exception as poll_err:
                    logger.warning(
                        "Embedding polling failed (non-fatal): %s", poll_err,
                    )
                    diagnostics["embedding_poll_error"] = str(poll_err)
                embedding_duration = time.time() - embed_start

            # Emit indexing.ready — index is now searchable
            total_duration = time.time() - _indexing_start_time
            if self.event_system:
                await self.event_system.emit(
                    EventTypes.Indexing.READY,
                    source="IndexingPipeline",
                    operation_id=operation_id,
                    files_processed=files_processed,
                    chunks_created=chunks_created,
                    entities_created=entities_created,
                    relationships_created=relationships_created,
                    duration_seconds=total_duration,
                    embedding_duration_seconds=embedding_duration,
                )

            # Emit deprecated indexing.completed for backward compatibility
            if self.event_system:
                await self.event_system.emit(
                    EventTypes.Indexing.COMPLETED,
                    source="IndexingPipeline",
                    operation_id=operation_id,
                    status=EventStatus.COMPLETED,
                    files_processed=files_processed,
                    chunks_created=chunks_created,
                    entities_created=entities_created,
                    relationships_created=relationships_created,
                    deprecated=True,
                )

            # Run database maintenance after successful indexing to prevent
            # unbounded storage growth from LanceDB's MVCC versioning.
            # This compacts files and removes old versions.
            if files_processed > 0:
                try:
                    maintenance_result = await self.db_manager.run_maintenance()
                    logger.info(
                        "Post-indexing maintenance: reduced %d fragments, removed %d versions",
                        maintenance_result["summary"]["fragments_reduced"],
                        maintenance_result["summary"]["versions_removed"],
                    )
                    diagnostics["maintenance"] = maintenance_result["summary"]
                except Exception as maint_err:
                    # Don't fail the indexing operation if maintenance fails
                    logger.warning(
                        "Post-indexing maintenance failed (non-fatal): %s",
                        maint_err,
                    )
                    diagnostics["maintenance_error"] = str(maint_err)

            return IndexingResult(
                operation_id=operation_id,
                status=status,
                chunks_created=chunks_created,
                entities_created=entities_created,
                relationships_created=relationships_created,
                files_processed=files_processed,
                files_failed=len(errors),
                errors=errors,
                message=message,
                diagnostics=diagnostics,
            )
            
        except asyncio.TimeoutError:
            logger.warning("Indexing timed out: operation_id=%s", operation_id)

            # Even on timeout, chunks/entities are already committed.
            # Generate embeddings for whatever was indexed.
            timeout_diagnostics: Dict[str, Any] = {
                "files_discovered": files_discovered,
                "files_processed": files_processed,
                "files_failed": len(errors),
            }
            if self._capabilities.needs_embedding_polling:
                try:
                    await self._generate_server_side_embeddings(timeout_diagnostics)
                except Exception as embed_err:
                    logger.warning(
                        "Post-timeout embedding generation failed: %s", embed_err,
                    )
                    timeout_diagnostics["embedding_error"] = str(embed_err)

            if self.event_system:
                await self.event_system.emit(
                    EventTypes.Indexing.FAILED,
                    source="IndexingPipeline",
                    operation_id=operation_id,
                    status=EventStatus.FAILED,
                    error="Timeout",
                )

            return IndexingResult(
                operation_id=operation_id,
                status="failed",
                chunks_created=chunks_created,
                entities_created=entities_created,
                relationships_created=relationships_created,
                files_processed=files_processed,
                files_failed=len(errors),
                errors=errors,
                message=f"Indexing timed out after processing {files_processed} file(s)",
                diagnostics=timeout_diagnostics,
            )

        except Exception as e:
            # Distinguish between async cleanup errors and genuine indexing failures.
            # "generator didn't stop after athrow()" is a Python async generator
            # teardown issue that occurs during cleanup, not during data processing.
            # If chunks were successfully created, treat it as a warning, not a failure.
            is_cleanup_error = "generator didn't stop" in str(e) or "athrow" in str(e)
            data_was_created = chunks_created > 0 or entities_created > 0

            if is_cleanup_error and data_was_created:
                logger.warning(
                    "Async cleanup error during indexing (non-fatal, data was created): %s",
                    e,
                )
                return IndexingResult(
                    operation_id=operation_id,
                    status="completed",
                    chunks_created=chunks_created,
                    entities_created=entities_created,
                    relationships_created=relationships_created,
                    files_processed=files_processed,
                    files_failed=len(errors),
                    errors=errors,
                    message=f"Indexing completed with async cleanup warning: {str(e)}",
                    diagnostics={
                        "files_discovered": files_discovered,
                        "files_processed": files_processed,
                        "files_failed": len(errors),
                        "cleanup_warning": str(e),
                    },
                )

            logger.error("Indexing failed: operation_id=%s, error=%s", operation_id, e, exc_info=True)

            if self.event_system:
                await self.event_system.emit(
                    EventTypes.Indexing.FAILED,
                    source="IndexingPipeline",
                    operation_id=operation_id,
                    status=EventStatus.FAILED,
                    error=str(e),
                )

            return IndexingResult(
                operation_id=operation_id,
                status="failed",
                chunks_created=chunks_created,
                entities_created=entities_created,
                relationships_created=relationships_created,
                files_processed=files_processed,
                files_failed=len(errors) + 1,
                errors=errors,
                message=f"Indexing failed: {str(e)}",
                diagnostics={
                    "files_discovered": files_discovered,
                    "files_processed": files_processed,
                    "files_failed": len(errors) + 1,
                },
            )

    async def _index_async(
        self,
        path: Path,
        content_type: str,
        operation_id: str,
        timeout: int = 300,
        timeout_per_file: int = 5,
        base_timeout: int = 60
    ) -> "IndexingResult":
        """Asynchronous indexing that returns immediately.
        
        This method starts indexing in the background and returns immediately
        with status="in_progress". The caller can poll events to check for
        completion.
        
        Args:
            path: Path to file or directory to index
            content_type: Type of content ("file", "directory", "text")
            operation_id: Unique operation identifier
            timeout: Fixed timeout in seconds (used if > 0, otherwise dynamic)
            timeout_per_file: Seconds allowed per file for dynamic timeout
            base_timeout: Base seconds for setup/flush in dynamic timeout
            
        Returns:
            IndexingResult with status="in_progress" and operation_id
        """
        from agentic_inquiry.indexing.models import IndexingResult
        
        # Start indexing in background
        asyncio.create_task(
            self._index_sync(
                path=path,
                content_type=content_type,
                operation_id=operation_id,
                timeout=timeout,
                timeout_per_file=timeout_per_file,
                base_timeout=base_timeout
            )
        )
        
        # Return immediately
        return IndexingResult(
            operation_id=operation_id,
            status="in_progress",
            message=f"Indexing started for {path}"
        )

    async def index_directory(
        self,
        path: str,
        content_type: str = "directory",
        wait: bool = False,
        timeout: int = 300,
        timeout_per_file: int = 5,
        base_timeout: int = 60
    ) -> dict:
        """Index a directory with optional synchronous completion.
        
        This is the main entry point for directory indexing. It supports both
        synchronous (blocking) and asynchronous (background) modes.
        
        Args:
            path: Path to directory to index
            content_type: Type of content (default: "directory")
            wait: If True, block until indexing completes (default: False)
            timeout: Fixed timeout in seconds (used if > 0, otherwise dynamic)
            timeout_per_file: Seconds allowed per file for dynamic timeout
            base_timeout: Base seconds for setup/flush in dynamic timeout
            
        Returns:
            Dictionary with:
                - operation_id: Unique operation identifier
                - status: "completed" (if wait=True) or "in_progress" (if wait=False)
                - chunks_created: Number of chunks created (if wait=True)
                - entities_created: Number of entities created (if wait=True)
                - files_processed: Number of files processed (if wait=True)
                - message: Human-readable status message
                
        Example:
            >>> # Synchronous indexing
            >>> result = await pipeline.index_directory("./src", wait=True)
            >>> print(f"Indexed {result['files_processed']} files")
            
            >>> # Asynchronous indexing
            >>> result = await pipeline.index_directory("./src", wait=False)
            >>> print(f"Started indexing: {result['operation_id']}")
        """
        from pathlib import Path

        # Generate operation ID
        operation_id = self._generate_operation_id()
        
        # Convert path to Path object
        dir_path = Path(path)
        
        # Route to sync or async based on wait parameter
        if wait:
            result = await self._index_sync(
                path=dir_path,
                content_type=content_type,
                operation_id=operation_id,
                timeout=timeout,
                timeout_per_file=timeout_per_file,
                base_timeout=base_timeout
            )
        else:
            result = await self._index_async(
                path=dir_path,
                content_type=content_type,
                operation_id=operation_id,
                timeout=timeout,
                timeout_per_file=timeout_per_file,
                base_timeout=base_timeout
            )
        
        return result.to_dict()

    @property
    def _pending_relationships(self) -> List[Tuple[ParserRelationship, str]]:
        """Access pending relationships from GraphBuilder.
        
        This property provides backward compatibility by exposing the GraphBuilder's
        pending relationships list through the IndexingPipeline interface.
        
        Note: This uses the public GraphBuilder.pending_relationships property
        instead of accessing internal state directly.
        
        Returns:
            List of (relationship, file_path) tuples
        """
        return self.graph_builder.pending_relationships

    async def flush_pending_relationships(
        self,
        use_two_pass: bool = True,
        config: Optional[GraphBuilderConfig] = None,
        return_stats: bool = False,
    ) -> int:
        """Create all pending relationships after all documents are indexed.

        This method delegates to GraphBuilder for batched relationship resolution
        with progress tracking, incremental commits, and event system integration.
        Also flushes any external entities created during relationship resolution.

        Args:
            use_two_pass: Whether to use two-pass resolution (default: True)
            config: Optional GraphBuilderConfig for overriding defaults.
                    If not provided, config will be loaded from pipeline config.
            return_stats: If True, return (count, stats) tuple instead of just count.
                          Default is False for backward compatibility.

        Returns:
            If return_stats=False: Number of relationships created (int)
            If return_stats=True: Tuple of (count, stats_dict)
        """
        # Load config from pipeline config if not provided
        if config is None:
            config = GraphBuilderConfig.from_config(self.config)

        # Delegate to GraphBuilder for batched relationship resolution
        relationships, stats = await self.graph_builder.flush_pending_relationships_batched(
            document_processor=self.document_processor,
            use_two_pass=use_two_pass,
            config=config,
            event_system=self.event_system,
        )

        # Flush any external entities created during resolution
        # Use threshold-based flush for efficiency
        external_count = await self.graph_builder.flush_external_entities_if_needed(
            config=config,
            event_system=self.event_system,
        )
        if external_count > 0:
            logger.info("Flushed %d external entities to graph", external_count)

        # Also flush any remaining external entities (for small batches)
        remaining_entities = await self.graph_builder.flush_external_entities(
            document_processor=self.document_processor,
        )
        if remaining_entities:
            # Pass GraphEntity objects directly - add_graph_entities expects objects, not dicts
            await self.db_manager.add_graph_entities(remaining_entities)
            logger.info(
                "Flushed %d remaining external entities to graph",
                len(remaining_entities),
            )

        # Store statistics for backward compatibility and diagnostics
        self._last_resolution_stats = stats

        # Handle timeout status
        if stats.get("timed_out"):
            logger.warning(
                "Relationship flush timed out after %.1fs. "
                "Partial results: %d/%d relationships created",
                stats.get("timeout_at_elapsed", 0),
                len(relationships),
                stats.get("original_total", 0),
            )

        # Return based on return_stats flag for backward compatibility
        if return_stats:
            return len(relationships), stats  # type: ignore[return-value]
        return len(relationships)
    
    def get_resolution_stats(self) -> Optional[Dict[str, Any]]:
        """Get statistics from the last relationship resolution.
        
        Returns:
            Dictionary containing resolution statistics including:
            - total: Total relationships processed
            - resolved_cross_file: Successfully resolved cross-file imports
            - unresolved_external: External/stdlib dependencies (not resolved)
            - same_file_fallback: Relationships resolved to same file
            - by_strategy: Breakdown by resolution strategy
            - confidence_levels: Distribution of confidence scores
            - average_confidence: Mean confidence score
            - resolution_time_seconds: Time taken for resolution
            - two_pass_enabled: Whether two-pass resolution was used
            - first_pass_resolved: Relationships resolved in first pass
            - second_pass_improved: Relationships improved in second pass
            
            Returns None if no resolution has been performed yet.
        """
        # Delegate to GraphBuilder
        return self.graph_builder.get_resolution_stats()

    
    def _infer_type_from_file(self, file_path: str) -> Optional[str]:
        """Infer the most common entity type from a file using Symbol Registry.
        
        This is useful when we know a file path but need to determine what type
        of entity it represents (e.g., is it a module, class, or function file?).
        
        The method looks up all symbols registered from the file and returns
        the most common entity type. If the file has no registered symbols,
        it returns "module" as a default.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Most common entity type (e.g., "class", "function", "module") or None
        """
        # Check if file has any registered symbols
        if file_path not in self.symbol_registry._by_file:
            logger.debug("No symbols found for file %s, inferring type as 'module'", file_path)
            return "module"  # Default to module for files with no symbols
        
        # Get all symbols from this file
        symbol_names = self.symbol_registry._by_file[file_path]
        
        # Count entity types
        type_counts: Dict[str, int] = {}
        for symbol_name in symbol_names:
            metadata_list = self.symbol_registry.lookup_by_name(symbol_name)
            for metadata in metadata_list:
                if metadata.file_path == file_path:
                    entity_type = metadata.entity_type
                    type_counts[entity_type] = type_counts.get(entity_type, 0) + 1
        
        if not type_counts:
            logger.debug("No entity types found for file %s, inferring type as 'module'", file_path)
            return "module"
        
        # Return most common type
        most_common_type = max(type_counts.items(), key=lambda x: x[1])[0]
        logger.debug(
            f"Inferred type for {file_path}: {most_common_type} "
            f"(counts: {type_counts})"
        )
        return most_common_type
    


    def _build_metadata_payload(
        self,
        metadata: Optional[Dict[str, Any]],
        ranking_signals: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build a metadata payload by merging metadata and ranking signals.
        
        Args:
            metadata: Optional metadata dictionary
            ranking_signals: Optional ranking signals dictionary
            
        Returns:
            Merged metadata payload with ranking_signals nested under "ranking_signals" key
        """
        payload: Dict[str, Any] = {}
        if isinstance(metadata, dict):
            payload.update(metadata)
        if isinstance(ranking_signals, dict):
            container = payload.get("ranking_signals")
            if not isinstance(container, dict):
                container = {}
            else:
                container = container.copy()
            container.update(ranking_signals)
            payload["ranking_signals"] = container
        return payload

    def _normalise_relationship(self, relationship: Any) -> ParserRelationship:
        """Normalize a relationship to ParserRelationship type.
        
        Args:
            relationship: Relationship object (ParserRelationship or dict)
            
        Returns:
            ParserRelationship object
            
        Raises:
            TypeError: If relationship is not a ParserRelationship or dict
        """
        if isinstance(relationship, ParserRelationship):
            return relationship
        if isinstance(relationship, dict):
            allowed = {field.name for field in dataclass_fields(ParserRelationship)}
            filtered = {key: value for key, value in relationship.items() if key in allowed}
            return ParserRelationship(**filtered)
        raise TypeError("Unsupported relationship type %r" % (relationship,))

    def _chunk_relationships(self, chunk: ParserChunk) -> Iterable[ParserRelationship]:
        """Extract and normalize relationships from a parser chunk.
        
        Args:
            chunk: ParserChunk containing relationships
            
        Yields:
            Normalized ParserRelationship objects
        """
        for relationship in chunk.relationships:
            yield self._normalise_relationship(relationship)

    def _get_embedder_configuration(self, table: str, column: str):
        """Deprecated: Use embedding_service.get_embedder_configuration instead."""
        return self.embedding_service.get_embedder_configuration(table, column)

    async def _generate_embeddings_batch(
        self,
        texts: List[str],
        embedder,
        operation_name: str = "embedding generation",
    ) -> List[List[float]]:
        """Deprecated: Use embedding_service.generate_embeddings_batch instead."""
        return await self.embedding_service.generate_embeddings_batch(
            texts, embedder, operation_name
        )

    async def _register_symbols_batch(
        self,
        symbols_data: List[Dict[str, Any]],
    ) -> None:
        """Register multiple symbols in parallel with error handling.
        
        This method registers symbols in parallel using asyncio.gather()
        with proper error handling. If any registration fails, it logs
        the error but continues with other registrations.
        
        Args:
            symbols_data: List of dictionaries containing symbol registration data
                Each dict should have: name, file_path, entity_type, language,
                line_start, line_end, parent_scope, is_exported
        """
        if not symbols_data:
            return
        
        # Create registration tasks
        tasks = [
            self.symbol_registry.register(**data)
            for data in symbols_data
        ]
        
        # Run registrations in parallel with error handling
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Log any errors
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                symbol_name = symbols_data[i].get("name", "unknown")
                file_path = symbols_data[i].get("file_path", "unknown")
                logger.error(
                    f"Failed to register symbol {symbol_name} in {file_path}: {result}",
                    exc_info=result,
                )













    @validate_path()
    async def remove_file_data(self, file_path: str) -> None:
        """Remove all data associated with a file for incremental updates.
        
        This method removes:
        - Symbols from the symbol registry
        - Document chunks from the database
        - Graph entities from the database
        - Graph relationships from the database
        
        This should be called before re-indexing a file to ensure no stale
        data remains.
        
        Args:
            file_path: Path to the file whose data should be removed.
                      Must be within the project root directory.
                      Path validation is performed automatically to prevent
                      directory traversal attacks.
        
        Raises:
            PathValidationError: If file_path is outside the project root
        """
        logger.info("Removing data for file: %s", file_path)
        
        # Step 1: Remove symbols from symbol registry
        # This must be done first to prevent resolution of stale symbols
        self.symbol_registry.remove_file_symbols(file_path)
        logger.debug("Removed symbols from registry for %s", file_path)
        
        # Step 2: Clear resolution cache to invalidate cached resolutions
        # that may reference the removed symbols
        self.symbol_registry.clear_cache()
        logger.debug("Cleared resolution cache after removing %s", file_path)
        
        # Step 3: Find and delete document chunks for this file
        try:
            chunks = await self.db_manager.query_raw(
                table_name="document_chunks",
                filters={"file_path": file_path}
            )
            chunk_ids = [chunk["id"] for chunk in chunks]
            if chunk_ids:
                await self.db_manager.delete_document_chunks(chunk_ids)
                logger.debug("Deleted %s document chunks for %s", len(chunk_ids), file_path)
        except Exception as e:
            logger.warning("Failed to delete document chunks for %s: %s", file_path, e, exc_info=True)
        
        # Step 4: Find and delete graph entities for this file
        try:
            entities = await self.db_manager.query_raw(
                table_name="graph_entities",
                filters={"file_path": file_path}
            )
            entity_ids = [entity["id"] for entity in entities]
            if entity_ids:
                await self.db_manager.delete_graph_entities(entity_ids)
                logger.debug("Deleted %s graph entities for %s", len(entity_ids), file_path)
        except Exception as e:
            logger.warning("Failed to delete graph entities for %s: %s", file_path, e, exc_info=True)
        
        # Step 5: Find and delete graph relationships originating from this file
        # Relationships are identified by source_id which contains the file path
        try:
            # Get all relationships
            all_relationships = await self.db_manager.query_raw(
                table_name="graph_relationships"
            )
            
            # Filter relationships that originate from this file
            # source_id format: "{type}::{project_hash}::{file_path}::{name}"
            relationship_ids = [
                rel["id"] for rel in all_relationships
                if f"::{self.project_hash}::{file_path}::" in rel.get("source_id", "")
            ]
            
            if relationship_ids:
                await self.db_manager.delete_graph_relationships(relationship_ids)
                logger.debug("Deleted %s graph relationships for %s", len(relationship_ids), file_path)
        except Exception as e:
            logger.warning("Failed to delete graph relationships for %s: %s", file_path, e, exc_info=True)
        
        # Step 6: Remove any pending relationships for this file
        # This prevents stale relationships from being flushed later
        removed_count = self.graph_builder.remove_pending_relationships_for_file(file_path)
        if removed_count > 0:
            logger.debug("Removed %s pending relationships for %s", removed_count, file_path)
        
        logger.info("Successfully removed all data for file: %s", file_path)
    
    async def reindex_document(self, parsed_document: ParsedDocument) -> None:
        """Re-index a document by removing old data and processing the new version.
        
        This is a convenience method that combines remove_file_data() and
        process_document() to handle incremental updates. It ensures that:
        1. Old symbols are removed from the registry
        2. Resolution cache is cleared
        3. Old database entries are deleted
        4. New data is indexed
        
        After calling this method, you should call flush_pending_relationships()
        to update the graph relationships.
        
        Args:
            parsed_document: The newly parsed document to index.
                           The file_path in parsed_document must be within
                           the project root directory. Path validation is
                           performed automatically to prevent directory
                           traversal attacks.
            
        Raises:
            PathValidationError: If file_path in parsed_document is outside
                               the project root
            
        Example:
            >>> # File was modified, re-parse and re-index
            >>> parsed_doc = parser.parse(file_path)
            >>> await pipeline.reindex_document(parsed_doc)
            >>> await pipeline.flush_pending_relationships()
        """
        file_path = parsed_document.file_path
        logger.info("Re-indexing document: %s", file_path)
        
        # Remove old data (path validation happens in remove_file_data)
        await self.remove_file_data(file_path)
        
        # Process new version
        await self.process_document(parsed_document)
        
        logger.info("Successfully re-indexed document: %s", file_path)
    
    async def validate_relationships(
        self,
        check_circular_dependencies: bool = False
    ) -> Dict[str, Any]:
        """Validate relationship integrity and check for broken links.
        
        This method performs comprehensive validation of the graph relationships:
        1. Verifies all target entities exist in the database
        2. Checks for broken links (target_id points to non-existent entity)
        3. Reports validation issues with details
        4. Optionally detects circular dependencies
        
        The validation is performed on the database state, not pending relationships.
        Call flush_pending_relationships() before validation to ensure all
        relationships are materialized.
        
        Args:
            check_circular_dependencies: If True, detect circular dependency chains.
                                        This can be expensive for large graphs.
        
        Returns:
            Dictionary containing validation results:
            {
                "total_relationships": int,
                "valid_relationships": int,
                "broken_links": [
                    {
                        "relationship_id": str,
                        "source_id": str,
                        "target_id": str,
                        "type": str,
                        "issue": str,
                        "details": str
                    },
                    ...
                ],
                "circular_dependencies": [  # Only if check_circular_dependencies=True
                    {
                        "cycle": [entity_id1, entity_id2, ..., entity_id1],
                        "length": int
                    },
                    ...
                ],
                "summary": {
                    "broken_count": int,
                    "circular_count": int,  # Only if check_circular_dependencies=True
                    "health_percentage": float
                }
            }
        
        Example:
            >>> # After indexing and flushing relationships
            >>> validation_results = await pipeline.validate_relationships()
            >>> if validation_results["broken_links"]:
            ...     print(f"Found {len(validation_results['broken_links'])} broken links")
            ...     for issue in validation_results["broken_links"]:
            ...         print(f"  - {issue['relationship_id']}: {issue['issue']}")
            >>> print(f"Graph health: {validation_results['summary']['health_percentage']:.1f}%")
        """
        logger.info("Starting relationship validation...")
        
        # Initialize results structure
        results: Dict[str, Any] = {
            "total_relationships": 0,
            "valid_relationships": 0,
            "broken_links": [],
            "summary": {}
        }
        
        # Step 1: Get all relationships from database
        try:
            all_relationships = await self.db_manager.query_raw(table_name="graph_relationships")
            results["total_relationships"] = len(all_relationships)
            logger.info("Validating %s relationships", results["total_relationships"])
        except Exception as e:
            logger.error("Failed to fetch relationships for validation: %s", e, exc_info=True)
            results["summary"] = {
                "broken_count": 0,
                "health_percentage": 0.0,
                "error": str(e)
            }
            return results
        
        if not all_relationships:
            logger.info("No relationships to validate")
            results["summary"] = {
                "broken_count": 0,
                "health_percentage": 100.0
            }
            return results
        
        # Step 2: Get all entity IDs for existence checking
        try:
            all_entities = await self.db_manager.query_raw(table_name="graph_entities")
            entity_ids = {entity["id"] for entity in all_entities}
            logger.debug("Found %s entities in database", len(entity_ids))
        except Exception as e:
            logger.error("Failed to fetch entities for validation: %s", e, exc_info=True)
            results["summary"] = {
                "broken_count": 0,
                "health_percentage": 0.0,
                "error": str(e)
            }
            return results
        
        # Step 3: Validate each relationship
        broken_links = []
        valid_count = 0
        
        for rel in all_relationships:
            rel_id = rel.get("id", "unknown")
            source_id = rel.get("source_id", "")
            target_id = rel.get("target_id", "")
            rel_type = rel.get("type", "unknown")
            
            # Check if source entity exists
            source_exists = source_id in entity_ids
            
            # Check if target entity exists
            target_exists = target_id in entity_ids
            
            # Report issues
            if not source_exists and not target_exists:
                broken_links.append({
                    "relationship_id": rel_id,
                    "source_id": source_id,
                    "target_id": target_id,
                    "type": rel_type,
                    "issue": "both_missing",
                    "details": f"Both source entity '{source_id}' and target entity '{target_id}' do not exist"
                })
            elif not source_exists:
                broken_links.append({
                    "relationship_id": rel_id,
                    "source_id": source_id,
                    "target_id": target_id,
                    "type": rel_type,
                    "issue": "source_missing",
                    "details": f"Source entity '{source_id}' does not exist"
                })
            elif not target_exists:
                broken_links.append({
                    "relationship_id": rel_id,
                    "source_id": source_id,
                    "target_id": target_id,
                    "type": rel_type,
                    "issue": "target_missing",
                    "details": f"Target entity '{target_id}' does not exist"
                })
            else:
                valid_count += 1
        
        results["valid_relationships"] = valid_count
        results["broken_links"] = broken_links
        
        # Log broken links
        if broken_links:
            logger.warning("Found %s broken links:", len(broken_links))
            for issue in broken_links[:10]:  # Log first 10
                logger.warning(
                    "  - %s (%s): %s - %s",
                    issue['relationship_id'],
                    issue['type'],
                    issue['issue'],
                    issue['details']
                )
            if len(broken_links) > 10:
                logger.warning("  ... and %s more", len(broken_links) - 10)
        else:
            logger.info("No broken links found")
        
        # Step 4: Optional circular dependency detection
        if check_circular_dependencies:
            logger.info("Checking for circular dependencies...")
            circular_deps = self._detect_circular_dependencies(all_relationships, entity_ids)
            results["circular_dependencies"] = circular_deps
            
            if circular_deps:
                logger.warning("Found %s circular dependency chains:", len(circular_deps))
                for cycle_info in circular_deps[:5]:  # Log first 5
                    cycle = cycle_info["cycle"]
                    logger.warning("  - Cycle of length %s: %s...", cycle_info['length'], ' -> '.join(cycle[:4]))
                if len(circular_deps) > 5:
                    logger.warning("  ... and %s more", len(circular_deps) - 5)
            else:
                logger.info("No circular dependencies found")
        
        # Step 5: Calculate summary statistics
        broken_count = len(broken_links)
        health_percentage = (valid_count / results["total_relationships"] * 100) if results["total_relationships"] > 0 else 100.0
        
        summary = {
            "broken_count": broken_count,
            "health_percentage": health_percentage
        }
        
        if check_circular_dependencies:
            summary["circular_count"] = len(results.get("circular_dependencies", []))
        
        results["summary"] = summary
        
        logger.info(
            f"Validation complete: {valid_count}/{results['total_relationships']} valid "
            f"({health_percentage:.1f}% health), {broken_count} broken links"
        )
        
        return results
    
    def _detect_circular_dependencies(
        self,
        relationships: List[Dict[str, Any]],
        entity_ids: Set[str]
    ) -> List[Dict[str, Any]]:
        """Detect circular dependency chains in the relationship graph.
        
        Uses depth-first search to find cycles in the directed graph.
        Only considers relationships where both source and target exist.
        
        Args:
            relationships: List of relationship dictionaries
            entity_ids: Set of valid entity IDs
        
        Returns:
            List of circular dependency information:
            [
                {
                    "cycle": [entity_id1, entity_id2, ..., entity_id1],
                    "length": int
                },
                ...
            ]
        """
        # Build adjacency list (only for valid relationships)
        graph: Dict[str, List[str]] = {}
        for rel in relationships:
            source_id = rel.get("source_id", "")
            target_id = rel.get("target_id", "")
            
            # Only include if both entities exist
            if source_id in entity_ids and target_id in entity_ids:
                if source_id not in graph:
                    graph[source_id] = []
                graph[source_id].append(target_id)
        
        # Find cycles using DFS
        visited: Set[str] = set()
        rec_stack: Set[str] = set()
        cycles: List[Dict[str, Any]] = []
        
        def dfs(node: str, path: List[str]) -> None:
            """Depth-first search to detect cycles."""
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            # Visit all neighbors
            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    dfs(neighbor, path.copy())
                elif neighbor in rec_stack:
                    # Found a cycle
                    cycle_start_idx = path.index(neighbor)
                    cycle = path[cycle_start_idx:] + [neighbor]
                    
                    # Avoid duplicate cycles (same cycle in different order)
                    # Normalize by rotating to start with smallest ID
                    normalized = self._normalize_cycle(cycle[:-1])  # Remove duplicate end node
                    
                    # Check if we already found this cycle
                    if not any(c["cycle"][:-1] == normalized for c in cycles):
                        cycles.append({
                            "cycle": normalized + [normalized[0]],  # Add end node back
                            "length": len(normalized)
                        })
            
            path.pop()
            rec_stack.remove(node)
        
        # Run DFS from each unvisited node
        for node in graph:
            if node not in visited:
                dfs(node, [])
        
        return cycles
    
    def _normalize_cycle(self, cycle: List[str]) -> List[str]:
        """Normalize a cycle by rotating to start with the smallest ID.
        
        This ensures that cycles like [A, B, C] and [B, C, A] are treated as the same.
        
        Args:
            cycle: List of entity IDs forming a cycle
        
        Returns:
            Normalized cycle starting with smallest ID
        """
        if not cycle:
            return cycle
        
        min_idx = cycle.index(min(cycle))
        return cycle[min_idx:] + cycle[:min_idx]
    
    async def get_cached_document(self, file_path: str) -> Optional[ParsedDocument]:
        """Check if a parsed document is available in cache.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Cached ParsedDocument if available and valid, None otherwise
        """
        if self.cache is None:
            return None
        
        try:
            cached_doc = await self.cache.get(file_path)
            if cached_doc is not None:
                logger.debug("Cache hit for %s", file_path)
                return cached_doc
            else:
                logger.debug("Cache miss for %s", file_path)
                return None
        except Exception as e:
            logger.warning("Cache lookup failed for %s: %s", file_path, e)
            return None
    
    async def cache_document(self, parsed_document: ParsedDocument) -> None:
        """Store a parsed document in cache.
        
        Args:
            parsed_document: The parsed document to cache
        """
        if self.cache is None:
            return
        
        try:
            await self.cache.put(parsed_document.file_path, parsed_document)
            logger.debug("Cached parsed document for %s", parsed_document.file_path)
        except Exception as e:
            logger.warning("Failed to cache document %s: %s", parsed_document.file_path, e, exc_info=True)
    
    async def invalidate_cache(self, file_path: str) -> None:
        """Invalidate cache entry for a file.

        Args:
            file_path: Path to the file to invalidate
        """
        # Delegate to file watch manager
        await self._file_watch_manager._invalidate_cache(file_path)

    def stop_watching(self) -> None:
        """Stop the file watcher and clean up resources.

        This method stops the file watcher if it's running and cleans up
        any associated resources. It's safe to call this method even if
        no watcher is active.

        Example:
            >>> pipeline = IndexingPipeline(
            ...     db_manager,
            ...     project_root,
            ...     watcher_name="default",
            ...     auto_watch=True
            ... )
            >>> # ... do some work ...
            >>> pipeline.stop_watching()  # Stop watching when done
        """
        # Delegate to file watch manager
        self._file_watch_manager.stop_watching()
    
    async def process_document(
        self,
        parsed_document: ParsedDocument,
        flush_relationships: bool = True,
    ) -> None:
        # Use semaphore to limit concurrent document processing
        async with self._processing_semaphore:
            await self._process_document_impl(parsed_document, flush_relationships)

    async def _process_document_impl(
        self,
        parsed_document: ParsedDocument,
        flush_relationships: bool = True,
    ) -> None:
        # Track the entire indexing operation
        async with track_operation(
            self.event_system,
            "indexing",
            source="IndexingPipeline",
            file_path=parsed_document.file_path,
            doc_id=parsed_document.doc_id,
        ) as op:
            try:
                # Cache the parsed document if caching is enabled
                await self.cache_document(parsed_document)
                
                doc_chunks: List[DocumentChunk] = []
                graph_relationships: List[GraphRelationship] = []

                # Check if backend uses server-side embeddings (e.g. AlloyDB)
                from agentic_inquiry.storage.capabilities import get_capabilities_for_backend
                _caps = get_capabilities_for_backend(self._backend_type)
                _skip_local_embedding = _caps.uses_server_side_embedding

                if _skip_local_embedding:
                    chunk_embedder, chunk_dims = None, 768  # text-embedding-005 dimensionality
                    logger.debug("Server-side embedding backend: skipping local chunk embedding generation")
                else:
                    chunk_embedder, chunk_dims = self.embedding_service.get_embedder_configuration("document_chunks", "vector")

                stats = {
                    "skipped_chunks": 0,
                    "fallback_chunks": 0,
                    "duplicate_entities": 0,
                }

                # Store original total chunks count before filtering
                original_total_chunks = len(parsed_document.chunks)

                # Split oversized chunks if configured
                max_chunk_size = getattr(
                    getattr(self.config, "indexing", None),
                    "max_chunk_content_size",
                    0,
                )
                chunks_for_processing = list(parsed_document.chunks)
                if max_chunk_size > 0:
                    from agentic_inquiry.indexing.chunk_splitter import (
                        split_parser_chunks,
                    )
                    chunks_for_processing = split_parser_chunks(
                        chunks_for_processing, max_chunk_size
                    )
                    if len(chunks_for_processing) != original_total_chunks:
                        logger.info(
                            "Chunk splitting: %d → %d chunks for %s",
                            original_total_chunks,
                            len(chunks_for_processing),
                            parsed_document.file_path,
                        )
                        # Update total to reflect post-split count for
                        # correct chunk_index/total_chunks in storage
                        original_total_chunks = len(chunks_for_processing)

                # Step 1: Collect chunks and generate embeddings.
                #
                # Pass 1 — resolve embedding text per chunk, skip invalid
                # chunks (empty content, missing embedding text), and keep
                # the surviving chunks paired with their texts. Emit
                # skipped-chunk events here because they're per-chunk
                # decisions, not batch-level.
                #
                # Pass 2 — one batched ``generate(texts)`` call so the model
                # runs once over the whole file's chunks instead of N times
                # over single-item lists. Previously this loop called
                # ``generate([embedding_text])`` inside the per-chunk body,
                # which negated sentence-transformer's internal batching and
                # left GPUs idle between 1-item calls; batching recovers a
                # 2-3x speedup on CPU and is the main unlock for GPU /
                # MPS paths that need ≥32-item batches to saturate.
                chunks_to_process: List[ParserChunk] = []
                vectors_to_process: List[List[float]] = []
                texts_to_embed: List[str] = []
                chunks_awaiting_embedding: List[ParserChunk] = []

                for index, chunk in enumerate(chunks_for_processing):
                    doc_chunk_id = f"{parsed_document.doc_id}_{index}"

                    if _skip_local_embedding:
                        # AlloyDB: no embedding needed, just validate chunk has content
                        if not chunk.content:
                            stats["skipped_chunks"] += 1
                            logger.warning(
                                "Skipping chunk %s for document %s: empty content",
                                doc_chunk_id,
                                parsed_document.doc_id,
                            )
                            continue
                        chunks_to_process.append(chunk)
                        # Empty vector placeholder - AlloyDB generates real embedding from content
                        vectors_to_process.append([0.0] * chunk_dims)
                        continue

                    embedding_text, used_fallback = self.document_processor._resolve_embedding_text(chunk, chunk_embedder)
                    if embedding_text is None:
                        stats["skipped_chunks"] += 1
                        # Emit event for skipped chunk
                        if self.event_system is not None:
                            await self.event_system.emit(
                                EventTypes.Indexing.FILE_SKIPPED,
                                source="IndexingPipeline",
                                status=EventStatus.PROGRESS,
                                file_path=parsed_document.file_path,
                                doc_id=parsed_document.doc_id,
                                chunk_id=doc_chunk_id,
                                reason="missing_embedding_text",
                            )
                        logger.warning(
                            "Skipping chunk %s for document %s: missing embedding text",
                            doc_chunk_id,
                            parsed_document.doc_id,
                        )
                        continue

                    if used_fallback:
                        stats["fallback_chunks"] += 1
                        logger.debug(
                            "Using fallback embedding text for chunk %s of document %s",
                            doc_chunk_id,
                            parsed_document.doc_id
                        )
                        # Update chunk's content field with fallback text so it passes validation
                        chunk.content = embedding_text

                    texts_to_embed.append(embedding_text)
                    chunks_awaiting_embedding.append(chunk)

                # Pass 2: batched embedding. One call into the executor for
                # the whole file — ``generate`` handles the list in a single
                # model forward pass.
                #
                # Batch-then-per-item retry (NOT per-chunk error isolation):
                # if the batched forward pass raises (e.g. tensor-shape
                # issues, device-memory blip), we retry per-chunk
                # ``generate([text])``. This rescues batch-level failures
                # where each chunk on its own would have succeeded. It does
                # *not* isolate per-chunk failures — if one specific chunk
                # raises in the per-item retry, the whole document still
                # fails, same as pre-batching behaviour. True per-chunk
                # isolation would need a try/except per item plus
                # ``stats["skipped_chunks"]`` bookkeeping and a FILE_SKIPPED
                # event, which wasn't in the original contract; not worth
                # the added complexity given the practical hit rate.
                # Mirrors the contract of ``EmbeddingService.generate_embeddings_batch``
                # but keeps the executor offload — that helper runs
                # ``generate`` synchronously and would block the event loop.
                #
                # Memory note: ``texts_to_embed`` and ``batch_vectors`` hold
                # the whole file's worth of chunks simultaneously during
                # this stage. For 384-dim float vectors that's ~3KB per
                # chunk, so a 10k-chunk monolithic file is ~30 MB — rare
                # but not zero. Peak per-document memory for embedding
                # roughly doubles vs. the old per-chunk loop; fine for
                # typical workloads.
                if texts_to_embed:
                    loop = asyncio.get_running_loop()
                    try:
                        batch_vectors = await loop.run_in_executor(
                            get_embedding_executor(),
                            chunk_embedder.generate,
                            texts_to_embed,
                        )
                    except Exception as batch_err:
                        logger.warning(
                            "Batch embedding failed for document %s (%d chunks); "
                            "falling back to per-chunk generation: %s",
                            parsed_document.doc_id,
                            len(texts_to_embed),
                            batch_err,
                        )
                        batch_vectors = []
                        for text in texts_to_embed:
                            chunk_vectors = await loop.run_in_executor(
                                get_embedding_executor(),
                                chunk_embedder.generate,
                                [text],
                            )
                            batch_vectors.append(chunk_vectors[0])

                    if len(batch_vectors) != len(chunks_awaiting_embedding):
                        # Defensive: embedders must return one vector per
                        # input text. A mismatch means a provider bug; fail
                        # loud rather than silently misaligning vectors with
                        # chunks (which would corrupt search results).
                        raise RuntimeError(
                            f"Embedder returned {len(batch_vectors)} vectors for "
                            f"{len(chunks_awaiting_embedding)} inputs while processing "
                            f"document {parsed_document.doc_id}"
                        )
                    for chunk, vector in zip(chunks_awaiting_embedding, batch_vectors):
                        self.document_processor._validate_vector(
                            "document_chunks", "vector", vector, chunk_dims
                        )
                        chunks_to_process.append(chunk)
                        vectors_to_process.append(vector)
                
                # Step 2: Process all chunks with SchemaProcessor (validates, transforms, sanitizes)
                # Note: SchemaProcessor now handles database writes internally via transaction
                if chunks_to_process:
                    try:
                        # SchemaProcessor.process_chunks() now writes to DB and returns records
                        # Pass original_total_chunks so total_chunks field reflects original count
                        chunk_records = await self.schema_processor.process_chunks(
                            chunks=chunks_to_process,
                            parsed_document=parsed_document,
                            vectors=vectors_to_process,
                            project_id=self.project_id,
                            original_total_chunks=original_total_chunks
                        )
                        
                        # Convert records to DocumentChunk objects for use in graph building
                        for record in chunk_records:
                            doc_chunk = DocumentChunk(**record)
                            doc_chunks.append(doc_chunk)
                            
                    except Exception as e:
                        logger.error(
                            "Schema processing failed for document %s: %s",
                            parsed_document.doc_id,
                            e,
                            exc_info=True
                        )
                        raise
                
                # Emit progress event after processing chunks
                await op.progress(
                    chunks_processed=len(doc_chunks),
                    chunks_skipped=stats["skipped_chunks"],
                    chunks_fallback=stats["fallback_chunks"],
                )
                
                # Use GraphBuilder to create graph entities from chunks
                graph_entities, entity_stats = await self.graph_builder.create_graph_entities(
                    parsed_document=parsed_document,
                    chunks=parsed_document.chunks,
                    document_processor=self.document_processor,
                )
                
                # De-duplicate entities before adding to transaction
                unique_entities: Dict[str, Any] = {}
                for entity in graph_entities:
                    if entity.id in unique_entities:
                        stats["duplicate_entities"] += 1
                        logger.warning("Duplicate entity ID found and removed: %s", entity.id)
                    else:
                        unique_entities[entity.id] = entity
                
                deduplicated_entities = list(unique_entities.values())
                
                # Note: doc_chunks are already written to DB by SchemaProcessor
                # Only write graph entities and relationships here
                async with Transaction(self.db_manager) as transaction:
                    if deduplicated_entities:
                        transaction.add_operation(
                            self.db_manager.add_graph_entities,
                            deduplicated_entities,
                            rollback_operation=self.db_manager.delete_graph_entities,
                            rollback_data=[entity.id for entity in graph_entities],
                        )
                    if graph_relationships:
                        transaction.add_operation(
                            self.db_manager.add_graph_relationships,
                            graph_relationships,
                            rollback_operation=self.db_manager.delete_graph_relationships,
                            rollback_data=[relationship.id for relationship in graph_relationships],
                        )
                    await transaction.commit()

                # Flush any pending relationships that were queued during entity creation
                # Only flush if explicitly requested (disabled during batch indexing for performance)
                relationships_created = 0
                if flush_relationships:
                    try:
                        relationships_created = await self.flush_pending_relationships(
                            use_two_pass=True,
                            return_stats=False,
                        )
                        if relationships_created > 0:
                            logger.info(
                                "Flushed %d relationships for document %s",
                                relationships_created,
                                parsed_document.file_path,
                            )
                    except Exception as e:
                        logger.error(
                            "Failed to flush relationships for document %s: %s",
                            parsed_document.file_path,
                            e,
                        )
                        raise

                # Store relationships_created in stats for later use
                stats["relationships_created"] = relationships_created

                # Emit success event for indexed file
                if self.event_system is not None:
                    await self.event_system.emit(
                        EventTypes.Indexing.FILE_INDEXED,
                        source="IndexingPipeline",
                        status=EventStatus.COMPLETED,
                        file_path=parsed_document.file_path,
                        doc_id=parsed_document.doc_id,
                        chunks_indexed=len(doc_chunks),
                        entities_created=len(graph_entities),
                        relationships_created=relationships_created,
                    )

                # Log processing statistics
                if stats["skipped_chunks"]:
                    logger.warning(
                        "Document %s: skipped %d chunk(s) lacking embedding text",
                        parsed_document.doc_id,
                        stats["skipped_chunks"]
                    )
                if stats["fallback_chunks"]:
                    logger.debug(
                        "Document %s: fallback embedding text used for %d chunk(s)",
                        parsed_document.doc_id,
                        stats["fallback_chunks"]
                    )
                
                # Log entity registration statistics
                if stats.get("document_entities", 0) > 0:
                    logger.info(
                        "Document %s: registered %d document entities (headings, sections, tables, figures) in symbol registry",
                        parsed_document.doc_id,
                        stats["document_entities"]
                    )
                if stats.get("code_entities", 0) > 0:
                    logger.info(
                        "Document %s: registered %d code entities (functions, classes, etc.) in symbol registry",
                        parsed_document.doc_id,
                        stats["code_entities"]
                    )
                if stats.get("document_relationships", 0) > 0:
                    logger.info(
                        "Document %s: collected %d document relationships (contains, follows) for later processing",
                        parsed_document.doc_id,
                        stats["document_relationships"]
                    )
            
            except SchemaValidationError as e:
                # Log detailed schema validation error
                logger.error(
                    "Schema validation failed for document %s: %s",
                    parsed_document.doc_id,
                    str(e),
                    extra={
                        "project_id": self.project_id,
                        "file_path": parsed_document.file_path,
                        "doc_id": parsed_document.doc_id,
                        "table_name": e.table_name,
                        "missing_fields": e.missing_fields,
                        "type_mismatches": e.type_mismatches,
                    }
                )
                
                # Emit failure event with schema details
                if self.event_system is not None:
                    await self.event_system.emit(
                        EventTypes.Indexing.FILE_FAILED,
                        source="IndexingPipeline",
                        status=EventStatus.FAILED,
                        file_path=parsed_document.file_path,
                        doc_id=parsed_document.doc_id,
                        error=str(e),
                        error_type="schema_validation",
                        table_name=e.table_name,
                        missing_fields=e.missing_fields,
                    )
                raise

            except Exception as e:
                # Emit failure event
                if self.event_system is not None:
                    await self.event_system.emit(
                        EventTypes.Indexing.FILE_FAILED,
                        source="IndexingPipeline",
                        status=EventStatus.FAILED,
                        file_path=parsed_document.file_path,
                        doc_id=parsed_document.doc_id,
                        error=str(e),
                    )
                raise
