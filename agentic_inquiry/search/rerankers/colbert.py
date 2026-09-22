"""ColBERT reranker wrapper.

Wraps lancedb.rerankers.ColbertReranker for use with the RerankerProtocol.
ColBERT uses late interaction for efficient, accurate reranking.
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


@register_reranker("colbert")
class ColBERTReranker(RerankerProtocol):
    """ColBERT reranker using late interaction.

    ColBERT (Contextualized Late Interaction over BERT) provides efficient
    reranking by precomputing document embeddings and using late interaction
    at query time.

    Attributes:
        model_name: HuggingFace model name for ColBERT
        _reranker: Underlying LanceDB ColBERT reranker (lazy loaded)
    """

    def __init__(self, model_name: str = "colbert-ir/colbertv2.0"):
        """Initialize ColBERT reranker.

        Args:
            model_name: HuggingFace model name for ColBERT model.
        """
        self.model_name = model_name
        self._reranker: Any = None

    def _get_reranker(self) -> Any:
        """Lazy-load the underlying LanceDB reranker."""
        if self._reranker is None:
            try:
                from lancedb.rerankers import ColbertReranker as LanceColbert

                self._reranker = LanceColbert(model_name=self.model_name)
            except ImportError:
                logger.warning(
                    "lancedb.rerankers.ColbertReranker not available. "
                    "Install colbert-ai for ColBERT support."
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
        """Rerank results using ColBERT late interaction.

        Args:
            query: Original query string (used for ColBERT scoring)
            vector_results: Results from vector search
            fts_results: Results from FTS search
            config: Optional configuration overrides

        Returns:
            Merged results reranked by ColBERT scores, normalized to 0.0-1.0
        """
        # Merge results, preferring vector results for duplicates
        result_map = merge_results(vector_results, fts_results, prefer_vector=True)

        if not result_map:
            return []

        unique_results = list(result_map.values())

        try:
            reranker = self._get_reranker()

            # Extract text content for ColBERT
            documents = [
                {"id": result.id, "text": extract_text_content(result)}
                for result in unique_results
            ]

            # Score using ColBERT
            scores = reranker.compute_relevance_scores(query, documents)

            scored_results: List[tuple[str, float]] = [
                (unique_results[i].id, scores[i]) for i in range(len(unique_results))
            ]

            scored_results.sort(key=lambda x: x[1], reverse=True)

        except Exception as e:
            logger.warning(
                "ColBERT reranking failed: %s. Falling back to score merge.", e
            )
            scored_results = [
                (r.id, r.score)
                for r in sorted(unique_results, key=lambda x: x.score, reverse=True)
            ]

        # Normalize scores to 0.0-1.0 using shared utility
        return normalize_scored_tuples(scored_results, result_map, source="hybrid_colbert")
