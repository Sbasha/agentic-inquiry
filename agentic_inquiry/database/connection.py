"""Connection management for LanceDB.

This module provides ConnectionManager, which handles database connection
lifecycle including connect, close, reconnect, and health checking.

Design reference: DES-S3-001 in .sessions/deep-architecture-review/009-design.md
"""

from __future__ import annotations

import asyncio
import logging
import os
from functools import partial
from typing import TYPE_CHECKING, Any, Callable, Optional

from agentic_inquiry.exceptions import StorageError
from agentic_inquiry.executors import get_lancedb_executor

if TYPE_CHECKING:
    import lancedb

logger = logging.getLogger(__name__)

try:
    import lancedb as _lancedb
except ImportError:
    _lancedb = None  # type: ignore[assignment]


class ConnectionManager:
    """Handles LanceDB connection lifecycle.

    This class manages the database connection including:
    - Connection establishment and caching
    - Reconnection on errors
    - Thread-safe async access
    - Connection factory support for custom setups

    Parameters
    ----------
    uri:
        Path or URI pointing at a LanceDB store.
    connection:
        Pre-created LanceDB connection instance.
    connection_factory:
        Callable that yields a LanceDB connection.
    prepare_local_path:
        Whether to create local directories if they don't exist.

    Example:
        >>> manager = ConnectionManager(uri="./data")
        >>> await manager.connect()
        >>> conn = await manager.get_connection()
        >>> await manager.close()
    """

    def __init__(
        self,
        uri: Optional[str] = None,
        *,
        connection: Optional["lancedb.DBConnection"] = None,
        connection_factory: Optional[Callable[[], "lancedb.DBConnection"]] = None,
        prepare_local_path: bool = False,
    ):
        if connection is not None and connection_factory is not None:
            raise StorageError(
                "Provide either 'connection' or 'connection_factory', not both."
            )

        if connection is None and connection_factory is None and uri is None:
            raise StorageError(
                "A URI, connection or connection_factory must be provided."
            )

        self.uri = uri
        self._db: Optional["lancedb.DBConnection"] = connection
        self._lock = asyncio.Lock()
        self._connection_factory = connection_factory
        self._prepare_local_path = prepare_local_path

        if self._connection_factory is None and connection is None:
            self._connection_factory = self._default_connection_factory

    def _default_connection_factory(self) -> Any:
        """Create a default LanceDB connection.

        Returns:
            LanceDB connection instance

        Raises:
            ImportError: If lancedb package is not installed
            StorageError: If no URI is configured
        """
        if _lancedb is None:
            raise ImportError(
                "The 'lancedb' package is required to use ConnectionManager."
            )
        if self.uri is None:
            raise StorageError(
                "A URI must be provided when no connection factory is supplied."
            )
        if self._prepare_local_path:
            os.makedirs(self.uri, exist_ok=True)
        return _lancedb.connect(self.uri)

    def _ensure_db_sync(self) -> Any:
        """Synchronously ensure database connection exists.

        Returns:
            LanceDB connection instance

        Raises:
            StorageError: If no connection factory is available
        """
        if self._db is not None:
            return self._db
        if self._connection_factory is None:
            raise StorageError("No connection factory available to initialise LanceDB.")
        self._db = self._connection_factory()
        return self._db

    async def _ensure_db_async(self) -> Any:
        """Asynchronously ensure database connection exists.

        Returns:
            LanceDB connection instance
        """
        if self._db is not None:
            return self._db
        return await self._run_sync(self._ensure_db_sync)

    async def _run_sync(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Run a synchronous function in the LanceDB executor.

        Args:
            func: Synchronous function to run
            *args: Positional arguments for func
            **kwargs: Keyword arguments for func

        Returns:
            Result of the function call
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            get_lancedb_executor(), partial(func, *args, **kwargs)
        )

    async def connect(self) -> "ConnectionManager":
        """Open a connection to the LanceDB database.

        Returns:
            Self for method chaining
        """
        await self._ensure_db_async()
        return self

    async def close(self) -> None:
        """Close the database connection and clean up resources.

        This method closes the database connection and clears the connection
        reference. It should be called when the manager is no longer needed
        to free resources properly.

        Example:
            >>> manager = ConnectionManager(uri="./data")
            >>> await manager.connect()
            >>> # ... use manager ...
            >>> await manager.close()
        """
        async with self._lock:
            # Close database connection if it exists
            # LanceDB connections don't have an explicit close method,
            # but we can clear the reference to allow garbage collection
            if self._db is not None:
                logger.debug("Closing LanceDB connection")
                self._db = None

    async def reconnect(self) -> None:
        """Reconnect to the database.

        This method closes the existing connection and creates a new one.
        Useful for recovering from connection errors or refreshing stale
        connections.

        Example:
            >>> manager = ConnectionManager(uri="./data")
            >>> await manager.connect()
            >>> # ... connection error occurs ...
            >>> await manager.reconnect()
        """
        logger.info("Reconnecting to LanceDB")
        await self.close()
        await self.connect()

    def is_connected(self) -> bool:
        """Check if the database connection is active.

        Returns:
            True if connected, False otherwise
        """
        return self._db is not None

    async def get_connection(self) -> Any:
        """Get the current database connection, connecting if needed.

        Returns:
            LanceDB connection instance
        """
        return await self._ensure_db_async()

    async def __aenter__(self) -> "ConnectionManager":
        """Async context manager entry.

        Returns:
            Self after connecting to the database
        """
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        """Async context manager exit.

        Closes the connection when exiting the context.
        """
        await self.close()
