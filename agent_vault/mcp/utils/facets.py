"""Facet generation for search refinement."""

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List


def generate_facets(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate facets from search results for refinement.
    
    Facets help users understand result distribution and refine searches
    by showing counts for different categories.
    
    Args:
        results: List of search results
    
    Returns:
        Dictionary containing facets:
            - by_type: Count of results by type (code, doc, etc.)
            - by_language: Count of results by programming language
            - by_directory: Count of results by top-level directory
            - common_terms: Most common terms in results
            - total_count: Total number of results
    """
    if not results:
        return {
            "by_type": {},
            "by_language": {},
            "by_directory": {},
            "common_terms": {},
            "total_count": 0,
        }
    
    # Count by type
    types = [r.get("type", "unknown") for r in results]
    by_type = dict(Counter(types).most_common())
    
    # Count by language
    languages = []
    for r in results:
        # Check metadata for language
        metadata = r.get("metadata", {})
        if isinstance(metadata, dict):
            lang = metadata.get("language", metadata.get("lang"))
            if lang:
                languages.append(lang)
        
        # Fallback to file extension
        if not languages or len(languages) < len(results):
            file_path = r.get("file_path", r.get("location", ""))
            if file_path:
                ext = Path(file_path).suffix.lstrip(".")
                if ext:
                    languages.append(ext)
    
    by_language = dict(Counter(languages).most_common(10))
    
    # Count by directory (top-level only)
    directories = []
    for r in results:
        file_path = r.get("file_path", r.get("location", ""))
        if file_path:
            path = Path(file_path)
            # Get first directory component
            parts = path.parts
            if len(parts) > 1:
                directories.append(parts[0])
            elif len(parts) == 1:
                directories.append("root")
    
    by_directory = dict(Counter(directories).most_common(10))
    
    # Extract common terms from titles/summaries
    terms = []
    for r in results:
        title = r.get("title", r.get("name", ""))
        summary = r.get("summary", "")
        
        # Simple tokenization (split on non-alphanumeric)
        import re
        title_terms = re.findall(r'\w+', title.lower())
        summary_terms = re.findall(r'\w+', summary.lower())
        
        # Filter out common stop words and short terms
        stop_words = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
            "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
            "been", "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "should", "could", "may", "might", "must", "can", "this",
            "that", "these", "those", "it", "its", "i", "you", "he", "she", "we",
            "they", "them", "their", "what", "which", "who", "when", "where", "why",
            "how",
        }
        
        filtered_terms = [
            t for t in title_terms + summary_terms
            if len(t) > 2 and t not in stop_words
        ]
        terms.extend(filtered_terms)
    
    common_terms = dict(Counter(terms).most_common(15))
    
    return {
        "by_type": by_type,
        "by_language": by_language,
        "by_directory": by_directory,
        "common_terms": common_terms,
        "total_count": len(results),
    }


def generate_refinement_suggestions(
    facets: Dict[str, Any],
    current_filters: Dict[str, Any],
) -> List[str]:
    """Generate refinement suggestions based on facets.
    
    Args:
        facets: Facet information from generate_facets
        current_filters: Currently applied filters
    
    Returns:
        List of refinement suggestions
    """
    suggestions = []
    
    # Suggest filtering by type if multiple types exist
    by_type = facets.get("by_type", {})
    if len(by_type) > 1 and "type" not in current_filters:
        top_types = list(by_type.keys())[:3]
        suggestions.append(
            f"Narrow results by type: {', '.join(top_types)}"
        )
    
    # Suggest filtering by language if multiple languages exist
    by_language = facets.get("by_language", {})
    if len(by_language) > 1 and "language" not in current_filters:
        top_langs = list(by_language.keys())[:3]
        suggestions.append(
            f"Filter by language: {', '.join(top_langs)}"
        )
    
    # Suggest filtering by directory if multiple directories exist
    by_directory = facets.get("by_directory", {})
    if len(by_directory) > 1 and "directory" not in current_filters:
        top_dirs = list(by_directory.keys())[:3]
        suggestions.append(
            f"Focus on specific directories: {', '.join(top_dirs)}"
        )
    
    # Suggest refining query with common terms
    common_terms = facets.get("common_terms", {})
    if common_terms:
        top_terms = list(common_terms.keys())[:5]
        suggestions.append(
            f"Refine query with: {', '.join(top_terms)}"
        )
    
    return suggestions
