"""Reciprocal Rank Fusion (RRF) reranker.

Merges ranked lists by rank alone: ``score = sum(1 / (k + rank))`` over the
lists a result appears in (Cormack et al., SIGIR 2009). Raw scores from the
two retrievers live on different scales (cosine similarity against BM25), so
fusing ranks is what makes them comparable.

Reference: https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from agentic_inquiry.search.rerankers.protocol import RerankerProtocol, SearchResult
from agentic_inquiry.search.rerankers.registry import register_reranker

DEFAULT_K = 60


@register_reranker("rrf")
class RRFReranker(RerankerProtocol):
    """Plain reciprocal rank fusion of the vector and full-text lists.

    Scores are divided by the best achievable fused score (first in both
    lists), so 1.0 means both retrievers ranked the result first and 0.5
    means one retriever ranked it first and the other did not return it.
    Ties keep first-appearance order, vector list first.
    """

    def __init__(self, k: int = DEFAULT_K):
        self.k = k

    def rerank(
        self,
        query: str,
        vector_results: List[SearchResult],
        fts_results: List[SearchResult],
        config: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        return self.fuse([vector_results, fts_results])

    def fuse(self, rankings: List[List[SearchResult]]) -> List[SearchResult]:
        """Fuse any number of ranked lists; 1.0 means first in every list."""
        scores: Dict[str, float] = {}
        first: Dict[str, SearchResult] = {}
        for ranking in rankings:
            for rank, result in enumerate(ranking):
                scores[result.id] = scores.get(result.id, 0.0) + 1.0 / (self.k + rank + 1)
                first.setdefault(result.id, result)
        best = max(1, len(rankings)) / (self.k + 1)
        ordered = sorted(scores, key=lambda rid: -scores[rid])
        return [first[rid].with_score(min(1.0, scores[rid] / best), source="hybrid_rrf") for rid in ordered]
