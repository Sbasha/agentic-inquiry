"""Performance tests for event tracking system.

Tests performance targets:
- Event emission latency: < 1ms
- Batch write throughput: > 1000 events/sec
- Query performance: < 10ms for 1000 events
- Memory usage under load: < 10MB
"""

import asyncio
import time
import tracemalloc
from pathlib import Path
from typing import List

import pytest

pytestmark = pytest.mark.integration

from agent_vault.config import Config
from agent_vault.events import EventSystem
from agent_vault.events.models import Event, EventStatus
from agent_vault.events.store import EventStore


class TestEventEmissionLatency:
    """Test event emission latency (target: < 1ms)."""

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_single_event_emission_latency(self, tmp_path: Path):
        """Test that single event emission is under 1ms."""
        # Setup
        config = Config.load()
        
        system = await EventSystem.from_config(config, project_id="perf_test")
        async with system:
            # Warm up
            await system.emit("test.warmup", source="perf_test")
            await asyncio.sleep(0.1)
            
            # Measure emission latency
            latencies: List[float] = []
            num_samples = 100
            
            for i in range(num_samples):
                start = time.perf_counter()
                await system.emit(
                    "test.performance",
                    source="perf_test",
                    status=EventStatus.PROGRESS,
                    iteration=i,
                )
                end = time.perf_counter()
                latencies.append((end - start) * 1000)  # Convert to ms
            
            # Calculate statistics
            avg_latency = sum(latencies) / len(latencies)
            max_latency = max(latencies)
            p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]
            
            print("\nEvent Emission Latency:")
            print(f"  Samples: {num_samples}")
            print(f"  Average: {avg_latency:.3f}ms")
            print(f"  P95: {p95_latency:.3f}ms")
            print(f"  Max: {max_latency:.3f}ms")
            
            # Verify target: < 1ms average
            assert avg_latency < 1.0, \
                f"Average emission latency {avg_latency:.3f}ms exceeds 1ms target"
            
            # P95 should also be reasonable
            assert p95_latency < 2.0, \
                f"P95 emission latency {p95_latency:.3f}ms exceeds 2ms threshold"

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_concurrent_event_emission_latency(self, tmp_path: Path):
        """Test event emission latency under concurrent load."""
        config = Config.load()
        
        system = await EventSystem.from_config(config, project_id="perf_test_concurrent")
        async with system:
            # Warm up
            await system.emit("test.warmup", source="perf_test")
            await asyncio.sleep(0.1)
            
            # Measure concurrent emission
            num_concurrent = 10
            events_per_task = 50
            
            async def emit_events(task_id: int) -> List[float]:
                latencies = []
                for i in range(events_per_task):
                    start = time.perf_counter()
                    await system.emit(
                        "test.concurrent",
                        source=f"task_{task_id}",
                        iteration=i,
                    )
                    end = time.perf_counter()
                    latencies.append((end - start) * 1000)
                return latencies
            
            # Run concurrent tasks
            tasks = [emit_events(i) for i in range(num_concurrent)]
            results = await asyncio.gather(*tasks)
            
            # Flatten results
            all_latencies = [lat for task_latencies in results for lat in task_latencies]
            
            avg_latency = sum(all_latencies) / len(all_latencies)
            p95_latency = sorted(all_latencies)[int(len(all_latencies) * 0.95)]
            
            print("\nConcurrent Event Emission Latency:")
            print(f"  Concurrent tasks: {num_concurrent}")
            print(f"  Events per task: {events_per_task}")
            print(f"  Total events: {len(all_latencies)}")
            print(f"  Average: {avg_latency:.3f}ms")
            print(f"  P95: {p95_latency:.3f}ms")
            
            # Under concurrent load, latency should still be reasonable
            assert avg_latency < 2.0, \
                f"Average concurrent latency {avg_latency:.3f}ms exceeds 2ms threshold"


class TestBatchWriteThroughput:
    """Test batch write throughput (target: > 1000 events/sec)."""

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_batch_write_throughput(self, tmp_path: Path):
        """Test that batch writing achieves > 1000 events/sec."""
        config = Config.load()
        
        system = await EventSystem.from_config(config, project_id="perf_test_throughput")
        async with system:
            # Emit large number of events
            num_events = 5000
            
            start_time = time.time()
            
            for i in range(num_events):
                await system.emit(
                    "test.throughput",
                    source="perf_test",
                    status=EventStatus.PROGRESS,
                    iteration=i,
                    data=f"event_{i}",
                )
            
            # Wait for all events to be written
            # Give enough time for batching to complete
            await asyncio.sleep(2.0)
            
            # Stop system to flush remaining events
            await system.stop(timeout=5.0)
            
            end_time = time.time()
            duration = end_time - start_time
            throughput = num_events / duration
            
            print("\nBatch Write Throughput:")
            print(f"  Events: {num_events}")
            print(f"  Duration: {duration:.2f}s")
            print(f"  Throughput: {throughput:.1f} events/sec")
            
            # Verify target: > 1000 events/sec
            assert throughput > 1000, \
                f"Throughput {throughput:.1f} events/sec is below 1000 events/sec target"

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_sustained_throughput(self, tmp_path: Path):
        """Test sustained throughput over longer period."""
        config = Config.load()
        
        system = await EventSystem.from_config(config, project_id="perf_test_sustained")
        async with system:
            # Emit events continuously for several seconds
            duration_seconds = 5
            events_emitted = 0
            
            start_time = time.time()
            end_target = start_time + duration_seconds
            
            while time.time() < end_target:
                await system.emit(
                    "test.sustained",
                    source="perf_test",
                    iteration=events_emitted,
                )
                events_emitted += 1
                
                # Small delay to avoid overwhelming the queue
                if events_emitted % 100 == 0:
                    await asyncio.sleep(0.01)
            
            # Wait for writes to complete
            await asyncio.sleep(2.0)
            
            actual_duration = time.time() - start_time
            throughput = events_emitted / actual_duration
            
            print("\nSustained Throughput:")
            print(f"  Duration: {actual_duration:.2f}s")
            print(f"  Events: {events_emitted}")
            print(f"  Throughput: {throughput:.1f} events/sec")
            
            # Should maintain good throughput
            assert throughput > 500, \
                f"Sustained throughput {throughput:.1f} events/sec is too low"


class TestQueryPerformance:
    """Test query performance (target: < 10ms for 1000 events)."""

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_operation_query_performance(self, tmp_path: Path):
        """Test querying events by operation_id is under 10ms for 1000 events."""
        # Setup store with test data
        db_path = tmp_path / "query_perf.db"
        config = Config.load()
        
        store = await EventStore.from_config(config=config, project_id="perf_test_query", db_path=db_path)
        await store._ensure_initialized()
        
        # Insert 1000 events for same operation
        operation_id = "test_operation_123"
        events = [
            Event(
                project_id="perf_test_query",
                operation_id=operation_id,
                event_type="test.query",
                source="perf_test",
                status=EventStatus.PROGRESS,
                metadata={"index": i},
            )
            for i in range(1000)
        ]
        
        await store.store_events(events)
        
        # Measure query performance
        query_times: List[float] = []
        num_queries = 50
        
        for _ in range(num_queries):
            start = time.perf_counter()
            results = await store.get_operation_events(operation_id)
            end = time.perf_counter()
            query_times.append((end - start) * 1000)  # Convert to ms
            
            assert len(results) == 1000
        
        avg_query_time = sum(query_times) / len(query_times)
        max_query_time = max(query_times)
        p95_query_time = sorted(query_times)[int(len(query_times) * 0.95)]
        
        print("\nOperation Query Performance (1000 events):")
        print(f"  Queries: {num_queries}")
        print(f"  Average: {avg_query_time:.2f}ms")
        print(f"  P95: {p95_query_time:.2f}ms")
        print(f"  Max: {max_query_time:.2f}ms")
        
        await store.close()
        
        # Verify target: < 10ms average
        assert avg_query_time < 10.0, \
            f"Average query time {avg_query_time:.2f}ms exceeds 10ms target"

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_type_filter_query_performance(self, tmp_path: Path):
        """Test querying events by type is performant."""
        db_path = tmp_path / "type_query_perf.db"
        config = Config.load()
        
        store = await EventStore.from_config(config=config, project_id="perf_test_type_query", db_path=db_path)
        await store._ensure_initialized()
        
        # Insert events with different types
        events = []
        for i in range(2000):
            event_type = f"test.type_{i % 5}"  # 5 different types
            events.append(
                Event(
                    project_id="perf_test_type_query",
                    operation_id=f"op_{i}",
                    event_type=event_type,
                    source="perf_test",
                    status=EventStatus.PROGRESS,
                )
            )
        
        await store.store_events(events)
        
        # Query by specific type
        query_times: List[float] = []
        num_queries = 30
        
        for _ in range(num_queries):
            start = time.perf_counter()
            results = await store.get_events_by_type("test.type_0")
            end = time.perf_counter()
            query_times.append((end - start) * 1000)
            
            assert len(results) == 400  # 2000 / 5 types
        
        avg_query_time = sum(query_times) / len(query_times)
        
        print("\nType Filter Query Performance:")
        print("  Total events: 2000")
        print("  Matching events: 400")
        print(f"  Average query time: {avg_query_time:.2f}ms")
        
        await store.close()
        
        # Should be fast with index
        assert avg_query_time < 15.0, \
            f"Type query time {avg_query_time:.2f}ms is too slow"

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_time_range_query_performance(self, tmp_path: Path):
        """Test querying events by time range is performant."""
        db_path = tmp_path / "time_query_perf.db"
        config = Config.load()
        
        store = await EventStore.from_config(config=config, project_id="perf_test_time_query", db_path=db_path)
        await store._ensure_initialized()
        
        # Insert events with different timestamps
        base_time = time.time()
        events = []
        for i in range(3000):
            events.append(
                Event(
                    project_id="perf_test_time_query",
                    operation_id=f"op_{i}",
                    event_type="test.time",
                    source="perf_test",
                    status=EventStatus.PROGRESS,
                    timestamp=base_time + i * 0.1,  # 0.1s apart
                )
            )
        
        await store.store_events(events)
        
        # Query time range (middle 1000 events)
        start_time = base_time + 1000 * 0.1
        end_time = base_time + 2000 * 0.1
        
        query_times: List[float] = []
        num_queries = 30
        
        for _ in range(num_queries):
            start = time.perf_counter()
            results = await store.get_events_by_time_range(start_time, end_time)
            end = time.perf_counter()
            query_times.append((end - start) * 1000)
            
            assert len(results) == 1000
        
        avg_query_time = sum(query_times) / len(query_times)
        
        print("\nTime Range Query Performance:")
        print("  Total events: 3000")
        print("  Range events: 1000")
        print(f"  Average query time: {avg_query_time:.2f}ms")
        
        await store.close()
        
        # Should be fast with index
        assert avg_query_time < 15.0, \
            f"Time range query time {avg_query_time:.2f}ms is too slow"


class TestMemoryUsage:
    """Test memory usage under load (target: < 10MB)."""

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_memory_usage_under_load(self, tmp_path: Path):
        """Test that memory usage stays under 10MB during normal operation."""
        config = Config.load()
        
        # Start memory tracking
        tracemalloc.start()
        
        system = await EventSystem.from_config(config, project_id="perf_test_memory")
        async with system:
            # Get baseline memory
            baseline_snapshot = tracemalloc.take_snapshot()
            baseline_memory = sum(stat.size for stat in baseline_snapshot.statistics('lineno'))
            
            # Emit many events
            num_events = 2000
            for i in range(num_events):
                await system.emit(
                    "test.memory",
                    source="perf_test",
                    iteration=i,
                    data=f"event_data_{i}",
                )
                
                # Small delay to allow batching
                if i % 100 == 0:
                    await asyncio.sleep(0.05)
            
            # Wait for writes
            await asyncio.sleep(1.0)
            
            # Measure peak memory
            peak_snapshot = tracemalloc.take_snapshot()
            peak_memory = sum(stat.size for stat in peak_snapshot.statistics('lineno'))
            
            # Calculate memory increase
            memory_increase = (peak_memory - baseline_memory) / (1024 * 1024)  # MB
            
            print("\nMemory Usage Under Load:")
            print(f"  Events emitted: {num_events}")
            print(f"  Baseline memory: {baseline_memory / (1024 * 1024):.2f}MB")
            print(f"  Peak memory: {peak_memory / (1024 * 1024):.2f}MB")
            print(f"  Memory increase: {memory_increase:.2f}MB")
            
            tracemalloc.stop()
            
            # Verify target: < 10MB increase
            assert memory_increase < 10.0, \
                f"Memory increase {memory_increase:.2f}MB exceeds 10MB target"

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_queue_memory_limit(self, tmp_path: Path):
        """Test that queue doesn't grow unbounded."""
        config = Config.load()
        
        system = await EventSystem.from_config(config, project_id="perf_test_queue")
        async with system:
            # Fill queue to capacity
            queue_size = system._queue.maxsize
            
            # Emit more events than queue can hold
            for i in range(queue_size + 500):
                await system.emit(
                    "test.queue",
                    source="perf_test",
                    iteration=i,
                )
            
            # Check queue depth
            queue_depth = system._queue.qsize()
            
            print("\nQueue Memory Limit:")
            print(f"  Queue max size: {queue_size}")
            print(f"  Current depth: {queue_depth}")
            print(f"  Events dropped: {system.events_dropped_count}")
            
            # Queue should not exceed max size
            assert queue_depth <= queue_size, \
                f"Queue depth {queue_depth} exceeds max size {queue_size}"
            
            # Some events should have been dropped
            assert system.events_dropped_count > 0, \
                "Expected some events to be dropped when queue is full"


class TestStressTest:
    """Stress tests for event system."""

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_high_volume_stress(self, tmp_path: Path):
        """Test system under high volume load."""
        config = Config.load()
        
        system = await EventSystem.from_config(config, project_id="perf_test_stress")
        async with system:
            # Emit very large number of events
            num_events = 10000
            
            start_time = time.time()
            
            # Emit in batches to avoid overwhelming
            batch_size = 100
            for batch_start in range(0, num_events, batch_size):
                tasks = []
                for i in range(batch_start, min(batch_start + batch_size, num_events)):
                    task = system.emit(
                        "test.stress",
                        source="perf_test",
                        iteration=i,
                    )
                    tasks.append(task)
                
                await asyncio.gather(*tasks)
                
                # Small delay between batches
                if batch_start % 1000 == 0:
                    await asyncio.sleep(0.1)
            
            # Wait for processing
            await asyncio.sleep(3.0)
            
            duration = time.time() - start_time
            throughput = num_events / duration
            
            print("\nHigh Volume Stress Test:")
            print(f"  Events: {num_events}")
            print(f"  Duration: {duration:.2f}s")
            print(f"  Throughput: {throughput:.1f} events/sec")
            print(f"  Events emitted: {system.events_emitted_count}")
            print(f"  Events dropped: {system.events_dropped_count}")
            
            # Stress test: verify accounting is correct (emitted + dropped = total attempted)
            total_handled = system.events_emitted_count + system.events_dropped_count
            assert total_handled == num_events, \
                f"Event accounting error: {system.events_emitted_count} emitted + {system.events_dropped_count} dropped != {num_events}"
            
            # Under extreme load with queue size 1000 and 10000 events, drops are expected.
            # The system should still process a reasonable portion (at least 50%).
            success_rate = system.events_emitted_count / num_events
            assert success_rate >= 0.50, \
                f"Success rate {success_rate:.1%} is too low (expected >= 50%)"
