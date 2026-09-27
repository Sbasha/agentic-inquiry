"""Cross-encoder reranker wrapper.

Wraps lancedb.rerankers.CrossEncoderReranker for use with the RerankerProtocol.
Cross-encoders jointly encode query and document for more accurate relevance scoring.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agentic_inquiry.search.rerankers.base import (
    extract_text_content,
    merge_results,
    normalize_scored_tuples,
)
from agentic_inquiry.search.rerankers.protocol import RerankerProtocol, SearchResult
from agentic_inquiry.search.rerankers.registry import register_reranker

logger = logging.getLogger(__name__)


@register_reranker("cross_encoder")
class CrossEncoderReranker(RerankerProtocol):
    """Cross-encoder reranker using sentence-transformers.

    Cross-encoders jointly encode the query and each document, producing
    more accurate relevance scores than bi-encoders but at higher cost.

    Attributes:
        model_name: HuggingFace model name for cross-encoder
        _reranker: Underlying LanceDB cross-encoder reranker (lazy loaded)
    """

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        """Initialize cross-encoder reranker.

        Args:
            model_name: HuggingFace model name for cross-encoder.
                       Default is a fast, accurate model for general use.
        """
        self.model_name = model_name
        self._reranker: Any = None

    def _get_reranker(self) -> Any:
        """Lazy-load the underlying LanceDB reranker."""
        if self._reranker is None:
            try:
                from lancedb.rerankers import CrossEncoderReranker as LanceCrossEncoder

                self._reranker = LanceCrossEncoder(model_name=self.model_name)
            except ImportError:
                logger.warning(
                    "lancedb.rerankers.CrossEncoderReranker not available. "
                    "Install sentence-transformers for cross-encoder support."
                )
                raise
        return self._reranker

    def rerank(
        self,
        query: str,
        vector_results: List[SearchResult],
        fts_results: List[SearchResult],
        config: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Rerank results using cross-encoder scoring.

        Args:
            query: Original query string (used for cross-encoder scoring)
            vector_results: Results from vector search
            fts_results: Results from FTS search
            config: Optional configuration overrides

        Returns:
            Merged results reranked by cross-encoder scores, normalized to 0.0-1.0
        """
        # Merge results, preferring vector results for duplicates
        result_map = merge_results(vector_results, fts_results, prefer_vector=True)

        if not result_map:
            return []

        # Get unique results for reranking
        unique_results = list(result_map.values())

        try:
            reranker = self._get_reranker()

            # Extract text content for cross-encoder
            documents = [
                {"id": result.id, "text": extract_text_content(result)}
                for result in unique_results
            ]

            # Score using cross-encoder
            scores = reranker.compute_relevance_scores(query, documents)

            # Build scored results
            scored_results: List[tuple[str, float]] = [
                (unique_results[i].id, scores[i]) for i in range(len(unique_results))
            ]

            # Sort by score descending
            scored_results.sort(key=lambda x: x[1], reverse=True)

        except Exception as e:
            logger.warning(
                "Cross-encoder reranking failed: %s. Falling back to score merge.", e
            )
            # Fallback: merge by original scores
            scored_results = [
                (r.id, r.score)
                for r in sorted(unique_results, key=lambda x: x.score, reverse=True)
            ]

        # Normalize scores to 0.0-1.0 using shared utility
        return normalize_scored_tuples(
            scored_results, result_map, source="hybrid_cross_encoder"
        )
