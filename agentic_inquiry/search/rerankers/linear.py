"""Linear combination reranker.

Combines vector and FTS scores using weighted linear combination:
final_score = vector_weight * vector_score + fts_weight * fts_score
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agentic_inquiry.search.rerankers.base import normalize_scores
from agentic_inquiry.search.rerankers.protocol import RerankerProtocol, SearchResult
from agentic_inquiry.search.rerankers.registry import register_reranker

logger = logging.getLogger(__name__)


@register_reranker("linear_combination")
class LinearCombinationReranker(RerankerProtocol):
    """Linear combination of vector and FTS scores.

    Final score = vector_weight * vector_score + fts_weight * fts_score

    Results appearing in both searches get boosted proportionally.
    This is a simple, interpretable reranking strategy.

    Attributes:
        vector_weight: Weight for vector search scores (default 0.7)
        fts_weight: Weight for FTS scores (default 0.3)
    """

    def __init__(self, vector_weight: float = 0.7, fts_weight: float = 0.3):
        """Initialize linear combination reranker.

        Args:
            vector_weight: Weight for vector search scores (default 0.7)
            fts_weight: Weight for FTS scores (default 0.3)
        """
        self.vector_weight = vector_weight
        self.fts_weight = fts_weight

    def rerank(
        self,
        query: str,
        vector_results: List[SearchResult],
        fts_results: List[SearchResult],
        config: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Merge results using weighted linear combination.

        Args:
            query: Original query string (not used but required by protocol)
            vector_results: Results from vector search
            fts_results: Results from FTS search
            config: Optional config overriding vector_weight and fts_weight

        Returns:
            Merged results with combined scores, normalized to 0.0-1.0
        """
        config = config or {}
        vector_weight = config.get("vector_weight", self.vector_weight)
        fts_weight = config.get("fts_weight", self.fts_weight)

        # Build score lookup from FTS results
        fts_scores: Dict[str, float] = {}
        fts_result_map: Dict[str, SearchResult] = {}
        for result in fts_results:
            fts_scores[result.id] = result.score
            fts_result_map[result.id] = result

        # Combine scores
        combined_scores: Dict[str, float] = {}
        result_map: Dict[str, SearchResult] = {}

        # Process vector results
        for result in vector_results:
            vector_score = result.score
            fts_score = fts_scores.get(result.id, 0.0)
            combined = (vector_weight * vector_score) + (fts_weight * fts_score)

            combined_scores[result.id] = combined
            result_map[result.id] = result

        # Process FTS-only results
        for result in fts_results:
            if result.id not in result_map:
                combined = fts_weight * result.score
                combined_scores[result.id] = combined
                result_map[result.id] = result

        # Sort by combined score
        ranked_ids = sorted(
            combined_scores.keys(), key=lambda x: combined_scores[x], reverse=True
        )

        if not ranked_ids:
            return []

        # Normalize to 0.0-1.0 using shared utility
        raw_scores = [combined_scores[id_] for id_ in ranked_ids]
        return normalize_scores(
            raw_scores, ranked_ids, result_map, source="hybrid_linear"
        )
