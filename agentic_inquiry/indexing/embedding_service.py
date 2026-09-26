"""Embedding service component for the indexing pipeline.

This module handles embedding generation operations including batch processing,
error handling, and embedder configuration management.
"""

import logging
from typing import Any, List, Tuple

from agentic_inquiry.exceptions import StorageError

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Handles embedding generation and configuration.

    This component is responsible for:
    - Retrieving embedder configurations from the registry
    - Generating embeddings in batches with error handling
    - Falling back to individual generation on batch failures
    """

    def __init__(self, registry: Any):
        """Initialize the embedding service.

        Args:
            registry: EmbeddingRegistry instance for embedder configuration
        """
        self.registry = registry

    def get_embedder_configuration(self, table: str, column: str) -> Tuple[Any, int]:
        """Get embedder and dimensions for a table/column.

        Args:
            table: Table name (e.g., "document_chunks", "graph_entities")
            column: Column name (typically "vector")

        Returns:
            Tuple of (embedder instance, expected dimensions)
        """
        return self.registry.get_configuration(table, column)

    async def generate_embeddings_batch(
        self,
        texts: List[str],
        embedder: Any,
        operation_name: str = "embedding generation",
    ) -> List[List[float]]:
        """Generate embeddings for a batch of texts with error handling.

        This method wraps embedding generation with proper error handling
        for parallel operations. If batch generation fails, it falls back
        to individual generation.

        Args:
            texts: List of texts to embed
            embedder: Embedder instance to use
            operation_name: Name of the operation for logging

        Returns:
            List of embedding vectors

        Raises:
            StorageError: If embedding generation fails completely
        """
        if not texts:
            return []

        try:
            # Try batch generation first (most efficient)
            return embedder.generate(texts)
        except Exception as e:
            logger.warning(
                "Batch %s failed, falling back to individual generation: %s",
                exc_info=True,
            )

            # Fall back to individual generation
            vectors = []
            for i, text in enumerate(texts):
                try:
                    vector = embedder.generate([text])[0]
                    vectors.append(vector)
                except Exception as inner_e:
                    logger.error(
                        "Failed to generate embedding for text %s in %s: %s",
                        exc_info=True,
                    )
                    raise StorageError(
                        "Embedding generation failed for %s",
                        operation_name,
                        e,
                        i,
                        operation_name,
                        inner_e,
                        operation_name,
                    ) from inner_e

            return vectors
