"""Base reranker utilities.

Provides shared functionality for reranker implementations, including
score normalization and result merging.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from agentic_inquiry.search.rerankers.protocol import SearchResult


def normalize_scores(
    scores: List[float],
    result_ids: List[str],
    result_map: Dict[str, SearchResult],
    source: str,
) -> List[SearchResult]:
    """Normalize scores to 0.0-1.0 using proportional normalization.

    Uses max-proportional normalization instead of min-max to preserve
    absolute relevance signal. The top result's score reflects how close
    it is to the theoretical maximum, not always 1.0. Results that appear
    in both vector and FTS lists score higher than single-source results.

    Edge cases:
    - Empty results: returns empty list
    - Single result or all equal: scores set to raw/max ratio

    Args:
        scores: Raw scores in the same order as result_ids.
        result_ids: IDs of results in ranked order (highest score first).
        result_map: Mapping from result ID to SearchResult.
        source: Source label for the reranked results (e.g., "hybrid_rrf").

    Returns:
        List of SearchResult with normalized scores (0.0-1.0), ordered by
        score descending.
    """
    if not scores:
        return []

    max_score = max(scores)

    if max_score <= 0:
        return [result_map[id_].with_score(0.0, source=source) for id_ in result_ids]

    # Proportional normalization: divide by max score
    # This preserves the relative quality signal between results
    # while ensuring scores are in [0, 1] range.
    # Unlike min-max, the worst result doesn't become 0.0 -
    # its score reflects its actual proportion of the best score.
    return [
        result_map[id_].with_score(
            min(1.0, scores[i] / max_score),
            source=source,
        )
        for i, id_ in enumerate(result_ids)
    ]


def normalize_scored_tuples(
    scored_results: List[Tuple[str, float]],
    result_map: Dict[str, SearchResult],
    source: str,
) -> List[SearchResult]:
    """Normalize scores from (id, score) tuples using proportional normalization.

    Variant of normalize_scores for rerankers that work with (id, score) tuples
    like cross_encoder, colbert, and cohere.

    Args:
        scored_results: List of (id, score) tuples, already sorted by score descending.
        result_map: Mapping from result ID to SearchResult.
        source: Source label for the reranked results (e.g., "hybrid_cross_encoder").

    Returns:
        List of SearchResult with normalized scores (0.0-1.0), ordered by
        score descending.
    """
    if not scored_results:
        return []

    raw_scores = [score for _, score in scored_results]
    max_score = max(raw_scores)

    if max_score <= 0:
        return [
            result_map[id_].with_score(0.0, source=source) for id_, _ in scored_results
        ]

    # Proportional normalization: divide by max score
    return [
        result_map[id_].with_score(
            min(1.0, score / max_score),
            source=source,
        )
        for id_, score in scored_results
    ]


def merge_results(
    vector_results: List[SearchResult],
    fts_results: List[SearchResult],
    prefer_vector: bool = True,
) -> Dict[str, SearchResult]:
    """Merge vector and FTS results into a unified result map.

    When the same ID appears in both result sets, the preferred source
    is kept (vector by default).

    Args:
        vector_results: Results from vector search.
        fts_results: Results from FTS search.
        prefer_vector: If True (default), prefer vector results for duplicates.

    Returns:
        Dictionary mapping result ID to SearchResult.
    """
    result_map: Dict[str, SearchResult] = {}

    if prefer_vector:
        # Add FTS first, then vector (so vector overwrites duplicates)
        for result in fts_results:
            result_map[result.id] = result
        for result in vector_results:
            result_map[result.id] = result
    else:
        # Add vector first, then FTS (so FTS overwrites duplicates)
        for result in vector_results:
            result_map[result.id] = result
        for result in fts_results:
            result_map[result.id] = result

    return result_map


def extract_text_content(result: SearchResult) -> str:
    """Extract text content from a SearchResult for ML rerankers.

    Tries common field names in order: text, content, chunk_text.
    Falls back to string representation of data.

    Args:
        result: SearchResult to extract text from.

    Returns:
        Text content suitable for ML reranking.
    """
    return (
        result.data.get("text")
        or result.data.get("content")
        or result.data.get("chunk_text")
        or str(result.data)
    )
