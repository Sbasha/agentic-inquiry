"""Query file loader for tree-sitter queries."""

import logging
from pathlib import Path
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class QueryLoader:
    """Loads tree-sitter query files for different languages."""

    def __init__(self, queries_dir: Optional[Path] = None):
        """Initialize the query loader.

        Args:
            queries_dir: Directory containing query files. If None, uses default location.
        """
        if queries_dir is None:
            # Default to queries directory next to this file
            self.queries_dir = Path(__file__).parent.parent / "queries"
        else:
            self.queries_dir = Path(queries_dir)

        self._query_cache: Dict[str, str] = {}
        logger.debug("QueryLoader initialized with directory: %s", self.queries_dir)

    def load_query(self, language: str) -> Optional[str]:
        """Load a tree-sitter query file for the specified language.

        Args:
            language: Programming language name (e.g., 'python', 'javascript')

        Returns:
            Query string or None if not found
        """
        # Check cache first
        if language in self._query_cache:
            return self._query_cache[language]

        # Try to load from file
        query_file = self.queries_dir / f"{language}.scm"

        if not query_file.exists():
            logger.debug("No query file found for language: %s", language)
            return None

        try:
            query_content = query_file.read_text(encoding="utf-8")
            self._query_cache[language] = query_content
            logger.debug("Loaded query file for language: %s", language)
            return query_content
        except Exception as e:
            logger.error("Failed to load query file for %s: %s", language, e)
            return None

    def has_query(self, language: str) -> bool:
        """Check if a query file exists for the specified language.

        Args:
            language: Programming language name

        Returns:
            True if query file exists, False otherwise
        """
        query_file = self.queries_dir / f"{language}.scm"
        return query_file.exists()

    def get_available_languages(self) -> list[str]:
        """Get list of languages with available query files.

        Returns:
            List of language names
        """
        if not self.queries_dir.exists():
            return []

        languages = []
        for query_file in self.queries_dir.glob("*.scm"):
            languages.append(query_file.stem)

        return sorted(languages)

    def clear_cache(self) -> None:
        """Clear the query cache."""
        self._query_cache.clear()


# Global query loader instance
_query_loader = QueryLoader()


def get_query_loader() -> QueryLoader:
    """Get the global query loader instance.

    Returns:
        Global QueryLoader instance
    """
    return _query_loader


def load_query(language: str) -> Optional[str]:
    """Convenience function to load a query for a language.

    Args:
        language: Programming language name

    Returns:
        Query string or None if not found
    """
    return _query_loader.load_query(language)
