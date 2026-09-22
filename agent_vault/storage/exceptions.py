"""Storage exceptions - extends base exceptions for storage-specific errors.

This module provides storage-specific exceptions that extend the base
StorageError from agent_vault.exceptions. These exceptions provide
more granular error handling for storage operations.

Exception Hierarchy:
    StorageError (from agent_vault.exceptions)
    ├── ConnectionError
    ├── QueryError
    ├── TransactionError
    └── ProviderNotFoundError

Usage:
    from agent_vault.storage.exceptions import ConnectionError, QueryError

    try:
        await provider.initialize()
    except ConnectionError as e:
        logger.error("Failed to connect: %s", e)
"""

# Re-export existing exception for consistency with existing error handling
from agent_vault.exceptions import StorageError


class ConnectionError(StorageError):
    """Failed to connect to storage backend.

    Raised when:
    - Initial connection fails
    - Connection is lost during operation
    - Connection pool is exhausted

    Example:
        try:
            await provider.initialize()
        except ConnectionError as e:
            logger.error("Cannot connect to LanceDB: %s", e)
            # Retry or fallback logic
    """

    pass


class QueryError(StorageError):
    """Query execution failed.

    Raised when:
    - Query syntax is invalid
    - Query references non-existent tables/columns
    - Query times out

    Example:
        try:
            results = await provider.vector_search(query_vector)
        except QueryError as e:
            logger.error("Search query failed: %s", e)
    """

    pass


class TransactionError(StorageError):
    """Transaction commit/rollback failed.

    Raised when:
    - Transaction cannot be started
    - Commit fails due to conflicts
    - Rollback fails

    Example:
        try:
            await provider.commit_transaction(txn_id)
        except TransactionError as e:
            logger.error("Transaction failed: %s", e)
            await provider.rollback_transaction(txn_id)
    """

    pass


class ProviderNotFoundError(StorageError):
    """Requested provider is not registered.

    Raised when:
    - Provider name is not in registry
    - Provider class cannot be imported

    Example:
        try:
            provider = factory.create_provider("nonexistent")
        except ProviderNotFoundError as e:
            logger.error("Unknown provider: %s", e)
    """

    pass


__all__ = [
    "StorageError",
    "ConnectionError",
    "QueryError",
    "TransactionError",
    "ProviderNotFoundError",
]
