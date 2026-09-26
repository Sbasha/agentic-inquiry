"""Event tracking system for agentic_inquiry.

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
    >>> from agentic_inquiry.events import EventSystem, track_operation
    >>> from agentic_inquiry.config import Config
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

from agentic_inquiry.events.bus import EventBus
from agentic_inquiry.events.context_managers import OperationTracker, track_operation
from agentic_inquiry.events.models import Event, EventStatus
from agentic_inquiry.events.project_lifecycle import (
    emit_project_closed,
    emit_project_initialized,
    emit_project_loaded,
)
from agentic_inquiry.events.protocols import (
    EventStorageBackend,
    EventStorageMaintenanceCapability,
    EventStorageQueryCapability,
    has_maintenance_capability,
    has_query_capability,
)
from agentic_inquiry.events.queries import (
    ActiveIndexingOperation,
    get_last_progress_timestamp,
    get_operation_progress,
    query_active_indexing_operations,
)
from agentic_inquiry.events.storage import SQLiteEventStorage
from agentic_inquiry.events.store import EventStore
from agentic_inquiry.events.system import EventSystem
from agentic_inquiry.events.types import EventTypes, validate_event_type

# Payload models are imported lazily to avoid circular dependencies
# Use: from agentic_inquiry.events.payloads import IndexingStartedPayload

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
