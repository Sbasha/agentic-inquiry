"""Backend lifecycle protocol for storage provider standardization.

This module defines the protocol that all storage backends should implement
for consistent lifecycle management. It establishes a standard pattern where
each backend owns its own setup/teardown, with agv core providing only context.

Protocols defined:
    - BackendLifecycle: Standard lifecycle interface for all storage backends

Design principles:
    - Inversion of responsibility: Backends create their own resources
    - Lazy initialization: Resources created on initialize(), not at config load
    - Idempotent operations: initialize() and close() safe to call multiple times
    - Capability-based: Check capabilities at runtime with isinstance()
    - Async-only: All I/O operations are async

Resource ownership model:
    agv Core Provides          Backend Creates
    ─────────────────          ───────────────
    • Base directory path  →   • Subdirectories
    • Configuration dict   →   • Connections/pools
    • Project ID           →   • Tables/schemas/indexes
                               • All teardown on close()

Implementations:
    - LanceDBConnectionManager: Local vector database lifecycle
    - PostgresConnectionManager: PostgreSQL connection pooling
    - SQLiteEventStorage: SQLite database lifecycle
    - MemoryVectorProvider: In-memory (no-op lifecycle)
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Dict,
    Protocol,
    TypeVar,
    runtime_checkable,
)

if TYPE_CHECKING:
    from typing import Type

T = TypeVar("T", bound="BackendLifecycle")


@runtime_checkable
class BackendLifecycle(Protocol):
    """Protocol for standard backend lifecycle management.

    This protocol defines the lifecycle interface that all storage backends
    should implement for consistent initialization, teardown, and health
    monitoring across different storage technologies.

    The lifecycle follows this pattern:
        1. from_config() - Create instance from configuration
        2. initialize() - Create resources (directories, connections, tables)
        3. [use the backend for operations]
        4. close() - Release all resources

    Class Attributes:
        SUPPORTED_ROLES: Set of storage roles this backend supports.
            Common roles: "vector", "graph", "events", "file_tracker"

    Implementations:
        - LanceDBConnectionManager: Vector/graph storage with local files
        - PostgresConnectionManager: PostgreSQL with connection pooling
        - SQLiteEventStorage: File-based event persistence
        - MemoryVectorProvider: In-memory storage (no persistence)

    Example:
        >>> # Create from configuration
        >>> config = {"uri": "/data/vectors", "embedding_dimension": 768}
        >>> provider = LanceDBVectorProvider.from_config(config, "my-project")
        >>>
        >>> # Initialize creates directories and tables
        >>> await provider.initialize()
        >>> assert provider.is_initialized
        >>>
        >>> # Use the provider...
        >>> await provider.add_chunks(chunks)
        >>>
        >>> # Health check
        >>> health = await provider.health_check()
        >>> assert health["status"] == "healthy"
        >>>
        >>> # Clean shutdown
        >>> await provider.close()
    """

    # =========================================================================
    # Class Attributes
    # =========================================================================

    SUPPORTED_ROLES: ClassVar[frozenset[str]]
    """Storage roles this backend supports.

    Used by the registry to determine which backends can fulfill which roles.
    Common roles:
        - "vector": Vector similarity search operations
        - "graph": Knowledge graph operations
        - "events": Event persistence operations
        - "file_tracker": File state tracking operations

    Example:
        >>> class MyVectorProvider:
        ...     SUPPORTED_ROLES: ClassVar[frozenset[str]] = frozenset({"vector"})
    """

    # =========================================================================
    # Factory Method
    # =========================================================================

    @classmethod
    def from_config(
        cls: "Type[T]",
        config: Dict[str, Any],
        project_id: str,
        **kwargs: Any,
    ) -> T:
        """Create a provider instance from configuration dictionary.

        Factory method that constructs a provider from a configuration dict.
        The provider is NOT initialized after construction - call initialize()
        to create resources.

        Args:
            config: Backend-specific configuration dictionary.
                Common keys: uri, embedding_dimension, connection_string
            project_id: Project identifier for resource namespacing
            **kwargs: Additional backend-specific arguments

        Returns:
            Uninitialized provider instance

        Raises:
            ValueError: If required configuration is missing or invalid
            TypeError: If configuration types are incorrect

        Example:
            >>> config = {
            ...     "uri": "postgresql://localhost/agv",
            ...     "pool_size": 10,
            ... }
            >>> provider = PostgresVectorProvider.from_config(config, "proj-1")
        """
        ...

    # =========================================================================
    # Lifecycle Operations
    # =========================================================================

    async def initialize(self) -> None:
        """Initialize the backend and create required resources.

        This method creates all resources needed by the backend:
            - Directories for file-based backends
            - Database connections and connection pools
            - Tables, schemas, and indexes
            - Any other backend-specific setup

        Must be called before any other operations. Implementations MUST be
        idempotent - calling initialize() multiple times is safe and should
        not create duplicate resources or fail.

        Resource creation is the backend's responsibility, not agv core.
        The backend receives context (base paths, config) but creates its
        own subdirectories, connections, and schemas.

        Raises:
            RuntimeError: If initialization fails
            ConnectionError: If database connection fails
            PermissionError: If directory creation fails

        Example:
            >>> provider = LanceDBProvider.from_config(config, project_id)
            >>> await provider.initialize()  # Creates directories and tables
            >>> await provider.initialize()  # Safe to call again (no-op)
        """
        ...

    async def close(self) -> None:
        """Close the backend and release all resources.

        Releases all resources acquired during initialize():
            - Closes database connections and drains connection pools
            - Releases file handles
            - Cleans up temporary resources

        Should be called during graceful shutdown. After close(), no other
        methods should be called except initialize() to restart.

        Implementations MUST be idempotent - calling close() multiple times
        is safe and should not raise errors.

        Note: close() does NOT delete persistent data (directories, databases).
        It only releases runtime resources (connections, handles).

        Raises:
            RuntimeError: If close fails (should be rare)

        Example:
            >>> try:
            ...     await provider.initialize()
            ...     # ... use provider ...
            ... finally:
            ...     await provider.close()  # Always clean up
        """
        ...

    async def health_check(self) -> Dict[str, Any]:
        """Check backend health and connectivity.

        Performs a lightweight health check to verify the backend is
        operational. Should complete quickly (< 1 second for healthy backends).

        Returns:
            Dictionary with health information:
                - status: "healthy", "degraded", or "unhealthy"
                - latency_ms: Response time in milliseconds
                - details: Optional dict with backend-specific info
                - error: Error message if unhealthy (optional)

        Example response:
            >>> health = await provider.health_check()
            >>> health
            {
                "status": "healthy",
                "latency_ms": 12.5,
                "details": {
                    "connection_pool_size": 10,
                    "active_connections": 2,
                    "tables_count": 4,
                }
            }

        Example:
            >>> health = await provider.health_check()
            >>> if health["status"] != "healthy":
            ...     logger.warning(f"Backend unhealthy: {health.get('error')}")
        """
        ...

    # =========================================================================
    # Status Properties
    # =========================================================================

    @property
    def is_initialized(self) -> bool:
        """Check if the backend is initialized and ready for operations.

        Returns True only after initialize() has been called successfully.
        Returns False before initialize() or after close().

        Returns:
            True if backend is ready for operations, False otherwise

        Example:
            >>> provider = LanceDBProvider.from_config(config, project_id)
            >>> provider.is_initialized
            False
            >>> await provider.initialize()
            >>> provider.is_initialized
            True
            >>> await provider.close()
            >>> provider.is_initialized
            False
        """
        ...


def has_lifecycle_support(provider: Any) -> bool:
    """Check if an object implements BackendLifecycle protocol.

    Uses runtime_checkable protocol for structural type checking.
    This allows duck-typed implementations to be recognized.

    Args:
        provider: Object to check for lifecycle support

    Returns:
        True if provider implements BackendLifecycle protocol

    Example:
        >>> if has_lifecycle_support(provider):
        ...     await provider.initialize()
        ...     try:
        ...         # ... use provider ...
        ...     finally:
        ...         await provider.close()
    """
    return isinstance(provider, BackendLifecycle)
