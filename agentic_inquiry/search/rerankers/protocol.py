"""Reranker protocol for hybrid search.

This module defines the RerankerProtocol interface that all reranker
implementations must follow. SearchResult is imported from the canonical
database.results module.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

# Import canonical SearchResult from database layer
from agentic_inquiry.database.results import SearchResult

# Re-export for backward compatibility
__all__ = ["RerankerProtocol", "SearchResult"]


@runtime_checkable
class RerankerProtocol(Protocol):
    """Pluggable reranker strategy for hybrid search.

    NOT a database adapter - operates on search results post-retrieval.
    Uses canonical SearchResult type.

    Contract:
    - Input: Two lists of SearchResult (vector and FTS results)
    - Output: Single merged/reranked list of SearchResult
    - Output scores MUST be normalized to 0.0-1.0 range
    """

    def rerank(
        self,
        query: str,
        vector_results: List[SearchResult],
        fts_results: List[SearchResult],
        config: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Merge and rerank results from multiple search strategies.

        Args:
            query: Original query string (needed for cross-encoder reranking)
            vector_results: Results from vector search (already normalized 0-1)
            fts_results: Results from FTS search (already normalized 0-1)
            config: Strategy-specific configuration overrides

        Returns:
            Merged, reranked results with normalized scores (0.0-1.0)
        """
        ...
