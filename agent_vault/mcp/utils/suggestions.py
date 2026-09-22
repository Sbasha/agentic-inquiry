"""Suggestion engine for empty search results."""

import logging
from typing import List

from agent_vault.config import Config
from agent_vault.search.service import SearchService

logger = logging.getLogger(__name__)


async def generate_suggestions(
    query: str,
    search_service: SearchService,
    project_id: str,
    config: Config,
) -> List[str]:
    """Generate suggestions for empty or poor search results.
    
    Implements:
    - Spelling correction suggestions
    - Similar topic suggestions
    - Lower-threshold alternatives
    
    Args:
        query: Original search query
        search_service: SearchService instance
        project_id: Project ID to search in
        config: Configuration instance
    
    Returns:
        List of suggestion strings
    """
    suggestions = []
    
    # 1. Spelling correction suggestions
    spelling_suggestions = await _generate_spelling_suggestions(
        query, search_service, project_id
    )
    suggestions.extend(spelling_suggestions)
    
    # 2. Similar topic suggestions
    topic_suggestions = await _generate_topic_suggestions(
        query, search_service, project_id, config
    )
    suggestions.extend(topic_suggestions)
    
    # 3. Lower-threshold alternatives
    threshold_suggestions = await _generate_threshold_suggestions(
        query, search_service, project_id, config
    )
    suggestions.extend(threshold_suggestions)
    
    # 4. General suggestions
    if not suggestions:
        suggestions.extend([
            "Try broader search terms",
            "Check if content has been indexed with 'add_knowledge'",
            "Use 'get_project_info' to see what's available",
        ])
    
    return suggestions[:5]  # Limit to top 5 suggestions


async def _generate_spelling_suggestions(
    query: str,
    search_service: SearchService,
    project_id: str,
) -> List[str]:
    """Generate spelling correction suggestions.
    
    Uses simple edit distance to find similar terms in the index.
    
    Args:
        query: Original query
        search_service: SearchService instance
        project_id: Project ID
    
    Returns:
        List of spelling suggestions
    """
    suggestions = []
    
    # Split query into terms
    terms = query.lower().split()
    
    # For each term, try to find similar terms in the index
    for term in terms:
        if len(term) < 3:
            continue
        
        # Try common typo patterns
        typo_variants = _generate_typo_variants(term)
        
        for variant in typo_variants:
            try:
                # Search for the variant
                results = await search_service.fts_search(
                    query_fts=variant,
                    limit=1,
                    project_id=project_id,
                )
                
                if results:
                    suggestions.append(f"Did you mean '{variant}' instead of '{term}'?")
                    break  # Found a match, move to next term
            except Exception as e:
                # S5-002: Log spelling suggestion search failure
                logger.debug(
                    "Spelling suggestion search failed for variant '%s': %s",
                    variant, e
                )
                continue
    
    return suggestions[:2]  # Limit to 2 spelling suggestions


async def _generate_topic_suggestions(
    query: str,
    search_service: SearchService,
    project_id: str,
    config: Config,
) -> List[str]:
    """Generate similar topic suggestions.
    
    Uses semantic search to find related topics.
    
    Args:
        query: Original query
        search_service: SearchService instance
        project_id: Project ID
        config: Configuration instance
    
    Returns:
        List of topic suggestions
    """
    suggestions = []
    
    try:
        # Get embeddings for the query
        from agent_vault.embeddings import EmbeddingService
        embedding_service = EmbeddingService(config)
        query_vector_array = await embedding_service.embed_async(query)
        query_vector = query_vector_array.tolist()
        
        # Search with lower threshold
        results = await search_service.vector_search(
            query_vector=query_vector,
            limit=5,
            project_id=project_id,
        )
        
        if results:
            # Extract unique topics from results
            topics = set()
            for result in results:
                # Get title or name
                title = result.data.get("title", result.data.get("name", ""))
                if title:
                    # Extract key terms from title
                    import re
                    terms = re.findall(r'\w+', title.lower())
                    # Filter out common words
                    stop_words = {"the", "a", "an", "and", "or", "in", "on", "at", "to", "for", "of"}
                    key_terms = [t for t in terms if len(t) > 3 and t not in stop_words]
                    topics.update(key_terms[:2])  # Take top 2 terms from each result
            
            if topics:
                topic_list = list(topics)[:3]
                suggestions.append(f"Try searching for: {', '.join(topic_list)}")

    except Exception as e:
        # S5-002: Log topic suggestion generation failure (e.g., embeddings unavailable)
        logger.debug(
            "Topic suggestion generation failed for query '%s': %s",
            query, e
        )
    
    return suggestions[:1]  # Limit to 1 topic suggestion


async def _generate_threshold_suggestions(
    query: str,
    search_service: SearchService,
    project_id: str,
    config: Config,
) -> List[str]:
    """Generate lower-threshold alternative suggestions.
    
    Suggests trying individual terms or broader searches.
    
    Args:
        query: Original query
        search_service: SearchService instance
        project_id: Project ID
        config: Configuration instance
    
    Returns:
        List of threshold suggestions
    """
    suggestions = []
    
    # If query has multiple terms, suggest searching individual terms
    terms = query.split()
    if len(terms) > 1:
        # Try each term individually
        for term in terms:
            if len(term) < 3:
                continue
            
            try:
                results = await search_service.fts_search(
                    query_fts=term,
                    limit=1,
                    project_id=project_id,
                )
                
                if results:
                    suggestions.append(f"Try searching for just '{term}'")
                    break  # Found one that works
            except Exception as e:
                # S5-002: Log threshold suggestion search failure
                logger.debug(
                    "Threshold suggestion search failed for term '%s': %s",
                    term, e
                )
                continue
    
    # Suggest using wildcards or partial matches
    if len(query) > 5:
        suggestions.append("Try a shorter or more general term")
    
    return suggestions[:1]  # Limit to 1 threshold suggestion


def _generate_typo_variants(term: str) -> List[str]:
    """Generate common typo variants of a term.
    
    Implements simple edit distance operations:
    - Character deletion
    - Character insertion
    - Character substitution
    - Character transposition
    
    Args:
        term: Original term
    
    Returns:
        List of typo variants
    """
    variants = []
    
    # Character deletion (remove one character)
    for i in range(len(term)):
        variant = term[:i] + term[i+1:]
        if len(variant) >= 3:
            variants.append(variant)
    
    # Character transposition (swap adjacent characters)
    for i in range(len(term) - 1):
        variant = term[:i] + term[i+1] + term[i] + term[i+2:]
        variants.append(variant)
    
    # Common character substitutions
    common_subs = {
        'a': ['e', 'o'],
        'e': ['a', 'i'],
        'i': ['e', 'o'],
        'o': ['a', 'u'],
        'u': ['o', 'i'],
        's': ['z'],
        'z': ['s'],
        'c': ['k', 's'],
        'k': ['c'],
    }
    
    for i, char in enumerate(term):
        if char in common_subs:
            for sub in common_subs[char]:
                variant = term[:i] + sub + term[i+1:]
                variants.append(variant)
    
    # Limit variants to avoid explosion
    return variants[:10]
