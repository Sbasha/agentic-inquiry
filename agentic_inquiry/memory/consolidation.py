"""
ConsolidationEngine for memory tier promotion.

Handles promotion of memories between tiers based on importance, frequency,
and pattern recognition. Supports both automatic and manual consolidation triggers.
"""

import logging
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from agentic_inquiry.embeddings.service import EmbeddingService
from agentic_inquiry.memory.layers.episodic import EpisodicMemory
from agentic_inquiry.memory.layers.semantic import SemanticMemory
from agentic_inquiry.memory.layers.working import WorkingMemory
from agentic_inquiry.memory.models import (
    ConsolidationResult,
    MemoryContext,
    MemoryItem,
    MemoryTier,
)

logger = logging.getLogger(__name__)


class ConsolidationEngine:
    """
    Engine for consolidating memories between tiers.

    Promotes memories from working to episodic, and episodic to semantic
    based on importance scores, access frequency, and pattern recognition.
    """

    def __init__(
        self,
        working_memory: WorkingMemory,
        episodic_memory: EpisodicMemory,
        semantic_memory: SemanticMemory,
        embedding_service: EmbeddingService,
        episodic_threshold: float = 0.8,
        semantic_threshold: float = 0.9,
    ) -> None:
        """
        Initialize ConsolidationEngine.

        Args:
            working_memory: WorkingMemory layer instance
            episodic_memory: EpisodicMemory layer instance
            semantic_memory: SemanticMemory layer instance
            embedding_service: EmbeddingService for re-embedding if needed
            episodic_threshold: Importance threshold for working → episodic (default: 0.8)
            semantic_threshold: Importance threshold for episodic → semantic (default: 0.9)
        """
        self.working_memory = working_memory
        self.episodic_memory = episodic_memory
        self.semantic_memory = semantic_memory
        self.embedding_service = embedding_service
        self.episodic_threshold = episodic_threshold
        self.semantic_threshold = semantic_threshold

        # Track consolidation statistics
        self._total_promotions = 0
        self._total_demotions = 0
        self._total_concepts_extracted = 0

        logger.info(
            "ConsolidationEngine initialized: episodic_threshold=%.2f, semantic_threshold=%.2f",
            episodic_threshold,
            semantic_threshold,
        )

    def should_consolidate(self, context: MemoryContext) -> bool:
        """
        Check if consolidation is needed for a context.

        Consolidation is needed if there are items in working memory
        that meet the importance threshold for promotion.

        Args:
            context: Memory context to check

        Returns:
            True if consolidation should be performed
        """
        # Get all items from working memory for this context
        items = []
        for item in self.working_memory._storage.values():
            if (
                item.context.agent_id == context.agent_id
                and item.context.session_id == context.session_id
            ):
                items.append(item)

        # Check if any items meet the threshold
        promotable_items = [
            item for item in items if item.importance >= self.episodic_threshold
        ]

        should_consolidate = bool(promotable_items)
        logger.debug(
            "Consolidation check: agent=%s, session=%s, items=%d, promotable=%d, should_consolidate=%s",
            context.agent_id,
            context.session_id,
            len(items),
            len(promotable_items),
            should_consolidate,
        )

        return should_consolidate

    def get_consolidation_stats(self) -> dict[str, Any]:
        """
        Get consolidation statistics.

        Returns:
            Dictionary with total promotions, demotions, and concepts extracted
        """
        return {
            "total_promotions": self._total_promotions,
            "total_demotions": self._total_demotions,
            "total_concepts_extracted": self._total_concepts_extracted,
        }

    async def promote_to_episodic(
        self, items: list[MemoryItem], re_embed: bool = True
    ) -> int:
        """
        Promote memory items from working to episodic memory.

        Items are filtered by importance threshold and stored in episodic memory.
        Re-embeds items with MEDIUM density to match episodic memory requirements.

        Args:
            items: List of MemoryItem objects to consider for promotion
            re_embed: Whether to re-embed items with MEDIUM density (default: True)
                     Should be True when promoting from working memory to avoid
                     dimension mismatches (LOW 128 dims -> MEDIUM 384 dims)

        Returns:
            Number of items promoted
        """
        promoted_count = 0

        for item in items:
            # Check importance threshold
            if item.importance < self.episodic_threshold:
                logger.debug(
                    "Skipping promotion to episodic: id=%s, importance=%.3f < threshold=%.3f",
                    item.id,
                    item.importance,
                    self.episodic_threshold,
                )
                continue

            # Re-embed if requested and embedding service is available
            if re_embed and self.embedding_service is not None:
                try:
                    # Generate embeddings for episodic memory
                    content_embedding = await self.embedding_service.embed_async(
                        item.content
                    )
                    summary_embedding = await self.embedding_service.embed_async(
                        item.summary
                    )

                    # Update embeddings
                    item.embedding = content_embedding
                    item.summary_embedding = summary_embedding

                    logger.debug(
                        "Re-embedded item for episodic: id=%s, content_dims=%d, summary_dims=%d",
                        item.id,
                        len(content_embedding),
                        len(summary_embedding),
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to re-embed item %s: %s. Using existing embeddings.",
                        item.id,
                        str(e),
                    )

            # Update tier
            item.tier = MemoryTier.EPISODIC
            item.modified_at = datetime.now(timezone.utc)

            # Store in episodic memory
            try:
                await self.episodic_memory.store(item)
                promoted_count += 1
                self._total_promotions += 1

                logger.debug(
                    "Promoted item to episodic: id=%s, importance=%.3f, agent=%s",
                    item.id,
                    item.importance,
                    item.context.agent_id,
                )
            except Exception as e:
                logger.error(
                    "Failed to promote item %s to episodic: %s",
                    item.id,
                    str(e),
                )

        logger.info(
            "Promoted %d items from working to episodic memory",
            promoted_count,
        )

        return promoted_count

    async def extract_concepts(self, items: list[MemoryItem]) -> list[MemoryItem]:
        """
        Extract concepts and patterns from episodic memories.

        Analyzes episodic items to identify recurring patterns, frequent terms,
        and relationships that should be promoted to semantic memory as facts.

        Args:
            items: List of episodic MemoryItem objects to analyze

        Returns:
            List of new MemoryItem objects representing extracted concepts
        """
        concepts: list[MemoryItem] = []

        if not items:
            return concepts

        # Analyze content for recurring patterns
        # Simple approach: find frequently occurring terms in content
        all_words: list[str] = []
        for item in items:
            # Simple tokenization (split on whitespace and punctuation)
            words = item.content.lower().split()
            # Filter out very short words
            words = [w.strip(".,!?;:()[]{}\"'-") for w in words if len(w) > 3]
            all_words.extend(words)

        # Count word frequencies
        word_counts = Counter(all_words)

        # Extract top concepts (words appearing more than once)
        frequent_terms = [
            word for word, count in word_counts.most_common(20) if count > 1
        ]

        if not frequent_terms:
            logger.debug("No frequent terms found in episodic items")
            return concepts

        # Create semantic facts for frequent concepts
        # Use the first item's context as a template
        template_context = items[0].context

        for term in frequent_terms[:10]:  # Limit to top 10 concepts
            # Find items containing this term
            related_items = [item for item in items if term in item.content.lower()]

            # Calculate average importance
            avg_importance = sum(item.importance for item in related_items) / len(
                related_items
            )

            # Create a semantic fact
            concept_content = f"Concept: {term} (mentioned {len(related_items)} times)"
            concept_summary = f"Recurring concept: {term}"

            # Generate embeddings if service is available
            embedding = None
            summary_embedding = None
            if self.embedding_service is not None:
                try:
                    embedding = await self.embedding_service.embed_async(
                        concept_content
                    )
                    summary_embedding = await self.embedding_service.embed_async(
                        concept_summary
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to embed concept '%s': %s",
                        term,
                        str(e),
                    )

            # Create MemoryItem for the concept
            concept_item = MemoryItem(
                id=f"concept_{term}_{int(time.time() * 1000)}",
                content=concept_content,
                summary=concept_summary,
                context=MemoryContext(
                    agent_id=template_context.agent_id,
                    session_id="consolidated",
                    conversation_id=template_context.conversation_id,
                    task_id=template_context.task_id,
                    project_id=template_context.project_id,
                ),
                importance=min(avg_importance * 1.1, 1.0),  # Boost importance slightly
                tier=MemoryTier.SEMANTIC,
                creator_agent_id=template_context.agent_id,
                modifier_agent_id=template_context.agent_id,
                content_source="consolidation_engine",
                embedding=embedding,
                summary_embedding=summary_embedding,
                subject=term,
                relationship="is_concept",
                object="knowledge",
                confidence=min(len(related_items) / len(items), 1.0),
                metadata={
                    "extraction_method": "frequency_analysis",
                    "occurrence_count": len(related_items),
                    "source_items": [item.id for item in related_items[:5]],
                },
            )

            concepts.append(concept_item)
            self._total_concepts_extracted += 1

        logger.info(
            "Extracted %d concepts from %d episodic items",
            len(concepts),
            len(items),
        )

        return concepts

    async def promote_to_semantic(
        self, items: list[MemoryItem], extract_patterns: bool = True
    ) -> int:
        """
        Promote memory items from episodic to semantic memory.

        Items are filtered by importance and frequency thresholds. Optionally
        extracts concepts and patterns from the items before promotion.

        Args:
            items: List of episodic MemoryItem objects to consider for promotion
            extract_patterns: Whether to extract concepts from patterns (default: True)

        Returns:
            Number of items promoted (including extracted concepts)
        """
        promoted_count = 0

        # Filter items by importance threshold
        high_importance_items = [
            item for item in items if item.importance >= self.semantic_threshold
        ]

        # Filter by access frequency (items accessed more than once)
        frequently_accessed_items = [item for item in items if item.access_count > 1]

        # Combine both criteria (union) - use dict to deduplicate by ID
        items_by_id = {item.id: item for item in high_importance_items}
        for item in frequently_accessed_items:
            items_by_id[item.id] = item
        items_to_promote = list(items_by_id.values())

        logger.debug(
            "Promoting to semantic: high_importance=%d, frequently_accessed=%d, total=%d",
            len(high_importance_items),
            len(frequently_accessed_items),
            len(items_to_promote),
        )

        # Promote individual items
        for item in items_to_promote:
            # Re-embed if needed
            if self.embedding_service is not None:
                try:
                    # Generate embeddings for semantic memory
                    content_embedding = await self.embedding_service.embed_async(
                        item.content
                    )
                    summary_embedding = await self.embedding_service.embed_async(
                        item.summary
                    )

                    # Update embeddings
                    item.embedding = content_embedding
                    item.summary_embedding = summary_embedding

                    logger.debug(
                        "Re-embedded item for semantic: id=%s, content_dims=%d, summary_dims=%d",
                        item.id,
                        len(content_embedding),
                        len(summary_embedding),
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to re-embed item %s: %s. Using existing embeddings.",
                        item.id,
                        str(e),
                    )

            # Update tier and add confidence score
            item.tier = MemoryTier.SEMANTIC
            item.modified_at = datetime.now(timezone.utc)

            # Set confidence based on access count and importance
            item.confidence = min(
                (item.importance * 0.7) + (min(item.access_count / 10.0, 1.0) * 0.3),
                1.0,
            )

            # Store in semantic memory
            try:
                await self.semantic_memory.store(item)
                promoted_count += 1
                self._total_promotions += 1

                logger.debug(
                    "Promoted item to semantic: id=%s, importance=%.3f, confidence=%.3f, agent=%s",
                    item.id,
                    item.importance,
                    item.confidence,
                    item.context.agent_id,
                )
            except Exception as e:
                logger.error(
                    "Failed to promote item %s to semantic: %s",
                    item.id,
                    str(e),
                )

        # Extract concepts if requested
        if extract_patterns and items:
            concepts = await self.extract_concepts(items)

            # Store extracted concepts
            for concept in concepts:
                try:
                    await self.semantic_memory.store(concept)
                    promoted_count += 1

                    logger.debug(
                        "Stored extracted concept: id=%s, subject=%s, confidence=%.3f",
                        concept.id,
                        concept.subject,
                        concept.confidence,
                    )
                except Exception as e:
                    logger.error(
                        "Failed to store concept %s: %s",
                        concept.id,
                        str(e),
                    )

        logger.info(
            "Promoted %d items from episodic to semantic memory",
            promoted_count,
        )

        return promoted_count

    async def consolidate(self, context: MemoryContext) -> ConsolidationResult:
        """
        Perform full consolidation for a memory context.

        Coordinates promotion from working to episodic, and episodic to semantic.
        Tracks timing and metrics for the consolidation operation.

        Args:
            context: Memory context to consolidate

        Returns:
            ConsolidationResult with statistics about the consolidation
        """
        start_time = time.time()

        items_promoted = 0
        items_demoted = 0
        concepts_extracted = 0
        relationships_created = 0

        logger.info(
            "Starting consolidation: agent=%s, session=%s, conversation=%s",
            context.agent_id,
            context.session_id,
            context.conversation_id,
        )

        try:
            # Step 1: Promote from working to episodic
            working_items = await self.working_memory.get_all_items(context)

            if working_items:
                logger.debug(
                    "Consolidating working memory: %d items",
                    len(working_items),
                )

                promoted_to_episodic = await self.promote_to_episodic(
                    working_items, re_embed=True
                )
                items_promoted += promoted_to_episodic

                # Clear promoted items from working memory
                for item in working_items:
                    if item.importance >= self.episodic_threshold:
                        await self.working_memory.delete(item.id)
                        logger.debug(
                            "Removed promoted item from working memory: id=%s",
                            item.id,
                        )

            # Step 2: Promote from episodic to semantic
            episodic_items = await self.episodic_memory.get_all_items(context)

            if episodic_items:
                logger.debug(
                    "Consolidating episodic memory: %d items",
                    len(episodic_items),
                )

                # Track concepts before promotion
                concepts_before = self._total_concepts_extracted

                promoted_to_semantic = await self.promote_to_semantic(
                    episodic_items, extract_patterns=True
                )
                items_promoted += promoted_to_semantic

                # Calculate concepts extracted in this consolidation
                concepts_extracted = self._total_concepts_extracted - concepts_before

                # Note: We don't delete from episodic memory after promotion
                # to maintain the event history. Capacity management will
                # handle cleanup if needed.

        except Exception as e:
            logger.error(
                "Error during consolidation for agent=%s, session=%s: %s",
                context.agent_id,
                context.session_id,
                str(e),
                exc_info=True,
            )
            # Continue and return partial results

        # Calculate duration
        duration_ms = (time.time() - start_time) * 1000

        result = ConsolidationResult(
            items_promoted=items_promoted,
            items_demoted=items_demoted,
            concepts_extracted=concepts_extracted,
            relationships_created=relationships_created,
            duration_ms=duration_ms,
            context=context,
        )

        logger.info(
            "Consolidation complete: agent=%s, session=%s, promoted=%d, concepts=%d, duration=%.2fms",
            context.agent_id,
            context.session_id,
            items_promoted,
            concepts_extracted,
            duration_ms,
        )

        return result
