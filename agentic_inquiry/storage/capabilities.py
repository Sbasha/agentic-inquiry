"""Storage provider capabilities declaration.

Each storage provider declares its capabilities via the ProviderCapabilities
dataclass. Consumers query these capabilities instead of checking backend_type
strings, eliminating hardcoded conditionals throughout the codebase.

Design principle: "Providers declare, consumers query."

Example:
    >>> caps = storage.get_capabilities()
    >>> if caps.embedding_strategy == EmbeddingStrategy.SERVER_SIDE:
    ...     # Skip local embedding generation
    ...     pass
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class EmbeddingStrategy(Enum):
    """How embeddings are generated for this backend.

    LOCAL: Client generates embeddings via sentence-transformers (LanceDB).
    SERVER_SIDE: Database generates embeddings via built-in function (AlloyDB).
    """

    LOCAL = "local"
    SERVER_SIDE = "server_side"


@dataclass(frozen=True)
class ProviderCapabilities:
    """Declares what a storage provider can do.

    This is the single source of truth for provider behavior. All consumer
    code should query capabilities instead of checking backend_type strings.

    Attributes:
        embedding_strategy: How embeddings are generated (local vs server-side)
        embedding_model: Server-side model name (e.g. "text-embedding-005")
        embedding_dimensions: Vector dimensionality
        requires_proxy: Whether a proxy binary is needed for connections
        proxy_type: Proxy binary name ("cloud-sql-proxy" or "alloydb-auth-proxy")
        proxy_port: Default proxy listen port
        is_postgresql_compatible: Whether this backend speaks PostgreSQL wire protocol
        supports_fts: Whether full-text search is available
        supports_graph: Whether graph storage is available
        backend_type: The raw backend type string (for logging/display only)
    """

    embedding_strategy: EmbeddingStrategy
    embedding_dimensions: int = 384
    embedding_model: Optional[str] = None
    requires_proxy: bool = False
    proxy_type: Optional[str] = None
    proxy_port: int = 5432
    is_postgresql_compatible: bool = False
    supports_fts: bool = True
    supports_graph: bool = True
    backend_type: str = "unknown"

    @property
    def uses_local_embedding(self) -> bool:
        """Whether this backend requires local embedding generation."""
        return self.embedding_strategy == EmbeddingStrategy.LOCAL

    @property
    def uses_server_side_embedding(self) -> bool:
        """Whether this backend generates embeddings server-side."""
        return self.embedding_strategy == EmbeddingStrategy.SERVER_SIDE

    @property
    def needs_embedding_polling(self) -> bool:
        """Whether post-indexing embedding generation polling is required.

        Returns True when the backend uses server-side embeddings and the
        pipeline must call generate_embeddings() after inserting chunks
        with NULL embedding columns.
        """
        return self.embedding_strategy == EmbeddingStrategy.SERVER_SIDE


# Pre-built capability profiles for each backend type
LANCEDB_CAPABILITIES = ProviderCapabilities(
    embedding_strategy=EmbeddingStrategy.LOCAL,
    embedding_dimensions=384,
    embedding_model=None,
    requires_proxy=False,
    is_postgresql_compatible=False,
    supports_fts=True,
    supports_graph=True,
    backend_type="lancedb",
)







def get_capabilities_for_backend(backend_type: str) -> ProviderCapabilities:
    """Get default capabilities for a backend type string.

    This returns the default capabilities. Providers may override these
    at construction time based on their configuration (e.g., a PostgreSQL
    provider configured with embedding_strategy=server_side).

    Args:
        backend_type: Backend type string from config

    Returns:
        ProviderCapabilities for that backend type.
        Falls back to LANCEDB_CAPABILITIES for unknown types.
    """
    registry = {
        "lancedb": LANCEDB_CAPABILITIES,
        "sqlite": LANCEDB_CAPABILITIES,
        "memory": LANCEDB_CAPABILITIES,
    }
    return registry.get(backend_type, LANCEDB_CAPABILITIES)
