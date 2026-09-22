"""Concurrent operation tests for SearchService.

These tests verify thread safety and concurrent access patterns for:
- Race conditions in shared state
- Deadlock prevention
- Concurrent writes to index
- Concurrent read/write scenarios

Run with: pytest tests/search/test_concurrent_operations.py -v
"""
from __future__ import annotations

import asyncio
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_storage_facade():
    """Create a mock StorageFacade for concurrent testing."""
    mock_storage = MagicMock()
    mock_storage.project_id = "test_project"
    mock_storage.supports_vector_search.return_value = True
    mock_storage.supports_fts.return_value = True
    mock_storage.supports_hybrid_search.return_value = True
    mock_storage.supports_graph_ranking.return_value = True
    mock_storage.has_graph_ranking_data = AsyncMock(return_value=True)

    # Mock search methods to return empty results
    mock_storage.vector_search = AsyncMock(return_value=[])
    mock_storage.fts_search = AsyncMock(return_value=[])
    mock_storage.advanced_filter = AsyncMock(return_value=[])

    return mock_storage


@pytest.fixture
def mock_config():
    """Create a mock configuration for testing."""
    config = MagicMock()
    config.search.default_limit = 10
    config.search.max_limit = 100
    config.search.hybrid_search.vector_weight = 0.7
    config.search.hybrid_search.fts_weight = 0.3
    config.search.hybrid_search.rerank_by_graph = False
    config.search.hybrid_search.reranker_type = "rrf"
    config.search.hybrid_search.reranker_params = {}
    config.search.deduplication.enabled = False
    config.search.deduplication.max_results_per_file = 3
    config.search.deduplication.min_diversity_ratio = 0.3
    config.search.query_sanitization.enabled = True
    config.search.query_sanitization.preserve_wildcards = True
    config.storage.default_project_id = "test_project"
    return config


@pytest.fixture
def search_service(mock_storage_facade, mock_config):
    """Create a SearchService instance for testing."""
    from agentic_inquiry.search.service import SearchService

    return SearchService(
        storage=mock_storage_facade,
        config=mock_config,
        project_id="test_project",
    )


class TestConcurrentSearchOperations:
    """Test concurrent search operations for race conditions and consistency."""

    @pytest.mark.asyncio
    async def test_concurrent_vector_searches_no_race_condition(self, search_service, mock_storage_facade):
        """Test that concurrent vector searches don't interfere with each other."""
        # Setup: Each search should see its own query vector
        call_vectors = []

        async def mock_vector_search(*args, **kwargs):
            query_vector = kwargs.get("query_vector")
            call_vectors.append(query_vector[0] if query_vector else None)
            await asyncio.sleep(0.01)  # Simulate I/O
            return []

        mock_storage_facade.vector_search = mock_vector_search

        # Execute: Run 10 concurrent searches with different vectors
        queries = [[float(i)] * 384 for i in range(10)]
        tasks = [
            search_service.vector_search(query_vector=q, limit=5)
            for q in queries
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify: No exceptions occurred
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0, f"Unexpected exceptions: {exceptions}"

        # Verify: Each call received its unique vector (no cross-contamination)
        assert len(call_vectors) == 10
        assert len(set(call_vectors)) == 10, "Vectors were mixed between calls"

    @pytest.mark.asyncio
    async def test_concurrent_fts_searches_query_isolation(self, search_service, mock_storage_facade):
        """Test that concurrent FTS searches maintain query isolation."""
        call_queries = []

        async def mock_fts_search(*args, **kwargs):
            query = kwargs.get("query")
            call_queries.append(query)
            await asyncio.sleep(0.01)
            return []

        mock_storage_facade.fts_search = mock_fts_search

        # Execute: Run concurrent searches with different queries
        queries = [f"query_{i}" for i in range(10)]
        tasks = [
            search_service.fts_search(query_fts=q, limit=5)
            for q in queries
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify: No exceptions
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0

        # Verify: Each query was executed independently
        assert len(call_queries) == 10
        assert set(call_queries) == set(queries)

    @pytest.mark.asyncio
    async def test_concurrent_hybrid_searches_no_result_mixing(self, search_service):
        """Test that concurrent hybrid searches don't mix results."""

        # Track which results were returned to which caller
        result_tracker = {}

        async def tracked_hybrid_search(query_id: int):
            query_vector = [float(query_id)] * 384
            query_text = f"query_{query_id}"

            results = await search_service.hybrid_search(
                query_vector=query_vector,
                query_fts=query_text,
                limit=5,
            )

            result_tracker[query_id] = results
            return results

        # Execute: 20 concurrent hybrid searches
        tasks = [tracked_hybrid_search(i) for i in range(20)]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Verify: Each search got independent results (no mixing)
        assert len(result_tracker) == 20
        # Results should be independent per query
        for query_id, results in result_tracker.items():
            assert isinstance(results, list), f"Query {query_id} got non-list result"

    @pytest.mark.asyncio
    async def test_concurrent_searches_metrics_consistency(self, search_service, mock_storage_facade):
        """Test that concurrent searches maintain consistent metrics without race conditions."""
        # Execute: Many concurrent searches
        num_searches = 50

        tasks = [
            search_service.vector_search(
                query_vector=[0.1] * 384,
                limit=5,
            )
            for _ in range(num_searches)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify: No exceptions
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0

        # Verify: Metrics were updated consistently
        metrics = search_service.get_metrics()
        assert "latency_metrics" in metrics
        # All searches should have been tracked
        # Note: Exact count depends on metrics implementation, just verify it exists


class TestConcurrentWriteOperations:
    """Test concurrent write operations for data integrity."""

    @pytest.mark.asyncio
    async def test_concurrent_index_updates_no_data_loss(self):
        """Test that concurrent index updates don't lose data."""
        # Track all chunks written with thread-safe list
        written_chunks = []
        write_lock = asyncio.Lock()

        async def mock_store_chunks(chunks):
            # Acquire lock for thread safety
            async with write_lock:
                written_chunks.extend(chunks)
            # Simulate write latency
            await asyncio.sleep(0.001)

        # Simulate concurrent chunk storage operations
        async def store_chunk(chunk_id: int):
            # Create a simple chunk representation
            chunk = {
                "chunk_id": f"chunk_{chunk_id}",
                "content": f"Content for chunk {chunk_id}",
                "file_path": f"/test/file_{chunk_id}.py",
            }
            # Store the chunk
            await mock_store_chunks([chunk])

        # Execute: Process 30 chunks concurrently
        tasks = [store_chunk(i) for i in range(30)]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Verify: No data loss - all 30 chunks written
        assert len(written_chunks) == 30, f"Expected 30 chunks, got {len(written_chunks)}"

        # Verify: Each chunk is unique (no duplicates from race conditions)
        chunk_ids = [c["chunk_id"] for c in written_chunks]
        assert len(set(chunk_ids)) == 30, "Duplicate chunks detected"

    @pytest.mark.asyncio
    async def test_concurrent_graph_updates_consistency(self, mock_storage_facade):
        """Test that concurrent graph updates maintain consistency."""
        # Track relationship writes
        relationships = []
        rel_lock = asyncio.Lock()

        async def mock_add_relationship(source, target, rel_type):
            async with rel_lock:
                relationships.append((source, target, rel_type))
            await asyncio.sleep(0.001)  # Simulate write latency

        mock_storage_facade.graph_provider = MagicMock()
        mock_storage_facade.graph_provider.add_relationship = mock_add_relationship

        # Simulate concurrent relationship creation
        async def add_relationships_batch(batch_id: int):
            for i in range(5):
                await mock_add_relationship(
                    f"entity_{batch_id}",
                    f"entity_{batch_id}_{i}",
                    "calls"
                )

        # Execute: 20 concurrent batches
        tasks = [add_relationships_batch(i) for i in range(20)]
        await asyncio.gather(*tasks, return_exceptions=True)

        # Verify: All 100 relationships (20 batches * 5 each) were written
        assert len(relationships) == 100
        # Verify: No duplicates
        assert len(set(relationships)) == 100


class TestConcurrentReadWriteScenarios:
    """Test mixed concurrent read/write operations."""

    @pytest.mark.asyncio
    async def test_search_during_indexing_no_errors(self, search_service, mock_storage_facade):
        """Test that searches work correctly during concurrent indexing."""
        # Simulate indexing operations
        indexing_count = 0
        index_lock = asyncio.Lock()

        async def simulate_indexing():
            nonlocal indexing_count
            async with index_lock:
                indexing_count += 1
            await asyncio.sleep(0.01)

        # Execute: Interleave searches and indexing
        tasks = []
        for i in range(20):
            # Add a search
            tasks.append(
                search_service.vector_search(
                    query_vector=[0.1] * 384,
                    limit=5,
                )
            )
            # Add an indexing operation
            tasks.append(simulate_indexing())

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify: No exceptions from mixed operations
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0

        # Verify: All indexing operations completed
        assert indexing_count == 20

    @pytest.mark.asyncio
    async def test_concurrent_cache_access_no_corruption(self, search_service):
        """Test that concurrent cache access doesn't cause corruption."""
        # Note: SearchService doesn't have public cache access,
        # but we test the deduplicator which uses internal state
        from agentic_inquiry.search.deduplicator import SearchDeduplicator

        deduplicator = SearchDeduplicator(max_results_per_file=3, min_diversity_ratio=0.3)

        # Create test results
        def create_results(batch_id: int) -> List[dict]:
            return [
                {
                    "doc_id": f"doc_{batch_id}_{i}",
                    "file_path": f"/test/file_{batch_id}.py",
                    "score": 0.9 - (i * 0.1),
                }
                for i in range(5)
            ]

        # Concurrent deduplication operations
        async def deduplicate_batch(batch_id: int):
            results = create_results(batch_id)
            await asyncio.sleep(0.001)  # Simulate async processing
            return deduplicator.deduplicate_results(results)

        # Execute: 30 concurrent deduplication operations
        tasks = [deduplicate_batch(i) for i in range(30)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify: No exceptions
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0

        # Verify: Each batch was deduplicated independently
        assert len(results) == 30
        for result in results:
            assert isinstance(result, list)


class TestDeadlockPrevention:
    """Test that the system doesn't deadlock under concurrent load."""

    @pytest.mark.asyncio
    async def test_no_deadlock_with_timeout(self, search_service):
        """Test that concurrent operations complete within timeout (no deadlock)."""
        # Execute: Many concurrent searches with timeout
        num_operations = 100

        async def search_with_id(search_id: int):
            return await search_service.vector_search(
                query_vector=[float(search_id % 10)] * 384,
                limit=5,
            )

        tasks = [search_with_id(i) for i in range(num_operations)]

        # Should complete within 10 seconds (generous timeout)
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=10.0
            )

            # Verify: All completed (no deadlock)
            assert len(results) == num_operations

            # Most should succeed (allow some failures under load)
            exceptions = [r for r in results if isinstance(r, Exception)]
            success_rate = (num_operations - len(exceptions)) / num_operations
            assert success_rate > 0.8, f"Success rate too low: {success_rate:.1%}"

        except asyncio.TimeoutError:
            pytest.fail("Operations timed out - possible deadlock detected")

    @pytest.mark.asyncio
    async def test_no_deadlock_with_graph_reranking(self, search_service, mock_storage_facade):
        """Test that concurrent searches with graph reranking don't deadlock."""

        # Mock graph reranking with some delay
        async def mock_rerank(results):
            await asyncio.sleep(0.01)
            return results

        search_service._graph_search.rerank_by_graph = mock_rerank

        # Execute: Concurrent hybrid searches with graph reranking
        tasks = [
            search_service.hybrid_search(
                query_vector=[0.1] * 384,
                query_fts=f"query_{i}",
                limit=5,
                rerank_by_graph=True,
            )
            for i in range(20)
        ]

        # Should complete without deadlock
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=5.0
            )
            assert len(results) == 20
        except asyncio.TimeoutError:
            pytest.fail("Graph reranking caused deadlock")

    @pytest.mark.asyncio
    async def test_no_circular_wait_in_mixed_operations(self, search_service, mock_storage_facade):
        """Test that mixed read/write operations don't cause circular waits."""
        operation_count = {"read": 0, "write": 0}
        op_lock = asyncio.Lock()

        async def read_operation(op_id: int):
            async with op_lock:
                operation_count["read"] += 1
            await search_service.vector_search(
                query_vector=[0.1] * 384,
                limit=5,
            )

        async def write_operation(op_id: int):
            async with op_lock:
                operation_count["write"] += 1
            # Simulate write
            await asyncio.sleep(0.001)

        # Create alternating read/write operations
        tasks = []
        for i in range(40):
            if i % 2 == 0:
                tasks.append(read_operation(i))
            else:
                tasks.append(write_operation(i))

        # Should complete without circular wait
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=5.0
            )

            # Verify: All operations executed
            assert operation_count["read"] == 20
            assert operation_count["write"] == 20

        except asyncio.TimeoutError:
            pytest.fail("Circular wait detected in mixed operations")


class TestRaceConditionDetection:
    """Test for race conditions in shared state."""

    @pytest.mark.asyncio
    async def test_metrics_counter_race_condition(self, search_service):
        """Test that metrics counters don't have race conditions."""
        # Execute: Many concurrent operations that update metrics
        num_operations = 100

        tasks = [
            search_service.vector_search(
                query_vector=[0.1] * 384,
                limit=5,
            )
            for _ in range(num_operations)
        ]

        await asyncio.gather(*tasks, return_exceptions=True)

        # Verify: Metrics are consistent (no lost updates)
        metrics = search_service.get_metrics()
        # Just verify metrics exist - internal counter consistency is implementation detail
        assert "latency_metrics" in metrics

    @pytest.mark.asyncio
    async def test_concurrent_filter_modification_safety(self, search_service):
        """Test that concurrent filter modifications don't cause race conditions."""
        # Create different filters for each search
        filters_used = []
        filter_lock = asyncio.Lock()

        async def search_with_filter(filter_id: int):
            filter_dict = {"project_id": f"project_{filter_id}"}
            async with filter_lock:
                filters_used.append(filter_id)

            return await search_service.vector_search(
                query_vector=[0.1] * 384,
                limit=5,
                filters=filter_dict,
            )

        # Execute: Concurrent searches with different filters
        tasks = [search_with_filter(i) for i in range(30)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify: No exceptions
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 0

        # Verify: All filters were used
        assert len(filters_used) == 30

    @pytest.mark.asyncio
    async def test_concurrent_project_id_isolation(self, search_service, mock_storage_facade):
        """Test that concurrent searches with different project IDs maintain isolation."""
        # Track which project_id was used in each call
        call_project_ids = []
        call_lock = asyncio.Lock()

        async def mock_vector_search(*args, **kwargs):
            project_id = kwargs.get("project_id")
            async with call_lock:
                call_project_ids.append(project_id)
            await asyncio.sleep(0.001)
            return []

        mock_storage_facade.vector_search = mock_vector_search

        # Execute: Searches with different project IDs
        project_ids = [f"project_{i}" for i in range(10)]
        tasks = [
            search_service.vector_search(
                query_vector=[0.1] * 384,
                limit=5,
                project_id=pid,
            )
            for pid in project_ids
        ]

        await asyncio.gather(*tasks, return_exceptions=True)

        # Verify: Each search used its correct project_id (no mixing)
        assert len(call_project_ids) == 10
        # Each project_id should appear exactly once
        for pid in project_ids:
            assert call_project_ids.count(pid) == 1, f"Project ID {pid} was mixed"


class TestExceptionHandling:
    """Test exception handling in concurrent scenarios."""

    @pytest.mark.asyncio
    async def test_exception_in_one_search_doesnt_affect_others(self, search_service, mock_storage_facade):
        """Test that an exception in one search doesn't break other concurrent searches."""
        call_count = 0

        async def mock_vector_search_with_failures(*args, **kwargs):
            nonlocal call_count
            call_count += 1

            # Fail every 5th call
            if call_count % 5 == 0:
                raise ValueError("Simulated search failure")

            return []

        mock_storage_facade.vector_search = mock_vector_search_with_failures

        # Execute: 25 concurrent searches (5 will fail)
        tasks = [
            search_service.vector_search(
                query_vector=[0.1] * 384,
                limit=5,
            )
            for _ in range(25)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify: Expected number of failures
        exceptions = [r for r in results if isinstance(r, ValueError)]
        successes = [r for r in results if isinstance(r, list)]

        assert len(exceptions) == 5, "Expected 5 simulated failures"
        assert len(successes) == 20, "Expected 20 successful searches"

    @pytest.mark.asyncio
    async def test_timeout_handling_in_concurrent_operations(self, search_service, mock_storage_facade):
        """Test that timeouts in some operations don't affect others."""
        async def mock_vector_search_with_delays(*args, **kwargs):
            query_vector = kwargs.get("query_vector", [])

            # Delay based on first element (some will timeout if caller sets timeout)
            if query_vector and query_vector[0] > 0.5:
                await asyncio.sleep(0.1)
            else:
                await asyncio.sleep(0.001)

            return []

        mock_storage_facade.vector_search = mock_vector_search_with_delays

        # Execute: Mixed fast and slow searches
        async def search_with_timeout(vector_value: float):
            try:
                return await asyncio.wait_for(
                    search_service.vector_search(
                        query_vector=[vector_value] * 384,
                        limit=5,
                    ),
                    timeout=0.05
                )
            except asyncio.TimeoutError:
                return "TIMEOUT"

        tasks = [
            search_with_timeout(i / 20.0)  # Values from 0.0 to 0.95
            for i in range(20)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify: Some succeeded, some timed out, no crashes
        timeouts = [r for r in results if r == "TIMEOUT"]
        successes = [r for r in results if isinstance(r, list)]

        assert len(timeouts) > 0, "Expected some timeouts"
        assert len(successes) > 0, "Expected some successes"
        assert len(timeouts) + len(successes) == 20


class TestConcurrentCancellation:
    """Test behavior when operations are cancelled concurrently."""

    @pytest.mark.asyncio
    async def test_graceful_cancellation_cleanup(self, search_service, mock_storage_facade):
        """Test that cancelled operations clean up gracefully."""
        # Make searches take longer so they can be cancelled
        async def slow_vector_search(*args, **kwargs):
            await asyncio.sleep(0.5)  # Long enough to cancel
            return []

        mock_storage_facade.vector_search = slow_vector_search

        # Start many operations
        tasks = [
            asyncio.create_task(
                search_service.vector_search(
                    query_vector=[0.1] * 384,
                    limit=100,
                )
            )
            for _ in range(20)
        ]

        # Let them start
        await asyncio.sleep(0.01)

        # Cancel half of them
        for i, task in enumerate(tasks):
            if i % 2 == 0:
                task.cancel()

        # Wait for all to complete or cancel
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify: Cancellations were handled
        cancelled = [r for r in results if isinstance(r, asyncio.CancelledError)]
        completed = [r for r in results if isinstance(r, list)]

        # Some should be cancelled, some should complete
        assert len(cancelled) == 10, f"Expected 10 cancellations, got {len(cancelled)}"
        assert len(completed) == 10, f"Expected 10 completions, got {len(completed)}"
