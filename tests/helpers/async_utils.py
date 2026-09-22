"""Async testing utilities.

Provides helper functions for async test patterns including condition polling
and cleanup management.
"""

import asyncio
from typing import Any, Callable, TypeVar, Awaitable

T = TypeVar("T")


class AsyncTestHelper:
    """Helper utilities for async testing."""

    @staticmethod
    async def wait_for_condition(
        condition_fn: Callable[[], bool],
        timeout: float = 5.0,
        poll_interval: float = 0.01,
    ) -> bool:
        """Wait for a condition to become true.

        This replaces fixed asyncio.sleep() calls with active polling,
        allowing tests to complete as soon as the condition is met.

        Args:
            condition_fn: Function that returns True when condition is met
            timeout: Maximum time to wait in seconds
            poll_interval: Time between condition checks in seconds

        Returns:
            True if condition was met, False if timeout occurred

        Example:
            >>> async def test_file_indexed():
            ...     await pipeline.index_file("test.py")
            ...     success = await AsyncTestHelper.wait_for_condition(
            ...         lambda: db.count_chunks() > 0,
            ...         timeout=5.0
            ...     )
            ...     assert success, "File was not indexed in time"
        """
        loop = asyncio.get_running_loop()
        start_time = loop.time()
        while loop.time() - start_time < timeout:
            if condition_fn():
                return True
            await asyncio.sleep(poll_interval)
        return False

    @staticmethod
    async def wait_for_async_condition(
        async_fn: Callable[[], Awaitable],
        condition_fn: Callable[[Any], bool],
        timeout: float = 5.0,
        poll_interval: float = 0.05,
    ) -> bool:
        """Wait for an async operation's result to satisfy a condition.

        This is similar to wait_for_condition but supports async operations
        like database queries. It polls the async function until the condition
        is met or timeout occurs.

        Args:
            async_fn: Async function that returns the value to check
            condition_fn: Function that takes the result and returns True if condition is met
            timeout: Maximum time to wait in seconds
            poll_interval: Time between condition checks in seconds

        Returns:
            True if condition was met, False if timeout occurred

        Example:
            >>> async def test_events_stored():
            ...     await system.emit("event", source="test")
            ...     success = await AsyncTestHelper.wait_for_async_condition(
            ...         lambda: store.get_latest_events(limit=10),
            ...         lambda events: len(events) == 1,
            ...         timeout=5.0
            ...     )
            ...     assert success, "Event was not stored in time"
        """
        loop = asyncio.get_running_loop()
        start_time = loop.time()
        while loop.time() - start_time < timeout:
            try:
                result = await async_fn()
                if condition_fn(result):
                    return True
            except Exception:
                pass  # Condition not ready yet
            await asyncio.sleep(poll_interval)
        return False

    @staticmethod
    async def ensure_cleanup(*awaitables: Awaitable) -> None:
        """Ensure all async operations complete.

        This is useful in async fixture cleanup to ensure all pending
        operations complete before the fixture is torn down.

        Args:
            *awaitables: Async operations to complete

        Example:
            >>> @pytest.fixture
            ... async def my_fixture():
            ...     resource = await create_resource()
            ...     yield resource
            ...     await AsyncTestHelper.ensure_cleanup(
            ...         resource.close(),
            ...         resource.cleanup()
            ...     )
        """
        await asyncio.gather(*awaitables, return_exceptions=True)
