"""Index state detection utilities for MCP responses.

This module provides utilities for detecting the current state of project indices
and calculating estimated time of arrival (ETA) for indexing operations.

The main function `detect_index_state()` returns an `IndexStateInfo` object that
describes whether the index is actively indexing, sparse, stale, or ready.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from agentic_inquiry.database.lancedb_manager import LanceDBManager
    from agentic_inquiry.events.store import EventStore

logger = logging.getLogger(__name__)


def is_indexing_stale(
    last_progress_time: Optional[datetime],
    start_time: datetime,
    max_stale_seconds: int = 300,
) -> bool:
    """Detect hung indexing (no progress in max_stale_seconds).

    This function determines if an indexing operation appears stuck by
    checking how long it has been since the last progress event (or since
    start if no progress events have occurred).

    Args:
        last_progress_time: Timestamp of last FILE_INDEXED event, or None
            if no progress events have been recorded yet
        start_time: When the operation started (used as fallback if no
            progress time is available)
        max_stale_seconds: Seconds without progress before considered stale
            (default: 300 seconds / 5 minutes)

    Returns:
        True if indexing appears stuck (no progress > max_stale_seconds)

    Examples:
        >>> from datetime import datetime, timedelta, timezone
        >>> now = datetime.now(timezone.utc)
        >>> old_time = now - timedelta(seconds=400)
        >>> is_indexing_stale(old_time, old_time, max_stale_seconds=300)
        True
        >>> recent_time = now - timedelta(seconds=60)
        >>> is_indexing_stale(recent_time, old_time, max_stale_seconds=300)
        False
    """
    # Use last progress time if available, otherwise start time
    reference_time = last_progress_time or start_time

    # Get current time - always use timezone-aware UTC
    now = datetime.now(timezone.utc)

    # Handle naive (non-timezone-aware) reference time by assuming UTC
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)

    elapsed = (now - reference_time).total_seconds()
    return elapsed > max_stale_seconds


class IndexState(str, Enum):
    """Current state of the project index.

    States:
        INDEXING: Actively indexing files
        EMBEDDING: Chunks stored but embeddings still generating (server-side)
        SPARSE: Too few chunks indexed (< threshold)
        STALE: Indexing appears stuck (no progress > max_stale_seconds)
        READY: Index is healthy and complete
    """

    INDEXING = "indexing"
    EMBEDDING = "embedding"
    SPARSE = "sparse"
    STALE = "stale"
    READY = "ready"


@dataclass
class IndexStateInfo:
    """Information about the current index state.

    Attributes:
        status: Current state of the index
        progress_percent: Progress percentage (0-100) if indexing
        eta_seconds: Estimated seconds remaining if indexing
        indexed_so_far: Number of chunks or files indexed so far
        total_discovered: Total items discovered for indexing
        message: Human-readable status message
    """

    status: IndexState
    progress_percent: Optional[float] = None
    eta_seconds: Optional[int] = None
    indexed_so_far: int = 0
    total_discovered: Optional[int] = None
    message: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dict, excluding None values.

        Returns:
            Dictionary representation with only non-None values
        """
        result: dict = {"status": self.status.value}
        if self.progress_percent is not None:
            result["progress_percent"] = round(self.progress_percent, 1)
        if self.eta_seconds is not None:
            result["eta_seconds"] = self.eta_seconds
        if self.indexed_so_far > 0:
            result["indexed_so_far"] = self.indexed_so_far
        if self.total_discovered is not None:
            result["total_discovered"] = self.total_discovered
        if self.message:
            result["message"] = self.message
        return result


def estimate_indexing_eta(
    files_processed: int,
    total_files: int,
    start_time: datetime,
    current_time: Optional[datetime] = None,
) -> Optional[int]:
    """Estimate seconds remaining for indexing to complete.

    Uses a simple rate calculation based on files processed divided by
    elapsed time. For more accurate estimates with varying processing
    rates, consider using a rolling average.

    Args:
        files_processed: Number of files processed so far
        total_files: Total number of files to process
        start_time: When indexing started (UTC)
        current_time: Current time for calculation (defaults to now UTC)

    Returns:
        Estimated seconds remaining, or None if:
        - Less than 5 seconds have elapsed (insufficient data)
        - No files have been processed yet
        - Processing rate is 0 or negative
        - files_processed >= total_files (already complete)

    Examples:
        >>> from datetime import datetime, timedelta
        >>> start = datetime.now(timezone.utc) - timedelta(seconds=10)
        >>> estimate_indexing_eta(10, 100, start)  # 10 files in 10s = 1 file/s
        90  # 90 files remaining / 1 file per second
    """
    if current_time is None:
        current_time = datetime.now(timezone.utc)

    # Handle timezone-aware vs naive datetime comparison
    if start_time.tzinfo is None:
        # Assume UTC if naive
        elapsed = (current_time.replace(tzinfo=None) - start_time).total_seconds()
    else:
        elapsed = (current_time - start_time).total_seconds()

    # Need at least 5 seconds of data for meaningful estimate
    if elapsed < 5:
        logger.debug(
            "Insufficient elapsed time for ETA: %.2f seconds", elapsed
        )
        return None

    if files_processed <= 0:
        logger.debug("No files processed yet, cannot estimate ETA")
        return None

    # Calculate rate (files per second)
    rate = files_processed / elapsed
    if rate <= 0:
        logger.debug("Processing rate is zero or negative")
        return None

    files_remaining = total_files - files_processed
    if files_remaining <= 0:
        return 0

    eta_seconds = int(files_remaining / rate)
    logger.debug(
        "ETA calculation: %d files remaining / %.2f files/sec = %d seconds",
        files_remaining,
        rate,
        eta_seconds,
    )
    return eta_seconds


async def detect_index_state(
    db_manager: "LanceDBManager",
    event_store: "EventStore",
    project_id: str,
    sparse_threshold: int = 50,
    max_stale_seconds: int = 300,
) -> IndexStateInfo:
    """Detect the current state of the project index.

    This function checks for active indexing operations first, then falls
    back to checking chunk counts to determine the index state.

    Args:
        db_manager: Database manager for querying chunk counts
        event_store: Event store for querying active operations
        project_id: Project to check
        sparse_threshold: Minimum chunks for READY state (default: 50)
        max_stale_seconds: Seconds without progress before STALE (default: 300)

    Returns:
        IndexStateInfo with current state and details

    State Detection Logic:
        1. Query event_store for recent indexing.started events
        2. For each started operation, check if completed/failed
        3. If active operation exists:
           - Check if stale (no progress > max_stale_seconds)
           - Calculate progress_percent and eta
           - Return INDEXING or STALE
        4. If no active operation:
           - Query chunk count from db_manager
           - Return SPARSE if < threshold, READY if >= threshold
    """
    logger.debug("Detecting index state for project %s", project_id)
    current_time = datetime.now(timezone.utc)

    # Step 1: Check for active indexing operations
    try:
        # Get recent indexing.started events (last hour)
        started_events = await event_store.get_events_by_type(
            event_type="indexing.started",
            project_id=project_id,
            limit=10,
        )

        # Check each started event to see if it's still active
        for started_event in started_events:
            operation_id = started_event.operation_id
            if not operation_id:
                continue

            # Get operation status to check if completed/failed
            op_status = await event_store.get_operation_status(
                operation_id=operation_id,
                project_id=project_id,
            )

            # Check if operation is still in progress
            if op_status.get("status") in ("started", "progress"):
                # Active indexing operation found
                logger.debug(
                    "Active indexing operation found: %s", operation_id
                )

                # Extract progress info from metadata
                metadata = started_event.metadata or {}
                total_files = metadata.get("file_count", 0)
                files_processed = metadata.get("files_processed", 0)

                # Get latest progress event for this operation
                progress_events = await event_store.get_events_by_type(
                    event_type="indexing.progress",
                    project_id=project_id,
                    limit=100,
                )

                # Find progress events for this operation
                for progress_event in progress_events:
                    if progress_event.operation_id == operation_id:
                        progress_metadata = progress_event.metadata or {}
                        files_processed = progress_metadata.get(
                            "files_processed", files_processed
                        )
                        total_files = progress_metadata.get(
                            "total_files",
                            progress_metadata.get("file_count", total_files),
                        )
                        break

                # Parse start time from the started event (needed for both
                # stale detection and ETA calculation)
                start_timestamp = started_event.timestamp
                if isinstance(start_timestamp, str):
                    try:
                        start_time = datetime.fromisoformat(
                            start_timestamp.replace("Z", "+00:00")
                        )
                    except ValueError:
                        start_time = datetime.fromtimestamp(
                            float(start_timestamp), tz=timezone.utc
                        )
                elif isinstance(start_timestamp, (int, float)):
                    start_time = datetime.fromtimestamp(
                        start_timestamp, tz=timezone.utc
                    )
                else:
                    start_time = start_timestamp

                if start_time.tzinfo is None:
                    start_time = start_time.replace(tzinfo=timezone.utc)

                # Check for stale operation (no progress in max_stale_seconds)
                # Parse last progress time from op_status
                last_progress_time: Optional[datetime] = None
                last_event_time = op_status.get("end_time")
                if last_event_time:
                    # Parse timestamp if it's a string
                    if isinstance(last_event_time, str):
                        try:
                            last_progress_time = datetime.fromisoformat(
                                last_event_time.replace("Z", "+00:00")
                            )
                        except ValueError:
                            # Fallback: assume Unix timestamp
                            last_progress_time = datetime.fromtimestamp(
                                float(last_event_time), tz=timezone.utc
                            )
                    elif isinstance(last_event_time, (int, float)):
                        last_progress_time = datetime.fromtimestamp(
                            last_event_time, tz=timezone.utc
                        )
                    else:
                        last_progress_time = last_event_time

                    # Ensure timezone aware
                    if last_progress_time.tzinfo is None:
                        last_progress_time = last_progress_time.replace(
                            tzinfo=timezone.utc
                        )

                # Use helper function to detect stale indexing
                if is_indexing_stale(
                    last_progress_time=last_progress_time,
                    start_time=start_time,
                    max_stale_seconds=max_stale_seconds,
                ):
                    # Calculate elapsed time for logging
                    reference_time = last_progress_time or start_time
                    seconds_since_progress = (
                        current_time - reference_time
                    ).total_seconds()

                    logger.warning(
                        "Indexing operation %s appears stale: %d seconds "
                        "since last progress",
                        operation_id,
                        int(seconds_since_progress),
                    )
                    return IndexStateInfo(
                        status=IndexState.STALE,
                        indexed_so_far=files_processed,
                        total_discovered=total_files if total_files > 0 else None,
                        message=(
                            f"Indexing appears stuck (no progress in "
                            f"{max_stale_seconds // 60} minutes). "
                            "Consider restarting with add_knowledge(force_reindex=true)."
                        ),
                    )

                # Calculate progress and ETA
                progress_percent: Optional[float] = None
                eta_seconds: Optional[int] = None

                if total_files > 0:
                    progress_percent = (files_processed / total_files) * 100

                    eta_seconds = estimate_indexing_eta(
                        files_processed=files_processed,
                        total_files=total_files,
                        start_time=start_time,
                        current_time=current_time,
                    )

                return IndexStateInfo(
                    status=IndexState.INDEXING,
                    progress_percent=progress_percent,
                    eta_seconds=eta_seconds,
                    indexed_so_far=files_processed,
                    total_discovered=total_files if total_files > 0 else None,
                    message=_format_indexing_message(
                        files_processed, total_files, eta_seconds
                    ),
                )

    except Exception as e:
        logger.error(
            "Error checking indexing events for project %s: %s",
            project_id,
            e,
            exc_info=True,
        )
        # Fall through to chunk count check

    # Step 2: Check for embedding-in-progress state (indexing.stored without indexing.ready)
    try:
        stored_events = await event_store.get_events_by_type(
            event_type="indexing.stored",
            project_id=project_id,
            limit=1,
        )
        if stored_events:
            # Check if a corresponding indexing.ready event exists
            ready_events = await event_store.get_events_by_type(
                event_type="indexing.ready",
                project_id=project_id,
                limit=1,
            )
            if not ready_events:
                # Also check for legacy indexing.completed as fallback
                completed_events = await event_store.get_events_by_type(
                    event_type="indexing.completed",
                    project_id=project_id,
                    limit=1,
                )
                if not completed_events:
                    stored_meta = stored_events[0].metadata or {}
                    chunks = stored_meta.get("chunks_created", 0)
                    return IndexStateInfo(
                        status=IndexState.EMBEDDING,
                        indexed_so_far=chunks,
                        message=(
                            "Chunks are stored but embeddings are still generating. "
                            "Search results may be incomplete until embedding completes."
                        ),
                    )
    except Exception as e:
        logger.warning(
            "Error checking stored/ready events for project %s: %s",
            project_id,
            e,
        )
        # Fall through to chunk count check

    # Step 3: No active indexing - check chunk count
    try:
        chunk_count = await db_manager.count_records(
            table_name="document_chunks",
            project_id=project_id,
        )
        logger.debug(
            "Project %s has %d chunks (threshold: %d)",
            project_id,
            chunk_count,
            sparse_threshold,
        )
    except Exception as e:
        logger.warning(
            "Error getting chunk count for project %s: %s — assuming data may exist",
            project_id,
            e,
        )
        # On error, return READY rather than falsely reporting SPARSE/empty
        return IndexStateInfo(
            status=IndexState.READY,
            indexed_so_far=0,
            message="Could not determine chunk count — assuming index is available.",
        )

    if chunk_count < sparse_threshold:
        return IndexStateInfo(
            status=IndexState.SPARSE,
            indexed_so_far=chunk_count,
            message=(
                f"Index has only {chunk_count} chunks. "
                f"Consider indexing more content for better results."
            ),
        )

    return IndexStateInfo(
        status=IndexState.READY,
        indexed_so_far=chunk_count,
        message=f"Index is ready with {chunk_count} chunks.",
        progress_percent=100.0,
    )


def _format_indexing_message(
    files_processed: int,
    total_files: int,
    eta_seconds: Optional[int],
) -> str:
    """Format a human-readable indexing progress message.

    Args:
        files_processed: Number of files processed
        total_files: Total files to process
        eta_seconds: Estimated seconds remaining

    Returns:
        Formatted progress message
    """
    if total_files > 0:
        percent = (files_processed / total_files) * 100
        base_msg = f"Indexing in progress: {files_processed}/{total_files} files ({percent:.1f}%)"
    else:
        base_msg = f"Indexing in progress: {files_processed} files processed"

    if eta_seconds is not None and eta_seconds > 0:
        if eta_seconds < 60:
            time_str = f"{eta_seconds} seconds"
        elif eta_seconds < 3600:
            minutes = eta_seconds // 60
            time_str = f"{minutes} minute{'s' if minutes != 1 else ''}"
        else:
            hours = eta_seconds // 3600
            time_str = f"{hours} hour{'s' if hours != 1 else ''}"
        return f"{base_msg}. ETA: {time_str}"

    return base_msg


__all__ = [
    "IndexState",
    "IndexStateInfo",
    "detect_index_state",
    "estimate_indexing_eta",
    "is_indexing_stale",
]
