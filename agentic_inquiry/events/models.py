"""Event data models.

This module defines the core Event dataclass and related types for the event
tracking system.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, TYPE_CHECKING
import time
import uuid

if TYPE_CHECKING:
    from agentic_inquiry.events.payloads import BaseEventPayload


class EventStatus(str, Enum):
    """Event status enumeration.
    
    Represents the lifecycle state of an operation:
    - STARTED: Operation has begun
    - PROGRESS: Operation is in progress (intermediate state)
    - COMPLETED: Operation finished successfully
    - FAILED: Operation encountered an error
    """
    STARTED = "started"
    PROGRESS = "progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Event:
    """Structured event record.
    
    Represents a single event in the system with full contextual information.
    Events are immutable once created and stored.
    
    Attributes:
        event_id: Unique event identifier (UUID)
        project_id: Project identifier for isolation
        operation_id: Groups related events (often correlation ID)
        session_id: Groups operations in a session
        timestamp: Unix timestamp with microsecond precision
        event_type: Hierarchical type (e.g., "indexing.started")
        status: Event status (started, progress, completed, failed)
        source: Component that emitted the event
        metadata: Arbitrary contextual data
        schema_version: Schema version for evolution
    
    Example:
        >>> event = Event(
        ...     project_id="my_project",
        ...     event_type="indexing.started",
        ...     source="pipeline",
        ...     status=EventStatus.STARTED,
        ...     operation_id="op_123",
        ...     metadata={"file_count": 42}
        ... )
    """
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str = ""
    operation_id: Optional[str] = None
    session_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    event_type: str = ""
    status: EventStatus = EventStatus.PROGRESS
    source: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage.
        
        Returns:
            Dictionary representation suitable for JSON serialization
        """
        return {
            "event_id": self.event_id,
            "project_id": self.project_id,
            "operation_id": self.operation_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "status": self.status.value if isinstance(self.status, EventStatus) else self.status,
            "source": self.source,
            "metadata": self.metadata,
            "schema_version": self.schema_version,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        """Create from dictionary.

        Args:
            data: Dictionary with event data

        Returns:
            Event instance
        """
        # Convert status string to enum
        if "status" in data and isinstance(data["status"], str):
            data["status"] = EventStatus(data["status"])
        return cls(**data)

    @classmethod
    def from_payload(
        cls,
        event_type: str,
        source: str,
        payload: "BaseEventPayload",
        project_id: str = "",
        status: EventStatus = EventStatus.PROGRESS,
        operation_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> "Event":
        """Create event from typed payload.

        This method validates the payload and converts it to metadata,
        providing type-safe event creation.

        Args:
            event_type: Event type (e.g., "indexing.started")
            source: Source component
            payload: Typed Pydantic payload model
            project_id: Project identifier
            status: Event status
            operation_id: Optional operation ID
            session_id: Optional session ID

        Returns:
            Event instance with validated metadata

        Example:
            >>> from agentic_inquiry.events.payloads import IndexingStartedPayload
            >>> payload = IndexingStartedPayload(path="/path", content_type="code")
            >>> event = Event.from_payload(
            ...     "indexing.started",
            ...     "pipeline",
            ...     payload,
            ...     project_id="my_project"
            ... )
        """
        return cls(
            event_type=event_type,
            source=source,
            status=status,
            project_id=project_id,
            operation_id=operation_id,
            session_id=session_id,
            metadata=payload.to_metadata(),
        )

    def validate_payload(self, payload_class: type) -> "BaseEventPayload":
        """Validate metadata against a payload schema.

        This method validates the event's metadata against a Pydantic payload
        model, raising ValidationError if the metadata doesn't match the schema.

        Args:
            payload_class: Pydantic model class to validate against

        Returns:
            Validated payload instance

        Raises:
            ValidationError: If metadata doesn't match schema

        Example:
            >>> from agentic_inquiry.events.payloads import IndexingStartedPayload
            >>> event = Event(metadata={"path": "/path", "content_type": "code"})
            >>> payload = event.validate_payload(IndexingStartedPayload)
            >>> assert payload.path == "/path"
        """
        return payload_class(**self.metadata)
