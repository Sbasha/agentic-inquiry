"""AlloyDB connection manager using ADC and AlloyDB Auth Proxy.

This module provides a connection manager for GCP AlloyDB PostgreSQL instances.
It extends the CloudSQLConnectionManager pattern but uses AlloyDB-specific
connection naming and ensures the google_ml_integration extension is available.

Connection naming format:
    projects/{project}/locations/{region}/clusters/{cluster}/instances/{instance}

Key differences from CloudSQL:
    - 4-part connection name (project/region/cluster/instance)
    - Requires google_ml_integration extension for server-side embeddings
    - Connects via AlloyDB Auth Proxy (alloydb-auth-proxy binary)
    - Uses standard asyncpg pool (proxy handles auth)

Example:
    >>> config = BackendConfig(
    ...     type="alloydb",
    ...     project="my-project",
    ...     region="us-central1",
    ...     cluster="my-cluster",
    ...     instance="primary",
    ...     database="agent-vault",
    ...     user="agv-user",
    ... )
    >>> manager = AlloyDBConnectionManager.from_config(config)
    >>> await manager.initialize()
    >>> async with manager.acquire() as conn:
    ...     await conn.execute("SELECT 1")
    >>> await manager.close()
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional
from urllib.parse import quote

if TYPE_CHECKING:
    import asyncpg

from agent_vault.storage.config import BackendConfig
from agent_vault.storage.providers.cloudsql.errors import (
    CloudSQLError,
    CloudSQLErrorCode,
)

logger = logging.getLogger(__name__)


class AlloyDBConnectionManager:
    """Manages AlloyDB PostgreSQL connections via AlloyDB Auth Proxy.

    This class connects to AlloyDB through the AlloyDB Auth Proxy running
    locally. The proxy handles IAM authentication and TLS termination.

    Unlike CloudSQLConnectionManager which uses the Cloud SQL Connector library,
    AlloyDB connections go through the auth proxy as a standard PostgreSQL
    connection on localhost.

    Attributes:
        table_prefix: Prefix for all table names (from config)
        is_initialized: Whether the connection pool is ready
        pool_size: Maximum number of connections in the pool
    """

    SUPPORTED_ROLES = frozenset({"vector", "graph", "events", "file_tracker"})

    # Default command_timeout for AlloyDB. 15 min covers
    # ``ai.initialize_embeddings`` on large tables (Vertex AI side can easily
    # exceed 5 min on first-time bulk initialization of 10k+ chunks). Was 300s
    # historically but surfaced as command timeouts on realistic first-run
    # bulk loads. Operators override via ``BackendConfig.command_timeout``;
    # don't change the default without coordinating with the analogous
    # default in ``PostgresConnectionManager.from_config``.
    DEFAULT_COMMAND_TIMEOUT = 900.0

    def __init__(self, config: BackendConfig) -> None:
        """Initialize AlloyDB connection manager.

        Args:
            config: Backend configuration with AlloyDB settings.
                Required: project, region, cluster, instance, database, user.
                Optional ``command_timeout`` on the config honours operator
                overrides; falls back to :attr:`DEFAULT_COMMAND_TIMEOUT`.
        """
        if config.type != "alloydb":
            raise ValueError(f"Expected alloydb backend type, got: {config.type}")

        self._config = config
        self.table_prefix = config.table_prefix or "agv_"
        self.pool_size = config.pool_size
        self.min_pool_size = config.min_pool_size
        self.max_overflow = config.max_overflow
        self.command_timeout = (
            config.command_timeout
            if config.command_timeout is not None
            else self.DEFAULT_COMMAND_TIMEOUT
        )

        self._pool: Optional["asyncpg.Pool"] = None
        self._initialized: bool = False
        self._lock = asyncio.Lock()

        # Stats
        self._query_count = 0
        self._error_count = 0
        self._last_error_time: Optional[float] = None
        self._consecutive_errors: int = 0
        self._init_time: Optional[float] = None

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "AlloyDBConnectionManager":
        """Create connection manager from configuration dictionary.

        AlloyDB small instances share ``max_connections=25`` across the
        whole project; ``BackendConfig``'s generic ``pool_size=10``
        default eats ~40% of the budget and concurrent indexing workers
        exhaust it. We default to 5 here when the config dict doesn't
        explicitly set ``pool_size`` — operators on larger AlloyDB tiers
        can override upward. Kept in sync with the analogous default in
        ``PostgresConnectionManager.from_config`` so both pg-family
        dispatch paths produce the same effective settings for AlloyDB.

        ``command_timeout`` flows through ``BackendConfig.command_timeout``
        directly — no extract-before-validate dance needed now that the
        field is modelled. ``__init__`` falls back to
        :attr:`DEFAULT_COMMAND_TIMEOUT` when the caller didn't set it.
        """
        from agent_vault.storage.config import BackendConfig

        if "pool_size" not in config:
            config = {**config, "pool_size": 5}
        backend_config = BackendConfig(**config)
        return cls(backend_config)

    @property
    def is_initialized(self) -> bool:
        """Check if the connection pool is initialized."""
        return self._initialized and self._pool is not None

    @property
    def connection_name(self) -> str:
        """Get the AlloyDB instance connection name."""
        return (
            f"projects/{self._config.project}/locations/{self._config.region}"
            f"/clusters/{self._config.cluster}/instances/{self._config.instance}"
        )

    async def initialize(self) -> None:
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return
            

            try:
                import asyncpg
            except ImportError as e:
                raise ImportError(
                    "asyncpg is required for AlloyDB support. "
                    "Install with: pip install asyncpg"
                ) from e

            try:
                # 1. Resolve password
                password = self._config.password
                
                # Check for password from env if missing
                if not password:
                    import os
                    password = os.environ.get("ALLOYDB_PASSWORD") or os.environ.get("PGPASSWORD")

                async def _init_logic():
                    port = getattr(self._config, "port", 5432)
                    use_ssl = getattr(self._config, "ssl", True)

                    # asyncpg ssl parameter: False disables SSL negotiation
                    ssl_param = "require" if use_ssl else False

                    self._pool = await asyncpg.create_pool(
                        user=self._config.user,
                        password=password,
                        database=self._config.database,
                        host="127.0.0.1",
                        port=port,
                        min_size=self.min_pool_size,
                        max_size=self.pool_size + self.max_overflow,
                        command_timeout=self.command_timeout,
                        ssl=ssl_param,
                    )

                    # Test connectivity
                    if self._pool:
                        async with self._pool.acquire() as conn:
                            await asyncio.wait_for(
                                conn.fetchval("SELECT 1"), timeout=5.0
                            )

                    # Ensure required extensions
                    await self._ensure_extensions()

                    # Ensure required extensions
                    await self._ensure_extensions()

                    self._initialized = True
                    self._init_time = time.time()
                    logger.info(
                        "AlloyDB pool initialized: %s, min=%d, max=%d",
                        self.connection_name,
                        self.min_pool_size,
                        self.pool_size + self.max_overflow,
                    )

                await asyncio.wait_for(_init_logic(), timeout=30.0)

            except asyncio.TimeoutError as e:
                error = CloudSQLError(
                    CloudSQLErrorCode.STARTUP_FAILED,
                    "AlloyDB initialization timed out after 30 seconds. "
                    "Ensure alloydb-auth-proxy is running.",
                )
                logger.error("AlloyDB startup timeout: %s", error.error_id)
                raise error from e
            except CloudSQLError:
                raise
            except Exception as e:
                error = CloudSQLError(CloudSQLErrorCode.STARTUP_FAILED, str(e))
                logger.error("AlloyDB startup failed: %s", error.error_id)
                raise error from e

    async def _ensure_extensions(self) -> None:
        """Ensure required PostgreSQL extensions are installed."""
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            # pgvector for vector storage
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            # google_ml_integration for server-side embeddings
            await conn.execute("CREATE EXTENSION IF NOT EXISTS google_ml_integration")
            logger.info("AlloyDB extensions verified: vector, google_ml_integration")

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool is not None:
            try:
                await self._pool.close()
                logger.info("AlloyDB pool closed")
            except Exception as e:
                logger.warning("Error closing AlloyDB pool: %s", e)
            finally:
                self._pool = None
        self._initialized = False

    @asynccontextmanager
    async def acquire(self, timeout: float = 10.0) -> AsyncIterator["asyncpg.Connection"]:
        """Acquire a connection from the pool."""
        if not self.is_initialized:
            raise CloudSQLError(CloudSQLErrorCode.STARTUP_FAILED)

        assert self._pool is not None

        try:
            async with self._pool.acquire(timeout=timeout) as conn:
                yield conn
        except asyncio.TimeoutError:
            self._error_count += 1
            self._last_error_time = time.time()
            self._consecutive_errors += 1
            raise CloudSQLError(
                CloudSQLErrorCode.CONNECTION_FAILED,
                f"Pool acquire timeout after {timeout}s",
            )
        except CloudSQLError:
            self._error_count += 1
            self._consecutive_errors += 1
            raise
        except Exception as e:
            self._error_count += 1
            self._last_error_time = time.time()
            self._consecutive_errors += 1
            raise CloudSQLError(CloudSQLErrorCode.CONNECTION_FAILED, str(e)) from e

    async def execute(self, query: str, *args: Any, timeout: Optional[float] = None) -> str:
        """Execute a query and return the status."""
        self._query_count += 1
        async with self.acquire() as conn:
            try:
                result = await conn.execute(query, *args, timeout=timeout)
                self._consecutive_errors = 0
                return result
            except Exception as e:
                self._error_count += 1
                self._consecutive_errors += 1
                raise CloudSQLError(CloudSQLErrorCode.QUERY_FAILED, str(e)) from e

    async def fetch(self, query: str, *args: Any, timeout: Optional[float] = None) -> list:
        """Execute a query and return all rows."""
        self._query_count += 1
        async with self.acquire() as conn:
            try:
                result = await conn.fetch(query, *args, timeout=timeout)
                self._consecutive_errors = 0
                return result
            except Exception as e:
                self._error_count += 1
                self._consecutive_errors += 1
                raise CloudSQLError(CloudSQLErrorCode.QUERY_FAILED, str(e)) from e

    async def fetchrow(self, query: str, *args: Any, timeout: Optional[float] = None) -> Optional[Any]:
        """Execute a query and return the first row."""
        self._query_count += 1
        async with self.acquire() as conn:
            try:
                result = await conn.fetchrow(query, *args, timeout=timeout)
                self._consecutive_errors = 0
                return result
            except Exception as e:
                self._error_count += 1
                self._consecutive_errors += 1
                raise CloudSQLError(CloudSQLErrorCode.QUERY_FAILED, str(e)) from e

    async def fetchval(self, query: str, *args: Any, column: int = 0, timeout: Optional[float] = None) -> Any:
        """Execute a query and return a single value."""
        self._query_count += 1
        async with self.acquire() as conn:
            try:
                result = await conn.fetchval(query, *args, column=column, timeout=timeout)
                self._consecutive_errors = 0
                return result
            except Exception as e:
                self._error_count += 1
                self._consecutive_errors += 1
                raise CloudSQLError(CloudSQLErrorCode.QUERY_FAILED, str(e)) from e

    async def executemany(self, query: str, args: list, *, timeout: Optional[float] = None) -> None:
        """Execute a query with multiple parameter sets."""
        self._query_count += len(args)
        async with self.acquire() as conn:
            try:
                await conn.executemany(query, args, timeout=timeout)
                self._consecutive_errors = 0
            except Exception as e:
                self._error_count += 1
                self._consecutive_errors += 1
                raise CloudSQLError(CloudSQLErrorCode.QUERY_FAILED, str(e)) from e

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["asyncpg.Connection"]:
        """Start a transaction."""
        async with self.acquire() as conn:
            async with conn.transaction():
                yield conn

    async def ensure_extension(self, extension: str) -> None:
        """Ensure a PostgreSQL extension is installed."""
        await self.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")
        logger.info("Ensured extension: %s", extension)

    async def check_extension(self, extension: str) -> bool:
        """Check if a PostgreSQL extension is installed."""
        result = await self.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = $1)",
            extension,
        )
        return bool(result)

    def get_table_name(self, base_name: str, role: str) -> str:
        """Get prefixed table name for a role."""
        role_prefixes = {
            "vector": "v_",
            "graph": "g_",
            "events": "e_",
            "file_tracker": "f_",
        }
        role_prefix = role_prefixes.get(role, "")
        return f"{self.table_prefix}{role_prefix}{base_name}"

    async def health_check(self) -> dict[str, Any]:
        """Check connection pool health."""
        if not self._initialized or self._pool is None:
            return {"healthy": False, "query_count": self._query_count, "error_count": self._error_count}

        try:
            result = await self.fetchval("SELECT 1")
            uptime = time.time() - self._init_time if self._init_time else 0.0
            return {
                "healthy": result == 1,
                "query_count": self._query_count,
                "error_count": self._error_count,
                "consecutive_errors": self._consecutive_errors,
                "uptime_seconds": uptime,
                "pool_size_current": self._pool.get_size(),
                "pool_connections_idle": self._pool.get_idle_size(),
            }
        except Exception:
            self._error_count += 1
            self._consecutive_errors += 1
            return {"healthy": False, "query_count": self._query_count, "error_count": self._error_count}

    async def __aenter__(self) -> "AlloyDBConnectionManager":
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    def __repr__(self) -> str:
        return (
            f"AlloyDBConnectionManager("
            f"connection={self.connection_name}, "
            f"database={self._config.database}, "
            f"prefix={self.table_prefix!r}, "
            f"initialized={self._initialized})"
        )
