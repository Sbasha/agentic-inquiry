"""Score normalization utilities for search results.

This module provides a single source of truth for score normalization
across all search components (SearchService, HybridSearchService).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Union

from agentic_inquiry.database.results import SearchResult


logger = logging.getLogger(__name__)


def normalize_scores_dict(
    results: List[Dict[str, Any]],
    method: Literal["min_max"] = "min_max",
) -> List[Dict[str, Any]]:
    """Normalize scores in dictionary results to [0, 1] range.

    Converts LanceDB distance scores to similarity scores and normalizes them.
    LanceDB returns _distance (lower is better), we convert to score (higher is better).

    Args:
        results: List of search results with _distance or _score fields
        method: Normalization method (currently only min_max supported)

    Returns:
        Results with normalized score field in [0, 1] range
    """
    if not results:
        return results

    # Extract scores - convert distance to similarity if needed
    scores = []
    for r in results:
        if "_distance" in r:
            # Convert distance to similarity: similarity = 1 / (1 + distance)
            # This ensures: distance=0 -> similarity=1, distance=inf -> similarity=0
            distance = r["_distance"]
            similarity = 1.0 / (1.0 + distance)
            scores.append(similarity)
        elif "_score" in r:
            scores.append(r["_score"])
        else:
            # No score field - assign 0.0
            scores.append(0.0)

    # Check if all scores are zero
    if all(s == 0.0 for s in scores):
        logger.warning(
            "All search scores are 0.0 - check embedding quality or query. "
            "Results may not be properly ranked."
        )
        # Return results with score=0.0 for all
        for r in results:
            r["score"] = 0.0
        return results

    # Min-max normalization to [0, 1]
    min_score = min(scores)
    max_score = max(scores)

    if max_score == min_score:
        # All scores are identical - normalize to 1.0
        for r in results:
            r["score"] = 1.0
    else:
        # Normalize: (score - min) / (max - min)
        for i, r in enumerate(results):
            normalized = (scores[i] - min_score) / (max_score - min_score)
            r["score"] = normalized

    return results


def normalize_scores_search_result(
    results: List[SearchResult],
    method: Literal["proportional", "min_max"] = "proportional",
) -> List[SearchResult]:
    """Normalize scores in SearchResult objects to [0, 1] range.

    Uses proportional normalization (divide by max) by default to preserve
    absolute quality signal. Unlike min-max, the worst result doesn't become
    0.0 - its score reflects its actual proportion of the best score.

    Args:
        results: List of SearchResult objects
        method: Normalization method ("proportional" or "min_max")

    Returns:
        New list of SearchResult with normalized scores in [0, 1] range
    """
    if not results:
        return results

    # Extract current scores from SearchResult objects
    scores = [r.score for r in results]

    # Check if all scores are zero
    if all(s == 0.0 for s in scores):
        logger.warning(
            "All search scores are 0.0 - check embedding quality or query. "
            "Results may not be properly ranked."
        )
        return results

    max_score = max(scores)

    if max_score <= 0:
        return results

    if method == "proportional":
        # Proportional normalization: divide by max
        # Preserves relative quality - a set of high-quality results all
        # get high scores, while noise at the bottom stays proportionally low
        return [
            r.with_score(min(1.0, scores[i] / max_score)) for i, r in enumerate(results)
        ]
    else:
        # Min-max normalization (legacy)
        min_score = min(scores)
        if max_score == min_score:
            return [r.with_score(1.0) for r in results]
        return [
            r.with_score((scores[i] - min_score) / (max_score - min_score))
            for i, r in enumerate(results)
        ]


def normalize_scores(
    results: Union[List[Dict[str, Any]], List[SearchResult]],
    method: Literal["min_max"] = "min_max",
) -> Union[List[Dict[str, Any]], List[SearchResult]]:
    """Normalize search result scores to [0, 1] range.

    This is the main entry point that dispatches to the appropriate
    normalization function based on the result type.

    Args:
        results: Search results (either dicts or SearchResult objects)
        method: Normalization method (currently only min_max supported)

    Returns:
        Results with normalized scores
    """
    if not results:
        return results

    # Dispatch based on type of first result
    if isinstance(results[0], dict):
        return normalize_scores_dict(results, method)  # type: ignore
    elif isinstance(results[0], SearchResult):
        return normalize_scores_search_result(results, method)  # type: ignore
    else:
        raise TypeError(
            f"Unsupported result type: {type(results[0]).__name__}. "
            "Expected dict or SearchResult."
        )
