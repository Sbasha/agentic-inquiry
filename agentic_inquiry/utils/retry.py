"""Reusable retry policy with exponential backoff and jitter.

This module provides a flexible retry mechanism for async operations.
It supports configurable backoff strategies, jitter, and exception filtering.

Design reference: S2-005 in .sessions/deep-architecture-review/010-tasks.md

Example Usage:
    >>> # Basic usage with decorator
    >>> @retry(max_attempts=3, base_delay=0.1)
    ... async def unstable_operation():
    ...     await do_something()

    >>> # Using RetryPolicy directly
    >>> policy = RetryPolicy(max_attempts=5, base_delay=0.1, jitter=True)
    >>> result = await policy.execute(unstable_operation)

    >>> # With context manager for retry loop
    >>> policy = RetryPolicy(max_attempts=3)
    >>> async with policy.retry_context() as ctx:
    ...     while ctx.should_retry:
    ...         try:
    ...             await ctx.attempt(operation)
    ...             break
    ...         except Exception:
    ...             await ctx.handle_failure()
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Awaitable, Callable, Optional, Tuple, Type, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Default exceptions to retry on
DEFAULT_RETRYABLE_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


@dataclass
class RetryPolicy:
    """Configurable retry policy with exponential backoff and jitter.

    This class encapsulates retry logic that can be reused across components.
    It supports:
    - Configurable max attempts and delays
    - Exponential backoff with optional caps
    - Randomized jitter to prevent thundering herd
    - Exception filtering for selective retry

    Attributes:
        max_attempts: Maximum number of attempts (includes initial attempt)
        base_delay: Initial delay in seconds before first retry
        max_delay: Maximum delay cap in seconds (None = no cap)
        exponential_base: Base for exponential backoff calculation
        jitter: Whether to add randomized jitter to delays
        jitter_factor: Maximum jitter as fraction of delay (0.0-1.0)
        retryable_exceptions: Tuple of exception types to retry on
            If None, retries on all exceptions.

    Example:
        >>> policy = RetryPolicy(
        ...     max_attempts=5,
        ...     base_delay=0.1,
        ...     max_delay=10.0,
        ...     jitter=True,
        ... )
        >>> result = await policy.execute(my_async_function, arg1, arg2)
    """

    max_attempts: int = 3
    base_delay: float = 0.1
    max_delay: Optional[float] = 30.0
    exponential_base: float = 2.0
    jitter: bool = False
    jitter_factor: float = 0.25
    retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay for a given attempt number.

        Uses exponential backoff: delay = base_delay * (exponential_base ** attempt)
        Optionally adds jitter and caps at max_delay.

        Args:
            attempt: Zero-indexed attempt number (0 = first retry after initial failure)

        Returns:
            Delay in seconds before the next retry
        """
        # Calculate exponential backoff
        delay = self.base_delay * (self.exponential_base**attempt)

        # Apply max delay cap
        if self.max_delay is not None:
            delay = min(delay, self.max_delay)

        # Apply jitter if enabled
        if self.jitter:
            jitter_amount = delay * self.jitter_factor * random.random()
            # Randomly add or subtract jitter
            if random.random() < 0.5:
                delay -= jitter_amount
            else:
                delay += jitter_amount

        return max(0.0, delay)

    def should_retry_exception(self, exc: Exception) -> bool:
        """Check if an exception should trigger a retry.

        Args:
            exc: The exception that was raised

        Returns:
            True if the operation should be retried
        """
        if self.retryable_exceptions is None:
            # Retry on all exceptions
            return True
        return isinstance(exc, self.retryable_exceptions)

    async def execute(
        self,
        operation: Callable[..., Awaitable[T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Execute an operation with retry logic.

        Args:
            operation: Async callable to execute
            *args: Positional arguments for operation
            **kwargs: Keyword arguments for operation

        Returns:
            Result of the operation

        Raises:
            Exception: The last exception if all retries are exhausted
        """
        last_exception: Optional[Exception] = None

        for attempt in range(self.max_attempts):
            try:
                return await operation(*args, **kwargs)
            except asyncio.CancelledError:
                # Don't retry on cancellation
                raise
            except Exception as e:
                last_exception = e

                if not self.should_retry_exception(e):
                    raise

                if attempt < self.max_attempts - 1:
                    delay = self.calculate_delay(attempt)
                    logger.warning(
                        "Operation failed (attempt %d/%d), retrying in %.2fs: %s",
                        attempt + 1,
                        self.max_attempts,
                        delay,
                        e,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Operation failed after %d attempts: %s",
                        self.max_attempts,
                        e,
                    )

        # This should only be reached if max_attempts is 0 or all attempts failed
        if last_exception is not None:
            raise last_exception
        raise RuntimeError("Retry loop exited without success or exception")


@dataclass
class RetryContext:
    """Context for manual retry loop control.

    This class provides a more flexible way to handle retries when
    the simple execute() pattern doesn't fit, such as when you need
    custom logic between retries or want to handle specific failures.

    Example:
        >>> policy = RetryPolicy(max_attempts=3)
        >>> ctx = RetryContext(policy)
        >>> while ctx.should_retry:
        ...     try:
        ...         result = await operation()
        ...         break
        ...     except Exception as e:
        ...         await ctx.handle_failure(e)
    """

    policy: RetryPolicy
    attempt: int = field(default=0, init=False)
    last_exception: Optional[Exception] = field(default=None, init=False)

    @property
    def should_retry(self) -> bool:
        """Check if more retry attempts are available."""
        return self.attempt < self.policy.max_attempts

    @property
    def is_last_attempt(self) -> bool:
        """Check if this is the final attempt."""
        return self.attempt >= self.policy.max_attempts - 1

    async def handle_failure(self, exc: Optional[Exception] = None) -> None:
        """Handle a failed attempt.

        Increments the attempt counter, logs the failure, and waits
        for the appropriate backoff delay if more retries are available.

        Args:
            exc: The exception that caused the failure (optional)
        """
        self.last_exception = exc
        self.attempt += 1

        if self.should_retry:
            delay = self.policy.calculate_delay(self.attempt - 1)
            logger.warning(
                "Attempt %d/%d failed, retrying in %.2fs: %s",
                self.attempt,
                self.policy.max_attempts,
                delay,
                exc or "unknown error",
            )
            await asyncio.sleep(delay)
        else:
            logger.error(
                "All %d attempts exhausted: %s",
                self.policy.max_attempts,
                exc or "unknown error",
            )

    def reset(self) -> None:
        """Reset the retry context for reuse."""
        self.attempt = 0
        self.last_exception = None


def retry(
    max_attempts: int = 3,
    base_delay: float = 0.1,
    max_delay: Optional[float] = 30.0,
    exponential_base: float = 2.0,
    jitter: bool = False,
    jitter_factor: float = 0.25,
    retryable_exceptions: Optional[Tuple[Type[Exception], ...]] = None,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator for adding retry logic to async functions.

    Args:
        max_attempts: Maximum number of attempts (includes initial attempt)
        base_delay: Initial delay in seconds before first retry
        max_delay: Maximum delay cap in seconds
        exponential_base: Base for exponential backoff calculation
        jitter: Whether to add randomized jitter to delays
        jitter_factor: Maximum jitter as fraction of delay
        retryable_exceptions: Exception types to retry on (None = all)

    Returns:
        Decorator function

    Example:
        >>> @retry(max_attempts=5, jitter=True)
        ... async def fetch_data():
        ...     return await api.get_data()
    """
    policy = RetryPolicy(
        max_attempts=max_attempts,
        base_delay=base_delay,
        max_delay=max_delay,
        exponential_base=exponential_base,
        jitter=jitter,
        jitter_factor=jitter_factor,
        retryable_exceptions=retryable_exceptions,
    )

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            return await policy.execute(func, *args, **kwargs)

        return wrapper

    return decorator


# Convenience factory functions for common retry patterns


def create_database_retry_policy(
    max_attempts: int = 3,
    base_delay: float = 0.1,
) -> RetryPolicy:
    """Create a retry policy optimized for database operations.

    Uses shorter delays and retries on database lock errors.

    Args:
        max_attempts: Maximum retry attempts
        base_delay: Initial delay in seconds

    Returns:
        RetryPolicy configured for database operations
    """
    return RetryPolicy(
        max_attempts=max_attempts,
        base_delay=base_delay,
        max_delay=2.0,  # Short max delay for DB operations
        exponential_base=2.0,
        jitter=True,  # Prevent lock contention
        jitter_factor=0.3,
        retryable_exceptions=None,  # Retry on all exceptions, caller filters
    )


def create_network_retry_policy(
    max_attempts: int = 5,
    base_delay: float = 0.5,
) -> RetryPolicy:
    """Create a retry policy optimized for network operations.

    Uses longer delays and retries on connection/timeout errors.

    Args:
        max_attempts: Maximum retry attempts
        base_delay: Initial delay in seconds

    Returns:
        RetryPolicy configured for network operations
    """
    return RetryPolicy(
        max_attempts=max_attempts,
        base_delay=base_delay,
        max_delay=60.0,  # Longer max for network issues
        exponential_base=2.0,
        jitter=True,
        jitter_factor=0.25,
        retryable_exceptions=DEFAULT_RETRYABLE_EXCEPTIONS,
    )
