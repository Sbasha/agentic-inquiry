"""LanceDB connection manager with lifecycle support.

This module provides centralized connection management for LanceDB providers.
It wraps the existing LanceDBManager and implements the BackendLifecycle protocol.

Key responsibility: Directory creation during initialize(), not at config load time.
This is part of the backend lifecycle standardization where each backend owns
its own resource setup/teardown.

Example:
    >>> manager = LanceDBConnectionManager(config, project_id="my-project")
    >>> await manager.initialize()  # Creates directories and tables
    >>> # ... use manager for operations ...
    >>> await manager.close()
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar, Dict, Optional

if TYPE_CHECKING:
    from agentic_inquiry.config import Config
    from agentic_inquiry.database.lancedb_manager import LanceDBManager

logger = logging.getLogger(__name__)


class LanceDBConnectionManager:
    """Manages LanceDB connections and implements BackendLifecycle protocol.

    This class provides centralized connection management that can be shared
    across LanceDB providers. It handles directory creation, connection setup,
    table initialization, and graceful shutdown.

    Key Design Decision:
        Directory creation is handled in initialize(), not at config load time.
        This follows the principle that backends own their own resource setup,
        with ai core providing only context (config, project_id).

    Attributes:
        config: Configuration instance providing paths and settings
        project_id: Project identifier for data isolation
        SUPPORTED_ROLES: Storage roles this backend supports

    Example:
        >>> manager = LanceDBConnectionManager(config, "my-project")
        >>> await manager.initialize()  # Creates directories if needed
        >>> assert manager.is_initialized
        >>> await manager.close()
    """

    SUPPORTED_ROLES: ClassVar[frozenset[str]] = frozenset({"vector", "graph"})

    def __init__(
        self,
        config: "Config",
        project_id: str,
        db_manager: Optional["LanceDBManager"] = None,
    ) -> None:
        """Initialize connection manager.

        Note: This does NOT create directories or connections.
        Call initialize() to create resources.

        Args:
            config: Configuration instance
            project_id: Project identifier
            db_manager: Optional pre-configured LanceDBManager (for testing)
        """
        self._config = config
        self._project_id = project_id
        self._db_manager = db_manager
        self._initialized = False

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        project_id: str,
        **kwargs: Any,
    ) -> "LanceDBConnectionManager":
        """Create connection manager from configuration dictionary.

        This factory method creates an uninitialized connection manager.
        Call initialize() to create directories and establish connections.

        Args:
            config: Configuration dictionary or Config instance
            project_id: Project identifier
            **kwargs: Additional arguments (ignored)

        Returns:
            Uninitialized LanceDBConnectionManager
        """
        # Handle both dict and Config objects
        if hasattr(config, "storage") and hasattr(config.storage, "get_lancedb_path"):
            # It's a Config instance with storage config
            return cls(config, project_id)  # type: ignore[arg-type]
        else:
            # It's a dict - would need to construct Config
            # For now, raise an error since we expect Config objects
            raise TypeError(
                "LanceDBConnectionManager.from_config expects a Config instance, "
                "not a dictionary. Use the constructor directly with a Config object."
            )

    def _ensure_directories(self) -> None:
        """Create required directories for LanceDB storage.

        This method is called during initialize() to create the LanceDB
        data directory if it doesn't exist. This is the key change from
        the previous architecture where directories were created in config.py.

        Note: Only creates directories for local file-based storage.
        Remote storage URIs (e.g., s3://) are handled by LanceDB itself.
        """
        lancedb_path = self._config.storage.get_lancedb_path()

        # Check if this is a local path (not a remote URI)
        path_str = str(lancedb_path)
        if "://" in path_str:
            logger.debug(
                "LanceDB using remote storage URI, skipping directory creation: %s",
                path_str,
            )
            return

        # Create directory for local storage
        if not lancedb_path.exists():
            logger.info("Creating LanceDB directory: %s", lancedb_path)
            lancedb_path.mkdir(parents=True, exist_ok=True)
        else:
            logger.debug("LanceDB directory already exists: %s", lancedb_path)

    async def initialize(self) -> None:
        """Initialize LanceDB connection and create required resources.

        This method:
        1. Creates storage directories (if local storage)
        2. Establishes database connection
        3. Creates tables and indexes

        Idempotent: Safe to call multiple times.

        Raises:
            RuntimeError: If initialization fails
            PermissionError: If directory creation fails
        """
        if self._initialized:
            logger.debug("LanceDB connection manager already initialized")
            return

        logger.info(
            "Initializing LanceDB connection manager for project %s", self._project_id
        )

        # Create directories first (key lifecycle change)
        self._ensure_directories()

        # Create or use existing db_manager
        if self._db_manager is None:
            from agentic_inquiry.database.lancedb_manager import LanceDBManager

            self._db_manager = LanceDBManager.from_config(
                self._config, project_id=self._project_id
            )

        # Connect and create tables
        await self._db_manager.connect()
        await self._db_manager.create_tables_and_indexes()

        self._initialized = True
        logger.info(
            "LanceDB connection manager initialized for project %s", self._project_id
        )

    async def close(self) -> None:
        """Close database connections and release resources.

        Idempotent: Safe to call multiple times.
        Does NOT delete data directories.
        """
        if not self._initialized:
            return

        logger.info(
            "Closing LanceDB connection manager for project %s", self._project_id
        )

        if self._db_manager is not None:
            await self._db_manager.close()

        self._initialized = False

    async def health_check(self) -> Dict[str, Any]:
        """Check connection health.

        Returns:
            Dict with health status:
                - status: "healthy", "degraded", or "unhealthy"
                - latency_ms: Response time in milliseconds
                - details: Backend-specific information
                - error: Error message if unhealthy
        """
        import time

        start = time.perf_counter()

        if not self._initialized or self._db_manager is None:
            return {
                "status": "unhealthy",
                "latency_ms": 0,
                "error": "Connection manager not initialized",
            }

        try:
            is_healthy = await self._db_manager.health_check()
            latency_ms = (time.perf_counter() - start) * 1000

            if is_healthy:
                return {
                    "status": "healthy",
                    "latency_ms": round(latency_ms, 2),
                    "details": {
                        "project_id": self._project_id,
                        "lancedb_path": str(self._config.storage.get_lancedb_path()),
                    },
                }
            else:
                return {
                    "status": "degraded",
                    "latency_ms": round(latency_ms, 2),
                    "error": "Health check returned False",
                }
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            return {
                "status": "unhealthy",
                "latency_ms": round(latency_ms, 2),
                "error": str(e),
            }

    @property
    def is_initialized(self) -> bool:
        """Check if the connection manager is initialized."""
        return self._initialized

    @property
    def db_manager(self) -> Optional["LanceDBManager"]:
        """Get the underlying LanceDBManager.

        Returns:
            LanceDBManager if initialized, None otherwise
        """
        return self._db_manager

    @property
    def project_id(self) -> str:
        """Get the project ID."""
        return self._project_id

    @property
    def config(self) -> "Config":
        """Get the configuration."""
        return self._config
