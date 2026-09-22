"""Transaction awareness protocol for storage providers.

This module defines the protocol for storage providers that support
transaction coordination across multiple providers.

Design principles:
    - Protocol-based design for loose coupling
    - Connection injection pattern for shared transactions
    - Clear lifecycle management (set, clear, query state)
    - Type-safe interface for transaction-aware operations

Usage:
    >>> provider = PostgresVectorProvider(...)
    >>> provider.set_transaction_connection(conn)
    >>> await provider.store_chunks(chunks)  # Uses injected connection
    >>> provider.clear_transaction_connection()
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

try:
    import asyncpg
except ImportError:
    asyncpg = None  # type: ignore


@runtime_checkable
class TransactionAwareProvider(Protocol):
    """Protocol for providers that support transaction coordination.

    Providers implementing this protocol can participate in multi-provider
    transactions by accepting an injected database connection.

    The transaction coordinator calls:
        1. set_transaction_connection() - Inject shared connection
        2. Provider operations use injected connection
        3. clear_transaction_connection() - Reset to normal pool mode

    Example:
        >>> # Transaction coordinator manages the flow
        >>> async with transaction_coordinator.begin():
        ...     coordinator.inject_connection(vector_provider)
        ...     coordinator.inject_connection(graph_provider)
        ...     await vector_provider.store_chunks(chunks)
        ...     await graph_provider.store_relationships(rels)
        ...     await transaction_coordinator.commit()
    """

    def set_transaction_connection(self, conn: "asyncpg.Connection") -> None:
        """Inject a shared database connection for transaction coordination.

        Args:
            conn: The asyncpg connection to use for all operations

        Raises:
            TransactionError: If provider is already in a transaction
        """
        ...

    def clear_transaction_connection(self) -> None:
        """Remove the injected connection and return to pool mode.

        After calling this method, the provider will acquire connections
        from the pool for subsequent operations.
        """
        ...

    @property
    def in_transaction(self) -> bool:
        """Check if provider is currently using an injected connection.

        Returns:
            True if a transaction connection is set, False otherwise
        """
        ...
