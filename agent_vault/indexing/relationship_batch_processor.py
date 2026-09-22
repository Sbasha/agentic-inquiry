"""Batch processing for relationship operations.

This module provides RelationshipBatchProcessor, which handles concurrent
batch processing, committing, and progress tracking for relationship flush operations.

Design reference: DES-S3-002 in .sessions/deep-architecture-review/009-design.md
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, Generator, List, Optional, Tuple

if TYPE_CHECKING:
    from agent_vault.models import GraphRelationship
    from agent_vault.parsers.models import ParserRelationship

logger = logging.getLogger(__name__)


class RelationshipBatchProcessor:
    """Handles batch processing of relationship operations.

    This class encapsulates the batch processing infrastructure for
    relationship flush operations, including:
    - Chunking relationships into batches
    - Concurrent batch processing with semaphore control
    - Database commits with error isolation
    - Progress logging and statistics tracking
    - Adaptive batch sizing based on memory pressure

    Parameters
    ----------
    db_manager:
        Storage interface with add_graph_relationships() method.
        Accepts StorageFacade, LanceDBAdapter, LanceDBManager, or any compatible
        duck-typed object.
    pending_relationship_getter:
        Callable that returns count of pending relationships.
    pending_external_getter:
        Callable that returns count of pending external entities.

    Example:
        >>> processor = RelationshipBatchProcessor(
        ...     db_manager=db_manager,
        ...     pending_relationship_getter=lambda: queue_manager.pending_count,
        ...     pending_external_getter=lambda: entity_manager.pending_count,
        ... )
        >>> results = await processor.process_batch(batch, resolver_func, ...)
    """

    def __init__(
        self,
        db_manager: Any,  # StorageFacade or any object with add_graph_relationships()
        pending_relationship_getter: Callable[[], int],
        pending_external_getter: Callable[[], int],
    ):
        self._db_manager = db_manager
        self._get_pending_relationships = pending_relationship_getter
        self._get_pending_externals = pending_external_getter

    def chunk_relationships(
        self,
        relationships: List[Tuple["ParserRelationship", str]],
        batch_size: int,
    ) -> Generator[List[Tuple["ParserRelationship", str]], None, None]:
        """Split relationships into batches for processing.

        Args:
            relationships: List of (relationship, source_file_path) tuples
            batch_size: Maximum size of each batch

        Yields:
            Batches of relationships
        """
        for i in range(0, len(relationships), batch_size):
            yield relationships[i : i + batch_size]

    def initialize_stats(
        self,
        batch_size: int,
        total_relationships: int,
    ) -> Dict[str, Any]:
        """Initialize statistics tracking for batched flush.

        Args:
            batch_size: Size of each batch
            total_relationships: Total number of relationships to process

        Returns:
            Initialized statistics dictionary with both new and backward-compatible keys
        """
        return {
            # New batched flush stats
            "total_relationships": total_relationships,
            "relationships_created": 0,
            "relationships_failed": 0,
            "batch_count": 0,
            "batch_size": batch_size,
            "total_time_seconds": 0.0,
            "average_batch_time": 0.0,
            "cache_hit_rate": 0.0,
            "batch_times": [],
            "committed_count": 0,
            "commit_failures": 0,
            "by_strategy": {
                "import_path": 0,
                "exact_match": 0,
                "module_path": 0,
                "proximity": 0,
                "database": 0,
                "external_entity": 0,
                "document_structural": 0,
                "no_resolution": 0,
            },
            "cross_file_resolutions": 0,
            "same_file_resolutions": 0,
            "external_entity_resolutions": 0,
            "low_confidence_count": 0,
            "medium_confidence_count": 0,
            "high_confidence_count": 0,
            "operation_tracker": None,
            # Confidence tracking
            "confidence_scores": [],  # List to track individual confidence scores
            "first_pass_resolved": 0,  # Count of first pass resolutions
            # Backward-compatible keys (aliases for legacy API)
            "total": total_relationships,
            "resolved_cross_file": 0,
            "unresolved_external": 0,
            "same_file_fallback": 0,
            "confidence_levels": {"high": 0, "medium": 0, "low": 0},
            "ambiguous_resolutions": 0,
            "average_confidence": 0.0,
            "resolution_time_seconds": 0.0,
            "resolver_cache_statistics": {},
        }

    async def process_batch(
        self,
        batch: List[Tuple["ParserRelationship", str]],
        batch_number: int,
        resolver_func: Callable[
            [Tuple["ParserRelationship", str]], Any
        ],
        stats: Dict[str, Any],
        semaphore: asyncio.Semaphore,
    ) -> List["GraphRelationship"]:
        """Process a single batch of relationships concurrently.

        Uses asyncio.gather with return_exceptions=True for error isolation.

        Args:
            batch: List of (relationship, source_file_path) tuples
            batch_number: Sequential batch number for logging
            resolver_func: Async function to resolve a single relationship tuple
            stats: Shared statistics dict
            semaphore: Concurrency control semaphore

        Returns:
            List of successfully created GraphRelationship objects
        """
        from agent_vault.models import GraphRelationship

        async def process_single(
            rel_tuple: Tuple["ParserRelationship", str]
        ) -> Optional["GraphRelationship"]:
            relationship, source_file_path = rel_tuple
            async with semaphore:
                try:
                    result = await resolver_func(rel_tuple)
                    return result
                except Exception as e:
                    logger.error(
                        "Error processing relationship %s -> %s: %s",
                        relationship.source_name,
                        relationship.target_name,
                        e,
                        exc_info=True,
                    )
                    stats["relationships_failed"] += 1
                    return None

        # Process all relationships in batch concurrently
        results = await asyncio.gather(
            *[process_single(rel_tuple) for rel_tuple in batch],
            return_exceptions=True,
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
            batch_number,
            len(batch),
            len(created_relationships),
        )

        return created_relationships

    async def commit_batch(
        self,
        relationships: List["GraphRelationship"],
        batch_number: int,
        stats: Dict[str, Any],
        event_system: Optional[Any] = None,
    ) -> bool:
        """Commit a batch of relationships to the database.

        Implements error isolation for event emission only. A failed
        ``add_graph_relationships`` call is re-raised so the index cannot
        report success after a graph write failure.

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
            await self._db_manager.add_graph_relationships(relationships)
            stats["committed_count"] += len(relationships)
            logger.debug(
                "Committed batch %d (%d relationships, total committed: %d)",
                batch_number,
                len(relationships),
                stats["committed_count"],
            )

            # Emit batch_complete event
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
                batch_number,
                e,
                exc_info=True,
            )
            stats["commit_failures"] += 1
            stats["last_commit_error"] = str(e)
            raise

    def log_progress(
        self,
        processed: int,
        total: int,
        start_time: float,
        stats: Dict[str, Any],
    ) -> None:
        """Log progress during batched flush.

        Args:
            processed: Number of relationships processed so far
            total: Total relationships to process
            start_time: Operation start timestamp
            stats: Current statistics
        """
        elapsed = time.time() - start_time
        rate = processed / max(elapsed, 0.001)
        remaining = total - processed
        eta = remaining / rate if rate > 0 else 0
        percentage = (processed / total * 100) if total > 0 else 0

        logger.info(
            "Progress: %d/%d (%.1f%%) - Rate: %.1f/s - ETA: %.1fs - Committed: %d",
            processed,
            total,
            percentage,
            rate,
            eta,
            stats.get("committed_count", 0),
        )

    async def log_statistics(
        self,
        stats: Dict[str, Any],
        total_time: float,
        relationships_created: int,
    ) -> None:
        """Log final resolution statistics for batched flush.

        Args:
            stats: Accumulated statistics
            total_time: Total operation time in seconds
            relationships_created: Total relationships created
        """
        logger.info(
            "Batched flush completed: %d relationships in %.2fs (%.1f/s)",
            relationships_created,
            total_time,
            relationships_created / max(total_time, 0.001),
        )
        logger.info(
            "Batches: %d, Avg batch time: %.3fs, Committed: %d, Failures: %d",
            stats.get("batch_count", 0),
            stats.get("average_batch_time", 0),
            stats.get("committed_count", 0),
            stats.get("commit_failures", 0),
        )
        logger.info(
            "Cache hit rate: %.1f%%, Cross-file: %d, Same-file: %d",
            stats.get("cache_hit_rate", 0),
            stats.get("cross_file_resolutions", 0),
            stats.get("same_file_resolutions", 0),
        )

    def check_memory_pressure(
        self,
        auto_flush_threshold: int = 10000,
        external_entity_flush_threshold: int = 1000,
    ) -> Dict[str, Any]:
        """Check if memory thresholds are exceeded.

        Checks pending relationships and external entities against configured
        thresholds to determine if automatic flush or cleanup is needed.

        Args:
            auto_flush_threshold: Threshold for relationship flush
            external_entity_flush_threshold: Threshold for external entity flush

        Returns:
            Dictionary with pressure status:
            - needs_relationship_flush: bool
            - needs_external_entity_flush: bool
            - pending_relationships: int
            - pending_external_entities: int
            - relationship_threshold: int
            - external_entity_threshold: int
        """
        pending_rels = self._get_pending_relationships()
        pending_externals = self._get_pending_externals()

        needs_rel_flush = pending_rels >= auto_flush_threshold
        needs_ext_flush = pending_externals >= external_entity_flush_threshold

        if needs_rel_flush:
            logger.warning(
                "Memory pressure: %d pending relationships exceed threshold %d",
                pending_rels,
                auto_flush_threshold,
            )

        if needs_ext_flush:
            logger.warning(
                "Memory pressure: %d pending external entities exceed threshold %d",
                pending_externals,
                external_entity_flush_threshold,
            )

        return {
            "needs_relationship_flush": needs_rel_flush,
            "needs_external_entity_flush": needs_ext_flush,
            "pending_relationships": pending_rels,
            "pending_external_entities": pending_externals,
            "relationship_threshold": auto_flush_threshold,
            "external_entity_threshold": external_entity_flush_threshold,
        }

    def get_adaptive_batch_size(
        self,
        base_batch_size: int,
        auto_flush_threshold: int = 10000,
        external_entity_flush_threshold: int = 1000,
    ) -> int:
        """Calculate adaptive batch size based on memory pressure.

        When memory pressure is detected (pending items exceed 75% of threshold),
        reduce batch size to allow more frequent cleanup.

        Args:
            base_batch_size: The configured batch size
            auto_flush_threshold: Threshold for relationship flush
            external_entity_flush_threshold: Threshold for external entity flush

        Returns:
            Adapted batch size (may be reduced under memory pressure)
        """
        pressure = self.check_memory_pressure(
            auto_flush_threshold, external_entity_flush_threshold
        )

        # Calculate pressure ratio (0.0 to 1.0+)
        rel_ratio = pressure["pending_relationships"] / max(auto_flush_threshold, 1)
        ext_ratio = pressure["pending_external_entities"] / max(
            external_entity_flush_threshold, 1
        )

        max_ratio = max(rel_ratio, ext_ratio)

        # If under 75% of threshold, use full batch size
        if max_ratio < 0.75:
            return base_batch_size

        # Scale down batch size as pressure increases
        # At 75% pressure: use 75% of batch size
        # At 100% pressure: use 50% of batch size
        # Above 100%: use 25% of batch size
        if max_ratio >= 1.0:
            scale_factor = 0.25
            logger.warning(
                "High memory pressure (%.0f%%), reducing batch size to %.0f%%",
                max_ratio * 100,
                scale_factor * 100,
            )
        elif max_ratio >= 0.75:
            scale_factor = 1.0 - (max_ratio - 0.5)  # 0.75 -> 0.75, 1.0 -> 0.5
            logger.info(
                "Memory pressure at %.0f%%, reducing batch size to %.0f%%",
                max_ratio * 100,
                scale_factor * 100,
            )
        else:
            scale_factor = 1.0

        adapted_size = max(1, int(base_batch_size * scale_factor))
        return adapted_size
