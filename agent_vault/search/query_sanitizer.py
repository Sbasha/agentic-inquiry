"""Query sanitization for full-text search."""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


class QuerySanitizer:
    """Sanitizes search queries for FTS to prevent syntax errors.
    
    This class handles escaping of special characters that could cause
    FTS query parsing errors, particularly question marks and other
    regex/wildcard characters.
    
    Example:
        >>> sanitizer = QuerySanitizer()
        >>> sanitizer.sanitize("What is this?")
        'What is this\\?'
        >>> sanitizer.sanitize("file*.py")
        'file\\*.py'
    """
    
    # Special characters that need escaping in FTS queries
    SPECIAL_CHARS = ['?', '*', '[', ']', '(', ')', '{', '}', '\\', '+', '.', '^', '$', '|']
    
    def __init__(self, preserve_wildcards: bool = False):
        """Initialize QuerySanitizer.
        
        Args:
            preserve_wildcards: If True, preserve * and ? as wildcards.
                               If False, escape them for literal matching.
        """
        self.preserve_wildcards = preserve_wildcards
        
        # Build escape pattern for regex
        # Escape backslash first to avoid double-escaping
        chars_to_escape = self.SPECIAL_CHARS.copy()
        if preserve_wildcards:
            # Remove wildcards from escape list
            chars_to_escape = [c for c in chars_to_escape if c not in ['*', '?']]
        
        # Create regex pattern to match any special character
        # Need to escape special chars for regex itself
        escaped_chars = [re.escape(c) for c in chars_to_escape]
        self.escape_pattern = re.compile(f"[{''.join(escaped_chars)}]")
    
    def sanitize(self, query: str) -> str:
        """Escape special characters in query for safe FTS search.
        
        This method escapes characters that have special meaning in FTS
        queries to prevent syntax errors. The original semantic meaning
        of the query is preserved.
        
        Args:
            query: Raw query string from user
            
        Returns:
            Sanitized query safe for FTS, with special chars escaped
            
        Example:
            >>> sanitizer = QuerySanitizer()
            >>> sanitizer.sanitize("How does this work?")
            'How does this work\\?'
            >>> sanitizer.sanitize("test[123]")
            'test\\[123\\]'
        """
        if not query:
            return query
        
        # Log original query for debugging
        logger.debug("Sanitizing query: %s", query)
        
        # Escape special characters
        sanitized = self.escape_pattern.sub(lambda m: f"\\{m.group(0)}", query)

        # Escape tantivy boolean operators (AND, OR, NOT) when used as literal words
        # These must be lowercase to avoid being interpreted as operators
        sanitized = re.sub(r'\bAND\b', 'and', sanitized)
        sanitized = re.sub(r'\bOR\b', 'or', sanitized)
        sanitized = re.sub(r'\bNOT\b', 'not', sanitized)

        # Log sanitized query if it changed
        if sanitized != query:
            logger.debug("Sanitized query: %s", sanitized)
        
        return sanitized
    
    def preserve_wildcards_mode(self, query: str) -> str:
        """Sanitize query but preserve intentional wildcards.
        
        This method escapes special characters except * and ?, which
        are preserved as wildcards for pattern matching.
        
        Args:
            query: Raw query string potentially containing wildcards
            
        Returns:
            Sanitized query with wildcards preserved
            
        Example:
            >>> sanitizer = QuerySanitizer()
            >>> sanitizer.preserve_wildcards_mode("file*.py")
            'file*.py'
            >>> sanitizer.preserve_wildcards_mode("test[123]")
            'test\\[123\\]'
        """
        if not query:
            return query
        
        # Temporarily replace wildcards with placeholders
        query_with_placeholders = query.replace('*', '\x00STAR\x00')
        query_with_placeholders = query_with_placeholders.replace('?', '\x00QUESTION\x00')
        
        # Sanitize everything else
        sanitized = self.sanitize(query_with_placeholders)
        
        # Restore wildcards
        sanitized = sanitized.replace('\x00STAR\x00', '*')
        sanitized = sanitized.replace('\x00QUESTION\x00', '?')
        
        return sanitized
    
    def is_safe_query(self, query: str) -> bool:
        """Check if query contains special characters that need escaping.
        
        Args:
            query: Query string to check
            
        Returns:
            True if query is safe (no special chars), False otherwise
        """
        if not query:
            return True
        
        return self.escape_pattern.search(query) is None
    
    def get_sanitization_info(self, query: str) -> dict:
        """Get detailed information about query sanitization.
        
        Useful for debugging and understanding what changes were made.
        
        Args:
            query: Query to analyze
            
        Returns:
            Dictionary with sanitization details:
                - original: Original query
                - sanitized: Sanitized query
                - changed: Whether sanitization changed the query
                - special_chars_found: List of special characters found
                - is_safe: Whether query was already safe
        """
        if not query:
            return {
                "original": query,
                "sanitized": query,
                "changed": False,
                "special_chars_found": [],
                "is_safe": True,
            }
        
        # Find all special characters
        special_chars_found = []
        for char in self.SPECIAL_CHARS:
            if char in query:
                special_chars_found.append(char)
        
        sanitized = self.sanitize(query)
        
        return {
            "original": query,
            "sanitized": sanitized,
            "changed": sanitized != query,
            "special_chars_found": special_chars_found,
            "is_safe": not special_chars_found,
        }
