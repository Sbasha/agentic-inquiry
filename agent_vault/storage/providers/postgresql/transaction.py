"""Transaction coordinator for multi-provider atomicity in PostgreSQL storage.

This module implements FR-2 transaction coordination across VectorProvider and
GraphProvider to ensure atomic operations and prevent orphaned data. It provides
BEGIN/COMMIT/ROLLBACK lifecycle management with connection injection.

Design decisions:
    - Shared connection: Single connection used across all providers in transaction
    - Auto-cleanup: Connection released and providers cleared on exit
    - Fail-fast: Rollback on any exception
    - Delegated operations: Coordinator proxies operations to providers

Example:
    >>> coordinator = TransactionCoordinator(
    ...     connection_manager, vector_provider, graph_provider
    ... )
    >>> async with transaction_scope(coordinator) as txn:
    ...     await txn.store_chunks(chunks)
    ...     await txn.store_relationships(relationships)
    ...     # Auto-commits on success, rolls back on exception
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, AsyncIterator, Any, List

if TYPE_CHECKING:
    import asyncpg

    from .connection import PostgresConnectionManager
    from .vector import PostgresVectorProvider
    from .graph import PostgresGraphProvider

logger = logging.getLogger(__name__)


class TransactionError(Exception):
    """Raised when transaction operation fails or is called incorrectly."""

    pass


class PoolExhaustedError(Exception):
    """Raised when connection pool is exhausted during transaction acquisition."""

    pass


@dataclass
class TransactionContext:
    """Holds transaction state for multi-provider operations.

    Attributes:
        connection: Shared database connection for all providers
        savepoint_stack: Stack of savepoint names for nested operations
    """

    connection: "asyncpg.Connection"
    savepoint_stack: List[str] = field(default_factory=list)


class TransactionCoordinator:
    """Coordinates transactions across multiple PostgreSQL providers.

    This class implements FR-2.1, FR-2.2 by managing BEGIN/COMMIT/ROLLBACK
    lifecycle and injecting a shared connection into VectorProvider and
    GraphProvider for atomic multi-provider operations.

    Usage:
        >>> async with storage_facade.transaction() as txn:
        ...     await txn.store_chunks(chunks)
        ...     await txn.store_relationships(relationships)
        ...     # Auto-commits on success, rolls back on exception

    Attributes:
        _conn_manager: PostgreSQL connection manager
        _vector: Vector provider instance
        _graph: Graph provider instance
        _timeout: Connection acquisition timeout in seconds
        _context: Current transaction context (None if not started)
        _committed: Whether transaction has been committed
        _rolled_back: Whether transaction has been rolled back
    """

    def __init__(
        self,
        connection_manager: "PostgresConnectionManager",
        vector_provider: "PostgresVectorProvider",
        graph_provider: "PostgresGraphProvider",
        timeout: float = 30.0,
    ):
        """Initialize transaction coordinator.

        Args:
            connection_manager: PostgreSQL connection manager
            vector_provider: Vector storage provider
            graph_provider: Graph storage provider
            timeout: Connection acquisition timeout in seconds (default: 30.0)
        """
        self._conn_manager = connection_manager
        self._vector = vector_provider
        self._graph = graph_provider
        self._timeout = timeout
        self._context: TransactionContext | None = None
        self._committed = False
        self._rolled_back = False

    @property
    def connection(self) -> "asyncpg.Connection":
        """Get the shared transaction connection.

        Returns:
            Database connection for transaction operations

        Raises:
            TransactionError: If transaction not started
        """
        if self._context is None:
            raise TransactionError("Transaction not started")
        return self._context.connection

    async def begin(self) -> None:
        """Start the transaction.

        Acquires a dedicated connection from the pool, starts a database
        transaction with BEGIN, and injects the connection into providers.

        Raises:
            TransactionError: If transaction already started
            PoolExhaustedError: If connection pool exhausted
        """
        if self._context is not None:
            raise TransactionError("Transaction already started")

        # Acquire dedicated connection with timeout
        conn = await self._conn_manager.acquire_for_transaction(timeout=self._timeout)

        # Start transaction
        await conn.execute("BEGIN")

        self._context = TransactionContext(connection=conn, savepoint_stack=[])

        # Inject connection into providers (AC-4, AC-5)
        self._vector.set_transaction_connection(conn)
        self._graph.set_transaction_connection(conn)

        logger.debug("Transaction started")

    async def commit(self) -> None:
        """Commit the transaction.

        Executes COMMIT on the database connection, marks transaction as
        committed, and cleans up resources.

        Raises:
            TransactionError: If no active transaction or already finalized
        """
        if self._context is None:
            raise TransactionError("No active transaction")
        if self._committed or self._rolled_back:
            raise TransactionError("Transaction already finalized")

        try:
            await self._context.connection.execute("COMMIT")
            self._committed = True
            logger.debug("Transaction committed")
        except Exception as e:
            # COMMIT failed - transaction state is UNKNOWN
            # Log the error but allow rollback to be attempted
            logger.error(f"COMMIT failed, transaction state UNKNOWN: {e}")
            raise
        finally:
            # Only cleanup after successful commit (cleanup on rollback is separate)
            if self._committed:
                await self._cleanup()

    async def rollback(self) -> None:
        """Rollback the transaction.

        Executes ROLLBACK on the database connection. If connection is dead,
        marks as rolled back anyway (DB-side rollback happens automatically).

        Implements AC-4, AC-5: Full rollback on exception.
        """
        if self._context is None:
            raise TransactionError("No active transaction")
        if self._committed or self._rolled_back:
            return  # Already finalized, nothing to do

        try:
            await self._context.connection.execute("ROLLBACK")
            self._rolled_back = True
            logger.debug("Transaction rolled back")
        except Exception as e:
            # Connection may be dead; rollback still happens DB-side
            logger.warning(f"Rollback failed (connection issue): {e}")
            self._rolled_back = True
        finally:
            await self._cleanup()

    async def _cleanup(self) -> None:
        """Release resources after transaction completion.

        Clears provider transaction connections and releases the dedicated
        connection back to the pool.
        """
        if self._context is not None:
            # Clear provider transaction state
            self._vector.clear_transaction_connection()
            self._graph.clear_transaction_connection()

            # Release connection back to pool
            await self._conn_manager.release_transaction_connection(
                self._context.connection
            )
            self._context = None

    # Delegated operations (use shared connection)

    async def store_chunks(self, chunks: List[Any], **kwargs) -> int:
        """Store chunks atomically within the transaction.

        Args:
            chunks: List of DocumentChunk objects to store
            **kwargs: Additional arguments passed to provider

        Returns:
            Number of chunks that were stored

        Raises:
            TransactionError: If transaction not started
        """
        if self._context is None:
            raise TransactionError("Transaction not started")
        return await self._vector.upsert_chunks(chunks, self._vector._project_id, **kwargs)

    async def store_relationships(
        self, relationships: List[Any], **kwargs
    ) -> int:
        """Store relationships atomically within the transaction.

        Args:
            relationships: List of GraphRelationship objects to store
            **kwargs: Additional arguments passed to provider

        Returns:
            Number of relationships that were stored

        Raises:
            TransactionError: If transaction not started
        """
        if self._context is None:
            raise TransactionError("Transaction not started")
        return await self._graph.upsert_relationships(relationships, self._graph._project_id, **kwargs)

    async def delete_chunks(self, chunk_ids: List[str], **kwargs) -> int:
        """Delete chunks and their relationships atomically.

        Deletes from graph provider first (relationships reference chunks),
        then deletes chunks from vector provider.

        Args:
            chunk_ids: List of chunk IDs to delete
            **kwargs: Additional arguments passed to providers

        Returns:
            Number of chunks deleted

        Raises:
            TransactionError: If transaction not started
        """
        if self._context is None:
            raise TransactionError("Transaction not started")

        # Delete from graph first (relationships reference chunks)
        # Use delete_relationships_by_ids for each chunk's relationships
        await self._graph.delete_relationships_by_ids(chunk_ids, self._graph._project_id)

        # Then delete chunks
        return await self._vector.delete_chunks_by_ids(chunk_ids, self._vector._project_id, **kwargs)

    async def delete_file(self, file_path: str, **kwargs) -> int:
        """Delete all chunks for a file atomically.

        Gets chunk IDs for the file, then deletes chunks and relationships
        using delete_chunks().

        Args:
            file_path: Path of file whose chunks should be deleted
            **kwargs: Additional arguments passed to providers

        Returns:
            Number of chunks deleted

        Raises:
            TransactionError: If transaction not started
        """
        if self._context is None:
            raise TransactionError("Transaction not started")

        # Get chunks for file and extract IDs
        chunks = await self._vector.get_chunks_by_file(file_path, self._vector._project_id)
        if not chunks:
            return 0
        chunk_ids = [chunk.id for chunk in chunks]

        return await self.delete_chunks(chunk_ids, **kwargs)

    @asynccontextmanager
    async def transaction_scope(self) -> AsyncIterator["TransactionCoordinator"]:
        """Context manager for transaction lifecycle (instance method).

        Automatically begins the transaction on entry, commits on successful exit,
        and rolls back on exception. This is the recommended usage pattern.

        Yields:
            This coordinator instance for performing operations

        Raises:
            Any exception raised by operations within the transaction

        Example:
            >>> async with coordinator.transaction_scope() as txn:
            ...     await txn.store_chunks(chunks)
            ...     # Commits on success, rolls back on exception
        """
        await self.begin()
        try:
            yield self
            await self.commit()
        except Exception:
            await self.rollback()
            raise


@asynccontextmanager
async def transaction_scope(
    coordinator: TransactionCoordinator,
) -> AsyncIterator[TransactionCoordinator]:
    """Context manager for transaction lifecycle.

    Automatically begins the transaction on entry, commits on successful exit,
    and rolls back on exception. This implements the recommended usage pattern
    for TransactionCoordinator.

    Args:
        coordinator: TransactionCoordinator instance

    Yields:
        The coordinator instance for performing operations

    Raises:
        Any exception raised by operations within the transaction

    Example:
        >>> coordinator = TransactionCoordinator(conn_mgr, vector, graph)
        >>> async with transaction_scope(coordinator) as txn:
        ...     await txn.store_chunks(chunks)
        ...     # Commits on success, rolls back on exception
    """
    await coordinator.begin()
    try:
        yield coordinator
        await coordinator.commit()
    except Exception:
        await coordinator.rollback()
        raise
