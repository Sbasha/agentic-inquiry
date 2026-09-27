"""Document processing utilities for the indexing pipeline.

This module provides helper methods for document processing that are used
by the IndexingPipeline and GraphBuilder components.

Note: The main chunk transformation logic has been moved to SchemaProcessor.
This module only contains utility methods that are still needed.
"""

import logging
import re
from typing import Any, Optional, Tuple

from agentic_inquiry.exceptions import StorageError

logger = logging.getLogger(__name__)

_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _camel_words(text: str) -> str:
    """Distinct words from camelCase and PascalCase identifiers, in first-seen order."""
    seen: dict = {}
    for identifier in _IDENTIFIER.findall(text):
        parts = _CAMEL_BOUNDARY.split(identifier)
        if len(parts) > 1:
            for part in parts:
                seen.setdefault(part.lower(), None)
    return " ".join(seen)


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

    def index_texts(self, chunk: Any, relative_path: str) -> Optional[Tuple[str, str]]:
        """Embedding text and full-text field for a chunk, or None when it has no text.

        Both start with a header: the project-relative path, then the chunk's
        scope (enclosing definitions) when it has one, so a chunk carries the
        context an isolated body lacks. The full-text field also lists the
        words inside camelCase identifiers, which the BM25 tokenizer does not
        split (it already splits snake_case on the underscore).
        """
        body = chunk.content or chunk.fts_text or " ".join(chunk.symbols or [])
        if not body.strip():
            return None
        scope = (chunk.metadata or {}).get("scope") or ""
        header = f"{relative_path}\n{scope}" if scope else relative_path
        embed = f"{header}\n{body}"
        fts = embed
        if (chunk.content_type or "").upper() == "CODE":
            words = _camel_words(body)
            if words:
                fts = f"{embed}\n{words}"
        return embed, fts

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
