"""NoOp embedder for server-side embedding paths (AlloyDB).

When AlloyDB handles embeddings server-side via the embedding() SQL function,
no local embedding model is needed. This embedder satisfies the Embedder
interface without loading any ML models.
"""

from __future__ import annotations

from typing import List

from agent_vault.embeddings.base import Embedder


class NoOpEmbedder(Embedder):
    """No-operation embedder for backends with server-side embedding generation.

    Returns zero vectors if called directly. The primary purpose is to prevent
    the system from loading heavy sentence-transformer models when AlloyDB
    handles embedding generation server-side.

    Example:
        >>> embedder = NoOpEmbedder(ndims=768)
        >>> embedder.ndims()
        768
        >>> embedder.generate(["hello"])  # Returns zero vectors
        [[0.0, 0.0, ...]]
    """

    def __init__(self, ndims: int = 768) -> None:
        """Initialize NoOp embedder.

        Args:
            ndims: Embedding dimensionality to report (default: 768 for text-embedding-005)
        """
        self._ndims = ndims

    def generate(self, texts: List[str]) -> List[List[float]]:
        """Return zero vectors. Should not be called in normal AlloyDB flow.

        This method exists for interface compatibility. In the AlloyDB path,
        embeddings are generated server-side and this method should never
        be called during normal operation.

        Args:
            texts: List of text strings

        Returns:
            List of zero vectors with correct dimensionality
        """
        return [[0.0] * self._ndims for _ in texts]

    def ndims(self) -> int:
        """Return the embedding dimensionality.

        Returns:
            768 by default (text-embedding-005 output dimension)
        """
        return self._ndims
