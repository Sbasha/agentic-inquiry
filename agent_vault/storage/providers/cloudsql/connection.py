"""Cloud SQL connection manager using ADC and Cloud SQL Connector.

This module provides a connection manager for GCP Cloud SQL PostgreSQL instances
that uses Application Default Credentials (ADC) for authentication and the
Cloud SQL Python Connector for connection management.

Authentication:
    Uses Application Default Credentials (ADC) which works for:
    - Local dev: `gcloud auth application-default login`
    - GKE/Cloud Run: Workload Identity (automatic)
    - CI/CD: GOOGLE_APPLICATION_CREDENTIALS env var

Token Refresh:
    Handled automatically by Cloud SQL Connector via pool recycling.
    Connections are recycled every 55 minutes (max_inactive_connection_lifetime=3300)
    to ensure fresh IAM tokens before the 60-minute expiration.

Startup:
    Fail-fast - validates connectivity with SELECT 1 within 5 seconds,
    total initialization timeout of 30 seconds. Raises CloudSQLError on failure.

Design decisions:
    - Duck-typing: Matches PostgresConnectionManager interface without formal Protocol
    - ADC-only: No custom credential resolution needed
    - Fail-fast: Exits on startup failure (application handles graceful shutdown)
    - Observability: Logs auth source and basic metrics
    - Error sanitization: Never exposes IPs, credentials, paths, or SQL in errors

Example:
    >>> config = BackendConfig(
    ...     type="cloudsql",
    ...     project="my-project",
    ...     region="us-central1",
    ...     instance="my-instance",
    ...     database="agent-vault",
    ...     user="agv-user@my-project.iam",
    ... )
    >>> manager = CloudSQLConnectionManager.from_config(config)
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

if TYPE_CHECKING:
    import asyncpg

from agent_vault.storage.config import BackendConfig
from agent_vault.storage.providers.cloudsql.errors import (
    CloudSQLError,
    CloudSQLErrorCode,
)

logger = logging.getLogger(__name__)


class CloudSQLConnectionManager:
    """Manages Cloud SQL PostgreSQL connections with IAM authentication.

    This class provides a connection manager compatible with PostgreSQL providers
    but uses GCP Cloud SQL Connector with ADC for authentication. It handles:
    - ADC authentication (works for dev, GKE, Cloud Run, CI)
    - Automatic IAM token refresh via connection recycling
    - Fail-fast startup validation
    - Error sanitization (never exposes sensitive data)

    Attributes:
        table_prefix: Prefix for all table names (from config)
        is_initialized: Whether the connection pool is ready
        pool_size: Maximum number of connections in the pool
        min_pool_size: Minimum connections to maintain

    Thread Safety:
        This class is async-safe. Multiple coroutines can safely acquire
        connections from the pool.

    Example:
        >>> manager = CloudSQLConnectionManager(config)
        >>> await manager.initialize()
        >>> result = await manager.fetchval("SELECT version()")
        >>> await manager.close()
    """

    SUPPORTED_ROLES = frozenset({"vector", "graph", "events", "file_tracker"})

    def __init__(self, config: BackendConfig) -> None:
        """Initialize Cloud SQL connection manager.

        Args:
            config: Backend configuration with Cloud SQL settings
                Required fields: project, region, instance, database, user
                Optional fields: pool_size, max_overflow, table_prefix
        """
        if config.type != "cloudsql":
            raise ValueError(f"Expected cloudsql backend type, got: {config.type}")

        self._config = config
        self.table_prefix = config.table_prefix or "agv_"
        self.pool_size = config.pool_size
        self.min_pool_size = 2  # Match PostgresConnectionManager default
        self.max_overflow = config.max_overflow
        self.command_timeout = 60.0  # Match PostgresConnectionManager default

        self._pool: Optional["asyncpg.Pool"] = None
        self._connector: Optional[Any] = None  # google.cloud.sql.connector.Connector
        self._initialized: bool = False
        self._lock = asyncio.Lock()
        self._auth_source: Optional[str] = None

        # Stats for observability (FR-6.7, FR-6.8a)
        self._query_count = 0
        self._error_count = 0
        self._last_error_time: Optional[float] = None
        self._consecutive_errors: int = 0

        # Business metrics for Cloud SQL adoption tracking (T5.4)
        self._init_time: Optional[float] = None
        self._connection_count: int = 0

    @classmethod
    def from_config(cls, config: BackendConfig) -> "CloudSQLConnectionManager":
        """Create connection manager from configuration.

        Args:
            config: Backend configuration with Cloud SQL settings

        Returns:
            Configured CloudSQLConnectionManager instance

        Example:
            >>> config = BackendConfig(
            ...     type="cloudsql",
            ...     project="my-project",
            ...     region="us-central1",
            ...     instance="my-instance",
            ...     database="agent-vault",
            ...     user="app-user",
            ... )
            >>> manager = CloudSQLConnectionManager.from_config(config)
        """
        return cls(config)

    @property
    def is_initialized(self) -> bool:
        """Check if the connection pool is initialized.

        Returns:
            True if pool is ready for use, False otherwise
        """
        return self._initialized and self._pool is not None

    async def initialize(self) -> None:
        """Initialize the connection pool with fail-fast connectivity check.

        This method:
        1. Acquires ADC credentials via google.auth.default()
        2. Detects and logs the authentication source (FR-5.9a)
        3. Creates a Cloud SQL Connector instance
        4. Creates an asyncpg connection pool with IAM auth
        5. Tests connectivity with SELECT 1 (5 second timeout)
        6. Total initialization timeout: 30 seconds

        All operations are idempotent - multiple calls have no effect.

        Raises:
            CloudSQLError(AUTH_FAILED): If ADC authentication fails (FR-5.6)
            CloudSQLError(STARTUP_FAILED): If connection or connectivity check fails (FR-5.6, FR-3.5)
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
                    "asyncpg is required for Cloud SQL support. "
                    "Install with: pip install asyncpg"
                ) from e

            try:
                import google.auth
                from google.cloud.sql.connector import Connector
            except ImportError as e:
                raise ImportError(
                    "google-cloud-sql-connector is required for Cloud SQL support. "
                    "Install with: pip install google-cloud-sql-connector[asyncpg]"
                ) from e

            # FR-3.5: Wrap entire initialization in 30 second timeout
            try:
                async def _init_logic() -> None:
                    # FR-2.1: Authenticate with ADC
                    try:
                        credentials, project = google.auth.default()
                    except google.auth.exceptions.DefaultCredentialsError as e:
                        # FR-5.6: Auth failure - log guidance and raise
                        logger.error(
                            "ADC not configured. Run: gcloud auth application-default login"
                        )
                        raise CloudSQLError(
                            CloudSQLErrorCode.AUTH_FAILED, str(e)
                        ) from e

                    # FR-5.9a: Detect and log auth source at INFO level
                    self._auth_source = self._detect_auth_source(credentials)
                    logger.info("Cloud SQL auth source: %s", self._auth_source)

                    # FR-2.2: Create Cloud SQL Connector
                    self._connector = Connector()

                    # FR-2.3: Create connection factory for asyncpg pool
                    instance_connection_name = f"{self._config.project}:{self._config.region}:{self._config.instance}"

                    async def getconn() -> "asyncpg.Connection":
                        """Connection factory for asyncpg pool with IAM auth."""
                        assert self._connector is not None
                        conn = await self._connector.connect_async(
                            instance_connection_name,
                            "asyncpg",
                            user=self._config.user,
                            db=self._config.database,
                            enable_iam_auth=True,
                        )
                        self._connection_count += 1  # Track connection establishment
                        return conn

                    # FR-2.4, FR-6.2a: Create connection pool with recycling
                    self._pool = await asyncpg.create_pool(
                        min_size=self.min_pool_size,
                        max_size=self.pool_size + self.max_overflow,
                        max_inactive_connection_lifetime=3300,  # FR-6.2a: Recycle before 1hr token expiry
                        command_timeout=self.command_timeout,
                        connect=getconn,
                    )

                    # FR-3.5: Test connectivity with SELECT 1 (5 second timeout)
                    # We can use acquire() here which already has logic but better to use pool directly
                    # to avoid circular dependency on initialized state check
                    if self._pool:
                        async with self._pool.acquire() as conn:
                            await asyncio.wait_for(
                                conn.fetchval("SELECT 1"), timeout=5.0
                            )

                    self._initialized = True
                    self._init_time = time.time()  # Track initialization time for uptime metrics
                    logger.info(
                        "Cloud SQL pool initialized: %s, min=%d, max=%d",
                        instance_connection_name,
                        self.min_pool_size,
                        self.pool_size + self.max_overflow,
                    )

                await asyncio.wait_for(_init_logic(), timeout=30.0)

            except asyncio.TimeoutError as e:
                # FR-5.6, FR-3.5: Startup timeout - raise CloudSQLError
                error = CloudSQLError(
                    CloudSQLErrorCode.STARTUP_FAILED,
                    "Initialization timed out after 30 seconds",
                )
                logger.error("Cloud SQL startup timeout: %s", error.error_id)
                raise error from e

            except CloudSQLError:
                # Already wrapped - re-raise as-is
                raise

            except Exception as e:
                # FR-5.6, FR-6.10a: Startup failure - raise for application to handle exit
                error = CloudSQLError(CloudSQLErrorCode.STARTUP_FAILED, str(e))
                logger.error("Cloud SQL startup failed: %s", error.error_id)
                raise error from e

    def _detect_auth_source(self, credentials: Any) -> str:
        """Detect and log authentication source for observability (FR-5.9a, FR-6.7).

        Args:
            credentials: Credentials object from google.auth.default()

        Returns:
            Human-readable auth source identifier:
            - "service_account": Service account JSON key
            - "workload_identity": GKE/Cloud Run workload identity
            - "user_adc": User credentials from gcloud auth
            - "unknown (CredentialType)": Unknown credential type
        """
        cred_type = type(credentials).__name__

        if "ServiceAccountCredentials" in cred_type:
            return "service_account"
        elif "Credentials" in cred_type and hasattr(
            credentials, "_service_account_email"
        ):
            return "workload_identity"
        elif "UserCredentials" in cred_type or "AuthorizedUserCredentials" in cred_type:
            return "user_adc"
        else:
            return f"unknown ({cred_type})"

    async def close(self) -> None:
        """Close the connection pool and connector.

        Gracefully closes all connections in the pool and the Cloud SQL connector.
        Safe to call multiple times.
        """
        if self._pool is not None:
            try:
                await self._pool.close()
                logger.info("Cloud SQL pool closed")
            except Exception as e:
                logger.warning("Error closing Cloud SQL pool: %s", e)
            finally:
                self._pool = None

        if self._connector is not None:
            try:
                await self._connector.close_async()
                logger.info("Cloud SQL connector closed")
            except Exception as e:
                logger.warning("Error closing Cloud SQL connector: %s", e)
            finally:
                self._connector = None

        self._initialized = False

    @asynccontextmanager
    async def acquire(self, timeout: float = 10.0) -> AsyncIterator["asyncpg.Connection"]:
        """Acquire a connection from the pool.

        Args:
            timeout: Maximum time to wait for connection acquisition in seconds (default: 10.0)

        Usage:
            async with manager.acquire() as conn:
                await conn.execute("SELECT 1")

        Yields:
            asyncpg.Connection: Database connection

        Raises:
            CloudSQLError(STARTUP_FAILED): If not initialized
            CloudSQLError(CONNECTION_FAILED): If acquisition fails or times out
        """
        if not self.is_initialized:
            raise CloudSQLError(CloudSQLErrorCode.STARTUP_FAILED)

        # Ensure pool is available for mypy
        assert self._pool is not None

        try:
            # Pass timeout directly to asyncpg
            async with self._pool.acquire(timeout=timeout) as conn:
                yield conn
        except asyncio.TimeoutError:
            self._error_count += 1
            self._last_error_time = time.time()
            self._consecutive_errors += 1
            raise CloudSQLError(
                CloudSQLErrorCode.CONNECTION_FAILED,
                f"Pool acquire timeout after {timeout}s"
            )
        except CloudSQLError:
            self._error_count += 1
            self._last_error_time = time.time()
            self._consecutive_errors += 1
            raise  # Already wrapped
        except Exception as e:
            self._error_count += 1
            self._last_error_time = time.time()
            self._consecutive_errors += 1
            # FR-6.5: Never expose internal details
            raise CloudSQLError(CloudSQLErrorCode.CONNECTION_FAILED, str(e)) from e

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

        Raises:
            CloudSQLError(QUERY_FAILED): If query execution fails

        Example:
            >>> await manager.execute(
            ...     "INSERT INTO users (name) VALUES ($1)",
            ...     "Alice"
            ... )
        """
        self._query_count += 1
        async with self.acquire() as conn:
            try:
                result = await conn.execute(query, *args, timeout=timeout)
                self._consecutive_errors = 0  # Reset on success
                return result
            except CloudSQLError:
                self._error_count += 1
                self._last_error_time = time.time()
                self._consecutive_errors += 1
                raise  # Already wrapped
            except Exception as e:
                self._error_count += 1
                self._last_error_time = time.time()
                self._consecutive_errors += 1
                # FR-6.5: Never expose SQL, internal paths, or credentials
                raise CloudSQLError(CloudSQLErrorCode.QUERY_FAILED, str(e)) from e

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

        Raises:
            CloudSQLError(QUERY_FAILED): If query execution fails
        """
        self._query_count += 1
        async with self.acquire() as conn:
            try:
                result = await conn.fetch(query, *args, timeout=timeout)
                self._consecutive_errors = 0  # Reset on success
                return result
            except CloudSQLError:
                self._error_count += 1
                self._last_error_time = time.time()
                self._consecutive_errors += 1
                raise  # Already wrapped
            except Exception as e:
                self._error_count += 1
                self._last_error_time = time.time()
                self._consecutive_errors += 1
                raise CloudSQLError(CloudSQLErrorCode.QUERY_FAILED, str(e)) from e

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

        Raises:
            CloudSQLError(QUERY_FAILED): If query execution fails
        """
        self._query_count += 1
        async with self.acquire() as conn:
            try:
                result = await conn.fetchrow(query, *args, timeout=timeout)
                self._consecutive_errors = 0  # Reset on success
                return result
            except CloudSQLError:
                self._error_count += 1
                self._last_error_time = time.time()
                self._consecutive_errors += 1
                raise  # Already wrapped
            except Exception as e:
                self._error_count += 1
                self._last_error_time = time.time()
                self._consecutive_errors += 1
                raise CloudSQLError(CloudSQLErrorCode.QUERY_FAILED, str(e)) from e

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

        Raises:
            CloudSQLError(QUERY_FAILED): If query execution fails
        """
        self._query_count += 1
        async with self.acquire() as conn:
            try:
                result = await conn.fetchval(query, *args, column=column, timeout=timeout)
                self._consecutive_errors = 0  # Reset on success
                return result
            except CloudSQLError:
                self._error_count += 1
                self._last_error_time = time.time()
                self._consecutive_errors += 1
                raise  # Already wrapped
            except Exception as e:
                self._error_count += 1
                self._last_error_time = time.time()
                self._consecutive_errors += 1
                raise CloudSQLError(CloudSQLErrorCode.QUERY_FAILED, str(e)) from e

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

        Raises:
            CloudSQLError(QUERY_FAILED): If query execution fails
        """
        self._query_count += len(args)
        async with self.acquire() as conn:
            try:
                await conn.executemany(query, args, timeout=timeout)
                self._consecutive_errors = 0  # Reset on success
            except CloudSQLError:
                self._error_count += 1
                self._last_error_time = time.time()
                self._consecutive_errors += 1
                raise  # Already wrapped
            except Exception as e:
                self._error_count += 1
                self._last_error_time = time.time()
                self._consecutive_errors += 1
                raise CloudSQLError(CloudSQLErrorCode.QUERY_FAILED, str(e)) from e

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

    async def health_check(self) -> dict[str, Any]:
        """Check connection pool health (FR-6.8a: consistent shape).

        Returns:
            Dict with health status and pool statistics:
            - healthy: bool indicating if pool is operational
            - auth_source: Authentication source (if initialized)
            - query_count: Total queries executed
            - error_count: Total errors encountered
            - last_error_time: Unix timestamp of last error, None if no errors
            - consecutive_errors: Count of consecutive errors, resets on success
            - pool_size_current: Current pool size (if available)
            - pool_connections_idle: Idle connections (if available)
            - pool_connections_active: Active connections (if available)
            - uptime_seconds: Seconds since successful initialization (T5.4)
            - total_connections: Total connections established (T5.4)

        Example:
            >>> health = await manager.health_check()
            >>> print(health["healthy"])
            True
        """
        if not self._initialized or self._pool is None:
            return {
                "healthy": False,
                "auth_source": self._auth_source,
                "query_count": self._query_count,
                "error_count": self._error_count,
                "last_error_time": self._last_error_time,
                "consecutive_errors": self._consecutive_errors,
                "pool_size_current": 0,
                "pool_connections_idle": 0,
                "pool_connections_active": 0,
                "uptime_seconds": 0.0,
                "total_connections": self._connection_count,
            }

        try:
            # Simple connectivity test
            result = await self.fetchval("SELECT 1")
            pool_size = self._pool.get_size()
            idle_size = self._pool.get_idle_size()

            uptime = time.time() - self._init_time if self._init_time else 0.0

            return {
                "healthy": result == 1,
                "auth_source": self._auth_source,
                "query_count": self._query_count,
                "error_count": self._error_count,
                "last_error_time": self._last_error_time,
                "consecutive_errors": self._consecutive_errors,
                "pool_size_current": pool_size,
                "pool_connections_idle": idle_size,
                "pool_connections_active": pool_size - idle_size,
                "uptime_seconds": uptime,
                "total_connections": self._connection_count,
            }
        except Exception:
            self._error_count += 1
            self._last_error_time = time.time()
            self._consecutive_errors += 1
            # FR-6.8a: Always return consistent shape
            uptime = time.time() - self._init_time if self._init_time else 0.0

            return {
                "healthy": False,
                "auth_source": self._auth_source,
                "query_count": self._query_count,
                "error_count": self._error_count,
                "last_error_time": self._last_error_time,
                "consecutive_errors": self._consecutive_errors,
                "pool_size_current": 0,
                "pool_connections_idle": 0,
                "pool_connections_active": 0,
                "uptime_seconds": uptime,
                "total_connections": self._connection_count,
            }

    async def check_extension(self, extension: str) -> bool:
        """Check if a PostgreSQL extension is installed.

        Args:
            extension: Extension name (e.g., "vector")

        Returns:
            True if extension is available

        Raises:
            CloudSQLError(QUERY_FAILED): If query fails
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
            CloudSQLError(QUERY_FAILED): If extension cannot be created
        """
        if not await self.check_extension(extension):
            try:
                await self.execute(f"CREATE EXTENSION IF NOT EXISTS {extension}")
                logger.info("Created PostgreSQL extension: %s", extension)
            except CloudSQLError as e:
                # Re-raise with additional context
                logger.error(
                    "Failed to create extension '%s': %s. "
                    "Ensure database user has CREATE privileges.",
                    extension,
                    e.error_id,
                )
                raise

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

    async def __aenter__(self) -> "CloudSQLConnectionManager":
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()

    def __repr__(self) -> str:
        """String representation (never exposes credentials)."""
        return (
            f"CloudSQLConnectionManager("
            f"instance={self._config.project}:{self._config.region}:{self._config.instance}, "
            f"database={self._config.database}, "
            f"prefix={self.table_prefix!r}, "
            f"initialized={self._initialized})"
        )
