"""Canonical search result type for all database operations.

This module defines the single source of truth for search results across
all backends and operations. All adapters MUST normalize their results
to this format at the boundary.

See: docs/design/result-contract.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Canonical search result returned by all search operations.

    This is the ONLY result type used at adapter boundaries. All backends
    must normalize their results to this format.

    Attributes:
        id: Unique identifier for the result (required for deduplication)
        data: Original row/document data as returned by the backend
        score: Relevance score normalized to 0.0 (worst) to 1.0 (best).
               MUST be normalized at adapter boundaries.
        source: Origin of the result. One of:
               - "vector": Vector similarity search
               - "fts": Full-text search
               - "hybrid": Combined vector + FTS
               - "filter": Filter-only query (no ranking)
               - "graph": Graph traversal
               - "unknown": Source not specified
        distance: Raw distance value from backend (for debugging).
                  Only set if the backend provides distance metrics.

    Score Normalization Rules (per backend):
        - LanceDB distance: score = 1 / (1 + distance)
        - Pinecone similarity (0-1): use directly
        - Weaviate certainty (0-1): use directly
        - Filter-only queries: score = 1.0

    Example:
        >>> result = SearchResult(
        ...     id="doc_123",
        ...     data={"content": "Hello world", "file_path": "/src/main.py"},
        ...     score=0.95,
        ...     source="vector",
        ...     distance=0.052
        ... )
        >>> result.score
        0.95
    """

    id: str
    data: Dict[str, Any]
    score: float
    source: str = "unknown"
    distance: Optional[float] = None

    def __post_init__(self) -> None:
        """Validate score is in valid range."""
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(
                f"Score must be normalized to 0.0-1.0, got {self.score}"
            )

    def with_score(self, score: float, source: Optional[str] = None) -> SearchResult:
        """Create a new SearchResult with updated score.

        Args:
            score: New normalized score (0.0-1.0)
            source: Optional new source identifier

        Returns:
            New SearchResult with updated score (and optionally source)

        Example:
            >>> original = SearchResult(id="1", data={}, score=0.5, source="vector")
            >>> reranked = original.with_score(0.8, source="hybrid_rrf")
            >>> reranked.score
            0.8
        """
        return SearchResult(
            id=self.id,
            data=self.data,
            score=score,
            source=source or self.source,
            distance=self.distance,
        )

    def with_data(self, data: Dict[str, Any]) -> SearchResult:
        """Create a new SearchResult with updated data.

        Args:
            data: New data dictionary

        Returns:
            New SearchResult with updated data
        """
        return SearchResult(
            id=self.id,
            data=data,
            score=self.score,
            source=self.source,
            distance=self.distance,
        )

    # =========================================================================
    # Serialization Methods
    # =========================================================================

    def to_dict(self) -> Dict[str, Any]:
        """Convert SearchResult to a dictionary.

        Returns a dict containing all SearchResult fields, suitable for
        JSON serialization or storage.

        Returns:
            Dictionary with keys: id, data, score, source, distance

        Example:
            >>> result = SearchResult(id="1", data={"x": 1}, score=0.5)
            >>> result.to_dict()
            {'id': '1', 'data': {'x': 1}, 'score': 0.5, 'source': 'unknown', 'distance': None}
        """
        return {
            "id": self.id,
            "data": self.data,
            "score": self.score,
            "source": self.source,
            "distance": self.distance,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> SearchResult:
        """Create a SearchResult from a dictionary.

        Args:
            d: Dictionary with SearchResult fields

        Returns:
            SearchResult instance

        Example:
            >>> d = {'id': '1', 'data': {'x': 1}, 'score': 0.5}
            >>> SearchResult.from_dict(d)
            SearchResult(id='1', data={'x': 1}, score=0.5, source='unknown', distance=None)
        """
        return cls(
            id=d["id"],
            data=d.get("data", {}),
            score=d["score"],
            source=d.get("source", "unknown"),
            distance=d.get("distance"),
        )


def normalize_distance_to_score(distance: float) -> float:
    """Convert distance to normalized score (0.0-1.0).

    Uses the formula: score = 1 / (1 + distance)

    This ensures:
    - distance=0 → score=1.0 (perfect match)
    - distance=1 → score=0.5
    - distance→∞ → score→0.0

    Args:
        distance: Raw distance value (must be >= 0, small negatives from
                  floating point errors are clamped to 0)

    Returns:
        Normalized score in range 0.0-1.0

    Example:
        >>> normalize_distance_to_score(0.0)
        1.0
        >>> normalize_distance_to_score(1.0)
        0.5
    """
    # Clamp small negative values to zero (floating point precision errors)
    # LanceDB can return tiny negative distances like -4.77e-07 for near-identical vectors
    if distance < 0:
        if distance > -1e-6:  # Very small negative, treat as zero
            distance = 0.0
        else:
            raise ValueError(f"Distance must be >= 0, got {distance}")
    return 1.0 / (1.0 + distance)


def normalize_similarity_to_score(similarity: float) -> float:
    """Clamp similarity value to valid score range.

    Some backends return similarity scores that may slightly exceed 1.0
    due to floating point precision. This function clamps to valid range.

    Args:
        similarity: Similarity score (typically 0.0-1.0)

    Returns:
        Clamped score in range 0.0-1.0
    """
    return max(0.0, min(1.0, similarity))


def dict_to_search_result(
    row: Dict[str, Any],
    source: str = "unknown",
    id_fields: tuple[str, ...] = ("doc_id", "id", "chunk_id"),
) -> SearchResult:
    """Convert a raw database row (dict) to a SearchResult.

    This is the canonical conversion function for adapters. It handles:
    - ID extraction from common field names
    - Distance-to-score normalization for vector search results
    - Wrapping the original data

    Args:
        row: Raw row/document from database query
        source: Result provenance ("vector", "fts", "filter", etc.)
        id_fields: Field names to check for ID (in priority order)

    Returns:
        SearchResult with normalized score

    Example:
        >>> row = {"doc_id": "123", "content": "Hello", "_distance": 0.1}
        >>> result = dict_to_search_result(row, source="vector")
        >>> result.id
        '123'
        >>> result.score  # 1 / (1 + 0.1) ≈ 0.909
        0.9090909090909091
    """
    # Extract ID from common field names
    result_id: str | None = None
    for field in id_fields:
        if field in row and row[field] is not None:
            result_id = str(row[field])
            break
    if result_id is None:
        # Fallback to hash if no ID field found
        result_id = str(hash(frozenset(row.items())))

    # Calculate score from distance or use existing score
    distance = row.get("_distance")
    if distance is not None:
        score = normalize_distance_to_score(distance)
    elif "score" in row:
        # Use existing score, clamped to valid range
        score = normalize_similarity_to_score(float(row["score"]))
    else:
        # No distance or score - default to 1.0 (filter-only queries)
        score = 1.0

    return SearchResult(
        id=result_id,
        data=row,
        score=score,
        source=source,
        distance=distance,
    )


def dicts_to_search_results(
    rows: list[Dict[str, Any]],
    source: str = "unknown",
    id_fields: tuple[str, ...] = ("doc_id", "id", "chunk_id"),
) -> list[SearchResult]:
    """Convert a list of raw database rows to SearchResults.

    Convenience wrapper around dict_to_search_result for batch conversion.

    Args:
        rows: List of raw rows/documents from database query
        source: Result provenance ("vector", "fts", "filter", etc.)
        id_fields: Field names to check for ID (in priority order)

    Returns:
        List of SearchResult objects
    """
    return [dict_to_search_result(row, source, id_fields) for row in rows]
