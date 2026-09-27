"""Progress tracking utilities for long-running operations.

This module provides utilities for tracking and reporting progress during
long-running operations like indexing. It subscribes to progress events
and collects them for display to users.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ProgressEvent:
    """Progress update event."""

    event_type: str  # "progress", "complete", "error"
    current: int
    total: int
    file: Optional[str] = None
    percent: int = 0
    timestamp: datetime = field(default_factory=datetime.now)
    message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "event_type": self.event_type,
            "current": self.current,
            "total": self.total,
            "file": self.file,
            "percent": self.percent,
            "timestamp": self.timestamp.isoformat(),
            "message": self.message,
        }


class ProgressHandler:
    """Handler for collecting and formatting progress events.

    This class subscribes to progress events from the event system
    and collects them for later retrieval. It can format progress
    messages for display to users.

    Example:
        >>> handler = ProgressHandler()
        >>> event_system.subscribe("indexing.progress", handler.on_progress)
        >>> event_system.subscribe("indexing.complete", handler.on_complete)
        >>> # ... operation runs ...
        >>> events = handler.get_events()
        >>> formatted = handler.format_progress()
    """

    def __init__(self) -> None:
        """Initialize progress handler."""
        self.events: List[ProgressEvent] = []
        self._start_time: Optional[datetime] = None
        self._last_event_time: Optional[datetime] = None

    def on_progress(self, **kwargs: Any) -> None:
        """Handle progress event.

        Args:
            **kwargs: Event data including current, total, file, percent
        """
        if self._start_time is None:
            self._start_time = datetime.now()

        self._last_event_time = datetime.now()

        event = ProgressEvent(
            event_type="progress",
            current=kwargs.get("current", 0),
            total=kwargs.get("total", 0),
            file=kwargs.get("file"),
            percent=kwargs.get("percent", 0),
            timestamp=self._last_event_time,
        )

        self.events.append(event)
        logger.debug(
            "Progress: %s/%s (%s%%) - %s",
            event.current,
            event.total,
            event.percent,
            event.file or "unknown",
        )

    def on_complete(self, **kwargs: Any) -> None:
        """Handle completion event.

        Args:
            **kwargs: Event data including total, duration_ms
        """
        completion_time = datetime.now()

        event = ProgressEvent(
            event_type="complete",
            current=kwargs.get("total", 0),
            total=kwargs.get("total", 0),
            percent=100,
            timestamp=completion_time,
            message=f"Completed {kwargs.get('total', 0)} items",
        )

        self.events.append(event)
        logger.info(
            "Operation complete: %s items in %s ms",
            kwargs.get("total", 0),
            kwargs.get("duration_ms", 0),
        )

    def on_error(self, **kwargs: Any) -> None:
        """Handle error event.

        Args:
            **kwargs: Event data including error message
        """
        error_time = datetime.now()

        event = ProgressEvent(
            event_type="error",
            current=kwargs.get("current", 0),
            total=kwargs.get("total", 0),
            percent=kwargs.get("percent", 0),
            timestamp=error_time,
            message=kwargs.get("error", "Unknown error"),
        )

        self.events.append(event)
        logger.error("Operation error: %s", kwargs.get("error", "Unknown error"))

    def get_events(self) -> List[ProgressEvent]:
        """Get all collected progress events.

        Returns:
            List of progress events
        """
        return self.events

    def format_progress(self) -> List[str]:
        """Format progress events as human-readable messages.

        Returns:
            List of formatted progress messages
        """
        messages = []

        for event in self.events:
            if event.event_type == "progress":
                msg = f"Progress: {event.current}/{event.total} ({event.percent}%)"
                if event.file:
                    msg += f" - {event.file}"
                messages.append(msg)
            elif event.event_type == "complete":
                messages.append(event.message or "Operation complete")
            elif event.event_type == "error":
                messages.append(f"Error: {event.message}")

        return messages

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of progress tracking.

        Returns:
            Dictionary with summary statistics
        """
        if not self.events:
            return {
                "total_events": 0,
                "completed": False,
                "had_errors": False,
            }

        last_event = self.events[-1]
        has_errors = any(e.event_type == "error" for e in self.events)
        is_complete = last_event.event_type == "complete"

        summary = {
            "total_events": len(self.events),
            "completed": is_complete,
            "had_errors": has_errors,
            "current": last_event.current,
            "total": last_event.total,
            "percent": last_event.percent,
        }

        if self._start_time and self._last_event_time:
            duration = (self._last_event_time - self._start_time).total_seconds()
            summary["duration_seconds"] = int(duration)

        return summary

    def clear(self) -> None:
        """Clear all collected events."""
        self.events.clear()
        self._start_time = None
        self._last_event_time = None
