"""Document processing utilities for the indexing pipeline.

This module provides helper methods for document processing that are used
by the IndexingPipeline and GraphBuilder components.

Note: The main chunk transformation logic has been moved to SchemaProcessor.
This module only contains utility methods that are still needed.
"""

import logging
from typing import Any, Optional, Tuple

from agentic_inquiry.exceptions import StorageError

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """Provides utility methods for document processing.

    This is a lightweight helper class that provides methods for:
    - Resolving embedding text from parser chunks
    - Validating embedding vectors

    The main chunk transformation logic has been moved to SchemaProcessor.
    """

    def __init__(self, project_hash: str, project_id: str):
        """Initialize the document processor.

        Args:
            project_hash: Hash identifier for the project
            project_id: Human-readable project identifier
        """
        self.project_hash = project_hash
        self.project_id = project_id

    def _resolve_embedding_text(
        self,
        chunk: Any,
        embedder: Any,
    ) -> Tuple[Optional[str], bool]:
        """Resolve embedding text from a parser chunk.

        This method determines what text should be used for generating embeddings,
        with fallback logic if the preferred text is not available.

        Args:
            chunk: Parser chunk to extract text from
            embedder: Embedder instance (used to check for fallback hooks)

        Returns:
            Tuple of (embedding_text, used_fallback):
            - embedding_text: Text to use for embedding, or None if no text available
            - used_fallback: True if fallback logic was used
        """
        # Try fts_text first (preferred for search)
        if chunk.fts_text:
            return chunk.fts_text, False

        # Fall back to content
        if chunk.content:
            return chunk.content, False

        # Try embedder-specific fallback if available
        if hasattr(embedder, "get_fallback_text"):
            fallback_text = embedder.get_fallback_text(chunk)
            if fallback_text:
                return fallback_text, True

        # Last resort: use symbols if available
        if chunk.symbols:
            return " ".join(chunk.symbols), True

        # No text available
        return None, False

    def _validate_vector(
        self,
        table_name: str,
        column_name: str,
        vector: list,
        expected_dims: int,
    ) -> None:
        """Validate that a vector has the expected dimensions.

        Args:
            table_name: Name of the table (for error messages)
            column_name: Name of the column (for error messages)
            vector: Vector to validate
            expected_dims: Expected number of dimensions

        Raises:
            StorageError: If vector dimensions don't match expected
        """
        if len(vector) != expected_dims:
            raise StorageError(
                f"Vector dimension mismatch for {table_name}.{column_name}: "
                f"expected {expected_dims}, got {len(vector)}"
            )
