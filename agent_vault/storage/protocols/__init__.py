"""Storage protocols for provider abstraction.

This module exports all protocol definitions that providers must implement.
Protocols use structural subtyping (duck typing) with runtime checking.

Design principles:
- Minimal surface area: Only methods that vary across backends
- Capability-based: Check capabilities at runtime with isinstance()
- Canonical types: Use domain types (DocumentChunk, GraphEntity, Event, etc.)
- Async-only: All I/O operations are async (with sync wrappers where needed)

Protocol hierarchy:
    BackendLifecycle        - Standard lifecycle for all backends (initialize/close)
    VectorStorageProtocol   - Vector similarity search operations (14 methods)
    MaintenanceProtocol     - Index maintenance and optimization (5 methods)
    TransactionProtocol     - Transactional operations (3 methods)
    GraphStorageProtocol    - Knowledge graph operations (18 methods)
    IndexingStorageProtocol - Document indexing operations
    EventStorageProtocol    - Event persistence operations
    FileTrackerProtocol     - File state tracking operations
"""

from agent_vault.storage.protocols.events import (
    EventStorageProtocol,
    has_event_storage,
)
from agent_vault.storage.protocols.lifecycle import (
    BackendLifecycle,
    has_lifecycle_support,
)
from agent_vault.storage.protocols.file_tracker import (
    FileTrackerProtocol,
    has_file_tracker,
)
from agent_vault.storage.protocols.graph import (
    GraphStorageProtocol,
    has_graph_storage,
)
from agent_vault.storage.protocols.indexing import (
    IndexingStorageProtocol,
    has_indexing_support,
)
from agent_vault.storage.protocols.vector import (
    FullVectorStorageProtocol,
    MaintenanceProtocol,
    TransactionContext,
    TransactionProtocol,
    VectorStorageProtocol,
    has_maintenance_support,
    has_transaction_support,
    is_full_provider,
)

__all__ = [
    # Lifecycle protocol
    "BackendLifecycle",
    # Vector protocols
    "VectorStorageProtocol",
    "MaintenanceProtocol",
    "TransactionProtocol",
    "FullVectorStorageProtocol",
    # Transaction context
    "TransactionContext",
    # Graph protocols
    "GraphStorageProtocol",
    # Indexing protocols
    "IndexingStorageProtocol",
    # Event protocols
    "EventStorageProtocol",
    # File tracker protocols
    "FileTrackerProtocol",
    # Capability detection
    "has_lifecycle_support",
    "has_maintenance_support",
    "has_transaction_support",
    "is_full_provider",
    "has_graph_storage",
    "has_indexing_support",
    "has_event_storage",
    "has_file_tracker",
]
