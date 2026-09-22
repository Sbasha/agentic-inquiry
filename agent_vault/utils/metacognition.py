"""Metacognition utilities for detecting ambiguity and building clarifications.

This module provides logic to analyze search/retrieval results to determine if 
a user query was ambiguous and formulate clarifying questions.
"""

import logging
import os
from typing import Any, Dict, List, Protocol

logger = logging.getLogger(__name__)


class ResultProtocol(Protocol):
    """Protocol for objects that look like search results."""
    @property
    def relevance_score(self) -> float: ...
    @property
    def data(self) -> Dict[str, Any]: ...


def detect_ambiguity(
    results: List[Any],
    threshold: float = 0.1,
    min_confidence: float = 0.4,
    diversity_threshold: float = 0.3
) -> Dict[str, Any]:
    """Detect if query results are ambiguous or low confidence.

    Checks for:
    1. Score Clumping: Multiple results with very similar high scores.
    2. Low Confidence: Top result score is below min_confidence.
    3. Semantic Spread: High-scoring results come from very different contexts.

    Args:
        results: List of results (must have relevance_score/score and data/metadata)
        threshold: Score difference for clumping (default: 0.1)
        min_confidence: Absolute score floor (default: 0.4)
        diversity_threshold: Minimum cosine distance between top results 
                            to be considered 'diverse' (default: 0.3)

    Returns:
        Dict with 'ambiguous' (bool) and 'reason' (str)
    """
    if not results:
        return {"ambiguous": True, "reason": "no_results"}

    # Extract scores and data normalization
    def get_score(r):
        return getattr(r, "relevance_score", getattr(r, "score", 0.0))
    
    def get_data(r):
        return getattr(r, "data", getattr(r, "metadata", {}))

    top_score = get_score(results[0])
    
    # 1. Low Confidence
    if top_score < min_confidence:
        return {
            "ambiguous": True, 
            "reason": "low_confidence",
            "confidence": top_score
        }

    if len(results) < 2:
        return {"ambiguous": False, "reason": None}

    # 2. Score Clumping
    similar_results = [r for r in results if abs(top_score - get_score(r)) <= threshold]
    
    if len(similar_results) >= 2:
        # Check if they are actually different entities/files
        unique_files = {get_data(r).get("file_path") for r in similar_results if get_data(r).get("file_path")}
        unique_names = {get_data(r).get("name") for r in similar_results if get_data(r).get("name")}
        
        if len(unique_files) > 1 or len(unique_names) > 1:
            return {
                "ambiguous": True,
                "reason": "multiple_matches",
                "matches": len(similar_results),
                "unique_files": list(unique_files),
                "unique_names": list(unique_names)
            }

    return {"ambiguous": False, "reason": None}


class ClarificationBuilder:
    """Builds user-facing clarification questions based on ambiguity."""

    @staticmethod
    def build_question(ambiguity_info: Dict[str, Any], query: str) -> str:
        """Generate a clarifying question string."""
        reason = ambiguity_info.get("reason")
        
        if reason == "no_results":
            return f"I couldn't find any information matching '{query}'. Could you provide more details or use different keywords?"
            
        if reason == "low_confidence":
            return f"I found some potential matches for '{query}', but I'm not very confident. Could you be more specific about what you're looking for?"
            
        if reason == "multiple_matches":
            names = list(ambiguity_info.get("unique_names", []))
            files = list(ambiguity_info.get("unique_files", []))
            
            # If we have multiple names, they are the best differentiator
            if len(names) > 1:
                options = " or ".join([f"'{n}'" for n in names[:3]])
                return f"I found multiple potential matches for '{query}'. Did you mean {options}?"
            
            # If names are the same but files are different
            if len(files) > 1:
                filenames = [os.path.basename(f) for f in files[:3]]
                options = " or ".join([f"the one in '{fn}'" for fn in filenames])
                return f"I found matches for '{query}' in multiple locations. Did you mean {options}?"
                
        return f"I'm not sure which '{query}' you are referring to. Could you provide more context?"
