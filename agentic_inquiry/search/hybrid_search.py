"""Hybrid search service combining vector and full-text search with RRF."""
from __future__ import annotations

import asyncio
import logging
import time
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Dict, FrozenSet, List, Optional

from agentic_inquiry.config import Config
from agentic_inquiry.constants import CURRENT_PROJECT_ID
from agentic_inquiry.events import EventSystem

if TYPE_CHECKING:
    from agentic_inquiry.storage.facade import StorageFacade
from agentic_inquiry.events.context_managers import track_operation
from agentic_inquiry.events.models import EventStatus
from agentic_inquiry.events.types import EventTypes
from agentic_inquiry.exceptions import ConfigurationError
from agentic_inquiry.metrics import get_metrics_tracker
from agentic_inquiry.search.deduplicator import SearchDeduplicator
from agentic_inquiry.search.rerankers import (
    LinearCombinationReranker,
    RerankerProtocol,
    RRFReranker,
    SearchResult,
    get_reranker,
)
from agentic_inquiry.search.rerankers.rrf import DEFAULT_K
from agentic_inquiry.utils.metacognition import detect_ambiguity

logger = logging.getLogger(__name__)

# Characters of a result the cross-encoder reads: its path, scope and content head.
_PASSAGE_CHARS = 2000


def _passage(row: Dict[str, Any]) -> str:
    from agentic_inquiry.search.context_pack import scope_of

    scope = scope_of(row)
    head = f"{row.get('file_path', '')}\n{scope}\n" if scope else f"{row.get('file_path', '')}\n"
    return (head + str(row.get("content") or ""))[:_PASSAGE_CHARS]


@lru_cache(maxsize=2)
def _cross_encoder(model_name: str) -> Any:
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name, device="cpu", max_length=512)


# Each retriever returns this many candidates per requested result, and at
# least MIN_CANDIDATES, so fusion and the per-file cap have enough to choose from.
CANDIDATE_MULTIPLIER = 3
MIN_CANDIDATES = 100

# Valid reranker types for configuration validation
# These are the officially supported reranker implementations
VALID_RERANKER_TYPES: FrozenSet[str] = frozenset({
    "rrf",                   # Reciprocal Rank Fusion (default, lightweight)
    "linear_combination",    # Weighted score combination (lightweight)
    "cross_encoder",         # Joint query-document encoding (requires model)
    "colbert",               # Late interaction reranking (requires model)
    "cohere",                # Cohere API reranking (requires API key)
})


class HybridSearchService:
    """Provides hybrid search combining vector and full-text search.

    .. versionchanged:: 0.5.0
        Constructor signature changed from ``db_manager: LanceDBManager`` to
        ``storage: StorageFacade`` as the first parameter. This is a breaking change.

        **Migration Example**::

            # Before (deprecated):
            from agentic_inquiry.database.lancedb_manager import LanceDBManager
            db_manager = LanceDBManager(uri="./data")
            service = HybridSearchService(db_manager, config, deduplicator)

            # After (current):
            from agentic_inquiry.storage.facade import StorageFacade
            storage = await StorageFacade.from_config(config, project_id)
            service = HybridSearchService(storage, config, deduplicator)
    """

    def __init__(
        self,
        storage: "StorageFacade",
        config: Config,
        deduplicator: SearchDeduplicator,
        event_system: Optional[EventSystem] = None,
        project_id: Optional[str] = None,
    ):
        """Initialize hybrid search service.

        Args:
            storage: StorageFacade instance providing unified storage access.
                This replaces the previous ``db_manager: LanceDBManager`` parameter.
            config: Configuration object
            deduplicator: Deduplicator for removing duplicate results
            event_system: Optional event system for tracking operations
            project_id: Optional default project ID

        Raises:
            ConfigurationError: If reranker_type is invalid
        """
        # Validate reranker configuration before initializing
        self._validate_reranker_config(config)

        self._storage_facade = storage
        self.config = config
        self.deduplicator = deduplicator
        self.event_system = event_system or EventSystem()
        self.project_id = project_id
        self._metrics = get_metrics_tracker()

    def _validate_reranker_config(self, config: Config) -> None:
        """Validate reranker configuration at startup.

        Args:
            config: Configuration object to validate

        Raises:
            ConfigurationError: If reranker_type is not a valid option
        """
        reranker_type = config.search.hybrid_search.reranker_type.lower()

        if reranker_type not in VALID_RERANKER_TYPES:
            valid_options = ", ".join(sorted(VALID_RERANKER_TYPES))
            raise ConfigurationError(
                f"Invalid reranker_type '{reranker_type}'. "
                f"Valid options: {valid_options}. "
                f"Check your configuration at search.hybrid_search.reranker_type."
            )

    def _resolve_project_id(self, project_id: Optional[str]) -> Optional[str]:
        """Resolve project ID from parameter or instance default."""
        if project_id == CURRENT_PROJECT_ID:
            return self.project_id
        return project_id

    def _dict_to_search_result(self, result: Dict[str, Any]) -> SearchResult:
        """Convert a Dict result to SearchResult for reranking.

        Args:
            result: Dict with id, score, and other fields

        Returns:
            SearchResult instance
        """
        # Use canonical 'id' field; hash fallback only for edge cases
        result_id = result.get("id") or str(hash(str(result)))
        return SearchResult(
            id=str(result_id),
            data=result,
            score=result.get("score", 0.0),
            source=result.get("source", "unknown"),
            distance=result.get("_distance"),
        )

    def _search_result_to_dict(self, result: SearchResult) -> Dict[str, Any]:
        """Convert a SearchResult back to Dict format.

        Args:
            result: SearchResult instance

        Returns:
            Dict with original data plus updated score and source
        """
        output = dict(result.data)
        output["score"] = result.score
        output["source"] = result.source
        if result.distance is not None:
            output["_distance"] = result.distance
        return output

    def _create_reranker(self) -> RerankerProtocol:
        """Create reranker based on configuration.

        Returns:
            RerankerProtocol implementation. Always returns a valid reranker,
            falling back to RRF if the configured type is unavailable.
            For RRF and linear_combination, returns our protocol-based rerankers.
            For ML-based rerankers (cohere, colbert, cross_encoder), returns
            our protocol-based wrappers.
        """
        hybrid_config = self.config.search.hybrid_search
        reranker_type = hybrid_config.reranker_type.lower()
        params = hybrid_config.reranker_params or {}

        # Use our protocol-based rerankers for RRF and linear_combination
        if reranker_type == "rrf":
            k = params.get("k", DEFAULT_K)
            logger.debug("Creating RRFReranker with k=%d", k)
            return RRFReranker(k=k)

        if reranker_type == "linear_combination":
            vector_weight = params.get("vector_weight", hybrid_config.vector_weight)
            fts_weight = params.get("fts_weight", hybrid_config.fts_weight)
            logger.debug(
                "Creating LinearCombinationReranker with vector_weight=%s, fts_weight=%s",
                vector_weight,
                fts_weight,
            )
            return LinearCombinationReranker(
                vector_weight=vector_weight, fts_weight=fts_weight
            )

        # For ML-based rerankers (cross_encoder, colbert, cohere), use registry
        # These may fail to load if optional dependencies are not installed
        reranker = get_reranker(reranker_type, params)
        if reranker is not None:
            logger.debug("Created %s reranker via registry", reranker_type)
            return reranker

        # Fallback to RRF if reranker fails to initialize
        # This can happen when optional dependencies (e.g., sentence-transformers,
        # colbert-ai, cohere) are not installed
        logger.warning(
            "Reranker '%s' failed to initialize (missing dependencies?), "
            "falling back to RRF. Install required packages for %s support.",
            reranker_type,
            reranker_type,
        )
        return RRFReranker()

    def _apply_deduplication(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply deduplication to search results."""
        return self.deduplicator.deduplicate_results(results)

    def _apply_content_preference(
        self,
        results: List[Dict[str, Any]],
        content_preference: Optional[str],
        content_preference_weight: float,
    ) -> List[Dict[str, Any]]:
        """Apply soft content preference boosting to search results.

        Unlike hard filtering which excludes non-matching content types entirely,
        this method boosts the score of matching content types while still
        including all results. This enables cross-content discovery while
        ensuring preferred content types rank higher.

        Args:
            results: List of search results as dicts with 'score' and 'content_type'
            content_preference: Preferred content type (e.g., "code", "documentation")
            content_preference_weight: Boost factor (0.0-1.0). A value of 0.7 means
                matching results score 70% higher.

        Returns:
            Results re-sorted by adjusted scores
        """
        if not content_preference or not results:
            return results

        # Normalize preference for case-insensitive matching
        preference_lower = content_preference.lower()

        boosted_results = []
        for result in results:
            # Get content_type from result
            content_type = result.get("content_type", "").lower()

            # Check if this result matches the preference
            is_preferred = content_type == preference_lower

            if is_preferred:
                # Boost score by weight factor
                original_score = result.get("score", 0.0)
                boosted_score = original_score * (1 + content_preference_weight)
                # Create new result with boosted score
                boosted_result = dict(result)
                boosted_result["score"] = boosted_score
                boosted_result["_content_preference_boosted"] = True
                boosted_results.append(boosted_result)
            else:
                boosted_results.append(result)

        # Re-sort by score (higher is better)
        boosted_results.sort(key=lambda r: r.get("score", 0), reverse=True)

        logger.debug(
            "Applied content preference '%s' with weight %.2f: boosted %d/%d results",
            content_preference,
            content_preference_weight,
            sum(1 for r in boosted_results if r.get("_content_preference_boosted")),
            len(boosted_results),
        )

        return boosted_results

    async def _rerank_head(self, query: str, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Reorder the fused top ``rerank_top_n`` by a cross-encoder, when one is configured.

        The reordered results take over the fused scores in descending order,
        so scores stay monotone with rank and on the fusion scale.
        """
        settings = self.config.search.hybrid_search
        if not settings.rerank_model or len(results) < 2:
            return results
        head = results[: settings.rerank_top_n]
        pairs = [(query, _passage(r)) for r in head]
        loop = asyncio.get_running_loop()
        scores = await loop.run_in_executor(None, _cross_encoder(settings.rerank_model).predict, pairs)
        order = sorted(range(len(head)), key=lambda i: -float(scores[i]))
        fused_scores = sorted((r.get("score", 0.0) for r in head), reverse=True)
        reordered = []
        for rank, index in enumerate(order):
            row = dict(head[index])
            row["score"] = fused_scores[rank]
            row["_rerank_score"] = float(scores[index])
            reordered.append(row)
        return reordered + results[settings.rerank_top_n:]

    async def hybrid_search(
        self,
        query_vector: List[float],
        query_fts: str,
        sanitized_fts_query: str,
        vector_search_fn,
        fts_search_fn,
        limit: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        vector_column_name: str = "vector",
        project_id: Optional[str] = CURRENT_PROJECT_ID,
        project_ids: Optional[List[str]] = None,
        content_preference: Optional[str] = None,
        content_preference_weight: float = 0.7,
        return_ambiguity: bool = False,
    ) -> List[Dict[str, Any]] | Dict[str, Any]:
        """Fuse vector and full-text candidates, cap results per file, cut to ``limit``.

        Order of operations: both retrievers return
        ``max(limit * CANDIDATE_MULTIPLIER, MIN_CANDIDATES)`` candidates; the
        configured reranker (RRF by default) fuses them; an optional soft
        content preference re-sorts; the per-file cap applies to the fused
        order; the list is cut to ``limit`` last, so callers get ``limit``
        results whenever enough candidates exist.

        Args:
            query_vector: Query embedding for vector search.
            query_fts: Query text for full-text search.
            sanitized_fts_query: Sanitized query text passed to the reranker.
            vector_search_fn: Coroutine returning ``List[SearchResult]``.
            fts_search_fn: Coroutine returning ``List[SearchResult]``.
            limit: Maximum number of results.
            filters: Optional filters applied by both retrievers.
            vector_column_name: Name of the vector column.
            project_id: Project to search.
            project_ids: Unused; kept for caller compatibility.
            content_preference: Content type to rank higher without excluding others.
            content_preference_weight: Multiplier bonus for the preferred type.
            return_ambiguity: Return ``{"results", "ambiguity"}`` instead of a list.

        Returns:
            Result dicts in rank order, or a dict with results and ambiguity.
        """
        async with track_operation(
            self.event_system,
            "search.query",
            source="HybridSearchService.hybrid_search",
            search_type="hybrid",
            limit=limit,
            project_id=project_id,
            project_ids=project_ids,
        ):
            if limit is None:
                limit = self.config.search.default_limit
            depth = max(limit * CANDIDATE_MULTIPLIER, MIN_CANDIDATES)

            started = time.perf_counter()
            vector_results = await vector_search_fn(
                query_vector=query_vector,
                limit=depth,
                filters=filters,
                vector_column_name=vector_column_name,
                project_id=project_id,
            )
            fts_results = await fts_search_fn(
                query_fts=query_fts,
                limit=depth,
                filters=filters,
                project_id=project_id,
            )
            fused = self._create_reranker().rerank(
                query=sanitized_fts_query or "",
                vector_results=vector_results,
                fts_results=fts_results,
                config={
                    "vector_weight": self.config.search.hybrid_search.vector_weight,
                    "fts_weight": self.config.search.hybrid_search.fts_weight,
                },
            )
            results = [self._search_result_to_dict(r) for r in fused]
            results = await self._rerank_head(query_fts, results)
            results = self._apply_content_preference(results, content_preference, content_preference_weight)
            results = self._apply_deduplication(results)[:limit]

            elapsed = time.perf_counter() - started
            if elapsed > 1.0:
                logger.warning(
                    "Slow hybrid search: %.3fs for %d vector and %d full-text candidates",
                    elapsed,
                    len(vector_results),
                    len(fts_results),
                )
            await self.event_system.emit(
                EventTypes.Search.RESULTS_RETURNED,
                source="HybridSearchService.hybrid_search",
                status=EventStatus.PROGRESS,
                result_count=len(results),
                search_type="hybrid",
            )
            if return_ambiguity:
                return {"results": results, "ambiguity": detect_ambiguity(results)}
            return results
