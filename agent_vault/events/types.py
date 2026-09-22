"""Event type constants for type-safe event emission.

This module provides centralized event type definitions organized by component,
along with validation utilities to ensure event types follow the required format.
"""

import re
from typing import Final


# Event type validation pattern
# Matches hierarchical event types like:
# - component.action (e.g., "system.started")
# - component.subcomponent.action (e.g., "indexing.file.indexed")
# - component.subcomponent.subaction.action (e.g., "search.query.advanced.executed")
EVENT_TYPE_PATTERN: Final = re.compile(
    r'^[a-z_]+(\.[a-z_]+){1,3}$'
)


def validate_event_type(event_type: str) -> None:
    """Validate event type format.
    
    Event types must follow the hierarchical naming convention:
    - component.action (e.g., "system.started")
    - component.subcomponent.action (e.g., "indexing.file.indexed")
    
    Args:
        event_type: Event type string to validate
        
    Raises:
        ValueError: If event type doesn't match pattern
        
    Example:
        >>> validate_event_type("indexing.started")  # Valid
        >>> validate_event_type("invalid")  # Raises ValueError
    """
    if not EVENT_TYPE_PATTERN.match(event_type):
        raise ValueError(
            f"Invalid event type: {event_type}. "
            f"Must match pattern: component.action or component.subcomponent.action"
        )


class EventTypes:
    """Centralized event type constants.
    
    Organizes event types by component for discoverability and type safety.
    Use these constants instead of string literals to avoid typos.
    
    Example:
        >>> from agent_vault.events import EventTypes
        >>> await events.emit(EventTypes.Indexing.STARTED, source="pipeline")
    """
    
    class Indexing:
        """Indexing operation events."""
        STARTED: Final = "indexing.started"
        PROGRESS: Final = "indexing.progress"
        COMPLETED: Final = "indexing.completed"  # Deprecated: use STORED + READY
        STORED: Final = "indexing.stored"  # Chunks written to storage
        READY: Final = "indexing.ready"  # Index is searchable (embeddings complete)
        FAILED: Final = "indexing.failed"
        FILE_INDEXED: Final = "indexing.file.indexed"
        FILE_SKIPPED: Final = "indexing.file.skipped"
        FILE_FAILED: Final = "indexing.file.failed"
        FAST_PATH_COMPLETE: Final = "indexing.fast_path_complete"
    
    class Search:
        """Search operation events."""
        QUERY_STARTED: Final = "search.query.started"
        QUERY_COMPLETED: Final = "search.query.completed"
        QUERY_FAILED: Final = "search.query.failed"
        RESULTS_RETURNED: Final = "search.results.returned"
    
    class Parsing:
        """Parser operation events."""
        STARTED: Final = "parsing.started"
        PROGRESS: Final = "parsing.progress"
        COMPLETED: Final = "parsing.completed"
        FAILED: Final = "parsing.failed"
        PARSER_SELECTED: Final = "parsing.parser.selected"
        CHUNK_CREATED: Final = "parsing.chunk.created"
    
    class Watching:
        """File watching events."""
        STARTED: Final = "watching.started"
        STOPPED: Final = "watching.stopped"
        FILE_CHANGED: Final = "watching.file.changed"
        FILE_CREATED: Final = "watching.file.created"
        FILE_DELETED: Final = "watching.file.deleted"

    class Memory:
        """Memory operation events."""
        STORED: Final = "memory.stored"       # Core system: memory stored
        RETRIEVED: Final = "memory.retrieved"  # Core system: memory retrieved
        CONSOLIDATED: Final = "memory.consolidated"  # Consolidation completed
        SAVED: Final = "memory.saved"         # MCP tool: save_memory completed
        RECALLED: Final = "memory.recalled"    # MCP tool: recall_memories completed

    class Maintenance:
        """Maintenance operation events."""
        STARTED: Final = "maintenance.started"
        COMPLETED: Final = "maintenance.completed"
        FAILED: Final = "maintenance.failed"

    class Project:
        """Project lifecycle events."""
        INITIALIZED: Final = "project.initialized"
        LOADED: Final = "project.loaded"
        CLOSED: Final = "project.closed"
    
    class System:
        """System-level events."""
        STARTED: Final = "system.started"
        STOPPED: Final = "system.stopped"
        ERROR: Final = "system.error"

    class Session:
        """Session lifecycle events."""
        STARTED: Final = "session.started"
        ENDED: Final = "session.ended"
