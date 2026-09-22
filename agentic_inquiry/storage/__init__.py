"""Composable storage layer for Agentic Inquiry.

This module provides a unified storage abstraction that composes
vector and graph providers into a simple facade for internal services.

The storage module follows the provider pattern:
- Protocols define the interface that providers must implement
- Providers are concrete implementations (LanceDB, InMemory, etc.)
- StorageFacade composes providers into a unified interface

Usage:
    from agentic_inquiry.storage import StorageFacade

    # Create from config (recommended)
    storage = await StorageFacade.from_config(config, project_id)

    # Vector search
    results = await storage.vector_search(query_vector, limit=10)

    # Hybrid search (vector + FTS)
    results = await storage.hybrid_search(
        query_vector=query_vector,
        query_text="authentication error",
        limit=10
    )

    # Graph operations
    entities = await storage.find_entities({"type": "function"})
    await storage.add_relationship(relationship)

    # Cleanup
    await storage.shutdown()

For protocol-aware code:
    from agentic_inquiry.storage.protocols import (
        VectorStorageProtocol,
        GraphStorageProtocol,
        has_graph_storage,
    )

    if has_graph_storage(provider):
        await provider.upsert_entities(entities, project_id)
"""

from agentic_inquiry.storage.exceptions import (
    ConnectionError,
    ProviderNotFoundError,
    QueryError,
    StorageError,
    TransactionError,
)
from agentic_inquiry.storage.facade import StorageFacade
from agentic_inquiry.storage.protocols import (
    FullVectorStorageProtocol,
    GraphStorageProtocol,
    MaintenanceProtocol,
    TransactionContext,
    TransactionProtocol,
    VectorStorageProtocol,
    has_graph_storage,
    has_maintenance_support,
    has_transaction_support,
    is_full_provider,
)

__all__ = [
    # Main facade (primary entry point)
    "StorageFacade",
    # Vector protocols
    "VectorStorageProtocol",
    "MaintenanceProtocol",
    "TransactionProtocol",
    "FullVectorStorageProtocol",
    # Transaction context
    "TransactionContext",
    # Graph protocols
    "GraphStorageProtocol",
    # Capability detection
    "has_maintenance_support",
    "has_transaction_support",
    "is_full_provider",
    "has_graph_storage",
    # Exceptions
    "StorageError",
    "ConnectionError",
    "QueryError",
    "TransactionError",
    "ProviderNotFoundError",
]
