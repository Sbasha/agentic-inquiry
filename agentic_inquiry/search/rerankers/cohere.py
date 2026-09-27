"""Cohere reranker wrapper.

Wraps lancedb.rerankers.CohereReranker for use with the RerankerProtocol.
Uses Cohere's hosted reranking API for high-quality semantic reranking.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from agentic_inquiry.search.rerankers.base import (
    extract_text_content,
    merge_results,
    normalize_scored_tuples,
)
from agentic_inquiry.search.rerankers.protocol import RerankerProtocol, SearchResult
from agentic_inquiry.search.rerankers.registry import register_reranker

logger = logging.getLogger(__name__)


@register_reranker("cohere")
class CohereReranker(RerankerProtocol):
    """Cohere API-based reranker.

    Uses Cohere's hosted reranking API for high-quality semantic reranking.
    Requires a Cohere API key.

    Attributes:
        model_name: Cohere reranker model name
        api_key: Cohere API key (from param or COHERE_API_KEY env var)
        _reranker: Underlying LanceDB Cohere reranker (lazy loaded)
    """

    def __init__(
        self,
        model_name: str = "rerank-english-v2.0",
        api_key: Optional[str] = None,
    ):
        """Initialize Cohere reranker.

        Args:
            model_name: Cohere reranker model name.
            api_key: Cohere API key. If not provided, reads from
                    COHERE_API_KEY environment variable.
        """
        self.model_name = model_name
        self.api_key = api_key or os.environ.get("COHERE_API_KEY")
        self._reranker: Any = None

    def _get_reranker(self) -> Any:
        """Lazy-load the underlying LanceDB reranker."""
        if self._reranker is None:
            if not self.api_key:
                raise ValueError(
                    "Cohere API key required. Set COHERE_API_KEY environment "
                    "variable or pass api_key parameter."
                )
            try:
                from lancedb.rerankers import CohereReranker as LanceCohere

                self._reranker = LanceCohere(
                    model_name=self.model_name, api_key=self.api_key
                )
            except ImportError:
                logger.warning(
                    "lancedb.rerankers.CohereReranker not available. "
                    "Install cohere for Cohere support."
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
        """Rerank results using Cohere API.

        Args:
            query: Original query string (sent to Cohere API)
            vector_results: Results from vector search
            fts_results: Results from FTS search
            config: Optional configuration overrides

        Returns:
            Merged results reranked by Cohere, normalized to 0.0-1.0
        """
        # Merge results, preferring vector results for duplicates
        result_map = merge_results(vector_results, fts_results, prefer_vector=True)

        if not result_map:
            return []

        unique_results = list(result_map.values())

        try:
            reranker = self._get_reranker()

            # Extract text content for Cohere
            documents = [
                {"id": result.id, "text": extract_text_content(result)}
                for result in unique_results
            ]

            # Score using Cohere API
            scores = reranker.compute_relevance_scores(query, documents)

            scored_results: List[tuple[str, float]] = [
                (unique_results[i].id, scores[i]) for i in range(len(unique_results))
            ]

            scored_results.sort(key=lambda x: x[1], reverse=True)

        except Exception as e:
            logger.warning(
                "Cohere reranking failed: %s. Falling back to score merge.", e
            )
            scored_results = [
                (r.id, r.score)
                for r in sorted(unique_results, key=lambda x: x.score, reverse=True)
            ]

        # Normalize scores to 0.0-1.0 using shared utility
        return normalize_scored_tuples(
            scored_results, result_map, source="hybrid_cohere"
        )
