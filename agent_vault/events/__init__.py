"""Event tracking system for agent_vault.

This module provides comprehensive, low-overhead tracking of all system operations.
It follows established patterns from FileTracker for SQLite storage and integrates
seamlessly with the existing correlation ID system for distributed tracing.

Key Features:
- Non-blocking event emission with async batching
- SQLite storage with WAL mode for concurrent reads
- Correlation ID integration for distributed tracing
- Project isolation via project_id
- Rich contextual metadata
- Graceful failure handling

Example Usage:
    >>> from agent_vault.events import EventSystem, track_operation
    >>> from agent_vault.config import Config
    >>> 
    >>> # Initialize event system
    >>> config = Config.load()
    >>> async with EventSystem.from_config(config, project_id="my_project") as events:
    ...     # Track an operation
    ...     async with track_operation(events, "indexing", "pipeline") as op:
    ...         await op.progress(files_processed=10)
    ...         # Automatically emits started/completed/failed events
    ...     
    ...     # Query events
    ...     operation_events = await events.store.get_operation_events(operation_id)
    ...     for event in operation_events:
    ...         print(f"{event.timestamp}: {event.event_type}")
"""

from agent_vault.events.bus import EventBus
from agent_vault.events.context_managers import OperationTracker, track_operation
from agent_vault.events.models import Event, EventStatus
from agent_vault.events.project_lifecycle import (
    emit_project_closed,
    emit_project_initialized,
    emit_project_loaded,
)
from agent_vault.events.protocols import (
    EventStorageBackend,
    EventStorageMaintenanceCapability,
    EventStorageQueryCapability,
    has_maintenance_capability,
    has_query_capability,
)
from agent_vault.events.queries import (
    ActiveIndexingOperation,
    get_last_progress_timestamp,
    get_operation_progress,
    query_active_indexing_operations,
)
from agent_vault.events.storage import SQLiteEventStorage
from agent_vault.events.store import EventStore
from agent_vault.events.system import EventSystem
from agent_vault.events.types import EventTypes, validate_event_type

# Payload models are imported lazily to avoid circular dependencies
# Use: from agent_vault.events.payloads import IndexingStartedPayload

__all__ = [
    # Core system
    "EventSystem",
    "EventStore",
    "EventBus",
    # Protocols (for backend abstraction)
    "EventStorageBackend",
    "EventStorageQueryCapability",
    "EventStorageMaintenanceCapability",
    "has_query_capability",
    "has_maintenance_capability",
    # Adapters
    "SQLiteEventStorage",
    # Models
    "Event",
    "EventStatus",
    # Event types
    "EventTypes",
    "validate_event_type",
    # Context managers
    "track_operation",
    "OperationTracker",
    # Project lifecycle
    "emit_project_initialized",
    "emit_project_loaded",
    "emit_project_closed",
    # Query utilities
    "ActiveIndexingOperation",
    "query_active_indexing_operations",
    "get_last_progress_timestamp",
    "get_operation_progress",
]
