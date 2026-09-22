"""
Memory System orchestrator.

Main entry point for the three-tier memory system, coordinating
working, episodic, and semantic memory layers with consolidation
and retrieval engines.

The system uses MemoryStorageProtocol for persistent storage operations,
enabling backend swappability. By default, LanceDBMemoryAdapter is used.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from types import TracebackType
from typing import Any, Dict, List, Union, TYPE_CHECKING

from agent_vault.config import Config
from agent_vault.database.lancedb_manager import LanceDBManager
from agent_vault.embeddings.service import EmbeddingService
from agent_vault.events.models import EventStatus
from agent_vault.memory.adapters.lancedb_adapter import LanceDBMemoryAdapter
from agent_vault.memory.consolidation import ConsolidationEngine
from agent_vault.memory.context import ContextManager
from agent_vault.memory.layers.episodic import EpisodicMemory
from agent_vault.memory.layers.semantic import SemanticMemory
from agent_vault.memory.layers.working import WorkingMemory
from agent_vault.memory.models import (
    ConsolidationResult,
    MemoryContext,
    MemoryItem,
    MemoryStatus,
    MemoryTier,
    RetrievalResult,
)
from agent_vault.memory.protocols import MemoryStorageProtocol
from agent_vault.memory.retrieval import RetrievalEngine

if TYPE_CHECKING:
    from agent_vault.events.system import EventSystem

logger = logging.getLogger(__name__)


class MemorySystem:
    """
    Main orchestrator for the three-tier memory system.

    Coordinates working, episodic, and semantic memory layers with
    consolidation and retrieval engines. Provides a unified API for
    storing, retrieving, and managing memories across all tiers.

    Example using async context manager (recommended):
        ```python
        from agent_vault.config import Config
        from agent_vault.embeddings.service import EmbeddingService
        from agent_vault.memory import MemorySystem, MemoryContext

        config = Config.load()
        embedding_service = EmbeddingService(config)

        async with MemorySystem(config, embedding_service) as memory:
            context = memory.create_agent_context(
                agent_id="assistant_001",
                session_id="session_xyz",
                conversation_id="conv_abc"
            )
            item = await memory.store(
                content="User prefers Python for data analysis",
                context=context,
                importance=0.9
            )
        # Automatically shuts down on exit
        ```

    Example with manual lifecycle management:
        ```python
        memory_system = MemorySystem(config, embedding_service)
        await memory_system.initialize()
        try:
            # Use memory system...
            results = await memory_system.retrieve(
                query="programming preferences",
                context=context,
                limit=10
            )
        finally:
            await memory_system.shutdown()
        ```
    """

    def __init__(
        self,
        config: Config,
        embedding_service: EmbeddingService,
        vector_store: LanceDBManager | None = None,
        event_system: "EventSystem | None" = None,
        episodic_storage: MemoryStorageProtocol | None = None,
        semantic_storage: MemoryStorageProtocol | None = None,
    ) -> None:
        """
        Initialize MemorySystem.

        Recommended usage: Inject storage adapters via episodic_storage and
        semantic_storage parameters. The factory creates these adapters.

        Args:
            config: System configuration
            embedding_service: Service for generating embeddings
            vector_store: LanceDBManager for internal adapter creation.
                Only used if episodic_storage/semantic_storage not provided.
                Prefer passing adapters directly for proper dependency injection.
            event_system: Optional event system for emitting memory events
            episodic_storage: Storage adapter for episodic memory (recommended)
            semantic_storage: Storage adapter for semantic memory (recommended)
        """
        self.config = config
        self.embedding_service = embedding_service
        self.event_system = event_system

        # Handle storage - prefer injected adapters over creating internally
        if episodic_storage is not None and semantic_storage is not None:
            # Adapters injected - no need for vector_store reference
            self.vector_store = None
        else:
            # Need to create adapters internally - use provided or create vector_store
            if vector_store is None:
                db_path = config.storage.get_lancedb_path()
                vector_store = LanceDBManager(
                    uri=str(db_path),
                    project_id="memory_system",
                )
            self.vector_store = vector_store

            # Get embedding dimensions from config
            embedding_dims = config.embeddings.default_dimensions

            # Create storage adapters if not provided
            if episodic_storage is None:
                episodic_storage = LanceDBMemoryAdapter(
                    manager=vector_store,
                    table_name=config.memory.episodic_memory.table_name,
                    embedding_dims=embedding_dims,
                )
            if semantic_storage is None:
                semantic_storage = LanceDBMemoryAdapter(
                    manager=vector_store,
                    table_name=config.memory.semantic_memory.table_name,
                    embedding_dims=embedding_dims,
                )

        # Store adapters for reference
        self._episodic_storage = episodic_storage
        self._semantic_storage = semantic_storage

        # Working memory (in-memory, no persistence)
        self.working_memory = WorkingMemory(
            capacity=config.memory.working_memory.capacity
        )

        # Episodic memory (uses storage adapter)
        self.episodic_memory = EpisodicMemory(
            storage=episodic_storage,
            limit=config.memory.episodic_memory.capacity,
        )

        # Semantic memory (uses storage adapter)
        self.semantic_memory = SemanticMemory(
            storage=semantic_storage,
            limit=config.memory.semantic_memory.capacity,
        )

        # Initialize consolidation engine
        self.consolidation_engine = ConsolidationEngine(
            working_memory=self.working_memory,
            episodic_memory=self.episodic_memory,
            semantic_memory=self.semantic_memory,
            embedding_service=embedding_service,
            episodic_threshold=config.memory.consolidation.episodic_threshold,
            semantic_threshold=config.memory.consolidation.semantic_threshold,
        )

        # Initialize retrieval engine
        self.retrieval_engine = RetrievalEngine(
            working_memory=self.working_memory,
            episodic_memory=self.episodic_memory,
            semantic_memory=self.semantic_memory,
            embedding_service=embedding_service,
            config=config,
        )

        # Initialize context manager with config values
        context_mgr_config = getattr(config.memory, "context_manager", None)
        self.context_manager = ContextManager(
            max_concurrent_contexts=getattr(context_mgr_config, "max_concurrent_contexts", 100) if context_mgr_config else 100,
            cleanup_interval=getattr(context_mgr_config, "cleanup_interval", 300) if context_mgr_config else 300,
            context_ttl=getattr(context_mgr_config, "context_ttl", 3600) if context_mgr_config else 3600,
        )

        # Initialization state
        self._initialized = False
        self._init_lock = asyncio.Lock()
        self._consolidation_task: asyncio.Task[None] | None = None

        logger.info("MemorySystem created (not yet initialized)")

    async def __aenter__(self) -> "MemorySystem":
        """
        Enter async context manager, initializing the memory system.

        Returns:
            Self after initialization

        Example:
            ```python
            async with MemorySystem(config, embedding_service) as memory:
                # Use memory system...
                item = await memory.store(content="...", context=ctx, importance=0.8)
            # Automatically shuts down on exit
            ```
        """
        await self.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """
        Exit async context manager, shutting down the memory system.

        Performs cleanup including final consolidation and resource release.

        Args:
            exc_type: Exception type if an exception was raised
            exc_val: Exception value if an exception was raised
            exc_tb: Exception traceback if an exception was raised
        """
        await self.shutdown()

    async def initialize(self) -> None:
        """
        Initialize all memory system components.

        Sets up LanceDB tables for episodic and semantic memory,
        starts background consolidation task if enabled, and
        validates configuration.

        This method is idempotent and can be called multiple times safely.

        Raises:
            ValueError: If configuration validation fails
        """
        async with self._init_lock:
            if self._initialized:
                logger.debug("MemorySystem already initialized")
                return

            logger.info("Initializing MemorySystem...")

            # Validate configuration
            self._validate_configuration()

            # Initialize memory layers
            logger.debug("Initializing episodic memory...")
            await self.episodic_memory.initialize()

            logger.debug("Initializing semantic memory...")
            await self.semantic_memory.initialize()

            # Start context manager
            logger.debug("Starting context manager...")
            await self.context_manager.start()

            # Start background consolidation task if enabled
            consolidation_config = getattr(self.config.memory, "consolidation", None)
            consolidation_enabled = getattr(consolidation_config, "enabled", True) if consolidation_config else True
            if consolidation_enabled:
                logger.debug("Starting background consolidation task...")
                self._consolidation_task = asyncio.create_task(
                    self._consolidation_loop()
                )

            self._initialized = True
            logger.info("MemorySystem initialized successfully")

    def _validate_configuration(self) -> None:
        """
        Validate configuration values.

        Raises:
            ValueError: If configuration is invalid
        """
        # Validate that required config sections exist
        if not hasattr(self.config, "storage"):
            raise ValueError("Config missing required 'storage' section")

        if not hasattr(self.config, "embeddings"):
            raise ValueError("Config missing required 'embeddings' section")

        logger.debug("Configuration validated successfully")

    async def _consolidation_loop(self) -> None:
        """
        Background task for periodic memory consolidation.

        Runs consolidation at configured intervals for all active contexts.
        """
        consolidation_config = getattr(self.config.memory, "consolidation", None)
        interval_seconds = getattr(consolidation_config, "interval_seconds", 300) if consolidation_config else 300
        
        logger.info("Consolidation loop started with interval %ds", interval_seconds)

        while self._initialized:
            try:
                await asyncio.sleep(interval_seconds)

                # Get all active contexts
                active_contexts = self.context_manager.get_active_contexts()

                if not active_contexts:
                    logger.debug("No active contexts for consolidation")
                    continue

                logger.debug(
                    "Running consolidation for %d active contexts",
                    len(active_contexts),
                )

                # Consolidate each context
                for context in active_contexts:
                    try:
                        if self.consolidation_engine.should_consolidate(context):
                            result = await self.consolidation_engine.consolidate(context)
                            logger.debug(
                                "Consolidated context %s: promoted=%d, concepts=%d",
                                context.context_key,
                                result.items_promoted,
                                result.concepts_extracted,
                            )
                    except Exception:
                        logger.exception(
                            "Error consolidating context %s",
                            context.context_key,
                        )

            except asyncio.CancelledError:
                logger.info("Consolidation loop cancelled")
                break
            except Exception:
                logger.exception("Error in consolidation loop")
                # Continue running despite errors

    async def shutdown(self) -> None:
        """
        Shutdown the memory system and cleanup resources.

        Stops background tasks, performs final consolidation,
        and closes database connections.
        """
        if not self._initialized:
            logger.debug("MemorySystem not initialized, nothing to shutdown")
            return

        logger.info("Shutting down MemorySystem...")

        # Stop consolidation task
        if self._consolidation_task:
            self._consolidation_task.cancel()
            try:
                await self._consolidation_task
            except asyncio.CancelledError:
                pass

        # Stop context manager
        await self.context_manager.stop()

        # Perform final consolidation for all active contexts
        active_contexts = self.context_manager.get_active_contexts()
        if active_contexts:
            logger.info(
                "Performing final consolidation for %d contexts",
                len(active_contexts),
            )
            for context in active_contexts:
                try:
                    await self.consolidation_engine.consolidate(context)
                except Exception:
                    logger.exception(
                        "Error in final consolidation for context %s",
                        context.context_key,
                    )

        # Close database connections
        # Note: LanceDBManager doesn't have explicit close method
        # but we mark as not initialized
        self._initialized = False

        logger.info("MemorySystem shutdown complete")

    async def store(
        self,
        content: str,
        context: MemoryContext,
        importance: float,
        summary: str | None = None,
        metadata: dict[str, Any] | None = None,
        event_type: str | None = None,
        emotional_valence: float | None = None,
        emotional_arousal: float | None = None,
        subject: str | None = None,
        relationship: str | None = None,
        object: str | None = None,
        confidence: float | None = None,
    ) -> MemoryItem:
        """
        Store a memory item with automatic tier selection.

        Generates embeddings for content and summary using appropriate densities
        based on the target tier (determined by importance score). Returns the
        full MemoryItem object for advanced usage.

        Args:
            content: Full content of the memory
            context: Memory context for agent/session/conversation scoping
            importance: Importance score (0.0-1.0) determines target tier
            summary: Optional concise summary (auto-generated if None)
            metadata: Optional metadata dictionary
            event_type: Optional event type for episodic memories
            emotional_valence: Optional emotional valence (-1.0 to 1.0)
            emotional_arousal: Optional emotional arousal (0.0 to 1.0)
            subject: Optional subject for semantic facts
            relationship: Optional relationship for semantic facts
            object: Optional object for semantic facts
            confidence: Optional confidence score for semantic facts

        Returns:
            Full MemoryItem object with all fields populated

        Raises:
            ValueError: If importance is out of range or system not initialized
        """
        if not self._initialized:
            raise ValueError("MemorySystem not initialized. Call initialize() first.")

        # Validate importance
        if not 0.0 <= importance <= 1.0:
            raise ValueError(f"importance must be between 0.0 and 1.0, got {importance}")

        # Auto-generate summary if not provided
        if summary is None:
            summary_config = getattr(self.config.memory, "summary", None)
            auto_threshold = getattr(summary_config, "auto_threshold", 150) if summary_config else 150
            if len(content) <= auto_threshold:
                summary = content
            else:
                # Simple truncation for now
                summary = content[:auto_threshold] + "..."

        # Determine target tier based on importance
        if importance >= 0.9:
            target_tier = MemoryTier.SEMANTIC
        elif importance >= 0.7:
            target_tier = MemoryTier.EPISODIC
        else:
            target_tier = MemoryTier.WORKING

        # Generate embeddings (same dimensions for all content)
        logger.debug("Generating embeddings for content and summary")

        content_embedding, summary_embedding = await asyncio.gather(
            self.embedding_service.embed_async(content),
            self.embedding_service.embed_async(summary),
        )

        # Create MemoryItem
        item = MemoryItem(
            id=str(uuid.uuid4()),
            content=content,
            summary=summary,
            context=context,
            importance=importance,
            tier=target_tier,
            creator_agent_id=context.agent_id,
            modifier_agent_id=context.agent_id,
            content_source="user_input",
            embedding=content_embedding,
            summary_embedding=summary_embedding,
            event_type=event_type,
            emotional_valence=emotional_valence,
            emotional_arousal=emotional_arousal,
            subject=subject,
            relationship=relationship,
            object=object,
            confidence=confidence,
            metadata=metadata or {},
        )

        # Store in appropriate tier
        if target_tier == MemoryTier.WORKING:
            await self.working_memory.store(item)
            logger.debug(
                "Stored in working memory: id=%s, importance=%.3f",
                item.id,
                importance,
            )
        elif target_tier == MemoryTier.EPISODIC:
            await self.episodic_memory.store(item)
            logger.debug(
                "Stored in episodic memory: id=%s, importance=%.3f",
                item.id,
                importance,
            )
        else:  # SEMANTIC
            await self.semantic_memory.store(item)
            logger.debug(
                "Stored in semantic memory: id=%s, importance=%.3f",
                item.id,
                importance,
            )

        logger.info(
            "Stored memory: id=%s, tier=%s, agent=%s, importance=%.3f",
            item.id,
            target_tier.value,
            context.agent_id,
            importance,
        )

        # Emit memory.stored event
        if self.event_system:
            await self.event_system.emit(
                "memory.stored",
                source="MemorySystem",
                status=EventStatus.COMPLETED,
                memory_id=item.id,
                tier=target_tier.value,
                agent_id=context.agent_id,
                session_id=context.session_id,
                importance=importance,
                content_length=len(content)
            )

        return item

    async def batch_store(
        self,
        items: list[tuple[str, MemoryContext, float, str | None, dict[str, Any] | None]],
    ) -> list[MemoryItem]:
        """
        Store multiple memory items in parallel.

        Args:
            items: List of tuples where each tuple contains:
                - content (str): The memory content text
                - context (MemoryContext): The memory context (agent_id, session_id, etc.)
                - importance (float): Importance score between 0.0 and 1.0
                - summary (str | None): Optional summary of the content
                - metadata (dict[str, Any] | None): Optional additional metadata

        Returns:
            List of MemoryItem objects in the same order as input

        Raises:
            ValueError: If system not initialized

        Example:
            >>> items = [
            ...     ("User completed task A", context, 0.8, "Task completion", None),
            ...     ("User asked about feature B", context, 0.6, "Feature inquiry", {"category": "support"}),
            ...     ("System error occurred", context, 0.9, "Error event", {"severity": "high"}),
            ... ]
            >>> stored_items = await memory_system.batch_store(items=items)
            >>> assert len(stored_items) == 3
        """
        if not self._initialized:
            raise ValueError("MemorySystem not initialized. Call initialize() first.")

        # Create storage tasks
        tasks = [
            self.store(content, context, importance, summary, metadata)
            for content, context, importance, summary, metadata in items
        ]

        # Execute in parallel
        results = await asyncio.gather(*tasks)

        logger.info("Batch stored %d memory items", len(results))

        return list(results)

    async def retrieve(
        self,
        query: str,
        context: MemoryContext,
        limit: int = 10,
        strategy: str = "adaptive",
    ) -> Union[List[RetrievalResult], Dict[str, Any]]:
        """
        Retrieve relevant memories using specified strategy.

        Args:
            query: Query string
            context: Memory context for filtering
            limit: Maximum number of results to return
            strategy: Search strategy (relevance, recency, importance, adaptive, hybrid_precision)

        Returns:
            List of RetrievalResult objects or Dict (if ambiguity detected)

        Raises:
            ValueError: If system not initialized or invalid strategy
        """
        if not self._initialized:
            raise ValueError("MemorySystem not initialized. Call initialize() first.")

        # Get agent profile for personalization
        profile = self.context_manager.get_agent_profile(context.agent_id)

        # Use profile's preferred strategy if available
        if strategy == "adaptive" and profile.successful_strategies:
            # Get most successful strategy
            most_successful = max(
                profile.successful_strategies.items(),
                key=lambda x: x[1],
            )[0]
            logger.debug(
                "Using agent's preferred strategy: %s (from profile)",
                most_successful,
            )
            # Note: We still use adaptive but could customize weights here

        # Call retrieval engine
        results = await self.retrieval_engine.retrieve(
            query=query,
            context=context,
            strategy=strategy,
            limit=limit,
        )
        
        results_count = len(results["results"]) if isinstance(results, dict) else len(results)

        # Update agent profile with query pattern
        # Simple pattern: first word of query
        query_pattern = query.split()[0] if query.split() else "unknown"
        self.context_manager.update_agent_profile_from_feedback(
            agent_id=context.agent_id,
            strategy=strategy,
            query_pattern=query_pattern,
            success=bool(results_count > 0),
        )

        logger.info(
            "Retrieved %d memories for query='%s', agent=%s, strategy=%s",
            results_count,
            query[:50],
            context.agent_id,
            strategy,
        )

        # Emit memory.retrieved event
        if self.event_system:
            await self.event_system.emit(
                "memory.retrieved",
                source="MemorySystem",
                status=EventStatus.COMPLETED,
                agent_id=context.agent_id,
                session_id=context.session_id,
                query=query[:100],  # Truncate long queries
                strategy=strategy,
                results_count=results_count,
                limit=limit
            )

        return results

    async def batch_retrieve(
        self,
        queries: list[tuple[str, MemoryContext]],
        limit: int = 10,
        strategy: str = "adaptive",
    ) -> List[Union[List[RetrievalResult], Dict[str, Any]]]:
        """
        Retrieve memories for multiple queries in parallel.

        Args:
            queries: List of (query, context) tuples
            limit: Maximum number of results per query
            strategy: Search strategy to use for all queries

        Returns:
            List of result lists (or dicts), one per query in the same order

        Raises:
            ValueError: If system not initialized
        """
        if not self._initialized:
            raise ValueError("MemorySystem not initialized. Call initialize() first.")

        # Use retrieval engine's batch method
        results = await self.retrieval_engine.batch_retrieve(
            queries=queries,
            strategy=strategy,
            limit=limit,
        )

        logger.info(
            "Batch retrieved %d queries with strategy=%s",
            len(queries),
            strategy,
        )

        return results

    async def update_importance(
        self,
        item_id: str,
        new_importance: float,
        tier: MemoryTier | None = None,
    ) -> bool:
        """
        Update the importance score of a memory item.

        Searches for the item in the specified tier (or all tiers if None)
        and updates its importance score.

        Args:
            item_id: Unique identifier of the memory item
            new_importance: New importance score (0.0-1.0)
            tier: Optional tier to search (searches all if None)

        Returns:
            True if item was found and updated, False otherwise

        Raises:
            ValueError: If importance is out of range or system not initialized
        """
        if not self._initialized:
            raise ValueError("MemorySystem not initialized. Call initialize() first.")

        if not 0.0 <= new_importance <= 1.0:
            raise ValueError(
                f"new_importance must be between 0.0 and 1.0, got {new_importance}"
            )

        # Search in specified tier or all tiers
        tiers_to_search = [tier] if tier else [
            MemoryTier.WORKING,
            MemoryTier.EPISODIC,
            MemoryTier.SEMANTIC,
        ]

        for search_tier in tiers_to_search:
            item = None

            if search_tier == MemoryTier.WORKING:
                item = await self.working_memory.get_by_id(item_id)
            elif search_tier == MemoryTier.EPISODIC:
                item = await self.episodic_memory.get_by_id(item_id, update_access=False)
            else:  # SEMANTIC
                item = await self.semantic_memory.get_by_id(item_id, update_access=False)

            if item:
                # Update importance
                item.importance = new_importance
                item.modified_at = datetime.now(timezone.utc)
                item.modifier_agent_id = item.context.agent_id

                # Store updated item
                if search_tier == MemoryTier.WORKING:
                    await self.working_memory.store(item)
                elif search_tier == MemoryTier.EPISODIC:
                    await self.episodic_memory.update(item)
                else:  # SEMANTIC
                    await self.semantic_memory.update(item)

                logger.info(
                    "Updated importance: id=%s, tier=%s, old=%.3f, new=%.3f",
                    item_id,
                    search_tier.value,
                    item.importance,
                    new_importance,
                )

                return True

        logger.warning("Item not found for importance update: id=%s", item_id)
        return False

    async def update_confidence(
        self,
        item_id: str,
        new_confidence: float,
    ) -> bool:
        """
        Update the confidence score of a semantic memory fact.

        Only applicable to semantic memory items.

        Args:
            item_id: Unique identifier of the memory item
            new_confidence: New confidence score (0.0-1.0)

        Returns:
            True if item was found and updated, False otherwise

        Raises:
            ValueError: If confidence is out of range or system not initialized
        """
        if not self._initialized:
            raise ValueError("MemorySystem not initialized. Call initialize() first.")

        if not 0.0 <= new_confidence <= 1.0:
            raise ValueError(
                f"new_confidence must be between 0.0 and 1.0, got {new_confidence}"
            )

        # Search in semantic memory
        item = await self.semantic_memory.get_by_id(item_id, update_access=False)

        if not item:
            logger.warning("Item not found for confidence update: id=%s", item_id)
            return False

        # Update confidence
        old_confidence = item.confidence
        item.confidence = new_confidence
        item.modified_at = datetime.now(timezone.utc)
        item.modifier_agent_id = item.context.agent_id

        # Store updated item
        await self.semantic_memory.update(item)

        logger.info(
            "Updated confidence: id=%s, old=%.3f, new=%.3f",
            item_id,
            old_confidence or 0.0,
            new_confidence,
        )

        return True

    async def delete(
        self,
        item_id: str,
        tier: MemoryTier | None = None,
    ) -> bool:
        """
        Delete a memory item from any tier.

        Searches for the item in the specified tier (or all tiers if None)
        and removes it.

        Args:
            item_id: Unique identifier of the memory item
            tier: Optional tier to search (searches all if None)

        Returns:
            True if item was found and deleted, False otherwise

        Raises:
            ValueError: If system not initialized
        """
        if not self._initialized:
            raise ValueError("MemorySystem not initialized. Call initialize() first.")

        # Search in specified tier or all tiers
        tiers_to_search = [tier] if tier else [
            MemoryTier.WORKING,
            MemoryTier.EPISODIC,
            MemoryTier.SEMANTIC,
        ]

        for search_tier in tiers_to_search:
            deleted = False

            if search_tier == MemoryTier.WORKING:
                deleted = await self.working_memory.delete(item_id)
            elif search_tier == MemoryTier.EPISODIC:
                deleted = await self.episodic_memory.delete(item_id)
            else:  # SEMANTIC
                deleted = await self.semantic_memory.delete(item_id)

            if deleted:
                logger.info(
                    "Deleted memory: id=%s, tier=%s",
                    item_id,
                    search_tier.value,
                )
                return True

        logger.warning("Item not found for deletion: id=%s", item_id)
        return False

    async def promote_to_semantic(
        self,
        item_id: str,
        confidence: float | None = None,
    ) -> bool:
        """
        Manually promote a memory item to semantic tier.

        Searches for the item in working or episodic memory and promotes
        it to semantic memory with optional confidence score.

        Args:
            item_id: Unique identifier of the memory item
            confidence: Optional confidence score (0.0-1.0)

        Returns:
            True if item was found and promoted, False otherwise

        Raises:
            ValueError: If system not initialized or confidence out of range
        """
        if not self._initialized:
            raise ValueError("MemorySystem not initialized. Call initialize() first.")

        if confidence is not None and not 0.0 <= confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {confidence}"
            )

        # Search in working and episodic memory
        item = None
        source_tier = None

        item = await self.working_memory.get_by_id(item_id)
        if item:
            source_tier = MemoryTier.WORKING
        else:
            item = await self.episodic_memory.get_by_id(item_id, update_access=False)
            if item:
                source_tier = MemoryTier.EPISODIC

        if not item:
            logger.warning("Item not found for promotion: id=%s", item_id)
            return False

        # Re-embed for semantic memory (same dimensions for all content)
        content_embedding, summary_embedding = await asyncio.gather(
            self.embedding_service.embed_async(item.content),
            self.embedding_service.embed_async(item.summary),
        )

        # Update item
        item.embedding = content_embedding
        item.summary_embedding = summary_embedding
        item.tier = MemoryTier.SEMANTIC
        item.modified_at = datetime.now(timezone.utc)

        # Set confidence if provided
        if confidence is not None:
            item.confidence = confidence
        elif item.confidence is None:
            # Calculate default confidence from importance and access count
            item.confidence = min(
                (item.importance * 0.7) + (min(item.access_count / 10.0, 1.0) * 0.3),
                1.0,
            )

        # Store in semantic memory
        await self.semantic_memory.store(item)

        # Delete from source tier
        if source_tier == MemoryTier.WORKING:
            await self.working_memory.delete(item_id)
        else:  # EPISODIC
            await self.episodic_memory.delete(item_id)

        # source_tier is guaranteed to be set at this point since we return early if item is None
        assert source_tier is not None
        logger.info(
            "Manually promoted to semantic: id=%s, from=%s, confidence=%.3f",
            item_id,
            source_tier.value,
            item.confidence or 0.0,
        )

        return True

    async def negate_memory(self, item_id: str) -> bool:
        """
        Mark a memory item as negated (invalid/false).

        Args:
            item_id: ID of the item to negate

        Returns:
            True if successful, False if item not found
        """
        if not self._initialized:
            raise ValueError("MemorySystem not initialized. Call initialize() first.")

        # Search all tiers
        tiers = [MemoryTier.WORKING, MemoryTier.EPISODIC, MemoryTier.SEMANTIC]
        
        for tier in tiers:
            # Check for item
            success = await self.update_importance(item_id, 0.0, tier=tier)
            if success:
                # We reuse update_importance to find the item, but we need to set status
                # Since update_importance doesn't allow setting arbitrary fields, we need
                # to do it manually here.
                
                # Re-fetch to update status
                item = None
                if tier == MemoryTier.WORKING:
                    item = await self.working_memory.get_by_id(item_id)
                elif tier == MemoryTier.EPISODIC:
                    item = await self.episodic_memory.get_by_id(item_id, update_access=False)
                else:
                    item = await self.semantic_memory.get_by_id(item_id, update_access=False)
                
                if item:
                    item.status = MemoryStatus.NEGATED
                    item.modified_at = datetime.now(timezone.utc)
                    
                    if tier == MemoryTier.WORKING:
                        await self.working_memory.store(item)
                    elif tier == MemoryTier.EPISODIC:
                        await self.episodic_memory.update(item)
                    else:
                        await self.semantic_memory.update(item)
                        
                    logger.info("Negated memory item: id=%s", item_id)
                    
                    # Emit memory.negated event
                    if self.event_system:
                        await self.event_system.emit(
                            "memory.negated",
                            source="MemorySystem",
                            status=EventStatus.COMPLETED,
                            memory_id=item_id,
                            tier=tier.value
                        )
                    return True
        
        return False

    async def supersede_memory(
        self, 
        old_item_id: str, 
        new_content: str,
        new_importance: float | None = None
    ) -> MemoryItem | None:
        """
        Supersede an old memory with a new one.

        Marks the old memory as SUPERSEDED and links it to the new one.

        Args:
            old_item_id: ID of the memory to supersede
            new_content: Content of the new memory
            new_importance: Optional importance for new item (defaults to old item's)

        Returns:
            The new MemoryItem if successful, None if old item not found
        """
        if not self._initialized:
            raise ValueError("MemorySystem not initialized. Call initialize() first.")

        # Find old item
        old_item = None
        old_tier = None
        
        tiers = [MemoryTier.WORKING, MemoryTier.EPISODIC, MemoryTier.SEMANTIC]
        for tier in tiers:
            if tier == MemoryTier.WORKING:
                old_item = await self.working_memory.get_by_id(old_item_id)
            elif tier == MemoryTier.EPISODIC:
                old_item = await self.episodic_memory.get_by_id(old_item_id, update_access=False)
            else:
                old_item = await self.semantic_memory.get_by_id(old_item_id, update_access=False)
            
            if old_item:
                old_tier = tier
                break
        
        if not old_item:
            logger.warning("Old item not found for supersede: id=%s", old_item_id)
            return None

        # Create new item
        # Use old item's context but update timestamps
        new_context = old_item.context
        importance = new_importance if new_importance is not None else old_item.importance
        
        new_item = await self.store(
            content=new_content,
            context=new_context,
            importance=importance,
            summary=None, # Auto-generate
            metadata=old_item.metadata.copy()
        )
        
        # Update old item status
        old_item.status = MemoryStatus.SUPERSEDED
        old_item.superseded_by = new_item.id
        old_item.modified_at = datetime.now(timezone.utc)
        
        if old_tier == MemoryTier.WORKING:
            await self.working_memory.store(old_item)
        elif old_tier == MemoryTier.EPISODIC:
            await self.episodic_memory.update(old_item)
        else:
            await self.semantic_memory.update(old_item)
            
        logger.info(
            "Superseded memory: old_id=%s, new_id=%s",
            old_item_id,
            new_item.id
        )
        
        return new_item

    async def consolidate(
        self,
        context: MemoryContext | None = None,
    ) -> ConsolidationResult:
        """
        Trigger memory consolidation.

        Promotes memories between tiers based on importance and frequency.
        If context is provided, consolidates only that context. Otherwise,
        consolidates all active contexts.

        Args:
            context: Optional context to consolidate (all contexts if None)

        Returns:
            ConsolidationResult with statistics

        Raises:
            ValueError: If system not initialized
        """
        if not self._initialized:
            raise ValueError("MemorySystem not initialized. Call initialize() first.")

        if context:
            # Consolidate single context
            result = await self.consolidation_engine.consolidate(context)
            logger.info(
                "Consolidated context %s: promoted=%d, concepts=%d",
                context.context_key,
                result.items_promoted,
                result.concepts_extracted,
            )
            
            # Emit memory.consolidated event
            if self.event_system:
                await self.event_system.emit(
                    "memory.consolidated",
                    source="MemorySystem",
                    status=EventStatus.COMPLETED,
                    agent_id=context.agent_id,
                    session_id=context.session_id,
                    context_key=context.context_key,
                    items_promoted=result.items_promoted,
                    items_demoted=result.items_demoted,
                    concepts_extracted=result.concepts_extracted,
                    relationships_created=result.relationships_created,
                    duration_ms=result.duration_ms
                )
            
            return result
        else:
            # Consolidate all active contexts
            active_contexts = self.context_manager.get_active_contexts()

            if not active_contexts:
                logger.debug("No active contexts to consolidate")
                # Return empty result
                return ConsolidationResult(
                    items_promoted=0,
                    items_demoted=0,
                    concepts_extracted=0,
                    relationships_created=0,
                    duration_ms=0.0,
                    context=MemoryContext(
                        agent_id="system",
                        session_id="none",
                        conversation_id="none",
                    ),
                )

            # Consolidate each context and aggregate results
            total_promoted = 0
            total_demoted = 0
            total_concepts = 0
            total_relationships = 0
            total_duration = 0.0

            for ctx in active_contexts:
                try:
                    result = await self.consolidation_engine.consolidate(ctx)
                    total_promoted += result.items_promoted
                    total_demoted += result.items_demoted
                    total_concepts += result.concepts_extracted
                    total_relationships += result.relationships_created
                    total_duration += result.duration_ms
                except Exception:
                    logger.exception(
                        "Error consolidating context %s",
                        ctx.context_key,
                    )

            logger.info(
                "Consolidated %d contexts: promoted=%d, concepts=%d",
                len(active_contexts),
                total_promoted,
                total_concepts,
            )

            # Emit memory.consolidated event for batch consolidation
            if self.event_system:
                await self.event_system.emit(
                    "memory.consolidated",
                    source="MemorySystem",
                    status=EventStatus.COMPLETED,
                    agent_id="system",
                    session_id="all",
                    contexts_count=len(active_contexts),
                    items_promoted=total_promoted,
                    items_demoted=total_demoted,
                    concepts_extracted=total_concepts,
                    relationships_created=total_relationships,
                    duration_ms=total_duration
                )

            # Return aggregated result
            return ConsolidationResult(
                items_promoted=total_promoted,
                items_demoted=total_demoted,
                concepts_extracted=total_concepts,
                relationships_created=total_relationships,
                duration_ms=total_duration,
                context=MemoryContext(
                    agent_id="system",
                    session_id="all",
                    conversation_id="all",
                ),
            )

    async def update_from_feedback(
        self,
        feedback: str,
        context: MemoryContext,
        importance: float = 0.7,
        feedback_type: str = "user_feedback",
    ) -> MemoryItem:
        """
        Update memory system based on user feedback.

        Stores feedback as an episodic memory and updates agent profile
        to learn from the feedback.

        Args:
            feedback: Feedback content
            context: Memory context
            importance: Importance score for the feedback (default: 0.7)
            feedback_type: Type of feedback (default: "user_feedback")

        Returns:
            MemoryItem created for the feedback

        Raises:
            ValueError: If system not initialized
        """
        if not self._initialized:
            raise ValueError("MemorySystem not initialized. Call initialize() first.")

        # Store feedback as episodic memory
        feedback_item = await self.store(
            content=feedback,
            context=context,
            importance=importance,
            event_type=feedback_type,
            metadata={
                "feedback_type": feedback_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        # Update agent profile based on feedback
        profile = self.context_manager.get_agent_profile(context.agent_id)

        # Simple learning: track feedback patterns
        if "query_patterns" not in profile.metadata:
            profile.metadata["query_patterns"] = {}

        feedback_pattern = feedback_type
        profile.metadata["query_patterns"][feedback_pattern] = (
            profile.metadata["query_patterns"].get(feedback_pattern, 0) + 1
        )

        self.context_manager.update_agent_profile(context.agent_id, profile)

        logger.info(
            "Stored feedback and updated profile: agent=%s, type=%s, importance=%.3f",
            context.agent_id,
            feedback_type,
            importance,
        )

        return feedback_item

    async def get_stats(
        self,
        context: MemoryContext | None = None,
    ) -> dict[str, Any]:
        """
        Get memory system statistics.

        Returns statistics about memory usage, retrieval performance,
        and consolidation metrics.

        Args:
            context: Optional context to filter stats (all if None)

        Returns:
            Dictionary with system statistics
        """
        stats = {
            "initialized": self._initialized,
            "working_memory": self.working_memory.get_stats(),
            "episodic_memory": await self.episodic_memory.get_stats(),
            "semantic_memory": await self.semantic_memory.get_stats(),
            "consolidation": self.consolidation_engine.get_consolidation_stats(),
            "retrieval": self.retrieval_engine.get_retrieval_stats(),
            "context_manager": self.context_manager.get_context_stats(),
        }

        if context:
            # Add context-specific stats
            stats["context"] = {
                "agent_id": context.agent_id,
                "session_id": context.session_id,
                "conversation_id": context.conversation_id,
                "context_key": context.context_key,
            }

        return stats

    def create_agent_context(
        self,
        agent_id: str,
        session_id: str,
        conversation_id: str,
        task_id: str | None = None,
        project_id: str | None = None,
        priority: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryContext:
        """
        Convenience method to create a memory context.

        Args:
            agent_id: Agent identifier
            session_id: Session identifier
            conversation_id: Conversation identifier
            task_id: Optional task identifier
            project_id: Optional project identifier
            priority: Priority level (0.0-1.0)
            metadata: Optional metadata dictionary

        Returns:
            New MemoryContext instance
        """
        return self.context_manager.create_context(
            agent_id=agent_id,
            session_id=session_id,
            conversation_id=conversation_id,
            task_id=task_id,
            project_id=project_id,
            priority=priority,
            metadata=metadata,
        )

    async def load_conversation(
        self,
        context: MemoryContext,
        limit: int = 20,
    ) -> list[MemoryItem]:
        """
        Load recent conversation events into working memory.

        Retrieves recent episodic memories for the conversation and
        loads them into working memory for quick access.

        Args:
            context: Memory context with conversation_id
            limit: Maximum number of events to load (default: 20)

        Returns:
            List of MemoryItem objects loaded into working memory

        Raises:
            ValueError: If system not initialized
        """
        if not self._initialized:
            raise ValueError("MemorySystem not initialized. Call initialize() first.")

        # Get all episodic items for this conversation
        all_items = await self.episodic_memory.get_all_items(context)

        # Filter by conversation_id
        conversation_items = [
            item
            for item in all_items
            if item.context.conversation_id == context.conversation_id
        ]

        # Sort by timestamp (most recent first)
        conversation_items.sort(key=lambda x: x.created_at, reverse=True)

        # Limit results
        items_to_load = conversation_items[:limit]

        # Load into working memory
        for item in items_to_load:
            # Update tier to working
            item.tier = MemoryTier.WORKING
            await self.working_memory.store(item)

        logger.info(
            "Loaded %d conversation events into working memory: conversation=%s",
            len(items_to_load),
            context.conversation_id,
        )

        return items_to_load

    async def clear_agent_memory(
        self,
        agent_id: str,
        tier: MemoryTier | None = None,
    ) -> dict[str, int]:
        """
        Clear all memory data for an agent.

        Removes all memories associated with the agent from the specified
        tier (or all tiers if None).

        Args:
            agent_id: Agent identifier
            tier: Optional tier to clear (all tiers if None)

        Returns:
            Dictionary with counts of items removed per tier

        Raises:
            ValueError: If system not initialized
        """
        if not self._initialized:
            raise ValueError("MemorySystem not initialized. Call initialize() first.")

        counts = {
            "working": 0,
            "episodic": 0,
            "semantic": 0,
        }

        # Determine tiers to clear
        tiers_to_clear = [tier] if tier else [
            MemoryTier.WORKING,
            MemoryTier.EPISODIC,
            MemoryTier.SEMANTIC,
        ]

        # Create a context for filtering
        filter_context = MemoryContext(
            agent_id=agent_id,
            session_id="all",
            conversation_id="all",
        )

        for clear_tier in tiers_to_clear:
            if clear_tier == MemoryTier.WORKING:
                # Get all items for this agent
                items = await self.working_memory.get_all_items(filter_context)
                for item in items:
                    await self.working_memory.delete(item.id)
                counts["working"] = len(items)

            elif clear_tier == MemoryTier.EPISODIC:
                # Get all items for this agent
                items = await self.episodic_memory.get_all_items(filter_context)
                for item in items:
                    await self.episodic_memory.delete(item.id)
                counts["episodic"] = len(items)

            else:  # SEMANTIC
                # Get all items for this agent
                items = await self.semantic_memory.get_all_items(filter_context)
                for item in items:
                    await self.semantic_memory.delete(item.id)
                counts["semantic"] = len(items)

        total_cleared = sum(counts.values())
        logger.info(
            "Cleared agent memory: agent=%s, total=%d, working=%d, episodic=%d, semantic=%d",
            agent_id,
            total_cleared,
            counts["working"],
            counts["episodic"],
            counts["semantic"],
        )

        return counts
