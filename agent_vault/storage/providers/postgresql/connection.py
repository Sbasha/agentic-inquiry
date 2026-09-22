"""PostgreSQL connection manager using asyncpg.

This module provides centralized connection pool management for PostgreSQL
providers. It integrates with the BackendPoolManager for singleton pools.

Design decisions:
    - asyncpg-only: Uses native async/await throughout
    - Sync wrappers: Provides asyncio.run() wrappers for sync contexts (watchdog)
    - Pool integration: Works with BackendPoolManager for centralized pooling
    - Schema isolation: Supports table prefixes for multi-tenant deployments

Example:
    >>> manager = PostgresConnectionManager(
    ...     connection_string="postgresql://user:pass@localhost/db",
    ...     table_prefix="myproject_"
    ... )
    >>> await manager.initialize()
    >>> async with manager.acquire() as conn:
    ...     await conn.execute("SELECT 1")
    >>> await manager.close()
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict, Optional

from agent_vault.storage.similarity import DEFAULT_SIMILARITY_METRIC

if TYPE_CHECKING:
    import asyncpg

logger = logging.getLogger(__name__)

# Connection mode tracking for Python 3.13+ compatibility (FR-4.4)
_CONNECTOR_AVAILABLE: Optional[bool] = None


class PostgresConnectionError(Exception):
    """Raised when PostgreSQL connection operations fail."""

    pass


class PoolExhaustedError(PostgresConnectionError):
    """Raised when connection pool is exhausted and no connections are available."""

    pass


class PostgresConnectionManager:
    """Manages PostgreSQL connections via asyncpg connection pool.

    This class provides a centralized connection manager that can be shared
    across multiple PostgreSQL providers. It handles pool creation, health
    checks, and graceful shutdown.

    Attributes:
        connection_string: PostgreSQL connection URI
        table_prefix: Prefix for all table names (schema isolation)
        pool_size: Maximum number of connections in the pool
        min_pool_size: Minimum connections to maintain
        _pool: asyncpg connection pool instance
        _initialized: Whether the pool has been created

    Thread Safety:
        This class is async-safe. Multiple coroutines can safely acquire
        connections from the pool. For sync contexts (e.g., watchdog callbacks),
        use the *_sync methods which wrap async calls with asyncio.run().

    Example:
        >>> manager = PostgresConnectionManager(
        ...     connection_string="postgresql://localhost/db",
        ...     pool_size=10
        ... )
        >>> await manager.initialize()
        >>> result = await manager.execute("SELECT version()")
        >>> print(result)
        >>> await manager.close()
    """

    SUPPORTED_ROLES = frozenset({"vector", "graph", "events", "file_tracker"})

    # Transaction support configuration
    DEFAULT_ACQUISITION_TIMEOUT = 5.0  # seconds
    DEFAULT_STATEMENT_TIMEOUT = 30000  # milliseconds (30s)
    POOL_CLOSE_TIMEOUT_SECONDS = 5.0

    def __init__(
        self,
        connection_string: str,
        *,
        table_prefix: str = "agv_",
        pool_size: int = 10,
        min_pool_size: int = 2,
        max_overflow: int = 5,
        command_timeout: float = 60.0,
        similarity_metric: str = DEFAULT_SIMILARITY_METRIC,
    ) -> None:
        """Initialize connection manager.

        Args:
            connection_string: PostgreSQL connection URI
                Format: postgresql://user:pass@host:port/database
            table_prefix: Prefix for table names (default: "agv_")
            pool_size: Target pool size (default: 10)
            min_pool_size: Minimum connections to keep alive (default: 2)
            max_overflow: Additional connections beyond pool_size (default: 5)
            command_timeout: Default command timeout in seconds (default: 60)
            similarity_metric: Canonical similarity metric name for vector
                operations (default: "cosine"). Shared with sub-providers so
                index DDL and runtime distance operators stay consistent.
        """
        if not connection_string:
            raise ValueError("connection_string is required")

        # Validate pool size configuration (W-5 from code review)
        if min_pool_size > pool_size:
            raise ValueError(
                f"min_pool_size ({min_pool_size}) cannot exceed pool_size ({pool_size})"
            )
        if pool_size < 1:
            raise ValueError(f"pool_size must be at least 1, got {pool_size}")
        if min_pool_size < 0:
            raise ValueError(f"min_pool_size cannot be negative, got {min_pool_size}")

        self.connection_string = connection_string
        self.table_prefix = table_prefix
        self.pool_size = pool_size
        self.min_pool_size = min_pool_size
        self.max_overflow = max_overflow
        self.command_timeout = command_timeout
        self.similarity_metric = similarity_metric

        self._pool: Optional["asyncpg.Pool"] = None
        self._initialized: bool = False
        self._lock = asyncio.Lock()

        # Detect connection mode (FR-4.4, AC-8)
        self._connection_mode = self._detect_connection_mode()
        logger.info(f"Connection mode: {self._connection_mode}")

    def _detect_connection_mode(self) -> str:
        """Detect which connection mode to use.

        Implements FR-4.4: Python 3.13+ compatibility.

        Returns:
            "direct" for direct asyncpg, "connector" for Cloud SQL connector

        Note:
            Currently always returns "direct". Full Cloud SQL connector support
            (for Python <3.13) is planned for future enhancement. For Python 3.13+,
            direct asyncpg connections are the intended fallback (AC-8).
        """
        global _CONNECTOR_AVAILABLE

        # Cache connector availability check
        if _CONNECTOR_AVAILABLE is None:
            try:
                from google.cloud.sql.connector import Connector  # noqa: F401

                _CONNECTOR_AVAILABLE = True
                logger.debug("Cloud SQL connector available")
            except ImportError:
                _CONNECTOR_AVAILABLE = False
                logger.debug(
                    "Cloud SQL connector not available (Python 3.13+ or extras not installed)"
                )

        # For now, always use direct asyncpg
        # This satisfies AC-8: direct connection works when connector unavailable
        # Future enhancement: Use connector when available and configured via BackendConfig
        if _CONNECTOR_AVAILABLE:
            logger.info(
                "Cloud SQL connector available but direct asyncpg mode selected. "
                "To use connector, configure via BackendConfig (future enhancement)."
            )

        return "direct"

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        table_prefix: str = "agv_",
    ) -> "PostgresConnectionManager":
        """Create connection manager from configuration dict.

        Args:
            config: Configuration dictionary with connection settings
                Required: connection_string
                Optional: pool_size, min_pool_size, max_overflow, command_timeout
            table_prefix: Table name prefix for schema isolation

        Returns:
            Configured PostgresConnectionManager instance

        Example:
            >>> config = {
            ...     "connection_string": "postgresql://localhost/db",
            ...     "pool_size": 20
            ... }
            >>> manager = PostgresConnectionManager.from_config(config)
        """
        # AlloyDB small instances share ``max_connections=25`` across the
        # whole project; the generic 10 default eats ~40% of the budget and
        # concurrent indexing workers can exhaust it. Drop to 5 for AlloyDB
        # and let operators on larger tiers override upward — the other
        # pg-family dialects (postgresql/cloudsql/rds/azure) typically run
        # against instances with 100+ max_connections where 10 is fine.
        backend_type = config.get("type")
        default_pool_size = 5 if backend_type == "alloydb" else 10
        return cls(
            connection_string=config["connection_string"],
            table_prefix=table_prefix,
            pool_size=config.get("pool_size", default_pool_size),
            min_pool_size=config.get("min_pool_size", 2),
            max_overflow=config.get("max_overflow", 5),
            # Cloud-hosted + server-side-embedding backends need a long
            # command_timeout because bulk embedding paths are slow:
            #   - alloydb: ``ai.initialize_embeddings`` processes whole tables
            #     in one shot (minutes on large batches)
            #   - rds: Bedrock fallback is per-row (~25/sec)
            #   - azure: per-row ``azure_ai.generate_embeddings`` is similarly paced
            #   - cloudsql: shares the AlloyDB-adjacent tooling path
            # Self-hosted postgresql stays on 60s — operators running their own
            # pg can override if they wire in a slow helper function.
            command_timeout=config.get(
                "command_timeout",
                900.0
                if config.get("type") in ("alloydb", "cloudsql", "rds", "azure")
                else 60.0,
            ),
            similarity_metric=config.get(
                "similarity_metric", DEFAULT_SIMILARITY_METRIC
            ),
        )

    @classmethod
    def from_backend_config(
        cls,
        backend_config: Any,
    ) -> "PostgresConnectionManager":
        """Create connection manager from BackendConfig with full validation.

        This factory method performs full connection mode detection and SSL
        validation as specified in SEC-1 and FR-4.4.

        Args:
            backend_config: BackendConfig instance with connection settings
                Required: connection_string
                Optional: pool_size, max_overflow, table_prefix, ssl_mode, ssl_ca_cert

        Returns:
            Configured PostgresConnectionManager instance

        Raises:
            SSLRequiredError: If SSL not properly configured for direct connection
            ConfigurationError: If configuration has conflicting options

        Example:
            >>> from agent_vault.storage.config import BackendConfig
            >>> config = BackendConfig(
            ...     type="postgresql",
            ...     connection_string="postgresql://localhost/db",
            ...     ssl_mode="require"
            ... )
            >>> manager = PostgresConnectionManager.from_backend_config(config)
        """
        from agent_vault.storage.providers.postgresql.connection_mode import (
            detect_connection_mode,
            validate_config_consistency,
        )

        # Validate configuration consistency (AC-17)
        validate_config_consistency(backend_config)

        # Detect and validate connection mode (FR-4.4, SEC-1)
        mode = detect_connection_mode(backend_config)
        logger.info(f"Connection mode detected: {mode.value}")

        if not backend_config.connection_string:
            raise ValueError(
                "connection_string is required for PostgresConnectionManager. "
                "Connector mode is not yet supported."
            )

        return cls(
            connection_string=backend_config.connection_string,
            table_prefix=backend_config.table_prefix or "agv_",
            pool_size=backend_config.pool_size,
            max_overflow=backend_config.max_overflow,
            similarity_metric=getattr(
                backend_config, "similarity_metric", DEFAULT_SIMILARITY_METRIC
            ),
        )

    async def initialize(self) -> None:
        """Initialize the connection pool.

        Creates the asyncpg connection pool if not already initialized.
        This method is idempotent - multiple calls have no effect.

        Raises:
            PostgresConnectionError: If pool creation fails
        """
        if self._initialized:
            return

        async with self._lock:
            # Double-check after acquiring lock
            if self._initialized:
                return

            try:
                import asyncpg
            except ImportError as e:
                raise ImportError(
                    "asyncpg is required for PostgreSQL support. "
                    "Install with: pip install asyncpg"
                ) from e

            try:
                self._pool = await asyncpg.create_pool(
                    self.connection_string,
                    min_size=self.min_pool_size,
                    max_size=self.pool_size + self.max_overflow,
                    command_timeout=self.command_timeout,
                )

                self._initialized = True
                logger.info(
                    "PostgreSQL pool initialized: min=%d, max=%d",
                    self.min_pool_size,
                    self.pool_size + self.max_overflow,
                )
            except Exception as e:
                raise PostgresConnectionError(
                    f"Failed to create PostgreSQL pool: {e}"
                ) from e

    async def close(self) -> None:
        """Close the connection pool with a hard timeout.

        Attempts graceful close first. If connections do not release within
        POOL_CLOSE_TIMEOUT_SECONDS, terminates all connections forcibly.
        Safe to call multiple times.
        """
        if self._pool is None:
            return

        async with self._lock:
            if self._pool is None:
                return

            pool = self._pool
            self._pool = None
            self._initialized = False

            try:
                await asyncio.wait_for(
                    pool.close(), timeout=self.POOL_CLOSE_TIMEOUT_SECONDS
                )
                logger.info("PostgreSQL pool closed gracefully")
            except asyncio.TimeoutError:
                logger.warning(
                    "Pool close timed out after %.1fs, terminating connections",
                    self.POOL_CLOSE_TIMEOUT_SECONDS,
                )
                pool.terminate()
            except Exception as e:
                logger.warning("Error closing PostgreSQL pool: %s", e)
                try:
                    pool.terminate()
                except Exception:
                    logger.debug("Failed to terminate pool during close", exc_info=True)

    @property
    def is_initialized(self) -> bool:
        """Check if the connection pool is initialized."""
        return self._initialized and self._pool is not None

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator["asyncpg.Connection"]:
        """Acquire a connection from the pool.

        Usage:
            async with manager.acquire() as conn:
                await conn.execute("SELECT 1")

        Yields:
            asyncpg.Connection: Database connection

        Raises:
            PostgresConnectionError: If not initialized or acquisition fails
        """
        if not self._initialized or self._pool is None:
            raise PostgresConnectionError(
                "Connection manager not initialized. Call initialize() first."
            )

        max_retries = 3
        last_error: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                async with self._pool.acquire() as conn:
                    yield conn
                    return
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    wait = 0.5 * (2**attempt)  # 0.5s, 1s, 2s
                    logger.warning(
                        "Connection acquire failed (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1,
                        max_retries,
                        wait,
                        e,
                    )
                    await asyncio.sleep(wait)
        raise PostgresConnectionError(
            f"Failed to acquire connection after {max_retries} attempts: {last_error}"
        ) from last_error

    async def execute(
        self,
        query: str,
        *args: Any,
        timeout: Optional[float] = None,
    ) -> str:
        """Execute a query and return the status.

        Args:
            query: SQL query to execute
            *args: Query parameters
            timeout: Optional query timeout in seconds

        Returns:
            Query status string (e.g., "INSERT 0 1")

        Example:
            >>> await manager.execute(
            ...     "INSERT INTO users (name) VALUES ($1)",
            ...     "Alice"
            ... )
        """
        async with self.acquire() as conn:
            return await conn.execute(query, *args, timeout=timeout)

    async def fetch(
        self,
        query: str,
        *args: Any,
        timeout: Optional[float] = None,
    ) -> list:
        """Execute a query and return all rows.

        Args:
            query: SQL query to execute
            *args: Query parameters
            timeout: Optional query timeout in seconds

        Returns:
            List of asyncpg.Record objects
        """
        async with self.acquire() as conn:
            return await conn.fetch(query, *args, timeout=timeout)

    async def fetchrow(
        self,
        query: str,
        *args: Any,
        timeout: Optional[float] = None,
    ) -> Optional[Any]:
        """Execute a query and return the first row.

        Args:
            query: SQL query to execute
            *args: Query parameters
            timeout: Optional query timeout in seconds

        Returns:
            First row as asyncpg.Record, or None if no rows
        """
        async with self.acquire() as conn:
            return await conn.fetchrow(query, *args, timeout=timeout)

    async def fetchval(
        self,
        query: str,
        *args: Any,
        column: int = 0,
        timeout: Optional[float] = None,
    ) -> Any:
        """Execute a query and return a single value.

        Args:
            query: SQL query to execute
            *args: Query parameters
            column: Column index to return (default: 0)
            timeout: Optional query timeout in seconds

        Returns:
            Value from the specified column of the first row
        """
        async with self.acquire() as conn:
            return await conn.fetchval(query, *args, column=column, timeout=timeout)

    async def executemany(
        self,
        query: str,
        args: list,
        *,
        timeout: Optional[float] = None,
    ) -> None:
        """Execute a query with multiple parameter sets.

        Args:
            query: SQL query to execute
            args: List of parameter tuples
            timeout: Optional query timeout in seconds
        """
        async with self.acquire() as conn:
            await conn.executemany(query, args, timeout=timeout)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["asyncpg.Connection"]:
        """Start a transaction.

        Usage:
            async with manager.transaction() as conn:
                await conn.execute("INSERT INTO ...")
                await conn.execute("UPDATE ...")
                # Auto-commits on exit, rolls back on exception

        Yields:
            asyncpg.Connection: Connection with active transaction
        """
        async with self.acquire() as conn:
            async with conn.transaction():
                yield conn

    async def acquire_for_transaction(
        self, timeout: Optional[float] = None
    ) -> "asyncpg.Connection":
        """Acquire a dedicated connection for transaction coordination.

        Unlike acquire(), this returns a connection that the caller
        is responsible for releasing via release_transaction_connection().
        Used by TransactionCoordinator to maintain a single connection
        across multiple operations.

        Args:
            timeout: Acquisition timeout in seconds (default: 5.0)

        Returns:
            asyncpg.Connection: Dedicated connection for transaction

        Raises:
            PostgresConnectionError: If not initialized
            PoolExhaustedError: If no connection available within timeout

        Example:
            >>> conn = await manager.acquire_for_transaction()
            >>> try:
            ...     await conn.execute("BEGIN")
            ...     await conn.execute("INSERT ...")
            ...     await conn.execute("COMMIT")
            ... finally:
            ...     await manager.release_transaction_connection(conn)
        """
        if not self._initialized or self._pool is None:
            raise PostgresConnectionError(
                "Connection manager not initialized. Call initialize() first."
            )

        timeout = timeout or self.DEFAULT_ACQUISITION_TIMEOUT

        try:
            conn = await asyncio.wait_for(self._pool.acquire(), timeout=timeout)
            # Set statement timeout for deadlock detection
            await conn.execute(
                f"SET statement_timeout = {self.DEFAULT_STATEMENT_TIMEOUT}"
            )
            return conn
        except asyncio.TimeoutError:
            pool_status = self.get_pool_status()
            raise PoolExhaustedError(
                f"Connection pool exhausted. "
                f"Active: {pool_status['active']}/{pool_status['max_size']}. "
                f"Consider increasing pool_size or reducing concurrent transactions."
            )

    async def release_transaction_connection(self, conn: "asyncpg.Connection") -> None:
        """Release a connection acquired via acquire_for_transaction().

        Args:
            conn: Connection to release

        Example:
            >>> conn = await manager.acquire_for_transaction()
            >>> try:
            ...     # Use connection
            ...     pass
            ... finally:
            ...     await manager.release_transaction_connection(conn)
        """
        if self._pool is None:
            logger.warning("Cannot release connection: pool is None")
            return

        # Reset statement timeout to default
        try:
            await conn.execute("RESET statement_timeout")
        except Exception as e:
            logger.warning("Error resetting statement_timeout: %s", e)
            # Connection may be in bad state, but still try to release

        try:
            await self._pool.release(conn)
        except Exception as e:
            logger.warning("Error releasing connection to pool: %s", e)

    def get_pool_status(self) -> Dict[str, int]:
        """Return current pool statistics.

        Returns:
            Dictionary with pool statistics:
            - size: Current number of connections in pool
            - idle: Number of idle connections
            - active: Number of active connections
            - max_size: Maximum pool size

        Example:
            >>> status = manager.get_pool_status()
            >>> print(f"Active: {status['active']}/{status['max_size']}")
        """
        if self._pool is None:
            return {
                "size": 0,
                "idle": 0,
                "active": 0,
                "max_size": 0,
            }

        return {
            "size": self._pool.get_size(),
            "idle": self._pool.get_idle_size(),
            "active": self._pool.get_size() - self._pool.get_idle_size(),
            "max_size": self._pool.get_max_size(),
        }

    async def health_check(self) -> Dict[str, Any]:
        """Check connection pool health.

        Returns:
            Dict with health status and pool statistics

        Example:
            >>> health = await manager.health_check()
            >>> print(health["healthy"])
            True
        """
        if not self._initialized or self._pool is None:
            return {
                "healthy": False,
                "error": "Connection pool not initialized",
            }

        try:
            # Simple connectivity test
            result = await self.fetchval("SELECT 1")
            pool_size = self._pool.get_size()
            idle_size = self._pool.get_idle_size()

            return {
                "healthy": result == 1,
                "pool_size": pool_size,
                "idle_connections": idle_size,
                "active_connections": pool_size - idle_size,
                "min_size": self._pool.get_min_size(),
                "max_size": self._pool.get_max_size(),
            }
        except Exception as e:
            return {
                "healthy": False,
                "error": str(e),
            }

    async def check_extension(self, extension: str) -> bool:
        """Check if a PostgreSQL extension is installed.

        Args:
            extension: Extension name (e.g., "vector")

        Returns:
            True if extension is available
        """
        result = await self.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = $1)",
            extension,
        )
        return bool(result)

    async def ensure_extension(self, extension: str) -> None:
        """Ensure a PostgreSQL extension is installed.

        Args:
            extension: Extension name to create

        Raises:
            PostgresConnectionError: If extension cannot be created
        """
        if not await self.check_extension(extension):
            try:
                await self.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")
                logger.info("Created PostgreSQL extension: %s", extension)
            except Exception as e:
                raise PostgresConnectionError(
                    f"Failed to create extension '{extension}': {e}. "
                    f"Ensure you have superuser privileges or the extension is available."
                ) from e

    def get_table_name(self, base_name: str, role: str) -> str:
        """Get prefixed table name for a role.

        Args:
            base_name: Base table name (e.g., "chunks")
            role: Storage role (e.g., "vector", "graph")

        Returns:
            Fully prefixed table name

        Example:
            >>> manager.get_table_name("chunks", "vector")
            "agv_v_chunks"
        """
        role_prefixes = {
            "vector": "v_",
            "graph": "g_",
            "events": "e_",
            "file_tracker": "f_",
        }
        role_prefix = role_prefixes.get(role, "")
        return f"{self.table_prefix}{role_prefix}{base_name}"

    # Sync wrappers for contexts without event loop (e.g., watchdog)

    def initialize_sync(self) -> None:
        """Synchronous wrapper for initialize().

        For use in contexts without an event loop (e.g., watchdog callbacks).
        """
        asyncio.run(self.initialize())

    def close_sync(self) -> None:
        """Synchronous wrapper for close()."""
        asyncio.run(self.close())

    def execute_sync(self, query: str, *args: Any) -> str:
        """Synchronous wrapper for execute()."""
        return asyncio.run(self.execute(query, *args))

    def fetch_sync(self, query: str, *args: Any) -> list:
        """Synchronous wrapper for fetch()."""
        return asyncio.run(self.fetch(query, *args))

    def fetchrow_sync(self, query: str, *args: Any) -> Optional[Any]:
        """Synchronous wrapper for fetchrow()."""
        return asyncio.run(self.fetchrow(query, *args))

    def fetchval_sync(self, query: str, *args: Any) -> Any:
        """Synchronous wrapper for fetchval()."""
        return asyncio.run(self.fetchval(query, *args))

    async def __aenter__(self) -> "PostgresConnectionManager":
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()

    def __repr__(self) -> str:
        """String representation."""
        # Mask password in connection string for security
        masked = self.connection_string
        if "@" in masked:
            parts = masked.split("@")
            if ":" in parts[0]:
                user_pass = parts[0].rsplit(":", 1)
                masked = f"{user_pass[0]}:****@{parts[1]}"

        return (
            f"PostgresConnectionManager("
            f"connection={masked}, "
            f"prefix={self.table_prefix!r}, "
            f"initialized={self._initialized})"
        )
