"""Unit tests for AsyncTestHelper utilities.

Tests the async testing utilities including condition polling and cleanup.
"""

import pytest

pytestmark = pytest.mark.unit

import asyncio
from tests.helpers.async_utils import AsyncTestHelper


@pytest.mark.unit
class TestWaitForCondition:
    """Tests for wait_for_condition method."""

    async def test_condition_met_immediately(self):
        """Test when condition is already true."""
        result = await AsyncTestHelper.wait_for_condition(lambda: True, timeout=1.0)
        assert result is True

    async def test_condition_met_after_delay(self):
        """Test when condition becomes true after some time."""
        counter = {"value": 0}

        async def increment():
            await asyncio.sleep(0.05)
            counter["value"] = 1

        # Start incrementing in background
        task = asyncio.create_task(increment())

        # Wait for condition
        result = await AsyncTestHelper.wait_for_condition(
            lambda: counter["value"] == 1, timeout=1.0, poll_interval=0.01
        )

        await task
        assert result is True
        assert counter["value"] == 1

    async def test_condition_timeout(self):
        """Test when condition never becomes true."""
        result = await AsyncTestHelper.wait_for_condition(
            lambda: False, timeout=0.1, poll_interval=0.01
        )
        assert result is False

    async def test_custom_poll_interval(self):
        """Test with custom poll interval."""
        counter = {"value": 0}

        async def increment():
            await asyncio.sleep(0.05)
            counter["value"] = 1

        task = asyncio.create_task(increment())

        result = await AsyncTestHelper.wait_for_condition(
            lambda: counter["value"] == 1,
            timeout=1.0,
            poll_interval=0.02,  # Custom interval
        )

        await task
        assert result is True

    async def test_condition_with_exception(self):
        """Test when condition function raises exception."""

        def failing_condition():
            raise ValueError("Test error")

        with pytest.raises(ValueError, match="Test error"):
            await AsyncTestHelper.wait_for_condition(failing_condition, timeout=0.1)

    async def test_multiple_conditions(self):
        """Test waiting for multiple conditions in sequence."""
        state = {"step": 0}

        async def advance_state():
            for i in range(1, 4):
                await asyncio.sleep(0.02)
                state["step"] = i

        task = asyncio.create_task(advance_state())

        # Wait for each step
        result1 = await AsyncTestHelper.wait_for_condition(
            lambda: state["step"] >= 1, timeout=1.0
        )
        result2 = await AsyncTestHelper.wait_for_condition(
            lambda: state["step"] >= 2, timeout=1.0
        )
        result3 = await AsyncTestHelper.wait_for_condition(
            lambda: state["step"] >= 3, timeout=1.0
        )

        await task
        assert all([result1, result2, result3])
        assert state["step"] == 3


@pytest.mark.unit
class TestEnsureCleanup:
    """Tests for ensure_cleanup method."""

    async def test_single_awaitable(self):
        """Test cleanup with single awaitable."""
        completed = {"value": False}

        async def cleanup_task():
            await asyncio.sleep(0.01)
            completed["value"] = True

        await AsyncTestHelper.ensure_cleanup(cleanup_task())
        assert completed["value"] is True

    async def test_multiple_awaitables(self):
        """Test cleanup with multiple awaitables."""
        completed = {"task1": False, "task2": False, "task3": False}

        async def cleanup_task(name: str):
            await asyncio.sleep(0.01)
            completed[name] = True

        await AsyncTestHelper.ensure_cleanup(
            cleanup_task("task1"), cleanup_task("task2"), cleanup_task("task3")
        )

        assert completed["task1"] is True
        assert completed["task2"] is True
        assert completed["task3"] is True

    async def test_cleanup_with_exception(self):
        """Test that exceptions in cleanup don't prevent other cleanups."""
        completed = {"task1": False, "task2": False}

        async def failing_cleanup():
            await asyncio.sleep(0.01)
            raise ValueError("Cleanup failed")

        async def successful_cleanup(name: str):
            await asyncio.sleep(0.01)
            completed[name] = True

        # Should not raise, exceptions are caught
        await AsyncTestHelper.ensure_cleanup(
            successful_cleanup("task1"), failing_cleanup(), successful_cleanup("task2")
        )

        # Both successful cleanups should complete
        assert completed["task1"] is True
        assert completed["task2"] is True

    async def test_empty_cleanup(self):
        """Test cleanup with no awaitables."""
        # Should not raise
        await AsyncTestHelper.ensure_cleanup()

    async def test_cleanup_order_independence(self):
        """Test that cleanup tasks run concurrently."""
        start_time = asyncio.get_running_loop().time()

        async def slow_cleanup():
            await asyncio.sleep(0.1)

        # Run 3 cleanups that each take 0.1s
        await AsyncTestHelper.ensure_cleanup(
            slow_cleanup(), slow_cleanup(), slow_cleanup()
        )

        elapsed = asyncio.get_running_loop().time() - start_time

        # Should complete in ~0.1s (concurrent), not 0.3s (sequential)
        assert elapsed < 0.2, f"Cleanup took {elapsed}s, expected concurrent execution"

    async def test_cleanup_with_immediate_completion(self):
        """Test cleanup with tasks that complete immediately."""
        completed = {"value": 0}

        async def immediate_cleanup():
            completed["value"] += 1

        await AsyncTestHelper.ensure_cleanup(
            immediate_cleanup(), immediate_cleanup(), immediate_cleanup()
        )

        assert completed["value"] == 3
