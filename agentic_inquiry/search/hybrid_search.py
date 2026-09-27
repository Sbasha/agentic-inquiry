"""Hybrid search service combining vector and full-text search with RRF."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, FrozenSet, List, Optional

from typing import TYPE_CHECKING

from agentic_inquiry.config import Config
from agentic_inquiry.constants import CURRENT_PROJECT_ID
from agentic_inquiry.events import EventSystem

if TYPE_CHECKING:
    from agentic_inquiry.storage.facade import StorageFacade
from agentic_inquiry.events.context_managers import track_operation
from agentic_inquiry.events.models import EventStatus
from agentic_inquiry.events.types import EventTypes
from agentic_inquiry.exceptions import ConfigurationError
from agentic_inquiry.search.deduplicator import SearchDeduplicator
from agentic_inquiry.search.normalization import normalize_scores_search_result
from agentic_inquiry.search.rerankers import (
    RerankerProtocol,
    SearchResult,
    get_reranker,
    RRFReranker,
    LinearCombinationReranker,
)
from agentic_inquiry.metrics import get_metrics_tracker
from agentic_inquiry.utils.metacognition import detect_ambiguity
import time

logger = logging.getLogger(__name__)

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
            k = params.get("k", 60)
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

    # Stop words excluded from content boost matching
    _CONTENT_BOOST_STOP_WORDS = frozenset({
        'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been',
        'do', 'does', 'did', 'have', 'has', 'had', 'how', 'what',
        'when', 'where', 'which', 'who', 'this', 'that', 'and', 'or',
        'but', 'if', 'for', 'of', 'to', 'in', 'on', 'at', 'by',
        'with', 'from', 'it', 'its', 'can', 'will', 'not', 'no',
    })

    def _apply_query_content_boost(
        self,
        results: List[SearchResult],
        query: str,
        boost_factor: float = 1.5,
    ) -> List[SearchResult]:
        """Boost results whose chunk text contains actual query terms.

        This fixes the "import chunk" problem where vector search returns
        high-similarity import blocks instead of the class declarations or
        method bodies that actually contain the searched identifiers.

        Args:
            results: Reranked search results
            query: Original query string
            boost_factor: Maximum multiplicative boost (1.5 = 50% boost for
                full match). Actual boost scales with match ratio.

        Returns:
            Results with content-match boost applied, re-sorted by score.
        """
        if not results or not query:
            return results

        # Tokenize query: split CamelCase, snake_case, and spaces
        raw_terms = re.split(r'[\s_\-]+', query)
        terms = []
        for t in raw_terms:
            # Split CamelCase
            parts = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', t).split()
            parts = [re.sub(r'(?<=[A-Z])(?=[A-Z][a-z])', ' ', p).split() for p in parts]
            for part_list in parts:
                terms.extend(part_list)

        # Filter stop words and short terms
        significant = [
            t for t in terms
            if len(t) >= 2 and t.lower() not in self._CONTENT_BOOST_STOP_WORDS
        ]
        if not significant:
            return results

        # Deduplicate terms (case-insensitive)
        seen = set()
        unique_terms = []
        for t in significant:
            if t.lower() not in seen:
                seen.add(t.lower())
                unique_terms.append(t.lower())

        # Phase 1a: Pre-scan to calculate per-term frequency (IDF-like weights).
        # Rare terms like "BPM" are much more distinctive than common terms
        # like "service". Weighting by inverse frequency ensures the boost
        # favors results matching distinctive query terms.
        max_base = max(r.score for r in results) if results else 1.0
        searchable_cache = []
        term_doc_count = {t: 0 for t in unique_terms}
        for result in results:
            text = (
                result.data.get("text", "")
                or result.data.get("content", "")
                or result.data.get("chunk_text", "")
                or ""
            ).lower()
            file_path = (result.data.get("file_path", "") or "").lower()
            searchable = f"{text} {file_path}"
            searchable_cache.append(searchable)
            for t in unique_terms:
                if t in searchable:
                    term_doc_count[t] += 1

        # IDF-like weights: rare terms get higher weight
        n_results = len(results)
        term_weights = {}
        for t in unique_terms:
            freq = term_doc_count[t] / max(1, n_results)
            term_weights[t] = 1.0 / max(0.05, freq)  # cap at 20x weight
        total_weight = sum(term_weights.values())

        # Phase 1b: Calculate weighted match ratio + multiplicative boost + floor
        scored = []
        boost_count = 0
        floor_count = 0
        for idx, result in enumerate(results):
            searchable = searchable_cache[idx]

            # Weighted match: sum weights of matched terms / total weight
            matched_weight = sum(
                term_weights[t] for t in unique_terms if t in searchable
            )
            weighted_ratio = matched_weight / total_weight if total_weight > 0 else 0.0

            # Multiplicative boost using weighted ratio
            content_boost = 1.0 + (boost_factor - 1.0) * weighted_ratio
            raw_score = result.score * content_boost

            # Additive floor: when weighted match ratio >= 0.5, guarantee a
            # competitive score. This rescues results that FTS found correctly
            # but vector search missed entirely.
            if weighted_ratio >= 0.5:
                floor = max_base * content_boost  # match the boost of a top result
                if floor > raw_score:
                    raw_score = floor
                    floor_count += 1

            scored.append((result, raw_score))
            if content_boost > 1.05:
                boost_count += 1

        # Phase 2: Re-normalize proportionally to keep scores in [0, 1]
        max_score = max(s for _, s in scored) if scored else 1.0
        if max_score <= 0:
            max_score = 1.0

        boosted = []
        for result, raw_score in scored:
            normalized = min(1.0, raw_score / max_score)
            boosted.append(SearchResult(
                id=result.id,
                data=result.data,
                score=normalized,
                source=result.source,
                distance=result.distance,
            ))

        # Re-sort by boosted score
        boosted.sort(key=lambda r: r.score, reverse=True)

        if boost_count > 0 or floor_count > 0:
            logger.debug(
                "Content boost: %d/%d boosted, %d floored (query terms: %s)",
                boost_count, len(results), floor_count, unique_terms,
            )

        return boosted

    def _apply_overview_boosting(
        self, results: List[SearchResult], boost_overview: bool = False
    ) -> List[SearchResult]:
        """Apply overview boosting to search results."""
        if not boost_overview:
            return results

        # Boost results that are overviews (README, index, main files)
        overview_keywords = ["readme", "index", "main", "overview", "introduction"]
        boost_factor = self.config.search.hybrid_search.overview_boost_factor

        boosted_results = []
        for result in results:
            # Access file_path from data dict
            file_path = result.data.get("file_path", "").lower()
            is_overview = any(keyword in file_path for keyword in overview_keywords)

            if is_overview:
                # Boost score by configured factor (clamped to 1.0)
                boosted_score = min(result.score * boost_factor, 1.0)
                # Create new SearchResult with boosted score and mark as boosted
                new_data = dict(result.data)
                new_data["_overview_boosted"] = True
                boosted_results.append(
                    SearchResult(
                        id=result.id,
                        data=new_data,
                        score=boosted_score,
                        source=result.source,
                        distance=result.distance,
                    )
                )
            else:
                boosted_results.append(result)

        # Re-sort by score (higher is better)
        boosted_results.sort(key=lambda r: r.score, reverse=True)

        return boosted_results

    def _simple_merge(
        self,
        vector_results: List[Dict[str, Any]],
        fts_results: List[Dict[str, Any]],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Merge vector and FTS results with weighted scoring.

        Results matching both semantic and keyword criteria rank higher.
        Uses configurable weights from config.

        Args:
            vector_results: Results from vector search (already normalized)
            fts_results: Results from FTS search (already normalized)
            limit: Maximum number of results to return

        Returns:
            Merged list of results with weighted scores
        """
        # Get weights from config
        vector_weight = self.config.search.hybrid_search.vector_weight
        fts_weight = self.config.search.hybrid_search.fts_weight

        # Create lookup for FTS scores by result ID
        fts_scores = {}
        for result in fts_results:
            result_id = result.get("id")  # Use canonical 'id' field only
            if result_id:
                fts_scores[result_id] = result.get("score", 0.0)

        # Merge results with weighted scoring
        merged = {}
        seen_ids = set()

        # Process vector results
        for result in vector_results:
            result_id = result.get("id")  # Use canonical 'id' field only
            if not result_id or result_id in seen_ids:
                continue

            vector_score = result.get("score", 0.0)
            fts_score = fts_scores.get(result_id, 0.0)

            # Weighted combination (Task 8.4)
            # Results matching both semantic and keyword rank higher
            combined_score = (vector_weight * vector_score) + (fts_weight * fts_score)

            result["score"] = combined_score
            result["_vector_score"] = vector_score
            result["_fts_score"] = fts_score
            result["_matched_both"] = fts_score > 0.0  # Matched both methods

            merged[result_id] = result
            seen_ids.add(result_id)

        # Process FTS results not already in merged
        for result in fts_results:
            result_id = result.get("id")  # Use canonical 'id' field only
            if not result_id or result_id in seen_ids:
                continue

            fts_score = result.get("score", 0.0)
            # Only FTS match, no vector score
            combined_score = fts_weight * fts_score

            result["score"] = combined_score
            result["_vector_score"] = 0.0
            result["_fts_score"] = fts_score
            result["_matched_both"] = False

            merged[result_id] = result
            seen_ids.add(result_id)

        # Sort by combined score (descending)
        sorted_results = sorted(
            merged.values(),
            key=lambda x: x.get("score", 0.0),
            reverse=True
        )

        return sorted_results[:limit]

    def _apply_secondary_ranking(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply secondary ranking for results with similar scores.
        
        When scores are within 0.01, use file type and recency as tiebreakers.
        
        Args:
            results: List of search results sorted by score
            
        Returns:
            Results with secondary ranking applied
        """
        if len(results) <= 1:
            return results
        
        # Group results by similar scores (within 0.01)
        groups = []
        current_group = [results[0]]
        
        for i in range(1, len(results)):
            prev_score = results[i-1].get("score", 0.0)
            curr_score = results[i].get("score", 0.0)
            
            if abs(prev_score - curr_score) <= 0.01:
                # Similar score - add to current group
                current_group.append(results[i])
            else:
                # Different score - start new group
                groups.append(current_group)
                current_group = [results[i]]
        
        # Add last group
        groups.append(current_group)
        
        # Apply secondary ranking within each group
        ranked_results = []
        for group in groups:
            if len(group) == 1:
                ranked_results.extend(group)
            else:
                # Sort by file type priority, then recency
                sorted_group = sorted(
                    group,
                    key=lambda x: (
                        self._get_file_type_priority(x.get("file_path", "")),
                        -x.get("timestamp", 0),  # Negative for descending (newer first)
                    )
                )
                ranked_results.extend(sorted_group)
        
        return ranked_results
    
    def _get_file_type_priority(self, file_path: str) -> int:
        """Get priority for file type (lower is better).
        
        Priority order:
        1. Documentation files (README, docs)
        2. Source code files (.py, .js, .ts, etc.)
        3. Configuration files (.yaml, .json, .toml)
        4. Other files
        
        Args:
            file_path: Path to the file
            
        Returns:
            Priority value (lower is better)
        """
        file_path_lower = file_path.lower()
        
        # Documentation files (highest priority)
        if any(keyword in file_path_lower for keyword in ["readme", "doc", "guide", "tutorial"]):
            return 0
        
        # Source code files
        if any(file_path_lower.endswith(ext) for ext in [".py", ".js", ".ts", ".java", ".cpp", ".c", ".go", ".rs"]):
            return 1
        
        # Configuration files
        if any(file_path_lower.endswith(ext) for ext in [".yaml", ".yml", ".json", ".toml", ".ini", ".conf"]):
            return 2
        
        # Other files (lowest priority)
        return 3

    async def hybrid_search(
        self,
        query_vector: List[float],
        query_fts: str,
        sanitized_fts_query: str,
        vector_search_fn,
        fts_search_fn,
        limit: Optional[int] = None,
        filters: Optional[Dict[str, Any]] = None,
        rerank_by_graph: Optional[bool] = None,
        graph_rerank_fn=None,
        vector_column_name: str = "vector",
        project_id: Optional[str] = CURRENT_PROJECT_ID,
        project_ids: Optional[List[str]] = None,
        boost_overview: bool = False,
        content_preference: Optional[str] = None,
        content_preference_weight: float = 0.7,
        return_ambiguity: bool = False,
    ) -> List[Dict[str, Any]] | Dict[str, Any]:
        """Perform hybrid search combining vector and full-text search.

        Args:
            query_vector: Query vector for semantic search
            query_fts: Original FTS query string
            sanitized_fts_query: Sanitized FTS query string
            vector_search_fn: Function returning List[SearchResult]
            fts_search_fn: Function returning List[SearchResult]
            limit: Maximum number of results to return
            filters: Optional filters to apply
            rerank_by_graph: Whether to rerank by graph relationships
            graph_rerank_fn: Function to perform graph reranking
            vector_column_name: Name of the vector column
            project_id: Project ID to search in
            project_ids: List of project IDs for multi-project search
            boost_overview: Whether to boost overview documents
            content_preference: Optional preferred content type (e.g., "code").
                Results of this type get score boosted, but non-matching types
                are still included (soft preference, not hard filter).
            content_preference_weight: Boost factor for preferred content (0.0-1.0).
                A value of 0.7 means matching content scores 70% higher.
            return_ambiguity: If True, returns a dict with 'results' and 'ambiguity'.

        Returns:
            List of search results or Dict with results and ambiguity info.
        """
        # ... (implementation continues below)
        # Track the search operation
        async with track_operation(
            self.event_system,
            "search.query",
            source="HybridSearchService.hybrid_search",
            search_type="hybrid",
            limit=limit,
            project_id=project_id,
            project_ids=project_ids,
        ):
            try:
                # Use configuration defaults if not specified
                if limit is None:
                    limit = self.config.search.default_limit
                if rerank_by_graph is None:
                    rerank_by_graph = self.config.search.hybrid_search.rerank_by_graph

                logger.debug(
                    "Starting hybrid search: query_fts=%s, limit=%d, boost_overview=%s",
                    query_fts,
                    limit,
                    boost_overview,
                )

                # Track component timings for latency attribution
                component_timings = {}
                
                # Run vector and FTS searches separately to enable fallback
                start_time = time.perf_counter()
                vector_results = await vector_search_fn(
                    query_vector=query_vector,
                    limit=limit * 3,  # Get more results for better reranking + content boost
                    filters=filters,
                    vector_column_name=vector_column_name,
                    project_id=project_id,
                )
                component_timings['vector_search'] = time.perf_counter() - start_time

                start_time = time.perf_counter()
                fts_results = await fts_search_fn(
                    query_fts=query_fts,  # fts_search will sanitize internally
                    limit=limit * 3,  # Get more results for better reranking + content boost
                    filters=filters,
                    project_id=project_id,
                )
                component_timings['fts_search'] = time.perf_counter() - start_time

                logger.debug(
                    "Hybrid search input: vector_results=%d, fts_results=%d",
                    len(vector_results),
                    len(fts_results),
                )

                # Pre-filter: remove clearly irrelevant candidates before RRF
                # to reduce noise in the ranking. Uses raw scores (before normalization).
                # Vector scores are cosine similarity (0-1), FTS scores are ts_rank.
                MIN_VECTOR_SCORE = 0.15
                MIN_FTS_SCORE = 0.01
                pre_filter_vector = len(vector_results)
                pre_filter_fts = len(fts_results)

                # Preserve raw pre-normalization scores in result data
                # so downstream consumers can assess absolute quality.
                for r in vector_results:
                    r.data["_raw_vector_score"] = r.score
                for r in fts_results:
                    r.data["_raw_fts_score"] = r.score

                vector_results = [r for r in vector_results if r.score >= MIN_VECTOR_SCORE]
                fts_results = [r for r in fts_results if r.score >= MIN_FTS_SCORE]
                if pre_filter_vector != len(vector_results) or pre_filter_fts != len(fts_results):
                    logger.debug(
                        "Pre-filter: vector %d->%d, FTS %d->%d",
                        pre_filter_vector, len(vector_results),
                        pre_filter_fts, len(fts_results),
                    )

                # Normalize scores before combining (Task 8.3)
                vector_results = normalize_scores_search_result(vector_results)
                fts_results = normalize_scores_search_result(fts_results)

                # Apply overview boosting to both result sets before merging
                if boost_overview:
                    vector_results = self._apply_overview_boosting(vector_results, boost_overview=True)
                    fts_results = self._apply_overview_boosting(fts_results, boost_overview=True)

                # Fallback strategies when one search returns no results
                # Note: vector_results and fts_results are now List[SearchResult]
                if not vector_results and not fts_results:
                    logger.warning("Both vector and FTS returned no results")
                    if return_ambiguity:
                        return {"results": [], "ambiguity": {"ambiguous": False}}
                    return []

                if not vector_results and fts_results:
                    logger.warning("Vector search returned no results, using FTS only")
                    # Filter out results with score <= 0.0 (Task 8.3)
                    fallback = [r for r in fts_results if r.score > 0.0]
                    # Convert to dicts for deduplicator (uses Mapping protocol)
                    fallback_dicts = [self._search_result_to_dict(r) for r in fallback[:limit]]
                    deduped = self._apply_deduplication(fallback_dicts)
                    if return_ambiguity:
                        return {"results": deduped, "ambiguity": detect_ambiguity(deduped)}
                    return deduped

                if not fts_results and vector_results:
                    logger.warning("FTS returned no results, using vector search only")
                    # Filter out results with score <= 0.0 (Task 8.3)
                    fallback = [r for r in vector_results if r.score > 0.0]
                    # Convert to dicts for deduplicator
                    fallback_dicts = [self._search_result_to_dict(r) for r in fallback[:limit]]
                    deduped = self._apply_deduplication(fallback_dicts)
                    if return_ambiguity:
                        return {"results": deduped, "ambiguity": detect_ambiguity(deduped)}
                    return deduped

                # Both strategies returned results - proceed with reranking
                # Create reranker based on configuration
                reranker = self._create_reranker()

                # Use our protocol-based rerankers for all reranking
                start_time = time.perf_counter()

                # Results are already SearchResult from vector_search and fts_search
                # Rerank using our protocol-based reranker
                reranked = reranker.rerank(
                    query=sanitized_fts_query or "",
                    vector_results=vector_results,
                    fts_results=fts_results,
                    config={
                        "vector_weight": self.config.search.hybrid_search.vector_weight,
                        "fts_weight": self.config.search.hybrid_search.fts_weight,
                    },
                )

                # Keep as SearchResult for further processing, convert to dict at the end
                results = reranked
                component_timings["reranking"] = time.perf_counter() - start_time

                logger.debug(
                    "Hybrid search output (reranked by %s): %d results",
                    type(reranker).__name__,
                    len(results),
                )

                # Boost results whose text contains actual query terms.
                # This ensures chunks with class declarations and method bodies
                # rank higher than import-only chunks from the same file.
                results = self._apply_query_content_boost(
                    results, query_fts, boost_factor=1.5,
                )

                # Limit results (results is List[SearchResult])
                results = results[:limit]

                # Apply overview boosting after reranking (works with SearchResult)
                if boost_overview:
                    results = self._apply_overview_boosting(results, boost_overview=True)

                # Check if reranker eliminated all results
                if not results and (vector_results or fts_results):
                    logger.error(
                        "Reranker eliminated all results! vector_count=%d, fts_count=%d, falling back to vector search",
                        len(vector_results),
                        len(fts_results),
                    )
                    # Fallback to vector search (already SearchResult)
                    results = vector_results[:limit]

                # Filter out results with score <= 0.0 (Task 8.3)
                # results is List[SearchResult], use .score attribute
                results = [r for r in results if r.score > 0.0]

                # Convert to dicts for graph_rerank_fn and downstream processing
                # graph_rerank_fn expects List[Dict] (will be updated in future task)
                results_dicts = [self._search_result_to_dict(r) for r in results]

                # Apply graph reranking if enabled
                if rerank_by_graph and graph_rerank_fn:
                    results_dicts = await graph_rerank_fn(results_dicts)

                # Apply deduplication (expects and returns List[Dict])
                results_dicts = self._apply_deduplication(results_dicts)

                # Apply content preference boosting (soft filter, not hard)
                # This boosts preferred content types without excluding others
                if content_preference:
                    results_dicts = self._apply_content_preference(
                        results_dicts, content_preference, content_preference_weight
                    )

                # Apply secondary ranking for ties (Task 8.5)
                results_dicts = self._apply_secondary_ranking(results_dicts)

                # Log slow searches with component attribution (Requirement 15.4)
                total_time = sum(component_timings.values())
                if total_time > 1.0:
                    # Find which components contributed most to latency
                    slowest_components = sorted(
                        component_timings.items(),
                        key=lambda x: x[1],
                        reverse=True
                    )
                    component_breakdown = ", ".join(
                        f"{name}={duration:.3f}s" for name, duration in slowest_components
                    )
                    logger.warning(
                        "Slow hybrid search detected: total=%.3fs, components: %s",
                        total_time,
                        component_breakdown,
                        extra={
                            "operation": "hybrid_search",
                            "total_duration": total_time,
                            "component_timings": component_timings
                        }
                    )

                # Emit results event
                await self.event_system.emit(
                    EventTypes.Search.RESULTS_RETURNED,
                    source="HybridSearchService.hybrid_search",
                    status=EventStatus.PROGRESS,
                    result_count=len(results_dicts),
                    search_type="hybrid",
                )

                if return_ambiguity:
                    ambiguity_info = detect_ambiguity(results_dicts)
                    return {
                        "results": results_dicts,
                        "ambiguity": ambiguity_info
                    }

                return results_dicts

            except Exception:
                # Error is automatically tracked by track_operation context manager
                raise
