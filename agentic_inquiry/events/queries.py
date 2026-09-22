"""Event query utilities for indexing operations.

This module provides high-level query functions for tracking active indexing
operations and their progress. These functions build on the EventStore.query_events
method to provide convenient access to operation status.

Example:
    >>> from agentic_inquiry.events import EventStore
    >>> from agentic_inquiry.events.queries import query_active_indexing_operations
    >>>
    >>> store = EventStore.from_config(config, project_id="my_project")
    >>> await store.initialize()
    >>>
    >>> # Find all active indexing operations
    >>> active_ops = await query_active_indexing_operations(store, "my_project")
    >>> for op in active_ops:
    ...     print(f"Operation {op.operation_id}: {op.files_processed}/{op.files_discovered}")
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from agentic_inquiry.events.store import EventStore

from agentic_inquiry.events.types import EventTypes

logger = logging.getLogger(__name__)


@dataclass
class ActiveIndexingOperation:
    """Information about an active indexing operation.

    Attributes:
        operation_id: Unique identifier for the operation
        project_id: Project the operation belongs to
        start_time: When the operation started
        files_discovered: Total files to be indexed (from STARTED event)
        files_processed: Files indexed so far (count of FILE_INDEXED events)
        last_progress_time: Timestamp of most recent progress event
    """

    operation_id: str
    project_id: str
    start_time: datetime
    files_discovered: int
    files_processed: int
    last_progress_time: Optional[datetime] = None


async def query_active_indexing_operations(
    event_store: "EventStore",
    project_id: str,
    max_age_hours: int = 1,
) -> List[ActiveIndexingOperation]:
    """Find indexing operations that are currently in progress.

    An operation is "active" if:
    - Has a STARTED event
    - Does NOT have a matching COMPLETED or FAILED event
    - Started within max_age_hours

    Args:
        event_store: Event store to query
        project_id: Project to filter by
        max_age_hours: Ignore operations older than this (default: 1 hour)

    Returns:
        List of active indexing operations with metadata

    Example:
        >>> active_ops = await query_active_indexing_operations(store, "my_project")
        >>> for op in active_ops:
        ...     print(f"Operation {op.operation_id} started at {op.start_time}")
        ...     print(f"  Progress: {op.files_processed}/{op.files_discovered}")
    """
    # Calculate cutoff time as Unix timestamp
    cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    cutoff_timestamp = cutoff_dt.timestamp()

    # Query for STARTED events within the time window
    started_events = await event_store.query_events(
        event_type=EventTypes.Indexing.STARTED,
        min_timestamp=cutoff_timestamp,
        order_by="timestamp",
        order_direction="desc",
        limit=100,
        project_id=project_id,
    )

    if not started_events:
        return []

    # Collect operation IDs from started events
    operation_ids = {
        e.operation_id for e in started_events
        if e.operation_id is not None
    }

    if not operation_ids:
        return []

    # Query for COMPLETED events for these operations
    completed_events = await event_store.query_events(
        event_type=EventTypes.Indexing.COMPLETED,
        min_timestamp=cutoff_timestamp,
        order_by="timestamp",
        order_direction="desc",
        limit=1000,
        project_id=project_id,
    )

    # Query for FAILED events for these operations
    failed_events = await event_store.query_events(
        event_type=EventTypes.Indexing.FAILED,
        min_timestamp=cutoff_timestamp,
        order_by="timestamp",
        order_direction="desc",
        limit=1000,
        project_id=project_id,
    )

    # Collect operation IDs that have completed or failed
    finished_operation_ids = {
        e.operation_id for e in completed_events
        if e.operation_id is not None
    }
    finished_operation_ids.update({
        e.operation_id for e in failed_events
        if e.operation_id is not None
    })

    # Filter to only active operations
    active_operation_ids = operation_ids - finished_operation_ids

    if not active_operation_ids:
        return []

    # Build ActiveIndexingOperation for each active operation
    active_operations: List[ActiveIndexingOperation] = []

    for started_event in started_events:
        if started_event.operation_id not in active_operation_ids:
            continue

        # Extract metadata from STARTED event
        metadata = started_event.metadata or {}
        files_discovered = metadata.get("file_count", 0)

        # Get count of FILE_INDEXED events for this operation
        file_indexed_events = await event_store.query_events(
            event_type=EventTypes.Indexing.FILE_INDEXED,
            filters={"operation_id": started_event.operation_id},
            order_by="timestamp",
            order_direction="desc",
            limit=10000,  # Get all to count
            project_id=project_id,
        )
        files_processed = len(file_indexed_events)

        # Get last progress timestamp efficiently
        last_progress_time = await get_last_progress_timestamp(
            event_store,
            started_event.operation_id,
            project_id,
        )

        # Convert start_time from Unix timestamp to datetime
        start_time = datetime.fromtimestamp(started_event.timestamp, tz=timezone.utc)

        active_operations.append(ActiveIndexingOperation(
            operation_id=started_event.operation_id,
            project_id=project_id,
            start_time=start_time,
            files_discovered=files_discovered,
            files_processed=files_processed,
            last_progress_time=last_progress_time,
        ))

    return active_operations


async def get_last_progress_timestamp(
    event_store: "EventStore",
    operation_id: str,
    project_id: Optional[str] = None,
) -> Optional[datetime]:
    """Get timestamp of most recent progress event for an operation.

    IMPORTANT: This function is O(1), not O(n) where n = files processed.
    It uses limit=1 and order_by=timestamp desc to avoid loading thousands
    of FILE_INDEXED events into memory.

    Args:
        event_store: Event store to query
        operation_id: Operation ID to query
        project_id: Optional project ID filter

    Returns:
        Timestamp of most recent FILE_INDEXED event, or None if no progress events

    Example:
        >>> last_progress = await get_last_progress_timestamp(store, "op_123")
        >>> if last_progress:
        ...     print(f"Last progress at: {last_progress}")
    """
    events = await event_store.query_events(
        event_type=EventTypes.Indexing.FILE_INDEXED,
        filters={"operation_id": operation_id},
        order_by="timestamp",
        order_direction="desc",
        limit=1,  # Only get the most recent one - O(1)
        project_id=project_id,
    )

    if events:
        return datetime.fromtimestamp(events[0].timestamp, tz=timezone.utc)

    return None


async def get_operation_progress(
    event_store: "EventStore",
    operation_id: str,
    project_id: Optional[str] = None,
) -> dict:
    """Get detailed progress information for an indexing operation.

    This function provides comprehensive progress information including
    start time, files processed, and any errors encountered.

    Args:
        event_store: Event store to query
        operation_id: Operation ID to query
        project_id: Optional project ID filter

    Returns:
        Dictionary with operation progress:
        - operation_id: The operation ID
        - status: "started", "in_progress", "completed", or "failed"
        - start_time: When the operation started
        - end_time: When the operation ended (if completed/failed)
        - files_discovered: Total files to be indexed
        - files_processed: Files indexed so far
        - files_failed: Files that failed to index
        - last_progress_time: Timestamp of most recent progress
        - error_message: Error message if failed

    Example:
        >>> progress = await get_operation_progress(store, "op_123")
        >>> print(f"Status: {progress['status']}")
        >>> print(f"Progress: {progress['files_processed']}/{progress['files_discovered']}")
    """
    # Get all events for this operation
    all_events = await event_store.get_operation_events(
        operation_id=operation_id,
        project_id=project_id,
    )

    if not all_events:
        return {
            "operation_id": operation_id,
            "status": "unknown",
            "start_time": None,
            "end_time": None,
            "files_discovered": 0,
            "files_processed": 0,
            "files_failed": 0,
            "last_progress_time": None,
            "error_message": None,
        }

    # Find key events
    started_event = None
    completed_event = None
    failed_event = None
    file_indexed_count = 0
    file_failed_count = 0
    last_progress_timestamp = 0.0

    for event in all_events:
        if event.event_type == EventTypes.Indexing.STARTED:
            started_event = event
        elif event.event_type == EventTypes.Indexing.COMPLETED:
            completed_event = event
        elif event.event_type == EventTypes.Indexing.FAILED:
            failed_event = event
        elif event.event_type == EventTypes.Indexing.FILE_INDEXED:
            file_indexed_count += 1
            if event.timestamp > last_progress_timestamp:
                last_progress_timestamp = event.timestamp
        elif event.event_type == EventTypes.Indexing.FILE_FAILED:
            file_failed_count += 1

    # Determine status
    if failed_event:
        status = "failed"
    elif completed_event:
        status = "completed"
    elif file_indexed_count > 0:
        status = "in_progress"
    elif started_event:
        status = "started"
    else:
        status = "unknown"

    # Extract metadata
    files_discovered = 0
    if started_event and started_event.metadata:
        files_discovered = started_event.metadata.get("file_count", 0)

    error_message = None
    if failed_event and failed_event.metadata:
        error_message = failed_event.metadata.get("error", None)

    # Convert timestamps to datetime
    start_time = None
    if started_event:
        start_time = datetime.fromtimestamp(started_event.timestamp, tz=timezone.utc)

    end_time = None
    if completed_event:
        end_time = datetime.fromtimestamp(completed_event.timestamp, tz=timezone.utc)
    elif failed_event:
        end_time = datetime.fromtimestamp(failed_event.timestamp, tz=timezone.utc)

    last_progress_time = None
    if last_progress_timestamp > 0:
        last_progress_time = datetime.fromtimestamp(last_progress_timestamp, tz=timezone.utc)

    return {
        "operation_id": operation_id,
        "status": status,
        "start_time": start_time,
        "end_time": end_time,
        "files_discovered": files_discovered,
        "files_processed": file_indexed_count,
        "files_failed": file_failed_count,
        "last_progress_time": last_progress_time,
        "error_message": error_message,
    }
