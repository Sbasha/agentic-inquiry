"""Graph construction component for building knowledge graph entities and relationships."""

import asyncio
import sys
import hashlib
import json
import logging
import time
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, Generator, List, Optional, Tuple, TYPE_CHECKING, Union

from agentic_inquiry.embeddings.base import Embedder
from agentic_inquiry.executors import get_embedding_executor
from agentic_inquiry.models.graph_entity import GraphEntity
from agentic_inquiry.models.graph_relationship import GraphRelationship
from agentic_inquiry.parsers.models import ParsedDocument, ParserChunk, ParserRelationship
from agentic_inquiry.database.adapters.lancedb_adapter import LanceDBAdapter
from agentic_inquiry.database.lancedb_manager import LanceDBManager
from agentic_inquiry.mcp.utils.validation import validate_file_path

from agentic_inquiry.indexing.external_entity_manager import ExternalEntityManager
from agentic_inquiry.indexing.relationship_batch_processor import RelationshipBatchProcessor
from agentic_inquiry.indexing.relationship_queue_manager import RelationshipQueueManager

# Python 3.10 compatibility: asyncio.timeout was added in 3.11
if sys.version_info >= (3, 11):
    from asyncio import timeout as async_timeout
else:
    from contextlib import asynccontextmanager
    import warnings

    @asynccontextmanager
    async def async_timeout(delay: float):
        """Python 3.10 compatible timeout context manager.

        Note: This is a compatibility shim that provides no-op timeout behavior
        on Python 3.10. The timeout protection is only fully functional on
        Python 3.11+. This is acceptable as Python 3.10 reaches EOL in October 2026.
        """
        warnings.warn(
            f"asyncio.timeout not available on Python {sys.version_info.major}.{sys.version_info.minor}. "
            "Timeout protection disabled for flush operations. Upgrade to Python 3.11+ for full support.",
            RuntimeWarning,
            stacklevel=3
        )
        yield


if TYPE_CHECKING:
    from agentic_inquiry.indexing.external_entity_resolver import (
        ExternalEntityResolver,
        ExternalEntityInfo,
    )

logger = logging.getLogger(__name__)


@dataclass
class GraphBuilderConfig:
    """Configuration for GraphBuilder performance tuning.
    
    This configuration controls the batched relationship flush operation,
    including batch processing, progress tracking, incremental commits,
    timeouts, and memory management.
    
    Attributes:
        batch_size: Number of relationships per batch (default: 100)
        max_concurrent_batches: Semaphore limit for concurrent processing (default: 10)
        progress_log_interval: Log progress every N relationships (default: 1000)
        batch_commit_interval: Commit to database every N relationships (default: 100)
        auto_flush_threshold: Trigger automatic flush at N pending relationships (default: 50000)
        flush_timeout_seconds: Maximum time for flush operation in seconds (default: 3600)
        external_entity_flush_threshold: Flush external entities at N pending (default: 10000)
        enable_cache_prewarming: Pre-populate cache with common imports (default: True)
        enable_performance_monitoring: Track and log slow operations (default: True)
        slow_operation_threshold_ms: Log warning if operation exceeds this (default: 500.0)
        embedding_dimensions: Embedding vector dimensions for relationships (default: 384)
    """
    
    # Batch processing
    batch_size: int = 100
    max_concurrent_batches: int = 10
    
    # Progress tracking
    progress_log_interval: int = 1000
    
    # Incremental commits
    batch_commit_interval: int = 100
    auto_flush_threshold: int = 50000
    
    # Timeouts
    flush_timeout_seconds: int = 3600
    
    # Memory management
    external_entity_flush_threshold: int = 10000
    external_entity_embedding_batch_size: int = 100  # Max entities per embedding call

    # Performance monitoring
    enable_cache_prewarming: bool = True
    enable_performance_monitoring: bool = True
    slow_operation_threshold_ms: float = 500.0
    
    # Embedding configuration
    embedding_dimensions: int = 384
    
    @classmethod
    def from_config(cls, config: Any) -> "GraphBuilderConfig":
        """Create GraphBuilderConfig from a Config object.
        
        Reads configuration from the indexing.relationship_flush section.
        Invalid values are logged and defaults are used.
        
        Args:
            config: Configuration object with indexing settings
            
        Returns:
            GraphBuilderConfig with values from config or defaults
        """
        defaults = cls()
        
        # Get relationship_flush section, defaulting to empty dict
        try:
            indexing_config = getattr(config, 'indexing', None) or {}
            if isinstance(indexing_config, dict):
                flush_config = indexing_config.get('relationship_flush', {})
            else:
                flush_config = getattr(indexing_config, 'relationship_flush', {}) or {}
        except (AttributeError, TypeError):
            flush_config = {}
        
        def get_int(key: str, default: int, min_val: int = 1) -> int:
            """Get an integer value with validation."""
            try:
                value = flush_config.get(key, default)
                if value is None:
                    return default
                value = int(value)
                if value < min_val:
                    logger.warning(
                        "Invalid %s value %d (< %d), using default %d",
                        key, value, min_val, default
                    )
                    return default
                return value
            except (ValueError, TypeError) as e:
                logger.warning(
                    "Invalid %s configuration: %s, using default %d",
                    key, e, default
                )
                return default
        
        def get_float(key: str, default: float, min_val: float = 0.0) -> float:
            """Get a float value with validation."""
            try:
                value = flush_config.get(key, default)
                if value is None:
                    return default
                value = float(value)
                if value < min_val:
                    logger.warning(
                        "Invalid %s value %f (< %f), using default %f",
                        key, value, min_val, default
                    )
                    return default
                return value
            except (ValueError, TypeError) as e:
                logger.warning(
                    "Invalid %s configuration: %s, using default %f",
                    key, e, default
                )
                return default
        
        def get_bool(key: str, default: bool) -> bool:
            """Get a boolean value with validation."""
            try:
                value = flush_config.get(key, default)
                if value is None:
                    return default
                if isinstance(value, bool):
                    return value
                if isinstance(value, str):
                    return value.lower() in ('true', '1', 'yes')
                return bool(value)
            except (ValueError, TypeError) as e:
                logger.warning(
                    "Invalid %s configuration: %s, using default %s",
                    key, e, default
                )
                return default
        
        # Get embedding dimensions from config.embeddings.default_dimensions
        embedding_dimensions = defaults.embedding_dimensions
        try:
            embeddings_config = getattr(config, 'embeddings', None) or {}
            if isinstance(embeddings_config, dict):
                dim_value = embeddings_config.get('default_dimensions', defaults.embedding_dimensions)
            else:
                dim_value = getattr(embeddings_config, 'default_dimensions', defaults.embedding_dimensions)
            
            # Validate that we got an integer
            if isinstance(dim_value, int):
                embedding_dimensions = dim_value
        except (AttributeError, TypeError):
            pass  # Use default
        
        return cls(
            batch_size=get_int('batch_size', defaults.batch_size),
            max_concurrent_batches=get_int('max_concurrent_batches', defaults.max_concurrent_batches),
            progress_log_interval=get_int('progress_log_interval', defaults.progress_log_interval),
            batch_commit_interval=get_int('batch_commit_interval', defaults.batch_commit_interval),
            auto_flush_threshold=get_int('auto_flush_threshold', defaults.auto_flush_threshold),
            flush_timeout_seconds=get_int('flush_timeout_seconds', defaults.flush_timeout_seconds),
            external_entity_flush_threshold=get_int('external_entity_flush_threshold', defaults.external_entity_flush_threshold),
            external_entity_embedding_batch_size=get_int('external_entity_embedding_batch_size', defaults.external_entity_embedding_batch_size),
            enable_cache_prewarming=get_bool('enable_cache_prewarming', defaults.enable_cache_prewarming),
            enable_performance_monitoring=get_bool('enable_performance_monitoring', defaults.enable_performance_monitoring),
            slow_operation_threshold_ms=get_float('slow_operation_threshold_ms', defaults.slow_operation_threshold_ms),
            embedding_dimensions=embedding_dimensions,
        )


class GraphBuilder:
    """Handles graph entity and relationship construction.
    
    This component is responsible for:
    - Creating graph entities from parsed document chunks
    - Managing pending relationships
    - Resolving import targets using RelationshipResolver
    - Building graph relationships with confidence tracking
    - Two-pass resolution for improved accuracy
    
    Args:
        db_manager: Database manager for storing graph data
        symbol_registry: Registry for tracking symbols and imports
        relationship_resolver: Service for resolving import targets
        embedding_service: Service for generating embeddings
        project_id: Project identifier
        project_hash: Project hash for entity IDs
    """
    
    def __init__(
        self,
        db_manager: Union[LanceDBManager, LanceDBAdapter],
        symbol_registry: Any,
        relationship_resolver: Any,
        embedding_service: Any,
        project_id: str,
        project_hash: str,
        project_root: str,
        external_entity_resolver: Optional["ExternalEntityResolver"] = None,
        embedding_dimensions: int = 384,
        backend_type: str = "lancedb",
        capabilities: Optional[Any] = None,
    ):
        self.db_manager = db_manager
        self.symbol_registry = symbol_registry
        self.relationship_resolver = relationship_resolver
        self.embedding_service = embedding_service
        self.project_id = project_id
        self.project_hash = project_hash
        self.project_root = project_root
        self._embedding_dimensions = embedding_dimensions
        # Resolve capabilities: prefer injected, fall back to derivation
        if capabilities is not None:
            _caps = capabilities
        else:
            from agentic_inquiry.storage.capabilities import get_capabilities_for_backend
            _caps = get_capabilities_for_backend(backend_type)
        self._capabilities = _caps
        self._skip_local_embedding = _caps.uses_server_side_embedding

        # Use injected resolver or create default
        if external_entity_resolver is not None:
            self._external_resolver = external_entity_resolver
        else:
            from agentic_inquiry.indexing.external_entity_resolver import ExternalEntityResolver
            self._external_resolver = ExternalEntityResolver(project_hash)

        # Create ExternalEntityManager for handling external entities (composition)
        self._external_entity_manager = ExternalEntityManager(
            project_id=project_id,
            project_hash=project_hash,
            db_manager=db_manager,
            embedding_service=embedding_service,
            external_resolver=self._external_resolver,
            embedding_dimensions=embedding_dimensions,
            backend_type=backend_type,
            capabilities=_caps,
        )

        # Create RelationshipQueueManager for relationship queue management (composition)
        self._relationship_queue_manager = RelationshipQueueManager()

        # Create RelationshipBatchProcessor for batch processing (composition)
        self._batch_processor = RelationshipBatchProcessor(
            db_manager=db_manager,
            pending_relationship_getter=lambda: self._relationship_queue_manager.pending_count,
            pending_external_getter=lambda: self._external_entity_manager.pending_count,
        )

        # Track resolution stats separately (not part of queue manager)
        self._last_resolution_stats: Dict[str, Any] = {}

    @property
    def _pending_external_entities(self) -> Dict[str, "ExternalEntityInfo"]:
        """Backwards-compatible access to pending external entities.

        Returns a direct reference to the internal dict for test compatibility.
        Production code should use queue_external_entity() method instead.
        """
        return self._external_entity_manager._pending_external_entities

    @property
    def _pending_relationships(self) -> List[Tuple[ParserRelationship, str]]:
        """Backwards-compatible access to pending relationships.

        Returns a direct reference to the internal list for test compatibility.
        Production code should use add_pending_relationship() method instead.
        """
        return self._relationship_queue_manager._pending_relationships

    @property
    def pending_relationships(self) -> List[Tuple[ParserRelationship, str]]:
        """Get a copy of pending relationships.
        
        This is the public API for accessing pending relationships.
        Returns a copy of the list to prevent external modification.
        
        Returns:
            List of (ParserRelationship, source_file_path) tuples
        """
        return self._relationship_queue_manager.get_pending_relationships()

    def get_pending_relationship_count(self) -> int:
        """Return count of pending relationships.
        
        Use this for progress reporting instead of accessing the list directly.
        
        Returns:
            Number of pending relationships
        """
        return self._relationship_queue_manager.pending_count

    @property
    def _committed_relationship_ids(self) -> set:
        """Backwards-compatible access to committed relationship IDs.

        Returns a direct reference to the internal set for test compatibility.
        """
        return self._relationship_queue_manager._committed_relationship_ids

    @staticmethod
    def _generate_relationship_id(
        relationship: ParserRelationship,
        source_file_path: str
    ) -> str:
        """Generate a unique ID for a relationship for deduplication.

        Delegates to RelationshipQueueManager.generate_relationship_id.

        Args:
            relationship: The relationship to generate an ID for
            source_file_path: Path to the source file

        Returns:
            A unique identifier string for this relationship
        """
        return RelationshipQueueManager.generate_relationship_id(
            relationship, source_file_path
        )

    def add_pending_relationship(self, relationship: ParserRelationship, source_file_path: str) -> None:
        """Add a relationship to the pending queue for later resolution.

        Delegates to RelationshipQueueManager.

        Args:
            relationship: The relationship to add
            source_file_path: Path to the source file
        """
        self._relationship_queue_manager.add_pending_relationship(
            relationship, source_file_path
        )

    def clear_pending_relationships(self) -> None:
        """Clear all pending relationships.

        Delegates to RelationshipQueueManager.
        """
        self._relationship_queue_manager.clear_pending_relationships()

    def clear_committed_relationship_ids(self) -> None:
        """Clear the set of committed relationship IDs.

        Delegates to RelationshipQueueManager.

        Call this when starting a fresh flush operation that should not
        consider previous commits for deduplication.
        """
        self._relationship_queue_manager.clear_committed_relationship_ids()

    def get_committed_relationship_count(self) -> int:
        """Get the count of relationships that have been committed.

        Delegates to RelationshipQueueManager.

        Returns:
            Number of unique relationships committed in the current session
        """
        return self._relationship_queue_manager.committed_count

    def _filter_uncommitted_relationships(
        self,
        relationships: List[Tuple[ParserRelationship, str]],
    ) -> Tuple[List[Tuple[ParserRelationship, str]], int]:
        """Filter out relationships that have already been committed.

        Delegates to RelationshipQueueManager.

        This enables idempotent resume after interruption by skipping
        relationships that were already processed and committed.

        Args:
            relationships: List of (relationship, source_file_path) tuples

        Returns:
            Tuple of (filtered_relationships, skipped_count)
        """
        return self._relationship_queue_manager.filter_uncommitted_relationships(
            relationships
        )

    def _mark_relationships_committed(
        self,
        relationships: List[Tuple[ParserRelationship, str]],
    ) -> None:
        """Mark relationships as committed for deduplication.

        Delegates to RelationshipQueueManager.

        Args:
            relationships: List of (relationship, source_file_path) tuples
        """
        self._relationship_queue_manager.mark_relationships_committed(relationships)
    
    def remove_pending_relationships_for_file(self, file_path: str) -> int:
        """Remove pending relationships for a specific file.

        Delegates to RelationshipQueueManager.

        Args:
            file_path: Path to the file whose relationships should be removed

        Returns:
            Number of relationships removed
        """
        return self._relationship_queue_manager.remove_pending_relationships_for_file(
            file_path
        )
    
    def get_resolution_stats(self) -> Optional[Dict[str, Any]]:
        """Get statistics from the last relationship resolution.
        
        Returns:
            Dictionary containing resolution statistics, or None if no resolution has been performed yet.
            Returns a copy to prevent external modifications.
        """
        # Return None if no resolution has been performed yet
        if not self._last_resolution_stats:
            return None
        
        # Return a copy without internal tracking data
        stats_copy = self._last_resolution_stats.copy()
        
        # Remove internal tracking data that shouldn't be exposed
        stats_copy.pop("confidence_scores", None)
        
        return stats_copy

    def _check_memory_pressure(
        self,
        config: Optional[GraphBuilderConfig] = None,
    ) -> Dict[str, Any]:
        """Check if memory thresholds are exceeded.

        Delegates to RelationshipBatchProcessor.

        Args:
            config: Configuration with threshold values (uses defaults if None)

        Returns:
            Dictionary with pressure status:
            - needs_relationship_flush: bool
            - needs_external_entity_flush: bool
            - pending_relationships: int
            - pending_external_entities: int
            - relationship_threshold: int
            - external_entity_threshold: int
        """
        if config is None:
            config = GraphBuilderConfig()

        return self._batch_processor.check_memory_pressure(
            auto_flush_threshold=config.auto_flush_threshold,
            external_entity_flush_threshold=config.external_entity_flush_threshold,
        )

    def get_adaptive_batch_size(
        self,
        base_batch_size: int,
        config: Optional[GraphBuilderConfig] = None,
    ) -> int:
        """Calculate adaptive batch size based on memory pressure.

        Delegates to RelationshipBatchProcessor.

        Args:
            base_batch_size: The configured batch size
            config: Configuration with threshold values

        Returns:
            Adapted batch size (may be reduced under memory pressure)
        """
        if config is None:
            config = GraphBuilderConfig()

        return self._batch_processor.get_adaptive_batch_size(
            base_batch_size=base_batch_size,
            auto_flush_threshold=config.auto_flush_threshold,
            external_entity_flush_threshold=config.external_entity_flush_threshold,
        )

    def _cleanup_processed_batch(
        self,
        processed_relationships: List[Tuple[ParserRelationship, str]],
    ) -> int:
        """Clean up processed relationships from pending queue.

        Delegates to RelationshipQueueManager.

        This frees memory by removing relationships that have been successfully
        processed and committed.

        Args:
            processed_relationships: List of relationships that were processed

        Returns:
            Number of relationships removed from the pending queue
        """
        return self._relationship_queue_manager.cleanup_processed_batch(
            processed_relationships
        )

    def _cleanup_queues(self) -> Dict[str, int]:
        """Clean up all pending queues after flush completion.

        Clears pending relationships and external entities to free memory.
        Uses proper delegation to the respective managers.

        Returns:
            Dictionary with counts of cleared items
        """
        rels_cleared = self._relationship_queue_manager.pending_count
        externals_cleared = self._external_entity_manager.pending_count

        self._relationship_queue_manager.clear_pending_relationships()
        self._external_entity_manager.clear_pending()

        logger.debug(
            "Cleaned up queues: %d relationships, %d external entities",
            rels_cleared,
            externals_cleared,
        )

        return {
            "relationships_cleared": rels_cleared,
            "external_entities_cleared": externals_cleared,
        }

    async def flush_external_entities_if_needed(
        self,
        config: Optional[GraphBuilderConfig] = None,
        event_system: Optional[Any] = None,
    ) -> int:
        """Flush external entities if threshold is exceeded.

        Delegates to ExternalEntityManager for actual implementation.

        Args:
            config: Configuration with threshold values
            event_system: Optional event system for emitting flush events

        Returns:
            Number of external entities flushed (0 if threshold not exceeded)
        """
        if config is None:
            config = GraphBuilderConfig()

        return await self._external_entity_manager.flush_if_needed(
            threshold=config.external_entity_flush_threshold,
            batch_size=config.external_entity_embedding_batch_size,
            event_system=event_system,
        )

    def _count_entities_by_category(
        self,
        entities: List["ExternalEntityInfo"],
    ) -> Dict[str, int]:
        """Count external entities by category.

        Delegates to ExternalEntityManager.

        Args:
            entities: List of external entity info objects

        Returns:
            Dictionary mapping category names to counts
        """
        return self._external_entity_manager._count_entities_by_category(entities)

    async def _generate_external_entity_embeddings_batched(
        self,
        entities: List["ExternalEntityInfo"],
        batch_size: int,
    ) -> List[List[float]]:
        """Generate embeddings for external entities in batches.

        Delegates to ExternalEntityManager.

        Args:
            entities: List of external entity info objects
            batch_size: Maximum entities per embedding batch

        Returns:
            List of embedding vectors (as lists of floats)
        """
        return await self._external_entity_manager._generate_embeddings_batched(
            entities, batch_size
        )

    async def emit_slow_operation_event(
        self,
        slow_operation: Any,
        event_system: Optional[Any] = None,
    ) -> None:
        """Emit a slow_operation event for observability.

        This method is called by the PerformanceMonitor callback when a
        slow operation is detected. It emits an event for external monitoring.

        Args:
            slow_operation: SlowOperation dataclass with timing details
            event_system: Optional event system for event emission
        """
        # Property 37: Requirements 9.7 - slow_operation event emission
        if event_system is None:
            return

        try:
            await event_system.emit(
                "relationship_flush.slow_operation",
                source="graph_builder",
                operation_name=slow_operation.operation_name,
                duration_ms=slow_operation.duration_ms,
                threshold_ms=slow_operation.threshold_ms,
                context=slow_operation.context,
            )
        except Exception as e:
            logger.error("Failed to emit slow_operation event: %s", e)

    async def create_graph_entities(
        self,
        parsed_document: ParsedDocument,
        chunks: List[ParserChunk],
        document_processor: Any,
    ) -> Tuple[List[GraphEntity], Dict[str, int]]:
        """Create graph entities from parsed document chunks.

        Args:
            parsed_document: The parsed document. The file_path in parsed_document
                           must be within the project root directory. Path validation
                           is performed automatically to prevent directory traversal attacks.
            chunks: List of parser chunks
            document_processor: Document processor for validation

        Returns:
            Tuple of (list of graph entities, statistics dictionary)
            
        Raises:
            PathValidationError: If file_path in parsed_document is outside the project root
        """
        graph_entities: List[GraphEntity] = []
        stats = {
            "file_entities": 0,
            "document_entities": 0,
            "code_entities": 0,
            "document_relationships": 0,
        }

        entity_embedder: Optional[Embedder]
        if self._skip_local_embedding:
            entity_embedder, entity_dims = None, 768  # text-embedding-005
            logger.debug("AlloyDB backend: skipping local entity embedding generation")
        else:
            entity_embedder, entity_dims = self.embedding_service.get_embedder_configuration(
                "graph_entities", "vector"
            )

        # Create file entity for this document
        # This enables cross-file relationship traversal by matching source_id patterns
        # used in import relationships (source_type="file", source_name=file_path)
        file_path = parsed_document.file_path

        # Validate file path to prevent directory traversal attacks
        # This ensures the file is within the project root
        validated_file_path = str(validate_file_path(file_path, Path(self.project_root)))
        file_path = validated_file_path
        file_entity_id = f"file::{self.project_hash}::{file_path}::{file_path}"

        # Detect language from first chunk or file extension
        file_language = ""
        if chunks and chunks[0].language:
            file_language = chunks[0].language

        # Generate embedding for the file path (in executor to avoid blocking)
        if entity_embedder is None:
            file_vector = [0.0] * entity_dims
        else:
            loop = asyncio.get_running_loop()
            file_vectors = await loop.run_in_executor(
                get_embedding_executor(),
                entity_embedder.generate,
                [file_path]
            )
            file_vector = file_vectors[0]
            document_processor._validate_vector("graph_entities", "vector", file_vector, entity_dims)

        file_entity = GraphEntity(
            id=file_entity_id,
            name=file_path,
            type="file",
            file_path=file_path,
            doc_id=parsed_document.doc_id,
            project_id=self.project_id,
            vector=file_vector,
            line_start=-1,
            line_end=-1,
            pagerank=0.0,
            betweenness=None,
            community_id=None,
            has_ranking_signals=False,
        )
        graph_entities.append(file_entity)
        stats["file_entities"] += 1

        # Register file entity in symbol registry
        await self.symbol_registry.register(
            name=file_path,
            file_path=file_path,
            entity_type="file",
            language=file_language,
            line_start=-1,
            line_end=-1,
            parent_scope=None,
            is_exported=True
        )
        
        # Track relationship count during processing (Requirements 7.1, 7.2, 7.3, 7.4)
        total_pending_added = 0
        
        for chunk in chunks:
            element_name = chunk.element_name
            element_type = chunk.element_type
            
            # Register document entities (chunks with element_name but no symbols)
            if element_name and not chunk.symbols:
                stats["document_entities"] += 1
                logger.debug(
                    f"Document entity: {element_name} (type: {element_type}) "
                    f"in {parsed_document.file_path}"
                )
                
                # Extract metadata for entity registration
                language = chunk.language or ""
                line_start = chunk.line_start if chunk.line_start is not None else -1
                line_end = chunk.line_end if chunk.line_end is not None else -1
                parent_scope = chunk.parent_id if chunk.parent_id else None
                is_exported = True
                # Normalize entity type by stripping code_ prefix for ontology compatibility
                # TreeSitterCodeParser uses "code_class", "code_function" etc. but we want "class", "function"
                raw_entity_type = element_type or "section"
                entity_type = raw_entity_type.removeprefix("code_") if raw_entity_type.startswith("code_") else raw_entity_type
                
                # Register document entity in symbol registry
                await self.symbol_registry.register(
                    name=element_name,
                    file_path=parsed_document.file_path,
                    entity_type=entity_type,
                    language=language,
                    line_start=line_start,
                    line_end=line_end,
                    parent_scope=parent_scope,
                    is_exported=is_exported
                )
                
                logger.debug(
                    f"Registered document entity: {element_name} (type: {entity_type}) "
                    f"in {parsed_document.file_path} with parent_scope: {parent_scope}"
                )
                
                # Create graph entity for document element
                if entity_embedder is None:
                    vector_entity = [0.0] * entity_dims
                else:
                    vectors = await loop.run_in_executor(
                        get_embedding_executor(),
                        entity_embedder.generate,
                        [element_name]
                    )
                    vector_entity = vectors[0]
                    document_processor._validate_vector("graph_entities", "vector", vector_entity, entity_dims)
                
                entity = GraphEntity(
                    id=f"{entity_type}::{self.project_hash}::{parsed_document.file_path}::{element_name}",
                    name=element_name,
                    type=entity_type,
                    file_path=parsed_document.file_path,
                    doc_id=parsed_document.doc_id,
                    project_id=self.project_id,
                    vector=vector_entity,
                    line_start=line_start,
                    line_end=line_end,
                    pagerank=0.0,
                    betweenness=None,
                    community_id=None,
                    has_ranking_signals=False,
                )
                graph_entities.append(entity)
            
            # Register code entities (chunks with symbols)
            if chunk.symbols:
                stats["code_entities"] += len(chunk.symbols)
                for symbol in chunk.symbols:
                    # Generate embedding for symbol
                    if entity_embedder is None:
                        vector_entity = [0.0] * entity_dims
                    else:
                        vectors = await loop.run_in_executor(
                            get_embedding_executor(),
                            entity_embedder.generate,
                            [symbol]
                        )
                        vector_entity = vectors[0]
                        document_processor._validate_vector("graph_entities", "vector", vector_entity, entity_dims)
                    ranking = (chunk.symbol_rankings or {}).get(symbol, {})
                    has_ranking = bool(ranking)
                    pagerank = ranking.get("pagerank", 0.0)
                    symbol_metadata = (chunk.symbol_metadata or {}).get(symbol, {})
                    symbol_type = symbol_metadata.get("type", "function")
                    
                    # Extract metadata for symbol registration
                    language = chunk.language or ""
                    # Prefer symbol-level line numbers from symbol_metadata
                    symbol_start_line = symbol_metadata.get("start_line")
                    if symbol_start_line is not None:
                        line_start = int(symbol_start_line)
                    else:
                        line_start = chunk.line_start if chunk.line_start is not None else -1

                    symbol_end_line = symbol_metadata.get("end_line")
                    if symbol_end_line is not None:
                        line_end = int(symbol_end_line)
                    else:
                        line_end = chunk.line_end if chunk.line_end is not None else -1
                    parent_scope = chunk.parent_id if chunk.parent_id else None
                    is_exported = symbol_metadata.get("is_exported", True)
                    
                    # Register symbol with rich metadata
                    await self.symbol_registry.register(
                        name=symbol,
                        file_path=parsed_document.file_path,
                        entity_type=symbol_type,
                        language=language,
                        line_start=line_start,
                        line_end=line_end,
                        parent_scope=parent_scope,
                        is_exported=is_exported
                    )
                    
                    entity = GraphEntity(
                        id=f"{symbol_type}::{self.project_hash}::{parsed_document.file_path}::{symbol}",
                        name=symbol,
                        type=symbol_type,
                        file_path=parsed_document.file_path,
                        doc_id=parsed_document.doc_id,
                        project_id=self.project_id,
                        vector=vector_entity,
                        line_start=line_start,
                        line_end=line_end,
                        pagerank=pagerank,
                        betweenness=ranking.get("betweenness"),
                        community_id=symbol_metadata.get("community_id"),
                        has_ranking_signals=has_ranking,
                    )
                    graph_entities.append(entity)
            
            # Store relationships for later processing
            chunk_relationships = list(self._chunk_relationships(chunk))
            if chunk_relationships:
                # Track document relationships
                if element_name and not chunk.symbols:
                    stats["document_relationships"] += len(chunk_relationships)
                    logger.debug(
                        f"Document entity {element_name} has {len(chunk_relationships)} relationships"
                    )
                
                # Track count during processing (Requirements 7.1, 7.3, 7.4)
                total_pending_added += len(chunk_relationships)
                
                for relationship in chunk_relationships:
                    self.add_pending_relationship(relationship, parsed_document.file_path)
        
        # Log entity creation statistics (using tracked count instead of recomputing)
        if graph_entities or total_pending_added > 0:
            logger.info(
                "Created %d graph entities and queued %d relationships for document %s: %d file, %d document, %d code entities",
                len(graph_entities),
                total_pending_added,
                parsed_document.doc_id,
                stats["file_entities"],
                stats["document_entities"],
                stats["code_entities"]
            )
            
            # Log sample entity names for debugging
            entity_names = [e.name for e in graph_entities[:10]]
            logger.debug(
                "Sample entity names: %s",
                ", ".join(entity_names)
            )
        
        return graph_entities, stats
    
    def _chunk_relationships(self, chunk: ParserChunk) -> List[ParserRelationship]:
        """Extract relationships from a parser chunk.
        
        Args:
            chunk: Parser chunk to extract relationships from
            
        Returns:
            List of relationships
        """
        return chunk.relationships if chunk.relationships else []
    
    def _build_metadata_payload(
        self,
        metadata: Optional[Dict[str, Any]],
        ranking_signals: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build metadata payload for graph relationships.
        
        Args:
            metadata: Optional metadata dictionary
            ranking_signals: Optional ranking signals dictionary
            
        Returns:
            Combined metadata payload
        """
        payload = {}
        if metadata:
            payload.update(metadata)
        if ranking_signals:
            payload["ranking_signals"] = ranking_signals
        return payload
    
    def _normalise_relationship(self, relationship: ParserRelationship) -> ParserRelationship:
        """Normalize a relationship (placeholder for future normalization logic).
        
        Args:
            relationship: Relationship to normalize
            
        Returns:
            Normalized relationship
        """
        return relationship
    
    async def flush_pending_relationships(
        self,
        document_processor: Any,
        use_two_pass: bool = True
    ) -> int:
        """Create all pending relationships after all documents are indexed.
        
        This resolves import targets using the RelationshipResolver service
        and creates the graph relationships in the database.
        
        Enhanced with two-pass resolution:
        - First pass: Resolve high-confidence relationships (>= 0.8)
        - Learn from first pass: Track successful resolutions
        - Second pass: Re-resolve low-confidence relationships using learned patterns
        
        Args:
            document_processor: Document processor for validation
            use_two_pass: Whether to use two-pass resolution (default: True)
        
        Returns:
            Number of relationships created
        """
        if not self._pending_relationships:
            logger.info("No pending relationships to flush")
            return 0
        
        # Start timing resolution
        resolution_start_time = time.time()
        
        # Count relationship types for initial summary
        rel_type_counts: Dict[str, int] = {}
        for rel, _ in self._pending_relationships:
            rel_type_counts[rel.type] = rel_type_counts.get(rel.type, 0) + 1
        
        logger.info(
            "Flushing %d pending relationships: %s",
            len(self._pending_relationships), dict(rel_type_counts)
        )
        logger.debug("Symbol registry contains %d unique symbols", self.symbol_registry.get_symbol_count())
        
        relationship_embedder: Optional[Embedder]
        if self._skip_local_embedding:
            relationship_embedder, relationship_dims = None, 768
        else:
            relationship_embedder, relationship_dims = self.embedding_service.get_embedder_configuration(
                "graph_relationships", "vector"
            )

        # Pre-compute embeddings for all relationship types (batch generation)
        # This optimization reduces embedding calls from N relationships to ~5-10 unique types
        unique_rel_types = list({rel.type for rel, _ in self._pending_relationships})
        if relationship_embedder is None:
            rel_type_embedding_cache: Dict[str, List[float]] = {t: [0.0] * relationship_dims for t in unique_rel_types}
        else:
            # Run batch embedding in executor to avoid blocking
            loop = asyncio.get_running_loop()
            rel_type_vectors = await loop.run_in_executor(
                get_embedding_executor(),
                relationship_embedder.generate,
                unique_rel_types
            )
            rel_type_embedding_cache = dict(zip(unique_rel_types, rel_type_vectors))

        logger.info(
            "Pre-computed embeddings for %d unique relationship types: %s",
            len(unique_rel_types), unique_rel_types
        )

        graph_relationships: List[GraphRelationship] = []

        # Track resolution statistics
        stats = self._initialize_resolution_stats(use_two_pass)
        
        # Two-pass resolution: Track low-confidence relationships for second pass
        low_confidence_relationships: List[Tuple[ParserRelationship, str]] = []
        
        # FIRST PASS: Resolve all relationships
        total_relationships = len(self._pending_relationships)
        progress_interval = max(1000, total_relationships // 20)  # Log every 1000 or 5%
        
        for i, (relationship, source_file_path) in enumerate(self._pending_relationships):
            # Progress logging
            if i > 0 and i % progress_interval == 0:
                elapsed = time.time() - resolution_start_time
                rate = i / elapsed if elapsed > 0 else 0
                remaining = (total_relationships - i) / rate if rate > 0 else 0
                logger.info(
                    "Relationship resolution progress: %d/%d (%.1f%%) - %.1f/sec - ETA: %.0fs",
                    i, total_relationships, (i / total_relationships) * 100, rate, remaining
                )
            result = await self._resolve_single_relationship(
                relationship,
                source_file_path,
                relationship_embedder,
                relationship_dims,
                document_processor,
                stats,
                low_confidence_relationships,
                use_two_pass,
                rel_type_embedding_cache=rel_type_embedding_cache,
            )

            if result:
                graph_relationships.append(result)

        # SECOND PASS: Re-resolve low-confidence relationships
        if use_two_pass and low_confidence_relationships:
            improved_relationships = await self._second_pass_resolution(
                low_confidence_relationships,
                relationship_embedder,
                relationship_dims,
                document_processor,
                stats,
                graph_relationships,
                rel_type_embedding_cache=rel_type_embedding_cache,
            )
            graph_relationships.extend(improved_relationships)
        
        # Insert all relationships
        if graph_relationships:
            await self.db_manager.add_graph_relationships(graph_relationships)
        
        # End timing and log statistics
        resolution_end_time = time.time()
        resolution_time = resolution_end_time - resolution_start_time
        
        await self._log_resolution_statistics(stats, resolution_time, len(graph_relationships))
        
        # Store statistics for later retrieval
        self._last_resolution_stats = stats
        
        # Clear pending relationships
        self.clear_pending_relationships()
        
        return len(graph_relationships)


    async def flush_pending_relationships_batched(
        self,
        document_processor: Any,
        use_two_pass: bool = True,
        config: Optional[GraphBuilderConfig] = None,
        event_system: Optional[Any] = None,
    ) -> Tuple[List[GraphRelationship], Dict[str, Any]]:
        """Flush pending relationships using concurrent batch processing.

        This replaces the sequential flush_pending_relationships method
        with a batched, concurrent implementation that provides:
        - Progress tracking and logging
        - Incremental commits per batch
        - Event emission for observability
        - Timeout handling (configurable via flush_timeout_seconds)
        - Memory-bounded processing

        Args:
            document_processor: Document processor for validation
            use_two_pass: Whether to use two-pass resolution (default: True)
            config: Optional configuration overrides
            event_system: Optional event system for operation tracking

        Returns:
            Tuple of (created relationships, statistics dict)
            On timeout: Returns partial results with timed_out=True in stats
        """
        from agentic_inquiry.events import track_operation

        # Use provided config or defaults
        if config is None:
            config = GraphBuilderConfig()

        if not self._pending_relationships:
            logger.info("No pending relationships to flush")
            return [], {"total_relationships": 0, "relationships_created": 0}

        # Auto-detect initial index: if graph_relationships table is empty for this
        # project, skip database lookups during resolution. On a fresh index, every
        # DB lookup returns 0 rows — pure overhead (~70% of resolution time).
        # On re-index, the table is non-empty and DB lookups replay prior resolutions.
        try:
            existing_rel_count = await self.db_manager.count_records(  # type: ignore[union-attr]  # LanceDBAdapter lacks it; the except below absorbs the AttributeError
                table_name="graph_relationships",
                project_id=self.project_id,
            )
            if existing_rel_count == 0:
                logger.info(
                    "Initial index detected (0 existing relationships for project %s) — "
                    "skipping database lookups for faster resolution",
                    self.project_id,
                )
                self.relationship_resolver._skip_database_lookups = True
            else:
                logger.info(
                    "Re-index detected (%d existing relationships) — "
                    "using database lookups for consistency",
                    existing_rel_count,
                )
        except Exception as e:
            logger.debug("Could not check existing relationship count: %s", e)

        # Filter out already-committed relationships for idempotent resume
        # This enables resuming after interruption without duplicating work
        relationships_to_process, skipped_count = self._filter_uncommitted_relationships(
            self._pending_relationships
        )

        total_relationships = len(self._pending_relationships)
        uncommitted_count = len(relationships_to_process)

        if skipped_count > 0:
            logger.info(
                "Resume mode: skipping %d already-committed relationships, processing %d remaining",
                skipped_count, uncommitted_count
            )

        if not relationships_to_process:
            logger.info("All %d relationships already committed, nothing to do", total_relationships)
            return [], {
                "total_relationships": total_relationships,
                "relationships_created": 0,
                "skipped_already_committed": skipped_count,
            }

        # Initialize statistics
        stats = self._initialize_batched_stats(config, uncommitted_count)
        stats["timed_out"] = False
        stats["timeout_seconds"] = config.flush_timeout_seconds
        stats["skipped_already_committed"] = skipped_count
        stats["original_total"] = total_relationships

        # Get embedding configuration
        relationship_embedder: Optional[Embedder]
        if self._skip_local_embedding:
            relationship_embedder, relationship_dims = None, 768
        else:
            relationship_embedder, relationship_dims = self.embedding_service.get_embedder_configuration(
                "graph_relationships", "vector"
            )

        # Pre-compute embeddings for all relationship types (batch generation)
        # This optimization reduces embedding calls from N relationships to ~5-10 unique types
        unique_rel_types = list({rel.type for rel, _ in relationships_to_process})
        if relationship_embedder is None:
            rel_type_embedding_cache: Dict[str, List[float]] = {t: [0.0] * relationship_dims for t in unique_rel_types}
        else:
            # Run batch embedding in executor to avoid blocking
            loop = asyncio.get_running_loop()
            rel_type_vectors = await loop.run_in_executor(
                get_embedding_executor(),
                relationship_embedder.generate,
                unique_rel_types
            )
            rel_type_embedding_cache = dict(zip(unique_rel_types, rel_type_vectors))

        logger.info(
            "Pre-computed embeddings for %d unique relationship types: %s",
            len(unique_rel_types), unique_rel_types
        )

        # Create semaphore for concurrency control
        semaphore = asyncio.Semaphore(config.max_concurrent_batches)

        # Split relationships into batches
        batches = list(self._chunk_relationships_batched(
            relationships_to_process,
            config.batch_size
        ))

        stats["batch_count"] = len(batches)

        logger.info(
            "Flushing %d pending relationships in %d batches (batch_size=%d, timeout=%ds)",
            uncommitted_count, len(batches), config.batch_size, config.flush_timeout_seconds
        )

        # Track all created relationships
        all_relationships: List[GraphRelationship] = []
        start_time = time.time()
        operation_tracker = None

        # Wrap with track_operation if event system available
        async def process_all_batches():
            nonlocal all_relationships

            for batch_number, batch in enumerate(batches, 1):
                batch_start = time.time()

                # Process batch with concurrency control
                batch_results = await self._process_relationship_batch(
                    batch=batch,
                    batch_number=batch_number,
                    relationship_embedder=relationship_embedder,
                    relationship_dims=relationship_dims,
                    document_processor=document_processor,
                    use_two_pass=use_two_pass,
                    stats=stats,
                    semaphore=semaphore,
                    rel_type_embedding_cache=rel_type_embedding_cache,
                )

                all_relationships.extend(batch_results)

                # Incremental commit
                if batch_results:
                    commit_success = await self._commit_batch(
                        batch_results, batch_number, stats, event_system
                    )

                    # Mark relationships as committed for idempotent resume
                    # Only mark if commit was successful
                    if commit_success:
                        self._mark_relationships_committed(batch)

                batch_elapsed = time.time() - batch_start
                stats["batch_times"].append(batch_elapsed)

                # Log progress at configured intervals
                processed = batch_number * config.batch_size
                if processed % config.progress_log_interval < config.batch_size:
                    self._log_progress(
                        processed=min(processed, uncommitted_count),
                        total=uncommitted_count,
                        start_time=start_time,
                        stats=stats,
                    )

        try:
            # Apply timeout to the entire flush operation
            async with async_timeout(config.flush_timeout_seconds):
                # Execute with or without event tracking
                if event_system is not None:
                    async with track_operation(
                        event_system,
                        operation_type="relationship_flush",
                        source="graph_builder",
                        total_relationships=uncommitted_count,
                        skipped_already_committed=skipped_count,
                        original_total=total_relationships,
                        batch_size=config.batch_size,
                        batch_count=len(batches),
                    ) as operation_tracker:
                        stats["operation_tracker"] = operation_tracker
                        await process_all_batches()

                        # Emit final progress
                        await operation_tracker.progress(
                            relationships_processed=len(all_relationships),
                            total_relationships=uncommitted_count,
                            rate_per_second=len(all_relationships) / max(time.time() - start_time, 0.001),
                            eta_seconds=0,
                        )
                else:
                    await process_all_batches()

        except TimeoutError:
            # Handle timeout gracefully - return partial results
            elapsed = time.time() - start_time
            stats["timed_out"] = True
            stats["timeout_at_elapsed"] = elapsed
            stats["batches_completed"] = len(stats["batch_times"])

            logger.warning(
                "Flush operation timed out after %.1fs (limit: %ds). "
                "Processed %d/%d relationships (%d batches completed). "
                "Partial results will be returned.",
                elapsed,
                config.flush_timeout_seconds,
                len(all_relationships),
                uncommitted_count,
                stats["batches_completed"],
            )

            # Report failure to event system if available (Property 36: Requirements 11.6)
            if stats.get("operation_tracker"):
                try:
                    await stats["operation_tracker"].fail(
                        error="TimeoutError",
                        error_type="TimeoutError",
                        error_message=f"Flush operation timed out after {elapsed:.1f}s",
                        relationships_processed=len(all_relationships),
                        total_relationships=uncommitted_count,
                        batches_completed=stats["batches_completed"],
                        timeout_seconds=config.flush_timeout_seconds,
                    )
                except Exception as e:
                    logger.error("Failed to report timeout to event system: %s", e)

        except Exception as e:
            # Handle general errors - emit failure event (Property 36: Requirements 11.6)
            elapsed = time.time() - start_time
            stats["error"] = str(e)
            stats["error_type"] = type(e).__name__
            stats["batches_completed"] = len(stats["batch_times"])

            logger.error(
                "Flush operation failed after %.1fs: %s. "
                "Processed %d/%d relationships (%d batches completed).",
                elapsed,
                e,
                len(all_relationships),
                uncommitted_count,
                stats["batches_completed"],
                exc_info=True,
            )

            # Report failure to event system if available
            if event_system is not None:
                try:
                    await event_system.emit(
                        "relationship_flush.failed",
                        source="graph_builder",
                        error=str(e),
                        error_type=type(e).__name__,
                        relationships_processed=len(all_relationships),
                        total_relationships=uncommitted_count,
                        batches_completed=stats["batches_completed"],
                        elapsed_seconds=elapsed,
                    )
                except Exception as emit_err:
                    logger.error("Failed to emit failure event: %s", emit_err)

            # Re-raise the exception after logging
            raise

        # Calculate final statistics
        total_time = time.time() - start_time
        stats["total_time_seconds"] = total_time
        stats["relationships_created"] = len(all_relationships)
        stats["average_batch_time"] = sum(stats["batch_times"]) / len(stats["batch_times"]) if stats["batch_times"] else 0

        # Get cache statistics
        cache_stats = self.relationship_resolver.get_resolution_stats()
        stats["cache_hit_rate"] = cache_stats.get("cache_hit_rate", 0)
        stats["cache_statistics"] = cache_stats

        # Update backward-compatible keys for legacy API
        stats["total"] = stats["total_relationships"]
        stats["resolved_cross_file"] = stats["cross_file_resolutions"]
        stats["unresolved_external"] = stats["external_entity_resolutions"]
        stats["same_file_fallback"] = stats["same_file_resolutions"]
        stats["resolution_time_seconds"] = stats["total_time_seconds"]
        stats["resolver_cache_statistics"] = cache_stats
        stats["confidence_levels"]["high"] = stats["high_confidence_count"]
        stats["confidence_levels"]["medium"] = stats["medium_confidence_count"]
        stats["confidence_levels"]["low"] = stats["low_confidence_count"]
        # Calculate average confidence if we have relationships
        if stats["relationships_created"] > 0:
            high_count = stats["high_confidence_count"]
            low_count = stats["low_confidence_count"]
            total_conf = stats["relationships_created"]
            stats["average_confidence"] = (
                (high_count * 1.0 + (total_conf - high_count - low_count) * 0.7 + low_count * 0.3)
                / total_conf if total_conf > 0 else 0.0
            )

        # Log final summary (include timeout status)
        if stats["timed_out"]:
            logger.info(
                "Relationship flush TIMED OUT: %d/%d relationships created in %.2fs "
                "(committed: %d, timeout limit: %ds)",
                len(all_relationships),
                total_relationships,
                total_time,
                stats["committed_count"],
                config.flush_timeout_seconds,
            )
        else:
            await self._log_resolution_statistics_batched(stats, total_time, len(all_relationships))

            # Emit completion event with all metrics (Property 35: Requirements 11.4)
            if event_system is not None:
                try:
                    await event_system.emit(
                        "relationship_flush.completed",
                        source="graph_builder",
                        total_relationships=total_relationships,
                        relationships_created=len(all_relationships),
                        committed_count=stats["committed_count"],
                        skipped_already_committed=skipped_count,
                        batches_completed=len(stats["batch_times"]),
                        total_time_seconds=total_time,
                        average_batch_time=stats["average_batch_time"],
                        cache_hit_rate=stats["cache_hit_rate"],
                        relationships_failed=stats.get("relationships_failed", 0),
                        commit_failures=stats.get("commit_failures", 0),
                    )
                except Exception as emit_err:
                    logger.error("Failed to emit completion event: %s", emit_err)

        # Store statistics for later retrieval
        self._last_resolution_stats = stats

        # Clear pending relationships (even on timeout, committed ones are safe)
        self.clear_pending_relationships()

        return all_relationships, stats

    def _initialize_batched_stats(
        self,
        config: GraphBuilderConfig,
        total_relationships: int
    ) -> Dict[str, Any]:
        """Initialize statistics tracking for batched flush.

        Delegates to RelationshipBatchProcessor.

        Args:
            config: Configuration for the flush operation
            total_relationships: Total number of relationships to process

        Returns:
            Initialized statistics dictionary with both new and backward-compatible keys
        """
        return self._batch_processor.initialize_stats(
            batch_size=config.batch_size,
            total_relationships=total_relationships,
        )

    def _chunk_relationships_batched(
        self,
        relationships: List[Tuple[ParserRelationship, str]],
        batch_size: int
    ) -> Generator[List[Tuple[ParserRelationship, str]], None, None]:
        """Split relationships into batches for processing.

        Delegates to RelationshipBatchProcessor.

        Args:
            relationships: List of (relationship, source_file_path) tuples
            batch_size: Maximum size of each batch

        Yields:
            Batches of relationships
        """
        return self._batch_processor.chunk_relationships(relationships, batch_size)

    async def _process_relationship_batch(
        self,
        batch: List[Tuple[ParserRelationship, str]],
        batch_number: int,
        relationship_embedder: Optional[Embedder],
        relationship_dims: int,
        document_processor: Any,
        use_two_pass: bool,
        stats: Dict[str, Any],
        semaphore: asyncio.Semaphore,
        rel_type_embedding_cache: Dict[str, List[float]],
    ) -> List[GraphRelationship]:
        """Process a single batch of relationships concurrently.

        Uses asyncio.gather with return_exceptions=True for error isolation.

        Args:
            batch: List of (relationship, source_file_path) tuples
            batch_number: Sequential batch number for logging
            relationship_embedder: Embedder for vectors; None when the backend embeds server-side
            relationship_dims: Expected dimensions
            document_processor: Processor for validation
            use_two_pass: Two-pass resolution flag
            stats: Shared statistics dict
            semaphore: Concurrency control semaphore
            rel_type_embedding_cache: Pre-computed embeddings for relationship types

        Returns:
            List of successfully created GraphRelationship objects
        """
        async def process_single(rel_tuple: Tuple[ParserRelationship, str]) -> Optional[GraphRelationship]:
            relationship, source_file_path = rel_tuple
            async with semaphore:
                try:
                    # Use existing _resolve_single_relationship logic
                    result = await self._resolve_single_relationship(
                        relationship,
                        source_file_path,
                        relationship_embedder,
                        relationship_dims,
                        document_processor,
                        stats,
                        [],  # low_confidence_relationships not used in batched mode
                        use_two_pass=False,  # Two-pass handled separately
                        rel_type_embedding_cache=rel_type_embedding_cache,
                    )
                    return result
                except Exception as e:
                    logger.error(
                        "Error processing relationship %s -> %s: %s",
                        relationship.source_name,
                        relationship.target_name,
                        e,
                        exc_info=True
                    )
                    stats["relationships_failed"] += 1
                    return None
        
        # Process all relationships in batch concurrently
        results = await asyncio.gather(
            *[process_single(rel_tuple) for rel_tuple in batch],
            return_exceptions=True
        )
        
        # Filter out None and exceptions
        created_relationships: List[GraphRelationship] = []
        for result in results:
            if isinstance(result, Exception):
                logger.error("Batch processing exception: %s", result)
                stats["relationships_failed"] += 1
            elif isinstance(result, GraphRelationship):
                created_relationships.append(result)
        
        logger.debug(
            "Batch %d: processed %d relationships, created %d",
            batch_number, len(batch), len(created_relationships)
        )
        
        return created_relationships

    async def _commit_batch(
        self,
        relationships: List[GraphRelationship],
        batch_number: int,
        stats: Dict[str, Any],
        event_system: Optional[Any] = None,
    ) -> bool:
        """Commit a batch of relationships to the database.
        
        A failed ``add_graph_relationships`` call is re-raised so the
        index cannot report success after a graph write failure.
        
        Args:
            relationships: Relationships to commit
            batch_number: Batch number for logging
            stats: Statistics dictionary to update
            event_system: Optional event system for batch_complete events
            
        Returns:
            True if commit succeeded.

        Raises:
            Exception: Re-raises the database error after logging and
                incrementing ``stats["commit_failures"]``.
        """
        try:
            await self.db_manager.add_graph_relationships(relationships)
            stats["committed_count"] += len(relationships)
            logger.debug(
                "Committed batch %d (%d relationships, total committed: %d)",
                batch_number, len(relationships), stats["committed_count"]
            )
            
            # Emit batch_complete event (Property 34: Requirements 11.2)
            if event_system is not None:
                try:
                    await event_system.emit(
                        "relationship_flush.batch_complete",
                        source="graph_builder",
                        batch_number=batch_number,
                        batch_size=len(relationships),
                        total_committed=stats["committed_count"],
                        total_relationships=stats.get("total_relationships", 0),
                    )
                except Exception as e:
                    logger.error("Failed to emit batch_complete event: %s", e)
            
            return True
        except Exception as e:
            logger.error(
                "Batch commit failed for batch %d: %s",
                batch_number, e,
                exc_info=True
            )
            stats["commit_failures"] += 1
            stats["last_commit_error"] = str(e)
            raise

    def _log_progress(
        self,
        processed: int,
        total: int,
        start_time: float,
        stats: Dict[str, Any],
    ) -> None:
        """Log progress during batched flush.

        Delegates to RelationshipBatchProcessor.

        Args:
            processed: Number of relationships processed so far
            total: Total relationships to process
            start_time: Operation start timestamp
            stats: Current statistics
        """
        self._batch_processor.log_progress(processed, total, start_time, stats)

    async def _log_resolution_statistics_batched(
        self,
        stats: Dict[str, Any],
        total_time: float,
        relationships_created: int,
    ) -> None:
        """Log final resolution statistics for batched flush.

        Delegates to RelationshipBatchProcessor.

        Args:
            stats: Accumulated statistics
            total_time: Total operation time in seconds
            relationships_created: Total relationships created
        """
        await self._batch_processor.log_statistics(stats, total_time, relationships_created)
    
    def _initialize_resolution_stats(self, use_two_pass: bool) -> Dict[str, Any]:
        """Initialize statistics tracking for relationship resolution.
        
        Args:
            use_two_pass: Whether two-pass resolution is enabled
            
        Returns:
            Statistics dictionary
        """
        return {
            "total": len(self._pending_relationships),
            "resolved_cross_file": 0,
            "unresolved_external": 0,
            "same_file_fallback": 0,
            "by_strategy": {
                "import_path": 0,
                "exact_match": 0,
                "module_path": 0,
                "proximity": 0,
                "no_resolution": 0,
                "external_entity": 0,
            },
            "confidence_levels": {
                "high": 0,      # >= 0.8
                "medium": 0,    # >= 0.6
                "low": 0,       # < 0.6
            },
            "ambiguous_resolutions": 0,
            "confidence_scores": [],
            "two_pass_enabled": use_two_pass,
            "first_pass_resolved": 0,
            "second_pass_improved": 0,
            # New batched-compatible keys (used by _resolve_single_relationship)
            "cross_file_resolutions": 0,
            "same_file_resolutions": 0,
            "external_entity_resolutions": 0,
            "high_confidence_count": 0,
            "medium_confidence_count": 0,
            "low_confidence_count": 0,
        }
    
    async def _resolve_single_relationship(
        self,
        relationship: ParserRelationship,
        source_file_path: str,
        relationship_embedder: Optional[Embedder],
        relationship_dims: int,
        document_processor: Any,
        stats: Dict[str, Any],
        low_confidence_relationships: List[Tuple],
        use_two_pass: bool,
        rel_type_embedding_cache: Optional[Dict[str, List[float]]] = None,
    ) -> Optional[GraphRelationship]:
        """Resolve a single relationship and create GraphRelationship if successful.

        Args:
            relationship: The relationship to resolve
            source_file_path: Path to the source file
            relationship_embedder: Embedder for relationship vectors; None when the backend embeds server-side
            relationship_dims: Expected vector dimensions
            document_processor: Document processor for validation
            stats: Statistics dictionary to update
            low_confidence_relationships: List to store low-confidence relationships
            use_two_pass: Whether two-pass resolution is enabled
            rel_type_embedding_cache: Pre-computed embeddings for relationship types

        Returns:
            GraphRelationship if resolved, None otherwise
        """
        source_id = f"{relationship.source_type}::{self.project_hash}::{source_file_path}::{relationship.source_name}"
        
        target_path = relationship.target_path
        target_type = relationship.target_type
        confidence = None
        resolution_strategy = None
        
        # Extract import_path from relationship metadata if available
        import_path = None
        if hasattr(relationship, 'metadata') and isinstance(relationship.metadata, dict):
            import_path = relationship.metadata.get('import_path')
        
        if not target_path and relationship.type == "imports":
            # Resolve import using RelationshipResolver
            resolved = await self._resolve_import(
                relationship,
                source_file_path,
                import_path,
            )
            
            if resolved:
                target_path, target_type, confidence = resolved
                resolution_strategy = self._determine_resolution_strategy(confidence)
                stats["by_strategy"][resolution_strategy] += 1
                
                # Track import frequency for two-pass resolution
                await self.symbol_registry.track_import(
                    symbol_name=relationship.target_name,
                    source_file=source_file_path,
                    target_file=target_path
                )
                
                logger.debug(
                    f"Resolved {relationship.target_name} from {source_file_path} "
                    f"to {target_path} with confidence {confidence:.2f} "
                    f"using strategy '{resolution_strategy}'"
                )
            
            if target_path and confidence is not None:
                self._track_confidence_stats(
                    confidence,
                    stats,
                    relationship,
                    source_file_path,
                    target_path,
                    resolution_strategy or "unknown",
                    low_confidence_relationships,
                    use_two_pass,
                )
                
                if target_path != source_file_path:
                    stats["cross_file_resolutions"] += 1
                else:
                    stats["same_file_resolutions"] += 1
            else:
                # Unresolved - create external entity instead of dropping
                stats["external_entity_resolutions"] += 1
                stats["by_strategy"]["external_entity"] += 1

                # Detect language from file or metadata
                rel_metadata = getattr(relationship, 'metadata', None) or {}
                language = self._detect_language(source_file_path, rel_metadata)

                # Resolve via external entity resolver
                ext_info = self._queue_external_entity(
                    target_name=relationship.target_name,
                    target_type=relationship.target_type or "module",
                    language=language,
                    source_file=source_file_path,
                    metadata=rel_metadata,
                )

                # Use external entity info for relationship creation
                target_path = ext_info.virtual_path
                target_type = ext_info.entity_type
                confidence = ext_info.confidence
                resolution_strategy = "external_entity"

                logger.debug(
                    "Created external entity for unresolved import: %s -> %s",
                    relationship.source_name, ext_info.entity_id
                )
                # Continue to create relationship with external_target_id
                return await self._create_graph_relationship(
                    relationship,
                    source_id,
                    source_file_path,
                    target_path,
                    target_type,
                    confidence,
                    resolution_strategy,
                    relationship_embedder,
                    relationship_dims,
                    document_processor,
                    target_id=ext_info.entity_id,
                    rel_type_embedding_cache=rel_type_embedding_cache,
                )
        else:
            # Target path already known or not an import relationship
            if not target_path:
                # For "calls" relationships without a target_path, we need to check
                # if the target actually exists in the symbol registry
                if relationship.type == "calls":
                    # Look up the target in the symbol registry
                    candidates = self.symbol_registry.lookup_by_name(relationship.target_name)
                    if candidates:
                        rel_metadata = getattr(relationship, 'metadata', None) or {}

                        # If calling self.method(), prioritize same-file methods
                        # This enables proper resolution of intra-class method calls
                        if rel_metadata.get("object") == "self":
                            # Filter to same file first (self.method() must be in same file)
                            same_file_candidates = [
                                c for c in candidates if c.file_path == source_file_path
                            ]
                            if same_file_candidates:
                                candidates = same_file_candidates
                                logger.debug(
                                    "Filtered 'calls' candidates for self.%s to same-file: %d candidates",
                                    relationship.target_name,
                                    len(candidates)
                                )

                        target_path = candidates[0].file_path
                        target_type = candidates[0].entity_type
                        logger.debug(
                            "Resolved 'calls' target %s to %s via symbol registry",
                            relationship.target_name,
                            target_path
                        )
                    else:
                        # Target not found - create external entity instead of dropping
                        rel_metadata = getattr(relationship, 'metadata', None) or {}
                        language = self._detect_language(source_file_path, rel_metadata)

                        ext_info = self._queue_external_entity(
                            target_name=relationship.target_name,
                            target_type=relationship.target_type or "function",
                            language=language,
                            source_file=source_file_path,
                            metadata=rel_metadata,
                        )

                        target_path = ext_info.virtual_path
                        target_type = ext_info.entity_type
                        confidence = ext_info.confidence
                        resolution_strategy = "external_entity"

                        logger.debug(
                            "Created external entity for unresolved call: %s -> %s",
                            relationship.target_name, ext_info.entity_id
                        )
                        # Continue to create relationship with external_target_id
                        return await self._create_graph_relationship(
                            relationship,
                            source_id,
                            source_file_path,
                            target_path,
                            target_type,
                            confidence,
                            resolution_strategy,
                            relationship_embedder,
                            relationship_dims,
                            document_processor,
                            target_id=ext_info.entity_id,
                            rel_type_embedding_cache=rel_type_embedding_cache,
                        )
                elif relationship.type in ("contains", "follows", "next_sibling", "previous_sibling"):
                    # Document structural relationships - target is within same file
                    target_path = source_file_path
                    # Use provided target_type or infer from relationship type
                    if not target_type:
                        target_type = relationship.target_type or "section"
                    # Document relationships have high confidence (structural, not inferred)
                    confidence = 1.0
                    resolution_strategy = "document_structural"
                    stats["by_strategy"]["document_structural"] += 1
                    stats["same_file_resolutions"] += 1
                    stats["high_confidence_count"] += 1
                    logger.debug(
                        "Resolved document relationship: %s --%s--> %s in %s",
                        relationship.source_name,
                        relationship.type,
                        relationship.target_name,
                        target_path,
                    )
                else:
                    # For other relationship types, fall back to source file
                    target_path = source_file_path
                    # Ensure target_type is set to avoid None in entity ID
                    if not target_type:
                        target_type = relationship.target_type or "unknown"

        # Create GraphRelationship
        return await self._create_graph_relationship(
            relationship,
            source_id,
            source_file_path,
            target_path,
            target_type,
            confidence,
            resolution_strategy,
            relationship_embedder,
            relationship_dims,
            document_processor,
            rel_type_embedding_cache=rel_type_embedding_cache,
        )

    async def _resolve_import(
        self,
        relationship: ParserRelationship,
        source_file_path: str,
        import_path: Optional[str],
    ) -> Optional[Tuple[str, str, float]]:
        """Resolve an import relationship.
        
        Args:
            relationship: The relationship to resolve
            source_file_path: Path to the source file
            import_path: Optional import path from metadata
            
        Returns:
            Tuple of (target_path, target_type, confidence) or None
        """
        from pathlib import Path
        
        # Determine source language from file extension
        source_language = ""
        try:
            ext = Path(source_file_path).suffix.lower()
            language_map = {
                ".py": "python",
                ".js": "javascript",
                ".ts": "typescript",
                ".java": "java",
                ".cpp": "cpp",
                ".c": "c",
                ".go": "go",
                ".rs": "rust",
            }
            source_language = language_map.get(ext, "")
        except (KeyboardInterrupt, SystemExit):
            # Don't catch system signals - let them propagate
            raise
        except Exception as e:
            # Catch and log other exceptions with traceback
            logger.warning(
                "Failed to determine source language for %s: %s",
                source_file_path,
                e,
                exc_info=True
            )
        
        # Use RelationshipResolver to resolve the import
        return await self.relationship_resolver.resolve_import(
            target_name=relationship.target_name,
            target_type=relationship.target_type,
            source_file=source_file_path,
            source_language=source_language,
            import_path=import_path,
        )
    
    def _determine_resolution_strategy(self, confidence: float) -> str:
        """Determine resolution strategy from confidence level.
        
        Args:
            confidence: Confidence score
            
        Returns:
            Strategy name
        """
        if confidence >= 0.95:
            return "import_path"
        elif confidence >= 0.85:
            return "exact_match"
        elif confidence >= 0.7:
            return "module_path"
        else:
            return "proximity"
    
    def _track_confidence_stats(
        self,
        confidence: float,
        stats: Dict[str, Any],
        relationship: ParserRelationship,
        source_file_path: str,
        target_path: str,
        resolution_strategy: str,
        low_confidence_relationships: List[Tuple],
        use_two_pass: bool,
    ) -> None:
        """Track confidence statistics and store low-confidence relationships.
        
        Args:
            confidence: Confidence score
            stats: Statistics dictionary to update
            relationship: The relationship
            source_file_path: Source file path
            target_path: Resolved target path
            resolution_strategy: Resolution strategy used
            low_confidence_relationships: List to store low-confidence relationships
            use_two_pass: Whether two-pass resolution is enabled
        """
        stats["confidence_scores"].append(confidence)
        
        if confidence >= 0.8:
            stats["high_confidence_count"] += 1
            stats["first_pass_resolved"] += 1
            # Track successful high-confidence resolutions
            import asyncio
            asyncio.create_task(
                self.symbol_registry.track_import(
                    relationship.target_name,
                    source_file_path,
                    target_path
                )
            )
        elif confidence >= 0.6:
            # Medium confidence - track separately
            stats["medium_confidence_count"] += 1
            stats["first_pass_resolved"] += 1
            # Track medium-confidence resolutions
            import asyncio
            asyncio.create_task(
                self.symbol_registry.track_import(
                    relationship.target_name,
                    source_file_path,
                    target_path
                )
            )
        else:
            stats["low_confidence_count"] += 1
            stats["ambiguous_resolutions"] += 1
            
            # Store for second pass if enabled
            if use_two_pass:
                low_confidence_relationships.append((
                    relationship,
                    source_file_path,
                    target_path,
                    relationship.target_type,
                    confidence,
                    resolution_strategy
                ))
            
            logger.warning(
                f"Ambiguous resolution: {relationship.target_name} ({relationship.target_type}) "
                f"from {source_file_path} resolved to {target_path} "
                f"with low confidence {confidence:.2f} using strategy '{resolution_strategy}'",
                extra={
                    "project_id": self.project_id,
                    "source_file": source_file_path,
                    "target_name": relationship.target_name,
                    "confidence": confidence,
                    "strategy": resolution_strategy,
                },
            )
    
    async def _create_graph_relationship(
        self,
        relationship: ParserRelationship,
        source_id: str,
        source_file_path: str,
        target_path: str,
        target_type: str,
        confidence: Optional[float],
        resolution_strategy: Optional[str],
        relationship_embedder: Optional[Embedder],
        relationship_dims: int,
        document_processor: Any,
        target_id: Optional[str] = None,
        rel_type_embedding_cache: Optional[Dict[str, List[float]]] = None,
    ) -> GraphRelationship:
        """Create a GraphRelationship from a resolved relationship.

        Args:
            relationship: The original relationship
            source_id: Source entity ID
            source_file_path: Source file path
            target_path: Resolved target path
            target_type: Target entity type
            confidence: Resolution confidence
            resolution_strategy: Resolution strategy used
            relationship_embedder: Embedder for relationship vectors; None when the backend embeds server-side
            relationship_dims: Expected vector dimensions
            document_processor: Document processor for validation
            target_id: Optional explicit target ID (for external entities)
            rel_type_embedding_cache: Pre-computed embeddings for relationship types

        Returns:
            GraphRelationship instance
        """
        # Use provided target_id or generate from components
        if target_id is None:
            target_id = f"{target_type}::{self.project_hash}::{target_path}::{relationship.target_name}"
        rel_hash_input = f"{source_id}:{target_id}:{relationship.type}"
        rel_id = f"edge_{hashlib.md5(rel_hash_input.encode('utf-8')).hexdigest()[:8]}"

        # Use cached embedding if available, otherwise generate and cache
        if rel_type_embedding_cache is not None and relationship.type in rel_type_embedding_cache:
            rel_vector = rel_type_embedding_cache[relationship.type]
        elif relationship_embedder is None:
            rel_vector = [0.0] * relationship_dims
            if rel_type_embedding_cache is not None:
                rel_type_embedding_cache[relationship.type] = rel_vector
        else:
            # Generate embedding in executor to avoid blocking
            loop = asyncio.get_running_loop()
            vectors = await loop.run_in_executor(
                get_embedding_executor(),
                relationship_embedder.generate,
                [relationship.type]
            )
            rel_vector = vectors[0]
            # Cache for future use if cache is provided
            if rel_type_embedding_cache is not None:
                rel_type_embedding_cache[relationship.type] = rel_vector

        if not self._skip_local_embedding:
            document_processor._validate_vector("graph_relationships", "vector", rel_vector, relationship_dims)

        # Build metadata payload
        rel_metadata_payload = self._build_metadata_payload(
            getattr(relationship, "metadata", None),
            getattr(relationship, "ranking_signals", None),
        )
        
        # Add resolution metadata if available
        if confidence is not None and resolution_strategy is not None:
            rel_metadata_payload["resolution_confidence"] = confidence
            rel_metadata_payload["resolution_strategy"] = resolution_strategy
        
        rel_metadata_str = json.dumps(rel_metadata_payload, sort_keys=True) if rel_metadata_payload else None
        
        return GraphRelationship(
            id=rel_id,
            source_id=source_id,
            target_id=target_id,
            type=relationship.type,
            project_id=self.project_id,
            vector=rel_vector,
            metadata=rel_metadata_str,
        )

    def _detect_language(
        self, file_path: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """Detect programming language from metadata or file extension.

        Delegates to ExternalEntityManager.detect_language static method.

        Args:
            file_path: Path to source file
            metadata: Optional metadata that may contain language info

        Returns:
            Language identifier string (lowercase) or empty string
        """
        return ExternalEntityManager.detect_language(file_path, metadata)

    def _queue_external_entity(
        self,
        target_name: str,
        target_type: str,
        language: str = "",
        source_file: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "ExternalEntityInfo":
        """Queue an external entity for creation.

        Delegates to ExternalEntityManager for actual queuing.

        Args:
            target_name: The external symbol name
            target_type: The entity type (function, class, module)
            language: Source language for categorization
            source_file: Source file path
            metadata: Additional metadata from parser

        Returns:
            ExternalEntityInfo with entity_id and other details
        """
        return self._external_entity_manager.queue_external_entity(
            target_name=target_name,
            target_type=target_type,
            language=language,
            source_file=source_file,
            metadata=metadata,
        )

    async def flush_external_entities(
        self,
        document_processor: Any,
    ) -> List[GraphEntity]:
        """Create and return all queued external entities.

        Delegates to ExternalEntityManager.flush_all for actual processing.

        Args:
            document_processor: Document processor for validation

        Returns:
            List of created GraphEntity objects
        """
        return await self._external_entity_manager.flush_all(document_processor)

    async def _second_pass_resolution(
        self,
        low_confidence_relationships: List[Tuple],
        relationship_embedder: Optional[Embedder],
        relationship_dims: int,
        document_processor: Any,
        stats: Dict[str, Any],
        graph_relationships: List[GraphRelationship],
        rel_type_embedding_cache: Optional[Dict[str, List[float]]] = None,
    ) -> List[GraphRelationship]:
        """Perform second pass resolution on low-confidence relationships.

        Args:
            low_confidence_relationships: List of low-confidence relationships
            relationship_embedder: Embedder for relationship vectors; None when the backend embeds server-side
            relationship_dims: Expected vector dimensions
            document_processor: Document processor for validation
            stats: Statistics dictionary to update
            graph_relationships: Existing graph relationships to update
            rel_type_embedding_cache: Pre-computed embeddings for relationship types

        Returns:
            List of improved relationships
        """
        logger.info(
            f"Starting second pass: Re-resolving {len(low_confidence_relationships)} "
            f"low-confidence relationships using learned patterns"
        )
        
        # Clear resolution cache to force re-evaluation
        self.symbol_registry.clear_cache()
        self.relationship_resolver.clear_cache()
        
        improved_relationships = []
        improved_count = 0
        
        for (relationship, source_file_path, old_target_path,
             old_target_type, old_confidence, old_strategy) in low_confidence_relationships:
            
            # Extract import_path from relationship metadata
            import_path = None
            if hasattr(relationship, 'metadata') and isinstance(relationship.metadata, dict):
                import_path = relationship.metadata.get('import_path')
            
            # Re-resolve with enhanced scoring
            resolved = await self._resolve_import(
                relationship,
                source_file_path,
                import_path,
            )
            
            if resolved:
                new_target_path, new_target_type, new_confidence = resolved
                
                # Check if resolution improved
                if new_confidence > old_confidence:
                    improved_count += 1
                    stats["second_pass_improved"] += 1
                    
                    # Remove old relationship from graph_relationships list
                    source_id = f"{relationship.source_type}::{self.project_hash}::{source_file_path}::{relationship.source_name}"
                    old_target_id = f"{old_target_type}::{self.project_hash}::{old_target_path}::{relationship.target_name}"
                    old_rel_hash = f"{source_id}:{old_target_id}:{relationship.type}"
                    old_rel_id = f"edge_{hashlib.md5(old_rel_hash.encode('utf-8')).hexdigest()[:8]}"
                    
                    # Remove old relationship
                    graph_relationships[:] = [
                        rel for rel in graph_relationships
                        if rel.id != old_rel_id
                    ]
                    
                    # Create improved relationship
                    new_rel = await self._create_improved_relationship(
                        relationship,
                        source_id,
                        source_file_path,
                        new_target_path,
                        new_target_type,
                        new_confidence,
                        old_confidence,
                        relationship_embedder,
                        relationship_dims,
                        document_processor,
                        rel_type_embedding_cache=rel_type_embedding_cache,
                    )
                    improved_relationships.append(new_rel)
                    
                    # Track the improved resolution
                    await self.symbol_registry.track_import(
                        relationship.target_name,
                        source_file_path,
                        new_target_path
                    )
                    
                    # Update confidence level stats
                    if new_confidence >= 0.8:
                        stats["confidence_levels"]["high"] += 1
                        stats["confidence_levels"]["low"] -= 1
                    elif new_confidence >= 0.6:
                        stats["confidence_levels"]["medium"] += 1
                        stats["confidence_levels"]["low"] -= 1
                    
                    stats["confidence_scores"].append(new_confidence)
                    
                    logger.info(
                        f"Second pass improved: {relationship.target_name} from {source_file_path} "
                        f"confidence {old_confidence:.2f} → {new_confidence:.2f} "
                        f"(target: {old_target_path} → {new_target_path})"
                    )
        
        if improved_count > 0:
            logger.info(
                f"Second pass complete: Improved {improved_count}/{len(low_confidence_relationships)} "
                f"low-confidence resolutions ({improved_count/len(low_confidence_relationships)*100:.1f}%)"
            )
        else:
            logger.info("Second pass complete: No improvements found")
        
        return improved_relationships
    
    async def _create_improved_relationship(
        self,
        relationship: ParserRelationship,
        source_id: str,
        source_file_path: str,
        new_target_path: str,
        new_target_type: str,
        new_confidence: float,
        old_confidence: float,
        relationship_embedder: Optional[Embedder],
        relationship_dims: int,
        document_processor: Any,
        rel_type_embedding_cache: Optional[Dict[str, List[float]]] = None,
    ) -> GraphRelationship:
        """Create an improved relationship from second pass resolution.

        Args:
            relationship: The original relationship
            source_id: Source entity ID
            source_file_path: Source file path
            new_target_path: New resolved target path
            new_target_type: New target entity type
            new_confidence: New confidence score
            old_confidence: Old confidence score
            relationship_embedder: Embedder for relationship vectors; None when the backend embeds server-side
            relationship_dims: Expected vector dimensions
            document_processor: Document processor for validation
            rel_type_embedding_cache: Pre-computed embeddings for relationship types

        Returns:
            GraphRelationship instance
        """
        new_target_id = f"{new_target_type}::{self.project_hash}::{new_target_path}::{relationship.target_name}"
        new_rel_hash = f"{source_id}:{new_target_id}:{relationship.type}"
        new_rel_id = f"edge_{hashlib.md5(new_rel_hash.encode('utf-8')).hexdigest()[:8]}"

        # Use cached embedding if available, otherwise generate and cache
        if rel_type_embedding_cache is not None and relationship.type in rel_type_embedding_cache:
            rel_vector = rel_type_embedding_cache[relationship.type]
        elif relationship_embedder is None:
            rel_vector = [0.0] * relationship_dims
            if rel_type_embedding_cache is not None:
                rel_type_embedding_cache[relationship.type] = rel_vector
        else:
            loop = asyncio.get_running_loop()
            vectors = await loop.run_in_executor(
                get_embedding_executor(),
                relationship_embedder.generate,
                [relationship.type]
            )
            rel_vector = vectors[0]
            # Cache for future use if cache is provided
            if rel_type_embedding_cache is not None:
                rel_type_embedding_cache[relationship.type] = rel_vector

        rel_metadata_payload = self._build_metadata_payload(
            getattr(relationship, "metadata", None),
            getattr(relationship, "ranking_signals", None),
        )
        rel_metadata_payload["resolution_confidence"] = new_confidence
        rel_metadata_payload["resolution_strategy"] = "two_pass_enhanced"
        rel_metadata_payload["first_pass_confidence"] = old_confidence
        rel_metadata_str = json.dumps(rel_metadata_payload, sort_keys=True)
        
        return GraphRelationship(
            id=new_rel_id,
            source_id=source_id,
            target_id=new_target_id,
            type=relationship.type,
            project_id=self.project_id,
            vector=rel_vector,
            metadata=rel_metadata_str,
        )
    
    async def _log_resolution_statistics(
        self,
        stats: Dict[str, Any],
        resolution_time: float,
        relationship_count: int,
    ) -> None:
        """Log comprehensive resolution statistics.
        
        Args:
            stats: Statistics dictionary
            resolution_time: Time taken for resolution
            relationship_count: Number of relationships created
        """
        # Calculate average confidence score
        avg_confidence = (
            sum(stats["confidence_scores"]) / len(stats["confidence_scores"])
            if stats["confidence_scores"]
            else 0.0
        )
        
        # Get cache statistics from RelationshipResolver
        resolver_stats = self.relationship_resolver.get_resolution_stats()
        
        # Add computed statistics
        stats["average_confidence"] = avg_confidence
        stats["resolution_time_seconds"] = resolution_time
        
        # Calculate resolution rates
        internal_imports = stats["resolved_cross_file"] + stats["same_file_fallback"]
        if internal_imports > 0:
            stats["cross_file_resolution_rate"] = (stats["resolved_cross_file"] / internal_imports) * 100
        else:
            stats["cross_file_resolution_rate"] = 0.0
        
        total_resolved = stats["resolved_cross_file"] + stats["same_file_fallback"]
        total_attempted = total_resolved + stats["unresolved_external"]
        if total_attempted > 0:
            stats["overall_resolution_rate"] = (total_resolved / total_attempted) * 100
        else:
            stats["overall_resolution_rate"] = 0.0
        
        stats["resolver_cache_statistics"] = {
            "hits": resolver_stats["cache_hits"],
            "misses": resolver_stats["cache_misses"],
            "size": resolver_stats["cache_size"],
        }
        
        # Get symbol registry stats
        registry_stats = await self.symbol_registry.get_stats()
        
        # Build two-pass statistics message
        two_pass_msg = ""
        if stats["two_pass_enabled"]:
            two_pass_msg = (
                f"Two-pass resolution:\n"
                f"  - First pass resolved: {stats['first_pass_resolved']}\n"
                f"  - Second pass improved: {stats['second_pass_improved']}\n"
            )
        
        # Log comprehensive statistics
        logger.info(
            f"Created {relationship_count} relationships in {resolution_time:.2f}s:\n"
            f"  - Cross-file resolved: {stats['resolved_cross_file']}\n"
            f"  - External/stdlib (unresolved): {stats['unresolved_external']}\n"
            f"  - Same-file fallback: {stats['same_file_fallback']}\n"
            f"Resolution by strategy:\n"
            f"  - Import path: {stats['by_strategy']['import_path']}\n"
            f"  - Exact match: {stats['by_strategy']['exact_match']}\n"
            f"  - Module path: {stats['by_strategy']['module_path']}\n"
            f"  - Proximity: {stats['by_strategy']['proximity']}\n"
            f"  - No resolution: {stats['by_strategy']['no_resolution']}\n"
            f"Confidence distribution:\n"
            f"  - High (≥0.8): {stats['confidence_levels']['high']}\n"
            f"  - Medium (≥0.6): {stats['confidence_levels']['medium']}\n"
            f"  - Low (<0.6): {stats['confidence_levels']['low']}\n"
            f"  - Average: {avg_confidence:.3f}\n"
            f"Ambiguous resolutions (low confidence): {stats['ambiguous_resolutions']}\n"
            f"{two_pass_msg}"
            f"Enhanced features:\n"
            f"  - Import frequency tracked: {registry_stats['import_frequency_entries']} symbols\n"
            f"  - Co-occurrence tracked: {registry_stats['co_occurrence_entries']} file pairs\n"
            f"Resolver cache statistics:\n"
            f"  - Hits: {resolver_stats['cache_hits']}, Misses: {resolver_stats['cache_misses']}\n"
            f"  - Cache size: {resolver_stats['cache_size']}",
            extra={
                "project_id": self.project_id,
                "resolution_stats": stats,
            },
        )
        
        # Log resolution rates
        if stats["total"] > 0:
            if internal_imports > 0:
                cross_file_rate = (stats["resolved_cross_file"] / internal_imports) * 100
                logger.info(
                    f"Cross-file resolution rate: {cross_file_rate:.1f}% "
                    f"({stats['resolved_cross_file']}/{internal_imports} internal imports)"
                )
            
            if total_attempted > 0:
                overall_rate = (total_resolved / total_attempted) * 100
                logger.info(
                    f"Overall resolution success: {overall_rate:.1f}% "
                    f"({total_resolved}/{total_attempted} relationships)"
                )
            
            logger.info(
                f"External dependencies identified: {stats['unresolved_external']} "
                f"({stats['unresolved_external']/stats['total']*100:.1f}% of total)"
            )
