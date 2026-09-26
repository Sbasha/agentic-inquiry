"""Connection pool management for storage backends.

This module provides centralized connection pool management for backends
that support connection pooling (PostgreSQL, Spanner). For file-based
backends (SQLite, LanceDB), it returns path references.

Design principles:
    - Singleton pool per backend name: Avoid duplicate connections
    - Lazy initialization: Pools created on first access
    - Graceful shutdown: All pools closed on cleanup
    - Backend-specific pooling: Each backend type has appropriate pool config

Example:
    >>> pool_manager = BackendPoolManager()
    >>> pool = await pool_manager.get_or_create("primary", pg_config)
    >>> async with pool.acquire() as conn:
    ...     await conn.execute("SELECT 1")
    >>> await pool_manager.close_all()
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional, Set

if TYPE_CHECKING:
    from agentic_inquiry.storage.config import BackendConfig


logger = logging.getLogger(__name__)


class PoolError(Exception):
    """Base exception for pool-related errors."""

    pass


class PoolCreationError(PoolError):
    """Raised when pool creation fails."""

    def __init__(self, backend_name: str, backend_type: str, cause: Exception):
        self.backend_name = backend_name
        self.backend_type = backend_type
        self.cause = cause
        super().__init__(
            f"Failed to create pool for backend '{backend_name}' "
            f"(type={backend_type}): {cause}"
        )


class BackendPoolManager:
    """Manages connection pools for named storage backends.

    This class maintains a registry of connection pools keyed by backend name.
    It ensures only one pool exists per backend and handles proper cleanup.

    For PostgreSQL: Creates asyncpg connection pools
    For Spanner: Returns Spanner database client (handles internal pooling)
    For SQLite/LanceDB: Returns the database path (no pooling needed)
    For Memory: Returns None (no external resources)

    Thread Safety:
        This class is designed for async usage. Multiple coroutines can
        safely access pools through get_or_create().

    Attributes:
        _pools: Dict mapping backend name to pool object
        _initialized: Set of backend names that have been initialized
        _lock: Async lock for pool creation

    Example:
        >>> manager = BackendPoolManager()
        >>> pool = await manager.get_or_create("postgres_main", config)
        >>> print(manager.get_stats())
        >>> await manager.close_all()
    """

    def __init__(self) -> None:
        """Initialize the pool manager."""
        self._pools: Dict[str, Any] = {}
        self._initialized: Set[str] = set()
        self._lock = asyncio.Lock()

    async def get_or_create(
        self,
        backend_name: str,
        config: "BackendConfig",
    ) -> Any:
        """Get existing pool or create a new one.

        This method is idempotent - calling it multiple times with the same
        backend_name returns the same pool instance.

        Args:
            backend_name: Unique name for this backend instance
            config: BackendConfig with connection settings

        Returns:
            Pool object appropriate for the backend type:
            - str (path) for SQLite/LanceDB
            - None for memory

        Raises:
            PoolCreationError: If pool creation fails

        Example:
            >>> pool = await manager.get_or_create("primary", config)
        """
        # Fast path: return existing pool
        if backend_name in self._pools:
            logger.debug("Returning existing pool: %s", backend_name)
            return self._pools[backend_name]

        # Slow path: create new pool with lock
        async with self._lock:
            # Double-check after acquiring lock
            if backend_name in self._pools:
                return self._pools[backend_name]

            logger.info(
                "Creating pool for backend: %s (type=%s)", backend_name, config.type
            )
            pool = await self._create_pool(backend_name, config)
            self._pools[backend_name] = pool
            self._initialized.add(backend_name)
            return pool

    async def _create_pool(
        self,
        backend_name: str,
        config: "BackendConfig",
    ) -> Any:
        """Create a pool based on backend type.

        Args:
            backend_name: Name of the backend (for error messages)
            config: BackendConfig with connection settings

        Returns:
            Pool object or path reference

        Raises:
            PoolCreationError: If pool creation fails
        """
        try:
            if config.type in ("sqlite", "lancedb"):
                # File-based access; no pool is needed
                return config.database_path
            elif config.type == "memory":
                # Memory backend has no external resources
                return None
            else:
                raise ValueError(f"Unknown backend type: {config.type}")
        except Exception as e:
            raise PoolCreationError(backend_name, config.type, e) from e

    def get(self, backend_name: str) -> Optional[Any]:
        """Get existing pool without creating.

        Args:
            backend_name: Name of the backend

        Returns:
            Pool if exists, None otherwise
        """
        return self._pools.get(backend_name)

    def is_initialized(self, backend_name: str) -> bool:
        """Check if a backend pool has been initialized.

        Args:
            backend_name: Name of the backend

        Returns:
            True if pool exists
        """
        return backend_name in self._initialized

    async def close(self, backend_name: str) -> bool:
        """Close a specific backend pool.

        Args:
            backend_name: Name of the backend to close

        Returns:
            True if pool was closed, False if not found
        """
        if backend_name not in self._pools:
            return False

        pool = self._pools.pop(backend_name)
        self._initialized.discard(backend_name)

        if pool is not None and hasattr(pool, "close"):
            try:
                result = pool.close()
                if asyncio.iscoroutine(result):
                    await result
                logger.info("Closed pool: %s", backend_name)
            except Exception as e:
                logger.warning("Error closing pool %s: %s", backend_name, e)

        return True

    async def close_all(self) -> int:
        """Close all managed pools.

        Returns:
            Number of pools closed
        """
        count = 0
        backend_names = list(self._pools.keys())

        for name in backend_names:
            if await self.close(name):
                count += 1

        logger.info("Closed %d pools", count)
        return count

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about managed pools.

        Returns:
            Dict with pool information
        """
        stats: Dict[str, Any] = {
            "total_pools": len(self._pools),
            "initialized": list(self._initialized),
            "pools": {},
        }

        for name, pool in self._pools.items():
            pool_info: Dict[str, Any] = {"type": type(pool).__name__}

            # Get pool-specific stats if available
            if hasattr(pool, "get_size"):
                pool_info["size"] = pool.get_size()
            if hasattr(pool, "get_min_size"):
                pool_info["min_size"] = pool.get_min_size()
            if hasattr(pool, "get_max_size"):
                pool_info["max_size"] = pool.get_max_size()
            if hasattr(pool, "get_idle_size"):
                pool_info["idle_size"] = pool.get_idle_size()

            stats["pools"][name] = pool_info

        return stats

    def __len__(self) -> int:
        """Return number of managed pools."""
        return len(self._pools)

    def __contains__(self, backend_name: str) -> bool:
        """Check if backend has a pool."""
        return backend_name in self._pools

    async def __aenter__(self) -> "BackendPoolManager":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - close all pools."""
        await self.close_all()


# Global pool manager instance (optional singleton pattern)
_global_pool_manager: Optional[BackendPoolManager] = None


def get_pool_manager() -> BackendPoolManager:
    """Get the global pool manager instance.

    Creates the instance on first call (lazy initialization).

    Returns:
        Global BackendPoolManager instance

    Example:
        >>> manager = get_pool_manager()
        >>> pool = await manager.get_or_create("primary", config)
    """
    global _global_pool_manager
    if _global_pool_manager is None:
        _global_pool_manager = BackendPoolManager()
    return _global_pool_manager


async def cleanup_pools() -> int:
    """Cleanup the global pool manager.

    Call this during application shutdown.

    Returns:
        Number of pools closed
    """
    global _global_pool_manager
    if _global_pool_manager is not None:
        count = await _global_pool_manager.close_all()
        _global_pool_manager = None
        return count
    return 0
