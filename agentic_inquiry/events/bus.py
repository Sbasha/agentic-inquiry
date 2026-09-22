"""Simple event bus for file watching events.

This module provides a lightweight event bus implementation using the observer
pattern. It replaces the complex event system with batching, sampling, and
queuing that was designed for distributed systems but is unnecessary for
single-process file watching.
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)


class EventBus:
    """Simple event bus for publishing and subscribing to events.
    
    This is a lightweight implementation that:
    - Uses the observer pattern for event handling
    - Supports async event handlers
    - Provides simple subscribe/publish interface
    - Has no batching, sampling, or queuing complexity
    
    Example:
        >>> bus = EventBus()
        >>> 
        >>> async def handle_file_change(data: Dict[str, Any]):
        ...     print(f"File changed: {data['path']}")
        >>> 
        >>> bus.subscribe("file_changed", handle_file_change)
        >>> await bus.publish("file_changed", {"path": "/path/to/file"})
    """
    
    def __init__(self) -> None:
        """Initialize the event bus."""
        self._handlers: Dict[str, List[Callable]] = {}
        self._lock = asyncio.Lock()
    
    def subscribe(self, event_type: str, handler: Callable) -> None:
        """Subscribe to an event type.
        
        Args:
            event_type: The type of event to subscribe to
            handler: Async callable that will be invoked when event is published
        
        Example:
            >>> async def my_handler(data):
            ...     print(f"Received: {data}")
            >>> bus.subscribe("my_event", my_handler)
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        logger.debug("Subscribed handler to event type: %s", event_type)
    
    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        """Unsubscribe from an event type.
        
        Args:
            event_type: The type of event to unsubscribe from
            handler: The handler to remove
        """
        if event_type in self._handlers:
            try:
                self._handlers[event_type].remove(handler)
                logger.debug("Unsubscribed handler from event type: %s", event_type)
            except ValueError:
                logger.warning("Handler not found for event type: %s", event_type)
    
    async def publish(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publish an event to all subscribers.
        
        Args:
            event_type: The type of event to publish
            data: Event data to pass to handlers
        
        Example:
            >>> await bus.publish("file_changed", {"path": "/path/to/file"})
        """
        handlers = self._handlers.get(event_type, [])
        
        if not handlers:
            logger.debug("No handlers for event type: %s", event_type)
            return
        
        logger.debug("Publishing event: %s to %d handlers", event_type, len(handlers))
        
        # Call all handlers concurrently
        tasks = []
        for handler in handlers:
            try:
                task = asyncio.create_task(handler(data))
                tasks.append(task)
            except Exception as e:
                logger.error("Error creating task for handler: %s", e)
        
        # Wait for all handlers to complete
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Log any exceptions from handlers
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(
                        "Handler %d for event %s raised exception: %s",
                        i,
                        event_type,
                        result
                    )
    
    def clear(self) -> None:
        """Clear all event handlers."""
        self._handlers.clear()
        logger.debug("Cleared all event handlers")
    
    def get_handler_count(self, event_type: str) -> int:
        """Get the number of handlers for an event type.
        
        Args:
            event_type: The event type to check
            
        Returns:
            Number of handlers subscribed to the event type
        """
        return len(self._handlers.get(event_type, []))
