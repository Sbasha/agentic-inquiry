"""Event system with queue-based batching and sampling.

This module provides an EventSystem that:
- Queues events for batch processing
- Writes events in batches via background writer
- Supports sampling to reduce event volume
- Publishes events to EventBus for in-memory handlers
"""

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, Optional

from agentic_inquiry.correlation import get_correlation_id
from agentic_inquiry.events.bus import EventBus
from agentic_inquiry.events.models import Event, EventStatus
from agentic_inquiry.events.store import EventStore
from agentic_inquiry.utils.retry import RetryPolicy

if TYPE_CHECKING:
    from agentic_inquiry.config import Config

logger = logging.getLogger(__name__)


class EventSystem:
    """Event system with queue-based batching and sampling.

    Features:
    - Async queue for event buffering
    - Background writer for batch persistence
    - Configurable batch size and flush interval
    - Optional sampling for high-volume events
    - EventBus integration for in-memory handlers

    Example:
        >>> async with EventSystem.from_config(config, project_id="my_project") as events:
        ...     await events.emit("indexing.started", source="pipeline", file_count=42)
    """

    def __init__(
        self,
        config: Optional["Config"] = None,
        project_id: Optional[str] = None,
    ):
        """Initialize event system.

        Args:
            config: Config instance
            project_id: Project ID for data isolation
        """
        from agentic_inquiry.config import Config

        # Load config if not provided
        if config is None:
            config = Config.load()

        self.config = config

        # Resolve project_id
        if project_id is None:
            project_id = config.storage.default_project_id
            if not project_id:
                raise ValueError(
                    "project_id must be provided or set as storage.default_project_id in configuration"
                )

        self.project_id = project_id

        # Event bus for in-memory event handling
        self.bus = EventBus()

        # Event store for persistence
        self.store = EventStore(config, project_id=project_id)

        # Queue for batching
        self._queue: asyncio.Queue[Event] = asyncio.Queue(
            maxsize=config.events.queue_max_size
        )

        # Background writer task
        self._writer_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._shutdown = False

        # Metrics
        self.events_emitted_count = 0
        self.events_dropped_count = 0
        self._sampled_count = 0

        # Sampling configuration
        self._sampling_enabled = config.events.sampling_enabled
        self._sampling_ratio = config.events.sampling_ratio
        self._sampling_counter = 0

        # Alerting configuration
        self._drop_alert_threshold = getattr(config.events, "drop_alert_threshold", 100)
        self._drop_alert_triggered = False

    @classmethod
    async def from_config(
        cls,
        config: Optional["Config"] = None,
        project_id: Optional[str] = None,
    ) -> "EventSystem":
        """Create and start event system.

        Args:
            config: Config instance
            project_id: Project ID for data isolation

        Returns:
            Started EventSystem instance
        """
        system = cls(config, project_id)
        await system.start()
        return system

    async def start(self) -> None:
        """Start event system and background writer."""
        if self._writer_task is not None:
            # Already started (idempotent)
            return

        # Initialize store
        await self.store._ensure_initialized()

        # Start background writer
        self._writer_task = asyncio.create_task(self._writer_loop())

        # Start background cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

        logger.info("EventSystem started")

    async def stop(self, timeout: float = 5.0) -> bool:
        """Stop event system and flush pending events.

        Args:
            timeout: Maximum time to wait for flush (seconds)

        Returns:
            True if stopped successfully, False if timeout
        """
        if self._shutdown:
            # Already stopped (idempotent)
            return True

        # Signal shutdown
        self._shutdown = True

        # Cancel cleanup task first (it has long sleep intervals)
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                logger.debug("Cleanup task cancelled successfully")
            except Exception as e:
                logger.error("Error during cleanup task cancellation: %s", e)

        # Clear the cleanup task reference
        self._cleanup_task = None

        # Wait for writer to finish with timeout
        if self._writer_task and not self._writer_task.done():
            try:
                # Give writer loop a chance to see shutdown flag
                await asyncio.sleep(0.01)

                # Wait for writer to complete
                await asyncio.wait_for(self._writer_task, timeout=timeout)
                logger.debug("Writer task completed gracefully")
            except asyncio.TimeoutError:
                logger.warning(
                    "Writer task did not complete within timeout, cancelling"
                )
                self._writer_task.cancel()
                try:
                    await self._writer_task
                except asyncio.CancelledError:
                    logger.debug("Writer task cancelled successfully")
                except Exception as e:
                    logger.error("Error during writer task cancellation: %s", e)
                return False
            except asyncio.CancelledError:
                logger.debug("Writer task was already cancelled")
            except Exception as e:
                logger.error("Unexpected error stopping writer task: %s", e)

        # Clear the task reference
        self._writer_task = None

        # Clear event bus handlers to prevent any lingering references
        self.bus.clear()

        # Close store
        try:
            await self.store.close()
        except Exception as e:
            logger.error("Error closing event store: %s", e)

        # Give asyncio a chance to clean up any remaining tasks
        await asyncio.sleep(0)

        logger.info("EventSystem stopped")
        return True

    async def emit(
        self,
        event_type: str,
        source: str,
        status: EventStatus = EventStatus.PROGRESS,
        operation_id: Optional[str] = None,
        session_id: Optional[str] = None,
        **metadata: Any,
    ) -> None:
        """Emit an event.

        Args:
            event_type: Event type (e.g., "indexing.started")
            source: Source component
            status: Event status
            operation_id: Optional operation ID (defaults to correlation ID)
            session_id: Optional session ID
            **metadata: Additional event metadata
        """
        if self._shutdown:
            return

        # Auto-use correlation ID if no operation ID provided
        if operation_id is None:
            operation_id = get_correlation_id()

        # Apply sampling if enabled
        if self._should_sample(status):
            self._sampled_count += 1
            return

        event = Event(
            project_id=self.project_id,
            event_type=event_type,
            source=source,
            status=status,
            operation_id=operation_id,
            session_id=session_id,
            metadata=metadata,
        )

        # Publish to event bus (for in-memory handlers)
        await self.bus.publish(
            event_type,
            {
                "event": event,
                "project_id": self.project_id,
                "operation_id": operation_id,
                "session_id": session_id,
                "status": status,
                **metadata,
            },
        )

        # Queue event for batch persistence
        try:
            self._queue.put_nowait(event)
            self.events_emitted_count += 1
        except asyncio.QueueFull:
            # Queue is full - drop event and track metric
            self.events_dropped_count += 1

            # Log warning with queue depth for debugging
            logger.warning(
                "Event queue full (depth=%d, max=%d), dropped event: %s from %s",
                self.queue_depth,
                self.config.events.queue_max_size,
                event_type,
                source,
            )

            # Check if we've exceeded the drop alert threshold
            if (
                not self._drop_alert_triggered
                and self.events_dropped_count >= self._drop_alert_threshold
            ):
                self._drop_alert_triggered = True
                logger.error(
                    "High event drop rate detected: %d events dropped (threshold: %d). "
                    "Consider increasing queue_max_size (current: %d) or enabling sampling.",
                    self.events_dropped_count,
                    self._drop_alert_threshold,
                    self.config.events.queue_max_size,
                )

    async def emit_typed(
        self,
        event_type: str,
        source: str,
        payload: "Any",  # Type should be BaseEventPayload but using Any to avoid circular import
        status: EventStatus = EventStatus.PROGRESS,
        operation_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> None:
        """Emit an event with typed payload validation.

        This method provides type-safe event emission by validating the payload
        against a Pydantic model before creating the event. The payload is
        converted to metadata for storage.

        Args:
            event_type: Event type (e.g., "indexing.started")
            source: Source component
            payload: Typed Pydantic payload model (must have to_metadata() method)
            status: Event status
            operation_id: Optional operation ID (defaults to correlation ID)
            session_id: Optional session ID

        Example:
            >>> from agentic_inquiry.events.payloads import IndexingStartedPayload
            >>> payload = IndexingStartedPayload(path="/path", content_type="code")
            >>> await event_system.emit_typed(
            ...     EventTypes.Indexing.STARTED,
            ...     source="pipeline",
            ...     payload=payload
            ... )
        """
        # Extract metadata from payload
        metadata = payload.to_metadata()

        # Use existing emit method with validated metadata
        await self.emit(
            event_type=event_type,
            source=source,
            status=status,
            operation_id=operation_id,
            session_id=session_id,
            **metadata,
        )

    def _should_sample(self, status: EventStatus) -> bool:
        """Determine if event should be sampled (dropped).

        Sampling rules:
        - Never sample STARTED, COMPLETED, or FAILED events
        - Only sample PROGRESS events
        - Keep 1 in N events based on sampling_ratio

        Args:
            status: Event status

        Returns:
            True if event should be dropped, False if it should be kept
        """
        if not self._sampling_enabled:
            return False

        # Never sample important events
        if status in (EventStatus.STARTED, EventStatus.COMPLETED, EventStatus.FAILED):
            return False

        # Sample PROGRESS events
        if status == EventStatus.PROGRESS:
            self._sampling_counter += 1
            # Keep 1 in N events
            if self._sampling_counter % self._sampling_ratio != 0:
                return True

        return False

    async def _writer_loop(self) -> None:
        """Background writer loop that batches and persists events.

        This loop:
        1. Collects events from queue up to batch_size
        2. Waits up to flush_interval for more events
        3. Writes batch to store with exponential backoff retry
        4. Handles errors and continues running
        5. Restarts on errors to ensure reliability

        Design reference: S2-005 in .sessions/deep-architecture-review/010-tasks.md
        """
        batch_size = self.config.events.batch_size
        flush_interval = self.config.events.flush_interval_seconds
        max_retries = getattr(self.config.events, "retry_max_attempts", 5)
        base_delay = getattr(self.config.events, "retry_base_delay_seconds", 0.1)

        # Create retry policy for store writes
        # Note: max_retries is the number of retries (not including initial),
        # so total attempts = max_retries + 1
        retry_policy = RetryPolicy(
            max_attempts=max_retries + 1,
            base_delay=base_delay,
            max_delay=10.0,
            exponential_base=2.0,
            jitter=False,  # Keep deterministic for event ordering
            retryable_exceptions=None,  # Retry on all exceptions
        )

        logger.debug(
            "Writer loop started (batch_size=%d, flush_interval=%s, max_retries=%d, base_delay=%s)",
            batch_size,
            flush_interval,
            max_retries,
            base_delay,
        )

        consecutive_errors = 0
        max_consecutive_errors = 5

        try:
            while not self._shutdown:
                batch: list[Event] = []

                try:
                    # Collect events up to batch_size or flush_interval
                    deadline = asyncio.get_running_loop().time() + flush_interval

                    while len(batch) < batch_size and not self._shutdown:
                        timeout = max(0, deadline - asyncio.get_running_loop().time())

                        if timeout <= 0:
                            # Flush interval reached
                            break

                        try:
                            event = await asyncio.wait_for(
                                self._queue.get(), timeout=timeout
                            )
                            batch.append(event)
                        except asyncio.TimeoutError:
                            # Flush interval reached
                            break

                    # Write batch if we have events
                    if batch:
                        try:
                            # Record start time for performance monitoring
                            start_time = time.time()

                            # Use retry policy for store writes
                            await retry_policy.execute(self.store.store_events, batch)

                            # Calculate duration and log warning if exceeds threshold
                            duration_ms = (time.time() - start_time) * 1000
                            if duration_ms > 50:
                                logger.warning(
                                    "EventStore write took %.2fms (threshold: 50ms) for batch of %d events",
                                    duration_ms,
                                    len(batch),
                                )

                            logger.debug(
                                "Wrote batch of %d events in %.2fms",
                                len(batch),
                                duration_ms,
                            )
                            # Reset error counter on success
                            consecutive_errors = 0
                        except Exception as e:
                            # Max retries exceeded - drop batch and log error
                            logger.error(
                                "EventStore write failed after %d attempts, dropping batch of %d events: %s",
                                max_retries,
                                len(batch),
                                e,
                                exc_info=True,
                            )
                            self.events_dropped_count += len(batch)
                            consecutive_errors += 1

                        # Check for too many consecutive batch failures
                        if consecutive_errors >= max_consecutive_errors:
                            logger.error(
                                "Too many consecutive batch failures (%d), backing off",
                                consecutive_errors,
                            )
                            await asyncio.sleep(1.0)
                            consecutive_errors = 0  # Reset after backoff

                except asyncio.CancelledError:
                    # Task was cancelled - exit gracefully
                    logger.debug("Writer loop cancelled")
                    raise
                except Exception as e:
                    consecutive_errors += 1
                    logger.error(
                        "Error in writer loop (attempt %d/%d): %s",
                        consecutive_errors,
                        max_consecutive_errors,
                        e,
                        exc_info=True,
                    )

                    # Back off on repeated errors
                    if consecutive_errors >= max_consecutive_errors:
                        logger.error(
                            "Too many consecutive errors (%d), backing off",
                            consecutive_errors,
                        )
                        await asyncio.sleep(1.0)
                        consecutive_errors = 0  # Reset after backoff
                    else:
                        # Short delay before retry
                        await asyncio.sleep(0.1)
        finally:
            # Flush remaining events on shutdown
            remaining: list[Event] = []
            while not self._queue.empty():
                try:
                    remaining.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            if remaining:
                try:
                    await self.store.store_events(remaining)
                    logger.debug(
                        "Flushed %d remaining events on shutdown", len(remaining)
                    )
                except Exception as e:
                    logger.error(
                        "Error flushing remaining events: %s", e, exc_info=True
                    )

            logger.debug("Writer loop stopped")

    async def _cleanup_loop(self) -> None:
        """Background cleanup loop that periodically purges old events.

        This loop:
        1. Waits for the configured cleanup interval
        2. Calls store.cleanup_old_events with configured retention period
        3. Calls store.vacuum to reclaim disk space
        4. Logs the number of events purged
        5. Handles errors and continues running
        """
        cleanup_interval_hours = getattr(
            self.config.events, "cleanup_interval_hours", 24
        )
        retention_days = getattr(self.config.events, "retention_days", 30)
        cleanup_interval_seconds = cleanup_interval_hours * 3600

        logger.debug(
            "Cleanup loop started (interval=%s hours, retention=%s days)",
            cleanup_interval_hours,
            retention_days,
        )

        try:
            while not self._shutdown:
                # Wait for cleanup interval
                try:
                    await asyncio.sleep(cleanup_interval_seconds)
                except asyncio.CancelledError:
                    logger.debug("Cleanup loop cancelled during sleep")
                    raise

                if self._shutdown:
                    break

                # Run cleanup
                try:
                    logger.info("Starting periodic event cleanup")

                    # Delete old events
                    deleted_count = await self.store.cleanup_old_events(retention_days)

                    # Vacuum database to reclaim space
                    await self.store.vacuum()

                    logger.info(
                        "Periodic cleanup completed: purged %d events older than %d days",
                        deleted_count,
                        retention_days,
                    )

                except Exception as e:
                    logger.error("Error during periodic cleanup: %s", e, exc_info=True)
                    # Continue running despite errors

        except asyncio.CancelledError:
            logger.debug("Cleanup loop cancelled")
            raise
        except Exception as e:
            logger.error("Unexpected error in cleanup loop: %s", e, exc_info=True)
        finally:
            logger.debug("Cleanup loop stopped")

    @property
    def queue_depth(self) -> int:
        """Get current queue depth.

        Returns:
            Number of events in queue
        """
        return self._queue.qsize()

    def get_stats(self) -> Dict[str, Any]:
        """Get event system statistics.

        Returns:
            Dictionary with metrics
        """
        return {
            "events_emitted_count": self.events_emitted_count,
            "events_dropped_count": self.events_dropped_count,
            "queue_depth": self.queue_depth,
            "writer_running": self._writer_task is not None
            and not self._writer_task.done(),
            "sampling_active": self._sampling_enabled,
            "sampling_enabled": self._sampling_enabled,
            "sampled_count": self._sampled_count,
        }

    async def flush(self, timeout: float = 5.0) -> int:
        """Flush pending events from queue.

        Args:
            timeout: Maximum time to wait for flush (seconds)

        Returns:
            Number of events flushed
        """
        initial_depth = self.queue_depth

        # Wait for queue to drain
        try:
            deadline = asyncio.get_running_loop().time() + timeout
            while self.queue_depth > 0:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(0.1, remaining))
        except Exception as e:
            logger.error("Error during flush: %s", e)

        return initial_depth - self.queue_depth

    async def __aenter__(self) -> "EventSystem":
        """Async context manager entry."""
        # start() is idempotent, so safe to call even if already started
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.stop()
        # Give event loop a chance to clean up any remaining tasks
        await asyncio.sleep(0.01)
