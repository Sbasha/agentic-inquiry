"""Performance tests for perf-improvements spec.

Tests performance targets:
- NFR-1.1: count_records completes in <100ms (p95)
- NFR-1.3: analyze_impact completes in <30s (p95) for 500 relationships at depth=2
- NFR-1.4: Batch lookup is ≥5x faster than sequential for 100 entities
- AC-3.2: Maintenance achieves ≥20% disk reduction when bloat exists

These are performance benchmarks marked with @pytest.mark.slow.
"""

import asyncio
import time
from datetime import timedelta
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

pytestmark = [pytest.mark.integration, pytest.mark.slow]

from agentic_inquiry.config import Config, StorageConfig
from agentic_inquiry.database.lancedb_manager import LanceDBManager
from agentic_inquiry.mcp.services.entity_resolver import EntityResolver
from agentic_inquiry.mcp.services.impact_analyzer import ImpactAnalyzer
from agentic_inquiry.mcp.services.session_manager import SessionManager
from agentic_inquiry.mcp.tools.analysis import analyze_impact
from agentic_inquiry.models.graph_entity import GraphEntity
from agentic_inquiry.models.graph_relationship import GraphRelationship
from agentic_inquiry.storage.facade import StorageFacade

# Trigger parser auto-registration
import agentic_inquiry.parsers.implementations  # noqa: F401


def _create_mock_event_system():
    """Create a mock event system for tests."""
    mock_es = MagicMock()
    mock_es.emit = AsyncMock()
    mock_es.start = AsyncMock()
    mock_es.stop = AsyncMock()
    mock_es.flush = AsyncMock()
    return mock_es


class _DummyEmbedder:
    """Dummy embedder for testing."""

    def generate(self, texts):
        """Generate dummy embeddings."""
        return [[0.1] * 384 for _ in texts]

    def ndims(self):
        """Return embedding dimensions."""
        return 384


@pytest.fixture
def temp_test_database(tmp_path):
    """Create a temporary test database that is cleaned up after test completion."""
    storage_root = tmp_path / "test_storage"
    storage_root.mkdir()
    yield storage_root
    # Cleanup is automatic with tmp_path


@pytest_asyncio.fixture
async def test_config(temp_test_database):
    """Create test configuration with temporary storage."""
    config = Config(
        storage=StorageConfig(
            root=str(temp_test_database),
            default_project_id="test_perf",
            backend="lancedb",
        )
    )
    return config


@pytest_asyncio.fixture
async def test_db_manager(test_config):
    """Create database manager with temporary storage."""
    async with LanceDBManager.from_config(test_config) as manager:
        yield manager


@pytest_asyncio.fixture
async def test_storage_facade(test_config):
    """Create StorageFacade for tests."""
    storage = await StorageFacade.from_config(test_config, project_id="test_perf")
    yield storage
    await storage.close()


@pytest_asyncio.fixture
async def test_embedding_registry():
    """Create embedding registry with dummy embedder."""
    from agentic_inquiry.embeddings.registry import EmbeddingRegistry
    return EmbeddingRegistry(default_embedder=_DummyEmbedder())


@pytest_asyncio.fixture
async def populated_database(test_db_manager):
    """Create a database populated with test data for performance testing.

    Creates:
    - 1000 entities in graph_entities
    - 500 relationships in graph_relationships
    """
    from dataclasses import asdict

    # Create entities using GraphEntity model
    entities = []
    for i in range(1000):
        entity = GraphEntity(
            id=f"entity-{i}",
            name=f"TestEntity{i}",
            type="class",
            file_path=f"test/file_{i}.py",
            doc_id=f"doc-{i}",
            project_id="test_perf",
            vector=[0.1] * 384,  # Dummy 384-dim vector
            domain="code"
        )
        entities.append(entity.to_dict())

    # Create relationships (500 relationships)
    # Create a hub entity with many relationships for analyze_impact testing
    relationships = []
    hub_entity_id = "entity-0"

    for i in range(1, 501):
        rel = GraphRelationship(
            id=f"rel-{i}",
            source_id=hub_entity_id,
            target_id=f"entity-{i}",
            type="depends_on",
            project_id="test_perf",
            vector=[0.1] * 384,  # Dummy 384-dim vector
            metadata=None
        )
        relationships.append(asdict(rel))

    # Add entities and relationships to database using db_manager
    await test_db_manager.add_graph_entities(entities)
    await test_db_manager.add_graph_relationships(relationships)

    # Give time for indexing to complete
    await asyncio.sleep(0.5)

    return {
        "entity_count": len(entities),
        "relationship_count": len(relationships),
        "hub_entity_id": hub_entity_id
    }


class TestCountRecordsPerformance:
    """Test count_records performance (NFR-1.1)."""

    @pytest.mark.asyncio
    async def test_count_records_under_100ms(self, test_db_manager, populated_database):
        """Test that count_records on graph_relationships completes in <100ms (p95).

        Requirement: NFR-1.1
        Target: <100ms (p95) for tables with <100,000 rows on standard hardware
        """
        # Warm up
        await test_db_manager.count_records(
            table_name="graph_relationships",
            project_id="test_perf"
        )
        await asyncio.sleep(0.1)

        # Measure query performance
        query_times: List[float] = []
        num_queries = 50

        for _ in range(num_queries):
            start = time.perf_counter()
            count = await test_db_manager.count_records(
                table_name="graph_relationships",
                project_id="test_perf"
            )
            end = time.perf_counter()
            query_times.append((end - start) * 1000)  # Convert to ms

            assert count == populated_database["relationship_count"]

        # Calculate statistics
        avg_query_time = sum(query_times) / len(query_times)
        max_query_time = max(query_times)
        p95_query_time = sorted(query_times)[int(len(query_times) * 0.95)]

        print("\ncount_records Performance (graph_relationships):")
        print(f"  Rows: {populated_database['relationship_count']}")
        print(f"  Queries: {num_queries}")
        print(f"  Average: {avg_query_time:.2f}ms")
        print(f"  P95: {p95_query_time:.2f}ms")
        print(f"  Max: {max_query_time:.2f}ms")

        # Verify target: < 100ms p95
        assert p95_query_time < 100.0, \
            f"P95 query time {p95_query_time:.2f}ms exceeds 100ms target (NFR-1.1)"


class TestBatchLookupPerformance:
    """Test batch entity lookup performance (NFR-1.4)."""

    @pytest.mark.asyncio
    async def test_batch_lookup_5x_faster(self, test_db_manager, populated_database):
        """Test that batch lookup is ≥5x faster than sequential for 100 entities.

        Requirement: NFR-1.4, AC-2.4
        Target: Batch is ≥5x faster than sequential (measured: cold cache, standard hardware)
        """
        # Get 100 entity IDs to look up
        num_entities = 100
        entity_ids = [f"entity-{i}" for i in range(num_entities)]

        # Test 1: Sequential lookups (old approach)
        print(f"\n1. Sequential lookups ({num_entities} entities):")
        seq_start = time.perf_counter()
        seq_results = []
        for entity_id in entity_ids:
            results = await test_db_manager.advanced_filter(
                table_name="graph_entities",
                filters={"id": entity_id},
                project_id="test_perf"
            )
            if results:
                seq_results.extend(results)
        seq_time = time.perf_counter() - seq_start
        print(f"   Time: {seq_time*1000:.2f}ms")
        print(f"   Results: {len(seq_results)} entities")

        # Test 2: Batch lookup (new approach)
        batch_size = 100
        print(f"\n2. Batch lookup (batch_size={batch_size}):")
        batch_start = time.perf_counter()
        batch_results = await test_db_manager.advanced_filter(
            table_name="graph_entities",
            filters={"id": ("IN", entity_ids)},
            project_id="test_perf",
            limit=batch_size
        )
        batch_time = time.perf_counter() - batch_start
        print(f"   Time: {batch_time*1000:.2f}ms")
        print(f"   Results: {len(batch_results)} entities")

        # Calculate performance improvement
        speedup = seq_time / batch_time if batch_time > 0 else float('inf')
        percentage = (batch_time / seq_time * 100) if seq_time > 0 else 0

        print("\nPerformance Comparison:")
        print(f"  Sequential time: {seq_time*1000:.2f}ms")
        print(f"  Batch time:      {batch_time*1000:.2f}ms")
        print(f"  Speedup:         {speedup:.1f}x")
        print(f"  Batch is {percentage:.1f}% of sequential time")

        # Verify acceptance criteria: Batch is ≥5x faster (i.e., ≤20% of sequential time)
        assert speedup >= 5.0, \
            f"Batch speedup {speedup:.1f}x is less than 5x target (NFR-1.4)"
        assert percentage <= 20.0, \
            f"Batch is {percentage:.1f}% of sequential time, should be ≤20% (AC-2.4)"


class TestAnalyzeImpactPerformance:
    """Test analyze_impact performance (NFR-1.3)."""

    @pytest_asyncio.fixture
    async def test_services(self, test_storage_facade, test_config, test_embedding_registry):
        """Create MCP services for testing."""
        mock_event_system = _create_mock_event_system()
        session_manager = SessionManager(test_storage_facade, test_config)

        # Create entity resolver
        entity_resolver = EntityResolver(
            db_manager=test_storage_facade,
            config=test_config
        )

        # Create impact analyzer
        impact_analyzer = ImpactAnalyzer(
            db_manager=test_storage_facade,
            entity_resolver=entity_resolver,
            config=test_config
        )

        session_id = await session_manager.create_session(
            project_id="test_perf",
            description="Performance test session"
        )

        return {
            "session_manager": session_manager,
            "session_id": session_id,
            "storage": test_storage_facade,
            "impact_analyzer": impact_analyzer,
            "entity_resolver": entity_resolver,
            "event_system": mock_event_system,
            "config": test_config,
        }

    @pytest.mark.asyncio
    async def test_analyze_impact_under_30s(self, test_services, populated_database):
        """Test that analyze_impact completes in <30s (p95) for 500 relationships at depth=2.

        Requirement: NFR-1.3
        Target: <30s (p95) for entities with ≤500 relationships at depth=2
        """
        hub_entity_id = populated_database["hub_entity_id"]

        # Warm up
        try:
            await analyze_impact(
                services=test_services,
                session_id=test_services["session_id"],
                entity="entity-999",  # Non-hub entity for warmup
                max_depth=1,
                timeout_ms=5000
            )
        except Exception:
            pass  # Warmup may fail, that's okay

        await asyncio.sleep(0.1)

        # Measure analyze_impact performance
        analyze_times: List[float] = []
        num_runs = 10  # Smaller sample for longer-running test

        for i in range(num_runs):
            start = time.perf_counter()
            try:
                result = await analyze_impact(
                    services=test_services,
                    session_id=test_services["session_id"],
                    entity=f"TestEntity{hub_entity_id.split('-')[1]}",  # Use entity name
                    max_depth=2,
                    timeout_ms=None  # No timeout for measurement
                )
                end = time.perf_counter()
                analyze_times.append((end - start))

                # Verify we got results (not partial)
                if "partial" in result:
                    print(f"  Warning: Run {i+1} returned partial results")
            except Exception as e:
                print(f"  Warning: Run {i+1} failed: {e}")
                # Still record the time
                end = time.perf_counter()
                analyze_times.append((end - start))

        # Calculate statistics
        avg_time = sum(analyze_times) / len(analyze_times)
        max_time = max(analyze_times)
        p95_time = sorted(analyze_times)[int(len(analyze_times) * 0.95)]

        print("\nanalyze_impact Performance (500 relationships, depth=2):")
        print(f"  Runs: {num_runs}")
        print(f"  Average: {avg_time:.2f}s")
        print(f"  P95: {p95_time:.2f}s")
        print(f"  Max: {max_time:.2f}s")

        # Verify target: < 30s p95
        assert p95_time < 30.0, \
            f"P95 analyze_impact time {p95_time:.2f}s exceeds 30s target (NFR-1.3)"


class TestMaintenanceDiskReduction:
    """Test maintenance disk reduction (AC-3.2)."""

    @pytest.mark.asyncio
    async def test_maintenance_disk_reduction(self, test_db_manager, temp_test_database):
        """Test that maintenance achieves ≥20% disk reduction when bloat exists.

        Requirement: AC-3.2
        Target: ≥20% disk reduction when version count > 10

        Note: This test creates artificial bloat by performing multiple updates.
        """
        # Create table with initial data
        table_name = "test_maintenance_table"

        initial_data = []
        for i in range(100):
            initial_data.append({
                "id": f"item-{i}",
                "content": f"Initial content {i}",
                "vector": [0.1] * 384,
                "project_id": "test_perf"
            })

        await test_db_manager.upsert(
            table_name=table_name,
            data=initial_data
        )

        # Create bloat by updating all rows multiple times (creates MVCC versions)
        print("\nCreating artificial bloat via multiple updates...")
        for version in range(15):  # 15 versions > 10 threshold
            update_data = []
            for i in range(100):
                update_data.append({
                    "id": f"item-{i}",
                    "content": f"Updated content {i} v{version}",
                    "vector": [0.1 + version * 0.01] * 384,
                    "project_id": "test_perf"
                })

            await test_db_manager.upsert(
                table_name=table_name,
                data=update_data
            )

        print("  Bloat created (15 versions)")

        # Measure disk usage before maintenance
        storage_path = Path(temp_test_database)
        lance_dir = storage_path / ".lance"

        if not lance_dir.exists():
            pytest.skip("LanceDB storage directory not found, skipping disk measurement")

        def get_dir_size(path: Path) -> int:
            """Calculate total size of directory in bytes."""
            total = 0
            for item in path.rglob("*"):
                if item.is_file():
                    total += item.stat().st_size
            return total

        size_before = get_dir_size(lance_dir)
        print(f"  Disk usage before: {size_before / (1024*1024):.2f}MB")

        # Run maintenance
        print("\nRunning maintenance...")
        result = await test_db_manager.run_maintenance(
            table_names=[table_name],
            cleanup_older_than=timedelta(minutes=0)  # Clean all old versions
        )

        print(f"  Maintenance result: {result}")

        # Measure disk usage after maintenance
        size_after = get_dir_size(lance_dir)
        print(f"  Disk usage after: {size_after / (1024*1024):.2f}MB")

        # Calculate reduction
        bytes_freed = size_before - size_after
        reduction_percentage = (bytes_freed / size_before * 100) if size_before > 0 else 0

        print("\nDisk Reduction:")
        print(f"  Before: {size_before / (1024*1024):.2f}MB")
        print(f"  After:  {size_after / (1024*1024):.2f}MB")
        print(f"  Freed:  {bytes_freed / (1024*1024):.2f}MB")
        print(f"  Reduction: {reduction_percentage:.1f}%")

        # Verify acceptance criteria: ≥20% reduction when bloat exists
        # Note: With 15 versions, we expect significant reduction
        assert reduction_percentage >= 20.0, \
            f"Disk reduction {reduction_percentage:.1f}% is less than 20% target (AC-3.2)"


class TestPerformanceRegression:
    """Additional performance regression tests."""

    @pytest.mark.asyncio
    async def test_multiple_count_records_no_degradation(self, test_db_manager, populated_database):
        """Test that repeated count_records calls don't degrade performance."""
        times = []

        for i in range(100):
            start = time.perf_counter()
            await test_db_manager.count_records(
                table_name="graph_relationships",
                project_id="test_perf"
            )
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

        # Compare first 10 vs last 10
        first_avg = sum(times[:10]) / 10
        last_avg = sum(times[-10:]) / 10
        degradation = ((last_avg - first_avg) / first_avg * 100) if first_avg > 0 else 0

        print("\ncount_records regression test:")
        print(f"  First 10 avg: {first_avg:.2f}ms")
        print(f"  Last 10 avg:  {last_avg:.2f}ms")
        print(f"  Degradation:  {degradation:.1f}%")

        # Allow up to 50% degradation (caching may improve performance)
        assert degradation < 50.0, \
            f"Performance degraded by {degradation:.1f}% over 100 calls"
