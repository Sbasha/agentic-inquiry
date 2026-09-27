"""Embedder registry utilities."""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from agentic_inquiry.config import Config
from agentic_inquiry.embeddings.base import Embedder
from agentic_inquiry.exceptions import StorageError


class EmbeddingRegistry:
    """Manage embedder instances and metadata for Lance columns."""

    def __init__(
        self,
        default_embedder: Optional[Embedder] = None,
        *,
        default_ndims: Optional[int] = None,
        config: Optional[Config] = None,
    ) -> None:
        self._registry: Dict[Tuple[str, str], Embedder] = {}
        self._dimensions: Dict[Tuple[str, str], int] = {}
        self._default_embedder: Optional[Embedder] = None
        self._default_ndims: Optional[int] = None
        self._default_configured = False

        if config is None:
            config = Config.load()
        self.config = config

        if default_embedder is not None:
            self.configure_default_embedder(default_embedder, ndims=default_ndims)

    def configure_default_embedder(
        self, embedder: Embedder, *, ndims: Optional[int] = None
    ) -> None:
        """Configure the global default embedder once during application startup.

        If called multiple times, replaces the existing embedder with a warning.
        This is useful in test environments where fixtures may configure embedders.
        """
        import logging

        logger = logging.getLogger(__name__)

        if self._default_configured:
            logger.warning(
                "Default embedder has already been configured. Replacing with new embedder. "
                "This is expected in test environments but may indicate a configuration issue in production."
            )

        expected_ndims = ndims if ndims is not None else embedder.ndims()
        if expected_ndims <= 0:
            raise StorageError("Embedding dimensionality must be a positive integer.")

        self._default_embedder = embedder
        self._default_ndims = expected_ndims
        self._default_configured = True

    def has_default_embedder(self) -> bool:
        """Check if a default embedder is configured.

        Returns:
            True if a default embedder has been configured, False otherwise.
        """
        return self._default_configured

    def get_default_embedder(self) -> Embedder:
        """Get the configured default embedder.

        Returns:
            The configured default embedder instance.

        Raises:
            StorageError: If no default embedder has been configured.
        """
        if not self._default_configured or self._default_embedder is None:
            raise StorageError(
                "No default embedder configured. Call configure_default_embedder() first."
            )
        return self._default_embedder

    def register(
        self,
        table_name: str,
        column_name: str,
        embedder: Embedder,
        *,
        ndims: Optional[int] = None,
    ) -> None:
        """Register an embedder and optional dimensionality for a table/column pair."""

        expected_ndims = ndims if ndims is not None else embedder.ndims()
        if expected_ndims <= 0:
            raise StorageError("Embedding dimensionality must be a positive integer.")

        key = (table_name, column_name)
        self._registry[key] = embedder
        self._dimensions[key] = expected_ndims

    def get(self, table_name: str, column_name: str) -> Embedder:
        """Return the embedder configured for ``table_name.column_name``."""

        embedder, _ = self.get_configuration(table_name, column_name)
        return embedder

    def get_configuration(
        self, table_name: str, column_name: str
    ) -> Tuple[Embedder, int]:
        """Return the embedder and expected dimensionality for ``table_name.column_name``."""

        key = (table_name, column_name)
        embedder = self._registry.get(key)
        if embedder is not None:
            return embedder, self._dimensions[key]

        if self._default_embedder is None or self._default_ndims is None:
            raise StorageError(
                "No embedder configured for (%s, %s) and no default embedder has been provided. "
                "Configure a default embedder via EmbeddingRegistry.configure_default_embedder or "
                "register a dedicated embedder for this column."
                % (table_name, column_name)
            )

        return self._default_embedder, self._default_ndims

    def get_expected_dimensions(self, table_name: str, column_name: str) -> int:
        """Return the expected dimensionality for vectors stored in ``table_name.column_name``."""

        _, ndims = self.get_configuration(table_name, column_name)
        return ndims

    def reset(self) -> None:
        """Reset the registry to its initial state.

        This clears all registered embedders and resets the default embedder.
        Primarily used in test fixtures to ensure test isolation.
        """
        self._registry.clear()
        self._dimensions.clear()
        self._default_embedder = None
        self._default_ndims = None
        self._default_configured = False

    def configure_hybrid_embeddings(self, *, ndims: Optional[int] = None) -> None:
        """Configure hybrid embeddings for optimized performance.

        This registers lightweight embedders for tables where semantic similarity
        is not required, providing significant performance improvements:

        - graph_relationships: Uses HashingEmbedder (~1000x faster than ML models)
          Relationship types are simple strings ("imports", "calls", "defines")
          where deterministic hashing is sufficient.

        Args:
            ndims: Embedding dimensions to use. If not provided, uses the default
                   embedder's dimensions. Raises StorageError if neither is available.

        Raises:
            StorageError: If no dimensions can be determined (no ndims provided
                         and no default embedder configured).

        See Also:
            docs/design/hybrid-embedding-strategy.md for rationale and benchmarks.
        """
        import logging
        from agentic_inquiry.embeddings.hashing import HashingEmbedder

        logger = logging.getLogger(__name__)

        # Determine dimensions - don't guess with magic numbers to avoid mismatches
        effective_ndims = ndims
        if effective_ndims is None:
            if self._default_ndims is not None:
                effective_ndims = self._default_ndims
            else:
                raise StorageError(
                    "Cannot configure hybrid embeddings: No dimensions provided and "
                    "no default embedder configured yet. Either call configure_default_embedder() "
                    "first, or pass explicit 'ndims' parameter."
                )

        # Register HashingEmbedder for graph_relationships table
        # Relationship types are finite strings - hashing is sufficient and fast
        relationship_embedder = HashingEmbedder(ndims=effective_ndims)
        self.register(
            "graph_relationships",
            "vector",
            relationship_embedder,
            ndims=effective_ndims,
        )

        logger.info(
            "Hybrid embeddings configured: graph_relationships using HashingEmbedder (ndims=%d)",
            effective_ndims,
        )


# A global instance of the registry to be used throughout the application.
embedding_registry = EmbeddingRegistry()
