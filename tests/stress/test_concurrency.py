"""Stress tests for concurrent operations.

These tests verify that the system handles concurrent access correctly
and doesn't exhibit race conditions or resource contention issues.

Run with: pytest tests/stress/ -v --timeout=60

NOTE: These tests are currently skipped because they use outdated APIs:
1. HybridSearchService constructor changed - requires config and deduplicator
2. agent_vault.core.types module doesn't exist (moved/renamed)
3. Uses non-existent search_service.search() method

TODO: Update to use current SearchService API with proper dependencies.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

pytestmark = [
    pytest.mark.stress,
    pytest.mark.slow,
    pytest.mark.skip(reason="Stress tests use outdated APIs - need rewrite for current SearchService")
]


class TestConcurrentSearchOperations:
    """Test concurrent search operations."""

    @pytest.mark.asyncio
    async def test_concurrent_searches(
        self,
        stress_test_storage,
        stress_config,
        concurrent_semaphore,
    ):
        """Multiple concurrent searches complete without errors."""
        from agent_vault.search.hybrid_search import HybridSearchService

        search_service = HybridSearchService(
            storage=stress_test_storage,
            project_id="stress_test",
        )

        queries = [
            "async database connection",
            "embedding generation",
            "configuration loading",
            "error handling patterns",
            "MCP tool implementation",
        ] * 10  # 50 total queries

        async def run_search(query: str) -> list[Any]:
            async with concurrent_semaphore:
                return await search_service.search(query=query, limit=5)

        # Run all searches concurrently
        tasks = [run_search(q) for q in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Check no exceptions occurred
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0, f"Search exceptions: {exceptions}"

        # Check all returned results
        successful = [r for r in results if isinstance(r, list)]
        assert len(successful) == len(queries)

    @pytest.mark.asyncio
    async def test_concurrent_mixed_operations(
        self,
        stress_test_storage,
        stress_config,
        concurrent_semaphore,
    ):
        """Mixed read/write operations don't cause deadlocks."""
        from agent_vault.search.hybrid_search import HybridSearchService
        from agent_vault.core.types import Chunk, ContentType

        search_service = HybridSearchService(
            storage=stress_test_storage,
            project_id="stress_test",
        )

        async def search_operation(query: str) -> list:
            async with concurrent_semaphore:
                return await search_service.search(query=query, limit=5)

        async def write_operation(idx: int) -> None:
            async with concurrent_semaphore:
                chunk = Chunk(
                    id=f"stress_chunk_{idx}",
                    content=f"Test content for stress test {idx}",
                    content_type=ContentType.CODE,
                    source_uri=f"test://stress/{idx}.py",
                    embedding=[0.1] * 384,  # Mock embedding
                    metadata={"test": True},
                )
                await stress_test_storage.store_chunks([chunk])

        # Create mixed workload
        operations = []
        for i in range(25):
            operations.append(search_operation(f"query {i}"))
            operations.append(write_operation(i))

        # Run all operations concurrently
        results = await asyncio.gather(*operations, return_exceptions=True)

        # Check no exceptions
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0, f"Operation exceptions: {exceptions}"


class TestConcurrentIndexing:
    """Test concurrent indexing operations."""

    @pytest.mark.asyncio
    async def test_concurrent_chunk_storage(
        self,
        stress_test_storage,
        stress_config,
        concurrent_semaphore,
    ):
        """Multiple concurrent chunk stores complete without corruption."""
        from agent_vault.core.types import Chunk, ContentType

        async def store_chunk_batch(batch_id: int) -> None:
            async with concurrent_semaphore:
                chunks = [
                    Chunk(
                        id=f"batch_{batch_id}_chunk_{i}",
                        content=f"Content for batch {batch_id} chunk {i}",
                        content_type=ContentType.CODE,
                        source_uri=f"test://batch/{batch_id}/{i}.py",
                        embedding=[0.1 * (i + 1)] * 384,
                        metadata={"batch": batch_id, "index": i},
                    )
                    for i in range(10)
                ]
                await stress_test_storage.store_chunks(chunks)

        # Store 50 batches concurrently
        num_batches = stress_config["concurrent_operations"]
        tasks = [store_chunk_batch(i) for i in range(num_batches)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Check no exceptions
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0, f"Storage exceptions: {exceptions}"


class TestResourceContention:
    """Test resource contention scenarios."""

    @pytest.mark.asyncio
    async def test_connection_pool_under_load(
        self,
        stress_test_storage,
        stress_config,
    ):
        """Connection pool handles high load without exhaustion."""
        from agent_vault.search.hybrid_search import HybridSearchService

        search_service = HybridSearchService(
            storage=stress_test_storage,
            project_id="stress_test",
        )

        # Burst of requests without semaphore limiting
        burst_size = stress_config["concurrent_operations"] * 2
        tasks = [
            search_service.search(query=f"burst query {i}", limit=3)
            for i in range(burst_size)
        ]

        # Should complete within timeout
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=stress_config["timeout_seconds"],
            )
            exceptions = [r for r in results if isinstance(r, Exception)]
            # Some may fail under extreme load, but shouldn't deadlock
            assert len(exceptions) < burst_size // 2, "Too many failures under load"
        except asyncio.TimeoutError:
            pytest.fail("Connection pool exhausted - deadlock detected")

    @pytest.mark.asyncio
    async def test_graceful_degradation(
        self,
        stress_test_storage,
        stress_config,
    ):
        """System degrades gracefully under extreme load."""
        from agent_vault.search.hybrid_search import HybridSearchService

        search_service = HybridSearchService(
            storage=stress_test_storage,
            project_id="stress_test",
        )

        # Extreme burst - 5x normal capacity
        extreme_load = stress_config["concurrent_operations"] * 5

        async def timed_search(idx: int) -> tuple[int, float, bool]:
            import time
            start = time.monotonic()
            try:
                await search_service.search(query=f"extreme {idx}", limit=3)
                return (idx, time.monotonic() - start, True)
            except Exception:
                return (idx, time.monotonic() - start, False)

        tasks = [timed_search(i) for i in range(extreme_load)]
        results = await asyncio.gather(*tasks)

        # Analyze results
        successful = [r for r in results if r[2]]
        
        # At least 50% should succeed
        success_rate = len(successful) / len(results)
        assert success_rate >= 0.5, f"Success rate too low: {success_rate:.1%}"

        # Average latency for successful requests should be reasonable
        if successful:
            avg_latency = sum(r[1] for r in successful) / len(successful)
            assert avg_latency < 5.0, f"Average latency too high: {avg_latency:.2f}s"


class TestAsyncSafety:
    """Test async safety and proper cleanup."""

    @pytest.mark.asyncio
    async def test_cancelled_operations_cleanup(
        self,
        stress_test_storage,
    ):
        """Cancelled operations clean up resources properly."""
        from agent_vault.search.hybrid_search import HybridSearchService

        search_service = HybridSearchService(
            storage=stress_test_storage,
            project_id="stress_test",
        )

        async def long_search() -> list:
            return await search_service.search(
                query="long running query",
                limit=100,
            )

        # Start operations and cancel them
        tasks = [asyncio.create_task(long_search()) for _ in range(10)]

        # Let them start
        await asyncio.sleep(0.01)

        # Cancel half of them
        for task in tasks[:5]:
            task.cancel()

        # Gather results (cancelled tasks raise CancelledError)
        results = await asyncio.gather(*tasks, return_exceptions=True)

        cancelled = [r for r in results if isinstance(r, asyncio.CancelledError)]
        successful = [r for r in results if isinstance(r, list)]

        assert len(cancelled) == 5, "Not all cancellations registered"
        assert len(successful) == 5, "Remaining tasks should complete"

    @pytest.mark.asyncio
    async def test_exception_isolation(
        self,
        stress_test_storage,
        concurrent_semaphore,
    ):
        """Exceptions in one operation don't affect others."""
        from agent_vault.search.hybrid_search import HybridSearchService

        search_service = HybridSearchService(
            storage=stress_test_storage,
            project_id="stress_test",
        )

        async def maybe_failing_search(idx: int) -> list:
            async with concurrent_semaphore:
                if idx % 10 == 0:
                    raise ValueError(f"Intentional failure at {idx}")
                return await search_service.search(query=f"query {idx}", limit=3)

        tasks = [maybe_failing_search(i) for i in range(50)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Check expected failures
        failures = [r for r in results if isinstance(r, ValueError)]
        successes = [r for r in results if isinstance(r, list)]

        assert len(failures) == 5, "Expected 5 intentional failures"
        assert len(successes) == 45, "Other operations should succeed"
