"""Reciprocal Rank Fusion (RRF) reranker.

RRF is a lightweight, deterministic algorithm that doesn't require ML models.
It merges ranked lists by computing: score = sum(1 / (k + rank)) for each result.

Reference: https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agentic_inquiry.search.rerankers.base import normalize_scores
from agentic_inquiry.search.rerankers.protocol import RerankerProtocol, SearchResult
from agentic_inquiry.search.rerankers.registry import register_reranker

logger = logging.getLogger(__name__)


@register_reranker("rrf")
class RRFReranker(RerankerProtocol):
    """Reciprocal Rank Fusion reranker - backend-agnostic implementation.

    Score-aware RRF formula:
        score = sum(weight * raw_score / (k + rank)) for each result across strategies.

    Unlike classic RRF which ignores relevance scores and only uses ranks,
    this variant incorporates the raw similarity/rank signal. This prevents
    result dilution in larger indexes where many marginally-relevant results
    compete for top positions.

    Results appearing in BOTH vector and FTS lists get a dual-source bonus,
    as cross-method agreement is a strong relevance signal.

    Attributes:
        k: Rank constant that controls how much higher ranks are favored.
           Default 30 provides good separation between top and bottom ranks.
        dual_source_bonus: Multiplicative bonus for results in both lists.
    """

    def __init__(self, k: int = 30, dual_source_bonus: float = 1.3):
        """Initialize RRF reranker.

        Args:
            k: Rank constant that controls how much higher ranks are favored.
               Default 30 provides ~1.4x spread between rank 1 and rank 10.
               Lower values favor top ranks more aggressively.
            dual_source_bonus: Multiplicative bonus for results appearing in
               both vector and FTS results. Default 1.3 (30% boost).
        """
        self.k = k
        self.dual_source_bonus = dual_source_bonus

    def rerank(
        self,
        query: str,
        vector_results: List[SearchResult],
        fts_results: List[SearchResult],
        config: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Merge results using score-aware Reciprocal Rank Fusion.

        Args:
            query: Original query string (not used by RRF but required by protocol)
            vector_results: Results from vector search
            fts_results: Results from FTS search
            config: Optional config with vector_weight and fts_weight

        Returns:
            Merged results ranked by RRF score, normalized to 0.0-1.0
        """
        config = config or {}
        vector_weight = config.get("vector_weight", 0.7)
        fts_weight = config.get("fts_weight", 0.3)

        # Calculate score-aware RRF scores
        scores: Dict[str, float] = {}
        result_map: Dict[str, SearchResult] = {}
        vector_ids: set = set()
        fts_ids: set = set()

        for rank, result in enumerate(vector_results):
            # Score-aware: multiply by raw score so high-similarity results
            # contribute more than low-similarity ones at the same rank
            score_factor = max(0.1, result.score)
            rrf_score = vector_weight * score_factor / (self.k + rank + 1)
            scores[result.id] = scores.get(result.id, 0.0) + rrf_score
            result_map[result.id] = result
            vector_ids.add(result.id)

        for rank, result in enumerate(fts_results):
            score_factor = max(0.1, result.score)
            rrf_score = fts_weight * score_factor / (self.k + rank + 1)
            scores[result.id] = scores.get(result.id, 0.0) + rrf_score
            if result.id not in result_map:
                result_map[result.id] = result
            fts_ids.add(result.id)

        # Apply dual-source bonus for results appearing in both lists
        dual_source_ids = vector_ids & fts_ids
        for id_ in dual_source_ids:
            scores[id_] *= self.dual_source_bonus

        if dual_source_ids:
            logger.debug(
                "Dual-source bonus (%.1fx) applied to %d results",
                self.dual_source_bonus,
                len(dual_source_ids),
            )

        # Sort by combined score (descending)
        ranked_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

        if not ranked_ids:
            return []

        # Normalize scores to 0.0-1.0 using shared utility
        raw_scores = [scores[id_] for id_ in ranked_ids]
        return normalize_scores(raw_scores, ranked_ids, result_map, source="hybrid_rrf")
