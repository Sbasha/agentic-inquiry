"""
Retrieval engine for unified memory search across all tiers.

This module provides the RetrievalEngine class which implements multiple
search strategies and ranking algorithms for retrieving memories from
working, episodic, and semantic memory tiers.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING, Union, cast

import numpy as np


from agent_vault.memory.models import MemoryContext, MemoryStatus, MemoryTier, RetrievalResult
from agent_vault.utils.metacognition import detect_ambiguity, ClarificationBuilder

if TYPE_CHECKING:
    from agent_vault.config import Config
    from agent_vault.embeddings.service import EmbeddingService
    from agent_vault.memory.layers.episodic import EpisodicMemory
    from agent_vault.memory.layers.semantic import SemanticMemory
    from agent_vault.memory.layers.working import WorkingMemory

logger = logging.getLogger(__name__)


class RetrievalEngine:
    """
    Unified retrieval engine for searching across all memory tiers.

    Supports multiple search strategies:
    - relevance: Pure vector similarity
    - recency: Time-weighted scoring
    - importance: Importance-weighted scoring
    - adaptive: Combined scoring with configurable weights

    Attributes:
        working_memory: Working memory layer
        episodic_memory: Episodic memory layer
        semantic_memory: Semantic memory layer
        embedding_service: Service for generating query embeddings
        config: System configuration
    """

    def __init__(
        self,
        working_memory: "WorkingMemory",
        episodic_memory: "EpisodicMemory",
        semantic_memory: "SemanticMemory",
        embedding_service: "EmbeddingService",
        config: "Config",
    ) -> None:
        """
        Initialize the retrieval engine.

        Args:
            working_memory: Working memory layer
            episodic_memory: Episodic memory layer
            semantic_memory: Semantic memory layer
            embedding_service: Service for generating embeddings
            config: System configuration
        """
        self.working_memory = working_memory
        self.episodic_memory = episodic_memory
        self.semantic_memory = semantic_memory
        self.embedding_service = embedding_service
        self.config = config

        # Query cache with TTL - read from config
        self._cache: Dict[
            str, Tuple[Union[List[RetrievalResult], Dict[str, Any]], float]
        ] = {}
        self._cache_enabled = config.memory.retrieval.cache_enabled
        self._cache_ttl_seconds = config.memory.retrieval.cache_ttl_seconds
        self._cache_size = config.memory.retrieval.cache_size

        # Retrieval statistics
        self._stats: Dict[str, Any] = {
            "total_queries": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "queries_by_strategy": {
                "relevance": 0,
                "recency": 0,
                "importance": 0,
                "adaptive": 0,
            },
        }

        logger.info("RetrievalEngine initialized")

    async def _get_validated_embedding(self, query: str) -> np.ndarray:
        """Generate and validate query embedding.

        Args:
            query: Query string to embed

        Returns:
            Validated embedding vector

        Raises:
            ValueError: If embedding is empty or has wrong dimensions
        """
        embedding = await self.embedding_service.embed_async(query)
        
        expected_dims = self.config.embeddings.default_dimensions
        actual_dims = len(embedding) if embedding is not None else 0
        
        if actual_dims == 0:
            raise ValueError(
                f"Embedding service returned empty vector for query. "
                f"Expected {expected_dims} dimensions. "
                f"This may indicate the embedding model is not loaded."
            )
        
        if actual_dims != expected_dims:
            logger.warning(
                "Embedding dimension mismatch: expected %d, got %d. "
                "Proceeding with actual dimensions.",
                expected_dims,
                actual_dims,
            )
        
        return embedding

    def get_retrieval_stats(self) -> dict:
        """
        Get retrieval statistics.

        Returns:
            Dictionary containing retrieval metrics:
            - total_queries: Total number of queries processed
            - cache_hits: Number of cache hits
            - cache_misses: Number of cache misses
            - cache_hit_rate: Percentage of queries served from cache
            - cache_enabled: Whether caching is enabled
            - queries_by_strategy: Count of queries per strategy
        """
        total = self._stats["total_queries"]
        hits = self._stats["cache_hits"]

        return {
            "total_queries": total,
            "cache_hits": hits,
            "cache_misses": self._stats["cache_misses"],
            "cache_hit_rate": (hits / total * 100) if total > 0 else 0.0,
            "cache_enabled": self._cache_enabled,
            "queries_by_strategy": self._stats["queries_by_strategy"].copy(),
            "cache_size": len(self._cache),
        }

    def _get_cache_key(
        self, query: str, context: MemoryContext, strategy: str, limit: int, include_history: bool = False
    ) -> str:
        """
        Generate cache key for a query.

        Args:
            query: Query string
            context: Memory context
            strategy: Search strategy
            limit: Result limit
            include_history: Whether to include history

        Returns:
            Cache key string
        """
        return f"{context.agent_id}:{context.session_id}:{strategy}:{limit}:{include_history}:{query}"

    def _get_from_cache(
        self,
        key: str,
    ) -> Union[List[RetrievalResult], Dict[str, Any], None]:
        """
        Retrieve results from cache if valid.

        Args:
            key: Cache key

        Returns:
            Cached results or None if not found/expired
        """
        if not self.config.memory.retrieval.cache_enabled:
            return None

        if key not in self._cache:
            return None

        results, timestamp = self._cache[key]

        # Check expiration
        if time.time() - timestamp > self.config.memory.retrieval.cache_ttl_seconds:
            del self._cache[key]
            return None

        return results

    def _put_in_cache(
        self,
        key: str,
        results: Union[List[RetrievalResult], Dict[str, Any]],
    ) -> None:
        """Cache retrieval results."""
        if not self.config.memory.retrieval.cache_enabled:
            return

        self._cache[key] = (results, time.time())

        # Enforce cache size limit
        if len(self._cache) > self.config.memory.retrieval.cache_size:
            # Remove oldest entry (simple LRU approximation)
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]

    def _clear_cache(self) -> None:
        """Clear the query cache."""
        self._cache.clear()
        logger.debug("Query cache cleared")

    async def _search_relevance(
        self,
        query: str,
        context: MemoryContext,
        limit: int,
    ) -> list[RetrievalResult]:
        """
        Search using pure vector similarity.

        Args:
            query: Query string
            context: Memory context for filtering
            limit: Maximum number of results

        Returns:
            Results ranked by cosine similarity
        """
        # Generate and validate embedding for query
        query_embedding = await self._get_validated_embedding(query)
        working_embedding = episodic_embedding = semantic_embedding = query_embedding

        # Search all tiers in parallel
        # Pass query_text to episodic/semantic layers for server-side embedding
        working_results, episodic_results, semantic_results = await asyncio.gather(
            self.working_memory.retrieve(working_embedding, context, limit),
            self.episodic_memory.retrieve(episodic_embedding, context, limit, query_text=query),
            self.semantic_memory.retrieve(semantic_embedding, context, limit, query_text=query),
        )

        # Combine and sort by relevance score
        all_results = working_results + episodic_results + semantic_results
        all_results.sort(key=lambda r: r.relevance_score, reverse=True)

        return all_results[:limit]

    async def _search_recency(
        self,
        query: str,
        context: MemoryContext,
        limit: int,
    ) -> list[RetrievalResult]:
        """
        Search with time-weighted scoring.

        More recent memories get higher scores. Working memory items
        are considered most recent, followed by episodic, then semantic.

        Args:
            query: Query string
            context: Memory context for filtering
            limit: Maximum number of results

        Returns:
            Results ranked by recency-weighted relevance
        """
        # Generate and validate embedding for query
        query_embedding = await self._get_validated_embedding(query)
        working_embedding = episodic_embedding = semantic_embedding = query_embedding

        # Search all tiers in parallel
        working_results, episodic_results, semantic_results = await asyncio.gather(
            self.working_memory.retrieve(working_embedding, context, limit),
            self.episodic_memory.retrieve(episodic_embedding, context, limit, query_text=query),
            self.semantic_memory.retrieve(semantic_embedding, context, limit, query_text=query),
        )

        # Apply recency weighting
        now = datetime.now(timezone.utc)

        def calculate_recency_score(result: RetrievalResult) -> float:
            """Calculate recency-weighted score."""
            base_score = result.relevance_score

            # Tier-based recency boost
            if result.retrieval_tier == MemoryTier.WORKING:
                # Working memory is most recent
                tier_boost = 1.0
            elif result.retrieval_tier == MemoryTier.EPISODIC:
                # Episodic memory - calculate time decay
                age_seconds = (now - result.item.created_at).total_seconds()
                # Decay over 7 days (604800 seconds)
                decay = max(0.0, 1.0 - (age_seconds / 604800))
                tier_boost = 0.5 + (0.5 * decay)
            else:
                # Semantic memory is timeless
                tier_boost = 0.3

            return base_score * tier_boost

        # Combine and sort by recency-weighted score
        all_results = working_results + episodic_results + semantic_results
        all_results.sort(key=calculate_recency_score, reverse=True)

        return all_results[:limit]

    async def _search_importance(
        self,
        query: str,
        context: MemoryContext,
        limit: int,
    ) -> list[RetrievalResult]:
        """
        Search with importance-weighted scoring.

        Memories with higher importance scores are ranked higher.

        Args:
            query: Query string
            context: Memory context for filtering
            limit: Maximum number of results

        Returns:
            Results ranked by importance-weighted relevance
        """
        # Generate and validate embedding for query
        query_embedding = await self._get_validated_embedding(query)
        working_embedding = episodic_embedding = semantic_embedding = query_embedding

        # Search all tiers in parallel
        working_results, episodic_results, semantic_results = await asyncio.gather(
            self.working_memory.retrieve(working_embedding, context, limit),
            self.episodic_memory.retrieve(episodic_embedding, context, limit, query_text=query),
            self.semantic_memory.retrieve(semantic_embedding, context, limit, query_text=query),
        )

        # Apply importance weighting
        def calculate_importance_score(result: RetrievalResult) -> float:
            """Calculate importance-weighted score."""
            return result.relevance_score * result.item.importance

        # Combine and sort by importance-weighted score
        all_results = working_results + episodic_results + semantic_results
        all_results.sort(key=calculate_importance_score, reverse=True)

        return all_results[:limit]

    async def _search_adaptive(
        self,
        query: str,
        context: MemoryContext,
        limit: int,
        weights: dict[str, float] | None = None,
    ) -> list[RetrievalResult]:
        """
        Search with adaptive scoring using configurable weights.

        Combines relevance, recency, and importance with configurable weights.

        Args:
            query: Query string
            context: Memory context for filtering
            limit: Maximum number of results
            weights: Optional custom weights (relevance, recency, importance)

        Returns:
            Results ranked by adaptive score
        """
        # Use provided weights or defaults
        if weights is None:
            weights = {
                "relevance": 0.5,
                "recency": 0.3,
                "importance": 0.2,
            }

        # Validate weights sum to 1.0
        weight_sum = sum(weights.values())
        if not (0.99 <= weight_sum <= 1.01):  # Allow small floating point error
            logger.warning(
                "Adaptive search weights sum to %.2f, normalizing to 1.0",
                weight_sum,
            )
            # Normalize weights
            weights = {k: v / weight_sum for k, v in weights.items()}

        # Generate and validate embedding for query
        query_embedding = await self._get_validated_embedding(query)
        working_embedding = episodic_embedding = semantic_embedding = query_embedding

        # Search all tiers in parallel
        working_results, episodic_results, semantic_results = await asyncio.gather(
            self.working_memory.retrieve(working_embedding, context, limit),
            self.episodic_memory.retrieve(episodic_embedding, context, limit, query_text=query),
            self.semantic_memory.retrieve(semantic_embedding, context, limit, query_text=query),
        )

        # Calculate adaptive scores
        now = datetime.now(timezone.utc)

        def calculate_adaptive_score(result: RetrievalResult) -> float:
            """Calculate adaptive score with weighted components."""
            # Relevance component
            relevance = result.relevance_score

            # Recency component
            if result.retrieval_tier == MemoryTier.WORKING:
                recency = 1.0
            elif result.retrieval_tier == MemoryTier.EPISODIC:
                age_seconds = (now - result.item.created_at).total_seconds()
                decay = max(0.0, 1.0 - (age_seconds / 604800))  # 7 days
                recency = 0.5 + (0.5 * decay)
            else:
                recency = 0.3

            # Importance component
            importance = result.item.importance

            # Weighted combination
            score = (
                weights["relevance"] * relevance
                + weights["recency"] * recency
                + weights["importance"] * importance
            )

            return score

        # Combine and sort by adaptive score
        all_results = working_results + episodic_results + semantic_results
        all_results.sort(key=calculate_adaptive_score, reverse=True)

        return all_results[:limit]

    async def _search_with_keywords(
        self,
        query: str,
        context: MemoryContext,
        limit: int,
        keyword_weight: float = 0.3,
    ) -> list[RetrievalResult]:
        """
        Search with keyword matching boost.

        Combines semantic similarity with keyword matching to improve
        precision for distinguishing similar concepts.

        Args:
            query: Query string
            context: Memory context for filtering
            limit: Maximum number of results
            keyword_weight: Weight for keyword matching (default: 0.3)

        Returns:
            Results ranked by combined semantic + keyword score
        """
        from agent_vault.memory.keyword_extraction import (
            extract_keywords,
            calculate_keyword_match_score,
            boost_score_with_keywords,
        )

        # Extract keywords from query
        query_keywords = extract_keywords(query)

        # Generate and validate embedding for query
        query_embedding = await self._get_validated_embedding(query)
        working_embedding = episodic_embedding = semantic_embedding = query_embedding

        # Search all tiers in parallel
        working_results, episodic_results, semantic_results = await asyncio.gather(
            self.working_memory.retrieve(working_embedding, context, limit),
            self.episodic_memory.retrieve(episodic_embedding, context, limit, query_text=query),
            self.semantic_memory.retrieve(semantic_embedding, context, limit, query_text=query),
        )

        # Combine results
        all_results = working_results + episodic_results + semantic_results

        # Boost scores with keyword matching
        for result in all_results:
            # Extract keywords from content and summary
            content_keywords = extract_keywords(result.item.content)
            summary_keywords = extract_keywords(result.item.summary)
            combined_keywords = list(set(content_keywords + summary_keywords))

            # Calculate keyword match score
            keyword_score = calculate_keyword_match_score(
                query_keywords, combined_keywords
            )

            # Boost relevance score with keyword matching
            boosted_score = boost_score_with_keywords(
                result.relevance_score, keyword_score, keyword_weight
            )

            # Update relevance score
            result.relevance_score = boosted_score

        # Sort by boosted scores
        all_results.sort(key=lambda r: r.relevance_score, reverse=True)

        return all_results[:limit]

    def _calculate_metadata_match_score(
        self,
        query: str,
        item_metadata: dict[str, Any],
    ) -> float:
        """
        Calculate metadata match score for disambiguation.

        Checks if query terms match metadata fields like tags, categories,
        subject, or other metadata values.

        Args:
            query: Query string
            item_metadata: Metadata dictionary from MemoryItem

        Returns:
            Match score between 0.0 and 1.0
        """
        if not item_metadata:
            return 0.0

        query_lower = query.lower()
        matches = 0
        total_fields = 0

        # Check common metadata fields
        metadata_fields = ["tags", "categories", "subject", "type", "domain"]

        for field in metadata_fields:
            if field in item_metadata:
                total_fields += 1
                value = item_metadata[field]

                # Handle list values (e.g., tags)
                if isinstance(value, list):
                    for item in value:
                        if isinstance(item, str) and item.lower() in query_lower:
                            matches += 1
                            break
                # Handle string values
                elif isinstance(value, str) and value.lower() in query_lower:
                    matches += 1

        if total_fields == 0:
            return 0.0

        return matches / total_fields

    async def _search_with_metadata_boost(
        self,
        query: str,
        context: MemoryContext,
        limit: int,
        metadata_weight: float = 0.2,
    ) -> list[RetrievalResult]:
        """
        Search with metadata-based disambiguation.

        Boosts results that have metadata matching the query, improving
        precision when distinguishing similar concepts.

        Args:
            query: Query string
            context: Memory context for filtering
            limit: Maximum number of results
            metadata_weight: Weight for metadata matching (default: 0.2)

        Returns:
            Results ranked by combined semantic + metadata score
        """
        # Generate and validate embedding for query
        query_embedding = await self._get_validated_embedding(query)
        working_embedding = episodic_embedding = semantic_embedding = query_embedding

        # Search all tiers in parallel
        working_results, episodic_results, semantic_results = await asyncio.gather(
            self.working_memory.retrieve(working_embedding, context, limit),
            self.episodic_memory.retrieve(episodic_embedding, context, limit, query_text=query),
            self.semantic_memory.retrieve(semantic_embedding, context, limit, query_text=query),
        )

        # Combine results
        all_results = working_results + episodic_results + semantic_results

        # Boost scores with metadata matching
        for result in all_results:
            # Calculate metadata match score
            metadata_score = self._calculate_metadata_match_score(
                query, result.item.metadata
            )

            # Boost relevance score with metadata matching
            semantic_weight = 1.0 - metadata_weight
            boosted_score = (
                semantic_weight * result.relevance_score
                + metadata_weight * metadata_score
            )

            # Update relevance score
            result.relevance_score = boosted_score

        # Sort by boosted scores
        all_results.sort(key=lambda r: r.relevance_score, reverse=True)

        return all_results[:limit]

    async def _search_hybrid_precision(
        self,
        query: str,
        context: MemoryContext,
        limit: int,
        keyword_weight: float = 0.3,
        metadata_weight: float = 0.2,
    ) -> list[RetrievalResult]:
        """
        Search with hybrid scoring for maximum precision.

        Combines semantic similarity, keyword matching, and metadata matching
        to prioritize exact matches over related matches.

        Args:
            query: Query string
            context: Memory context for filtering
            limit: Maximum number of results
            keyword_weight: Weight for keyword matching (default: 0.3)
            metadata_weight: Weight for metadata matching (default: 0.2)

        Returns:
            Results ranked by combined semantic + keyword + metadata score
        """
        from agent_vault.memory.keyword_extraction import (
            extract_keywords,
            calculate_keyword_match_score,
        )

        # Extract keywords from query
        query_keywords = extract_keywords(query)

        # Generate and validate embedding for query
        query_embedding = await self._get_validated_embedding(query)
        working_embedding = episodic_embedding = semantic_embedding = query_embedding

        # Search all tiers in parallel
        working_results, episodic_results, semantic_results = await asyncio.gather(
            self.working_memory.retrieve(working_embedding, context, limit),
            self.episodic_memory.retrieve(episodic_embedding, context, limit, query_text=query),
            self.semantic_memory.retrieve(semantic_embedding, context, limit, query_text=query),
        )

        # Combine results
        all_results = working_results + episodic_results + semantic_results

        # Calculate weights
        semantic_weight = 1.0 - keyword_weight - metadata_weight

        # Boost scores with keyword and metadata matching
        for result in all_results:
            # Extract keywords from content and summary
            content_keywords = extract_keywords(result.item.content)
            summary_keywords = extract_keywords(result.item.summary)
            combined_keywords = list(set(content_keywords + summary_keywords))

            # Calculate keyword match score
            keyword_score = calculate_keyword_match_score(
                query_keywords, combined_keywords
            )

            # Calculate metadata match score
            metadata_score = self._calculate_metadata_match_score(
                query, result.item.metadata
            )

            # Check for exact match in subject field (semantic memory)
            exact_match_boost = 0.0
            if result.item.subject:
                query_lower = query.lower()
                subject_lower = result.item.subject.lower()
                if query_lower == subject_lower or query_lower in subject_lower:
                    exact_match_boost = 0.2  # Boost exact matches

            # Combine scores with weights
            combined_score = (
                semantic_weight * result.relevance_score
                + keyword_weight * keyword_score
                + metadata_weight * metadata_score
                + exact_match_boost
            )

            # Ensure score stays in [0, 1] range
            combined_score = min(1.0, combined_score)

            # Update relevance score
            result.relevance_score = combined_score

        # Sort by combined scores (exact matches will rank higher)
        all_results.sort(key=lambda r: r.relevance_score, reverse=True)

        return all_results[:limit]

    def _detect_ambiguity(
        self,
        results: list[RetrievalResult],
        threshold: float = 0.1,
    ) -> Dict[str, Any]:
        """
        Detect if query results are ambiguous using shared utility.
        """
        return detect_ambiguity(results, threshold=threshold)

    async def _search_with_ambiguity_detection(
        self,
        query: str,
        context: MemoryContext,
        limit: int,
        min_results_for_ambiguous: int = 3,
        max_results_for_ambiguous: int = 5,
    ) -> list[RetrievalResult] | Dict[str, Any]:
        """
        Search with automatic ambiguity detection.
        """
        # Request more results than needed to detect ambiguity
        extended_limit = max(limit, max_results_for_ambiguous * 2)
        results = await self._search_hybrid_precision(
            query, context, extended_limit
        )

        # Detect ambiguity using shared utility
        ambiguity_info = self._detect_ambiguity(results)

        if ambiguity_info["ambiguous"]:
            # Generate clarification question
            question = ClarificationBuilder.build_question(ambiguity_info, query)
            
            return {
                "results": results[:max_results_for_ambiguous],
                "ambiguity": ambiguity_info,
                "clarification_question": question
            }
        else:
            # Return requested limit for clear queries
            return results[:limit]

    def _determine_relationship_type(
        self,
        query: str,
        result: RetrievalResult,
        keyword_score: float,
        metadata_score: float,
    ) -> str:
        """
        Determine relationship type between query and result.

        Analyzes the match characteristics to classify the relationship.

        Args:
            query: Query string
            result: Retrieval result
            keyword_score: Keyword match score
            metadata_score: Metadata match score

        Returns:
            Relationship type string (exact_match, similar_to, related_to, etc.)
        """
        query_lower = query.lower()

        # Check for exact match in subject
        if result.item.subject:
            subject_lower = result.item.subject.lower()
            if query_lower == subject_lower:
                return "exact_match"
            elif query_lower in subject_lower or subject_lower in query_lower:
                return "partial_match"

        # Check for exact match in content
        content_lower = result.item.content.lower()
        if query_lower in content_lower:
            # High keyword score indicates strong keyword match
            if keyword_score > 0.7:
                return "keyword_match"
            else:
                return "contains_query"

        # High semantic similarity with low keyword match
        if result.relevance_score > 0.8 and keyword_score < 0.3:
            return "semantically_similar"

        # High keyword match with moderate semantic similarity
        if keyword_score > 0.5:
            return "keyword_related"

        # High metadata match
        if metadata_score > 0.5:
            return "metadata_related"

        # Default: related by semantic similarity
        return "related_to"

    async def _search_with_relationship_indicators(
        self,
        query: str,
        context: MemoryContext,
        limit: int,
    ) -> list[RetrievalResult]:
        """
        Search with relationship type indicators.

        Adds relationship_type field to each result indicating why
        it was returned (exact_match, similar_to, related_to, etc.).

        Args:
            query: Query string
            context: Memory context for filtering
            limit: Maximum number of results

        Returns:
            Results with relationship_type indicators
        """
        from agent_vault.memory.keyword_extraction import (
            extract_keywords,
            calculate_keyword_match_score,
        )

        # Extract keywords from query
        query_keywords = extract_keywords(query)

        # Use hybrid precision search
        results = await self._search_hybrid_precision(query, context, limit)

        # Add relationship type indicators
        for result in results:
            # Extract keywords from content
            content_keywords = extract_keywords(result.item.content)
            summary_keywords = extract_keywords(result.item.summary)
            combined_keywords = list(set(content_keywords + summary_keywords))

            # Calculate scores
            keyword_score = calculate_keyword_match_score(
                query_keywords, combined_keywords
            )
            metadata_score = self._calculate_metadata_match_score(
                query, result.item.metadata
            )

            # Determine relationship type
            relationship_type = self._determine_relationship_type(
                query, result, keyword_score, metadata_score
            )

            # Set result type (why this result was returned)
            result.type = relationship_type

        return results

    async def retrieve(
        self,
        query: str,
        context: MemoryContext,
        strategy: str = "adaptive",
        limit: int = 10,
        weights: dict[str, float] | None = None,
        include_history: bool = False,
    ) -> Union[List[RetrievalResult], Dict[str, Any]]:
        """
        Retrieve relevant memories using specified strategy.

        Args:
            query: Search query
            context: Retrieval context (agent, session, etc.)
            strategy: Search strategy name
            limit: Maximum number of results
            weights: Optional custom weights for adaptive strategy
            include_history: Whether to include non-active (historical) memories

        Returns:
            List of RetrievalResult objects or Dict (if ambiguity detected)
        """
        # Update statistics
        self._stats["total_queries"] += 1
        self._stats["queries_by_strategy"][strategy] = (
            self._stats["queries_by_strategy"].get(strategy, 0) + 1
        )

        # Check cache
        cache_key = self._get_cache_key(query, context, strategy, limit, include_history)
        cached_results = self._get_from_cache(cache_key)

        if cached_results is not None:
            self._stats["cache_hits"] += 1
            logger.debug(
                "Cache hit for query='%s', strategy=%s, agent=%s",
                query[:50],
                strategy,
                context.agent_id,
            )
            return cached_results

        self._stats["cache_misses"] += 1

        # Call appropriate search strategy (they handle embedding generation)
        results: Union[List[RetrievalResult], Dict[str, Any]]
        if strategy == "relevance":
            results = await self._search_relevance(query, context, limit)
        elif strategy == "recency":
            results = await self._search_recency(query, context, limit)
        elif strategy == "importance":
            results = await self._search_importance(query, context, limit)
        elif strategy == "adaptive":
            results = await self._search_adaptive(
                query, context, limit, weights
            )
        elif strategy == "hybrid_precision":
            # Strategy for exact match prioritization
            results = await self._search_hybrid_precision(query, context, limit)
        elif strategy == "ambiguity_aware":
            # Strategy that returns 3-5 results for ambiguous queries
            results = await self._search_with_ambiguity_detection(query, context, limit)
        elif strategy == "with_relationships":
            # Strategy that includes relationship type indicators
            results = await self._search_with_relationship_indicators(query, context, limit)
        else:
            raise ValueError(
                f"Invalid search strategy: {strategy}. "
                f"Must be one of: relevance, recency, importance, adaptive, "
                f"hybrid_precision, ambiguity_aware, with_relationships"
            )

        # Filter out non-active memories unless history is requested
        if not include_history:
            if isinstance(results, dict):
                # Apply filtering to results in the dict
                results["results"] = [
                    r for r in results["results"] 
                    if r.item.status == MemoryStatus.ACTIVE
                ]
            else:
                results = [
                    r for r in results 
                    if r.item.status == MemoryStatus.ACTIVE
                ]

        # Cache results
        self._put_in_cache(cache_key, results)

        logger.info(
            "Retrieved %d memories for query='%s', strategy=%s, agent=%s",
            len(results),
            query[:50],
            strategy,
            context.agent_id,
        )

        return results

    async def batch_retrieve(
        self,
        queries: list[tuple[str, MemoryContext]],
        strategy: str = "adaptive",
        limit: int = 10,
        weights: dict[str, float] | None = None,
    ) -> List[Union[List[RetrievalResult], Dict[str, Any]]]:
        """
        Retrieve memories for multiple queries in parallel.

        Args:
            queries: List of (query, context) tuples
            strategy: Search strategy to use for all queries
            limit: Maximum number of results per query
            weights: Optional custom weights for adaptive strategy

        Returns:
            List of result lists (or dicts), one per query in the same order
        """
        # Create retrieval tasks for all queries
        tasks = [
            self.retrieve(query, context, strategy, limit, weights)
            for query, context in queries
        ]

        # Execute all retrievals in parallel
        results = await asyncio.gather(*tasks)

        logger.info(
            "Batch retrieved %d queries with strategy=%s",
            len(queries),
            strategy,
        )

        return list(results)
