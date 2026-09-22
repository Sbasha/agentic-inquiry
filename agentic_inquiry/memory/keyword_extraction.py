"""
Keyword extraction utilities for memory query precision.

This module provides functions to extract keywords from queries and content
for improved memory retrieval precision.
"""

import re
from collections import Counter


def extract_keywords(text: str, min_length: int = 3, max_keywords: int = 10) -> list[str]:
    """
    Extract keywords from text using simple heuristics.
    
    Extracts meaningful words by:
    1. Converting to lowercase
    2. Removing punctuation
    3. Filtering out common stop words
    4. Filtering by minimum length
    5. Returning most frequent words
    
    Args:
        text: Input text to extract keywords from
        min_length: Minimum word length to consider (default: 3)
        max_keywords: Maximum number of keywords to return (default: 10)
        
    Returns:
        List of extracted keywords, ordered by frequency
    """
    # Common English stop words
    stop_words = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
        "been", "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "should", "could", "may", "might", "must", "can", "this",
        "that", "these", "those", "i", "you", "he", "she", "it", "we", "they",
        "what", "which", "who", "when", "where", "why", "how", "all", "each",
        "every", "both", "few", "more", "most", "other", "some", "such", "no",
        "nor", "not", "only", "own", "same", "so", "than", "too", "very"
    }
    
    # Convert to lowercase and extract words
    text_lower = text.lower()
    words = re.findall(r'\b[a-z]+\b', text_lower)
    
    # Filter words
    filtered_words = [
        word for word in words
        if len(word) >= min_length and word not in stop_words
    ]
    
    # Count frequencies
    word_counts = Counter(filtered_words)
    
    # Return most common keywords
    return [word for word, _ in word_counts.most_common(max_keywords)]


def calculate_keyword_match_score(
    query_keywords: list[str],
    content_keywords: list[str]
) -> float:
    """
    Calculate keyword match score between query and content.
    
    Uses Jaccard similarity: intersection / union
    
    Args:
        query_keywords: Keywords extracted from query
        content_keywords: Keywords extracted from content
        
    Returns:
        Match score between 0.0 and 1.0
    """
    if not query_keywords or not content_keywords:
        return 0.0
    
    query_set = set(query_keywords)
    content_set = set(content_keywords)
    
    intersection = len(query_set & content_set)
    union = len(query_set | content_set)
    
    if union == 0:
        return 0.0
    
    return intersection / union


def boost_score_with_keywords(
    base_score: float,
    keyword_score: float,
    keyword_weight: float = 0.3
) -> float:
    """
    Boost a base relevance score with keyword matching.
    
    Combines semantic similarity (base_score) with keyword matching
    using a weighted average.
    
    Args:
        base_score: Base relevance score (e.g., from vector similarity)
        keyword_score: Keyword match score
        keyword_weight: Weight for keyword score (default: 0.3)
        
    Returns:
        Combined score between 0.0 and 1.0
    """
    semantic_weight = 1.0 - keyword_weight
    return (semantic_weight * base_score) + (keyword_weight * keyword_score)
