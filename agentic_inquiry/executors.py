"""Thread pool executor management for async operations.

This module provides dedicated thread pool executors for different workload types
to prevent thread pool exhaustion and ensure isolation between operations.

Usage:
    from agentic_inquiry.executors import get_lancedb_executor, get_embedding_executor

    # In async code
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(get_lancedb_executor(), sync_func, *args)

    # Cleanup on shutdown
    from agentic_inquiry.executors import shutdown_executors
    await shutdown_executors()
"""

import asyncio
import atexit
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

logger = logging.getLogger(__name__)

# Executor instances (lazy initialization)
_lancedb_executor: Optional[ThreadPoolExecutor] = None
_embedding_executor: Optional[ThreadPoolExecutor] = None

# Configuration
# NOTE: Executor workers should be >= semaphore limits to prevent starvation.
# See ``config.py:processing_semaphore_limit`` (default 20) and
# ``graph_builder.py:max_concurrent_batches``. The embedding executor is
# intentionally sized to match the semaphore default — ``get_embedding_executor``
# is a process-global pool and gating file-level concurrency on a smaller
# pool than the semaphore allows means queued files block on executor
# threads that are busy running the PREVIOUS file's embedding. Keep this
# value in lockstep with ``processing_semaphore_limit``; if operators raise
# the semaphore higher than 20, they should either raise this too or accept
# that the effective concurrency is capped at ``min(semaphore, workers)``.
LANCEDB_EXECUTOR_WORKERS = 4  # For DB operations (I/O bound)
EMBEDDING_EXECUTOR_WORKERS = 20  # Aligned with processing_semaphore_limit=20


def get_lancedb_executor() -> ThreadPoolExecutor:
    """Get the dedicated executor for LanceDB operations.

    This executor is used for all LanceDB I/O operations including:
    - Table creation and opening
    - Queries and searches
    - Data insertion and updates
    - Index operations

    Returns:
        ThreadPoolExecutor dedicated to LanceDB operations
    """
    global _lancedb_executor
    if _lancedb_executor is None:
        _lancedb_executor = ThreadPoolExecutor(
            max_workers=LANCEDB_EXECUTOR_WORKERS, thread_name_prefix="lancedb"
        )
        logger.debug(
            "Created LanceDB executor with %d workers", LANCEDB_EXECUTOR_WORKERS
        )
    return _lancedb_executor


def get_embedding_executor() -> ThreadPoolExecutor:
    """Get the dedicated executor for embedding generation.

    This executor is used for CPU-intensive embedding operations:
    - Vector generation from text
    - Batch embedding computation

    Kept separate from LanceDB to prevent blocking DB operations
    during potentially slow embedding generation.

    Returns:
        ThreadPoolExecutor dedicated to embedding operations
    """
    global _embedding_executor
    if _embedding_executor is None:
        _embedding_executor = ThreadPoolExecutor(
            max_workers=EMBEDDING_EXECUTOR_WORKERS, thread_name_prefix="embedding"
        )
        logger.debug(
            "Created embedding executor with %d workers", EMBEDDING_EXECUTOR_WORKERS
        )
    return _embedding_executor


def shutdown_executors(wait: bool = True, cancel_futures: bool = False) -> None:
    """Shutdown all executors synchronously.

    Args:
        wait: If True, wait for pending futures to complete
        cancel_futures: If True, cancel pending futures (Python 3.9+)
    """
    global _lancedb_executor, _embedding_executor

    shutdown_kwargs = {"wait": wait}
    # cancel_futures parameter added in Python 3.9
    import sys

    if sys.version_info >= (3, 9):
        shutdown_kwargs["cancel_futures"] = cancel_futures

    if _lancedb_executor is not None:
        logger.debug("Shutting down LanceDB executor")
        _lancedb_executor.shutdown(**shutdown_kwargs)
        _lancedb_executor = None

    if _embedding_executor is not None:
        logger.debug("Shutting down embedding executor")
        _embedding_executor.shutdown(**shutdown_kwargs)
        _embedding_executor = None

    logger.info("All executors shut down")


async def shutdown_executors_async(
    wait: bool = True, cancel_futures: bool = False
) -> None:
    """Shutdown all executors asynchronously.

    Runs the synchronous shutdown in the default executor to avoid
    blocking the event loop.

    Args:
        wait: If True, wait for pending futures to complete
        cancel_futures: If True, cancel pending futures (Python 3.9+)
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,  # Use default executor for shutdown
        lambda: shutdown_executors(wait=wait, cancel_futures=cancel_futures),
    )


# Register cleanup on interpreter exit
atexit.register(lambda: shutdown_executors(wait=False))


__all__ = [
    "get_lancedb_executor",
    "get_embedding_executor",
    "shutdown_executors",
    "shutdown_executors_async",
    "LANCEDB_EXECUTOR_WORKERS",
    "EMBEDDING_EXECUTOR_WORKERS",
]
