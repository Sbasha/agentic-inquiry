"""Keyword extraction utility for MCP tools."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List

from agentic_inquiry.storage.facade import StorageFacade



# Common programming terms to filter out
COMMON_PROGRAMMING_TERMS = {
    # Keywords
    "if", "else", "elif", "for", "while", "do", "switch", "case", "break", "continue",
    "return", "yield", "await", "async", "def", "class", "import", "from", "as",
    "try", "except", "finally", "raise", "with", "lambda", "pass", "assert",
    "global", "nonlocal", "del", "in", "is", "not", "and", "or", "true", "false",
    "none", "null", "undefined", "var", "let", "const", "function", "new", "this",
    "super", "extends", "implements", "interface", "enum", "struct", "typedef",
    "public", "private", "protected", "static", "final", "abstract", "virtual",
    # Common words
    "the", "a", "an", "to", "of", "and", "or", "in", "on", "at", "by", "for",
    "with", "from", "as", "is", "was", "are", "be", "been", "being", "have",
    "has", "had", "do", "does", "did", "will", "would", "should", "could",
    "may", "might", "must", "can", "get", "set", "add", "remove", "delete",
    "create", "update", "read", "write", "open", "close", "start", "stop",
    "init", "main", "test", "tmp", "temp", "util", "utils", "helper", "helpers",
    # File extensions and common suffixes
    "py", "js", "ts", "jsx", "tsx", "md", "txt", "json", "yaml", "yml",
    "html", "css", "scss", "sass", "less", "xml", "svg", "png", "jpg", "gif",
}


class KeywordExtractor:
    """Extract keywords and terms from indexed content.
    
    This utility analyzes indexed document chunks to extract meaningful keywords
    that can help agents understand what content is available and formulate
    effective search queries.
    """
    
    def __init__(self, min_keyword_length: int = 3, max_keyword_length: int = 50):
        """Initialize keyword extractor.
        
        Args:
            min_keyword_length: Minimum length for a keyword to be considered
            max_keyword_length: Maximum length for a keyword to be considered
        """
        self.min_keyword_length = min_keyword_length
        self.max_keyword_length = max_keyword_length
    
    async def extract_top_keywords(
        self,
        db_manager: StorageFacade,
        project_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Extract most frequent keywords from indexed content.
        
        Analyzes symbols, element names, and content to identify the most
        relevant keywords in the indexed codebase.
        
        Args:
            db_manager: StorageFacade for querying indexed content
            project_id: Project identifier
            limit: Maximum number of keywords to return
        
        Returns:
            List of keyword dictionaries with:
                - keyword: The keyword string
                - frequency: Number of occurrences
                - sources: List of file paths where keyword appears
        """
        # Query all chunks for the project
        chunks = await db_manager.query_raw(
            table_name="document_chunks",
            filters={"project_id": project_id},
            limit=10000,  # Get a large sample of chunks for analysis
            project_id=project_id,
        )
        
        if not chunks:
            return []
        
        # Extract keywords from various fields
        keyword_sources: Dict[str, Dict[str, Any]] = {}
        
        for chunk in chunks:
            file_path = chunk.get("file_path", "")
            
            # Extract from symbols field
            symbols = chunk.get("symbols", [])
            if symbols:
                for symbol in symbols:
                    self._add_keyword(keyword_sources, symbol, file_path)
            
            # Extract from element_name field
            element_name = chunk.get("element_name", "")
            if element_name:
                self._add_keyword(keyword_sources, element_name, file_path)
            
            # Extract from fts_text using simple tokenization
            fts_text = chunk.get("fts_text", "")
            if fts_text:
                tokens = self._tokenize_text(fts_text)
                for token in tokens:
                    self._add_keyword(keyword_sources, token, file_path)
        
        # Convert to list and sort by frequency
        keywords = [
            {
                "keyword": keyword,
                "frequency": data["frequency"],
                "sources": list(data["sources"])[:10],  # Limit sources to 10
            }
            for keyword, data in keyword_sources.items()
        ]
        
        # Sort by frequency (descending) and return top N
        keywords.sort(key=lambda x: x["frequency"], reverse=True)
        return keywords[:limit]
    
    async def extract_related_keywords(
        self,
        search_results: List[Any],
        limit: int = 10,
    ) -> List[str]:
        """Extract related keywords from search results.

        Analyzes the returned search results to identify keywords that appear
        frequently and could be used to refine or expand the search.

        Args:
            search_results: List of SearchResult objects
            limit: Maximum number of related keywords to return

        Returns:
            List of related keyword strings, sorted by frequency
        """
        if not search_results:
            return []

        keyword_counts: Counter = Counter()

        for result in search_results:
            # Extract from symbols
            symbols = result.data.get("symbols", [])
            if symbols:
                for symbol in symbols:
                    if self._is_valid_keyword(symbol):
                        keyword_counts[symbol.lower()] += 1

            # Extract from element_name
            element_name = result.data.get("element_name", "")
            if element_name and self._is_valid_keyword(element_name):
                keyword_counts[element_name.lower()] += 1

            # Extract from content
            content = result.data.get("content", "")
            if content:
                tokens = self._tokenize_text(content)
                for token in tokens:
                    if self._is_valid_keyword(token):
                        keyword_counts[token.lower()] += 1
        
        # Get most common keywords
        most_common = keyword_counts.most_common(limit)
        return [keyword for keyword, _ in most_common]
    
    def _add_keyword(
        self,
        keyword_sources: Dict[str, Dict[str, Any]],
        keyword: str,
        file_path: str,
    ) -> None:
        """Add a keyword to the tracking dictionary.
        
        Args:
            keyword_sources: Dictionary tracking keywords and their sources
            keyword: The keyword to add
            file_path: File path where the keyword was found
        """
        if not self._is_valid_keyword(keyword):
            return
        
        # Normalize keyword to lowercase
        normalized = keyword.lower()
        
        if normalized not in keyword_sources:
            keyword_sources[normalized] = {
                "frequency": 0,
                "sources": set(),
            }
        
        keyword_sources[normalized]["frequency"] += 1
        keyword_sources[normalized]["sources"].add(file_path)
    
    def _is_valid_keyword(self, keyword: str) -> bool:
        """Check if a keyword is valid for extraction.
        
        Args:
            keyword: The keyword to validate
        
        Returns:
            True if the keyword should be included, False otherwise
        """
        if not keyword or not isinstance(keyword, str):
            return False
        
        # Check length constraints
        if len(keyword) < self.min_keyword_length or len(keyword) > self.max_keyword_length:
            return False
        
        # Filter out common programming terms
        if keyword.lower() in COMMON_PROGRAMMING_TERMS:
            return False
        
        # Filter out pure numbers
        if keyword.isdigit():
            return False
        
        # Filter out single characters
        if len(keyword) == 1:
            return False
        
        return True
    
    def _tokenize_text(self, text: str) -> List[str]:
        """Tokenize text into potential keywords.
        
        Uses simple word boundary splitting and filters out common terms.
        
        Args:
            text: Text to tokenize
        
        Returns:
            List of token strings
        """
        # Split on word boundaries, keeping alphanumeric and underscores
        tokens = re.findall(r'\b[a-zA-Z_][a-zA-Z0-9_]*\b', text)
        
        # Filter and return valid tokens
        return [token for token in tokens if self._is_valid_keyword(token)]
