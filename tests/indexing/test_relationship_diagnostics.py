"""
Diagnostic tests for relationship resolution logging and performance.

Tests verify:
- Logging captures resolution failures with helpful details
- Error messages provide actionable information
- Performance is acceptable for typical workloads
"""

import pytest

pytestmark = pytest.mark.unit

import asyncio
import logging
import time
from pathlib import Path
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest

from agentic_inquiry.database.lancedb_manager import LanceDBManager
from agentic_inquiry.indexing.relationship_resolver import RelationshipResolver
from agentic_inquiry.indexing.symbol_registry import SymbolRegistry


class LogCapture:
    """Capture log messages for testing."""

    def __init__(self):
        self.records: List[logging.LogRecord] = []
        self.handler = logging.Handler()
        self.handler.emit = self._emit

    def _emit(self, record: logging.LogRecord):
        self.records.append(record)

    def attach(self, logger_name: str):
        """Attach to a logger."""
        logger = logging.getLogger(logger_name)
        logger.addHandler(self.handler)
        logger.setLevel(logging.DEBUG)
        return self

    def detach(self, logger_name: str):
        """Detach from a logger."""
        logger = logging.getLogger(logger_name)
        logger.removeHandler(self.handler)

    def get_messages(self, level: str = None) -> List[str]:
        """Get captured messages, optionally filtered by level."""
        if level:
            level_num = getattr(logging, level.upper())
            return [r.getMessage() for r in self.records if r.levelno == level_num]
        return [r.getMessage() for r in self.records]

    def has_message_containing(self, text: str, level: str = None) -> bool:
        """Check if any message contains the given text."""
        messages = self.get_messages(level)
        return any(text in msg for msg in messages)

    def clear(self):
        """Clear captured records."""
        self.records.clear()


@pytest.fixture
def log_capture():
    """Fixture providing log capture for relationship resolver."""
    capture = LogCapture()
    capture.attach("agentic_inquiry.indexing.relationship_resolver")
    yield capture
    capture.detach("agentic_inquiry.indexing.relationship_resolver")


@pytest.fixture
async def mock_db_manager():
    """Mock database manager for testing."""
    db = AsyncMock(spec=LanceDBManager)

    # Mock query_entities to return empty results by default
    db.query_entities = AsyncMock(return_value=[])

    # Mock advanced_filter (used by database lookup strategies)
    db.advanced_filter = AsyncMock(return_value=[])

    return db


@pytest.fixture
async def resolver(mock_db_manager):
    """Create relationship resolver with mock dependencies."""
    symbol_registry = MagicMock(spec=SymbolRegistry)
    # Mock symbol registry methods to return empty results by default
    symbol_registry.lookup_by_name = MagicMock(return_value=[])
    symbol_registry.score_file_naming_pattern = MagicMock(return_value=0)
    symbol_registry.score_directory_structure = MagicMock(return_value=0)
    symbol_registry.get_co_occurrence_score = MagicMock(return_value=0)
    symbol_registry.get_import_frequency = MagicMock(return_value=0)

    project_root = Path("/test/project")

    resolver = RelationshipResolver(
        symbol_registry=symbol_registry,
        project_root=project_root,
        db_manager=mock_db_manager,
        # Enable database lookups to test the full resolution path
        skip_database_lookups=False,
        # Disable cache prewarming to avoid side effects in tests
        enable_cache_prewarming=False,
    )

    return resolver


class TestResolutionFailureLogging:
    """Test that resolution failures are logged with helpful details."""

    @pytest.mark.asyncio
    async def test_logs_failed_resolution_with_details(
        self, resolver: RelationshipResolver, log_capture: LogCapture
    ):
        """Test that failed resolutions log all relevant details."""
        # Attempt to resolve a symbol that doesn't exist
        result = await resolver.resolve_import(
            target_name="NonExistentClass",
            target_type="class",
            source_file="/test/project/src/main.py",
            source_language="python",
            import_path="some.module",
        )

        assert result is None

        # Verify failure is logged - detailed info is in WARNING level
        assert log_capture.has_message_containing("Failed to resolve", "WARNING")

        # Verify log includes key details (WARNING level has full diagnostic info)
        messages = log_capture.get_messages("WARNING")
        failure_msg = next(msg for msg in messages if "Failed to resolve" in msg)

        # Check that failure message includes all diagnostic info
        assert "NonExistentClass" in failure_msg
        assert "/test/project/src/main.py" in failure_msg
        assert "some.module" in failure_msg
        assert "class" in failure_msg
        assert "python" in failure_msg

    @pytest.mark.asyncio
    async def test_logs_no_entities_found(
        self, resolver: RelationshipResolver, log_capture: LogCapture
    ):
        """Test that 'no entities found' is logged clearly."""
        result = await resolver.resolve_import(
            target_name="MissingSymbol",
            target_type=None,
            source_file="/test/project/src/main.py",
            source_language="python",
        )

        assert result is None
        assert log_capture.has_message_containing(
            "No entities found for symbol", "DEBUG"
        )

    @pytest.mark.asyncio
    async def test_logs_database_errors(
        self,
        resolver: RelationshipResolver,
        mock_db_manager: AsyncMock,
        log_capture: LogCapture,
    ):
        """Test that database errors are logged with helpful context."""
        # Make query_entities raise an error
        mock_db_manager.query_entities.side_effect = Exception(
            "Database connection failed"
        )

        result = await resolver.resolve_import(
            target_name="SomeClass",
            target_type="class",
            source_file="/test/project/src/main.py",
            source_language="python",
        )

        assert result is None

        # Verify error is logged
        assert log_capture.has_message_containing(
            "Error", "DEBUG"
        ) or log_capture.has_message_containing("Error", "ERROR")


class TestResolutionSuccessLogging:
    """Test that successful resolutions are logged with strategy info."""

    @pytest.mark.asyncio
    async def test_logs_successful_exact_match(
        self,
        resolver: RelationshipResolver,
        mock_db_manager: AsyncMock,
        log_capture: LogCapture,
    ):
        """Test that exact match success is logged."""
        # Mock successful entity lookup
        mock_db_manager.query_entities.return_value = [
            {
                "id": "entity-123",
                "name": "TestClass",
                "file_path": "/test/project/src/module.py",
                "type": "class",
            }
        ]

        result = await resolver.resolve_import(
            target_name="TestClass",
            target_type="class",
            source_file="/test/project/src/main.py",
            source_language="python",
            import_path="module",
        )

        assert result is not None

        # Verify success is logged with strategy
        messages = log_capture.get_messages("DEBUG")
        assert any("Resolved TestClass" in msg for msg in messages)
        assert any(
            "exact match" in msg.lower() or "improved symbol resolution" in msg.lower()
            for msg in messages
        )

    @pytest.mark.asyncio
    async def test_logs_resolution_strategy_used(
        self,
        resolver: RelationshipResolver,
        mock_db_manager: AsyncMock,
        log_capture: LogCapture,
    ):
        """Test that the resolution strategy is logged."""
        # Mock fuzzy match (multiple entities, pick first)
        mock_db_manager.query_entities.return_value = [
            {
                "id": "entity-456",
                "name": "TestClass",
                "file_path": "/test/project/src/other.py",
                "type": "class",
            }
        ]

        result = await resolver.resolve_import(
            target_name="TestClass",
            target_type="class",
            source_file="/test/project/src/main.py",
            source_language="python",
        )

        assert result is not None

        # Verify strategy is mentioned in logs
        messages = log_capture.get_messages("DEBUG")
        strategy_mentioned = any(
            "fuzzy match" in msg.lower()
            or "proximity" in msg.lower()
            or "exact match" in msg.lower()
            or "improved symbol resolution" in msg.lower()
            for msg in messages
        )
        assert strategy_mentioned


class TestPerformanceDiagnostics:
    """Test that resolution performance is acceptable."""

    @pytest.mark.asyncio
    async def test_single_resolution_performance(
        self, resolver: RelationshipResolver, mock_db_manager: AsyncMock
    ):
        """Test that single resolution completes quickly."""
        # Mock entity lookup
        mock_db_manager.query_entities.return_value = [
            {
                "id": "entity-789",
                "name": "FastClass",
                "file_path": "/test/project/src/fast.py",
                "type": "class",
            }
        ]

        start_time = time.perf_counter()

        result = await resolver.resolve_import(
            target_name="FastClass",
            target_type="class",
            source_file="/test/project/src/main.py",
            source_language="python",
        )

        elapsed = time.perf_counter() - start_time

        assert result is not None
        # Single resolution should complete in under 100ms
        assert elapsed < 0.1, f"Resolution took {elapsed:.3f}s, expected < 0.1s"

    @pytest.mark.asyncio
    async def test_batch_resolution_performance(
        self, resolver: RelationshipResolver, mock_db_manager: AsyncMock
    ):
        """Test that batch resolutions complete in reasonable time."""
        # Mock entity lookup
        mock_db_manager.query_entities.return_value = [
            {
                "id": f"entity-{i}",
                "name": f"Class{i}",
                "file_path": f"/test/project/src/module{i}.py",
                "type": "class",
            }
            for i in range(10)
        ]

        start_time = time.perf_counter()

        # Resolve 50 symbols
        tasks = [
            resolver.resolve_import(
                target_name=f"Class{i}",
                target_type="class",
                source_file="/test/project/src/main.py",
                source_language="python",
            )
            for i in range(50)
        ]

        results = await asyncio.gather(*tasks)

        elapsed = time.perf_counter() - start_time

        # 50 resolutions should complete in under 5 seconds
        assert elapsed < 5.0, f"Batch resolution took {elapsed:.3f}s, expected < 5.0s"

        # Calculate average time per resolution
        avg_time = elapsed / len(results)
        assert avg_time < 0.1, (
            f"Average resolution time {avg_time:.3f}s, expected < 0.1s"
        )

    @pytest.mark.asyncio
    async def test_cache_improves_performance(
        self, resolver: RelationshipResolver, mock_db_manager: AsyncMock
    ):
        """Test that caching improves repeated resolution performance."""
        # Mock entity lookup
        mock_db_manager.query_entities.return_value = [
            {
                "id": "entity-cached",
                "name": "CachedClass",
                "file_path": "/test/project/src/cached.py",
                "type": "class",
            }
        ]

        # First resolution (cache miss)
        start_time = time.perf_counter()
        result1 = await resolver.resolve_import(
            target_name="CachedClass",
            target_type="class",
            source_file="/test/project/src/main.py",
            source_language="python",
        )
        first_elapsed = time.perf_counter() - start_time

        # Second resolution (cache hit)
        start_time = time.perf_counter()
        result2 = await resolver.resolve_import(
            target_name="CachedClass",
            target_type="class",
            source_file="/test/project/src/main.py",
            source_language="python",
        )
        second_elapsed = time.perf_counter() - start_time

        assert result1 == result2
        # Cached resolution should be faster (or at least not slower)
        # Allow some variance due to system load
        assert second_elapsed <= first_elapsed * 1.5


class TestResolutionStatistics:
    """Test that resolution statistics are tracked correctly."""

    @pytest.mark.asyncio
    async def test_tracks_resolution_stats(
        self, resolver: RelationshipResolver, mock_db_manager: AsyncMock
    ):
        """Test that resolution statistics are tracked."""
        # Mock some successful resolutions
        mock_db_manager.query_entities.return_value = [
            {
                "id": "entity-stats",
                "name": "StatsClass",
                "file_path": "/test/project/src/stats.py",
                "type": "class",
            }
        ]

        # Perform several resolutions
        for i in range(5):
            await resolver.resolve_import(
                target_name=f"Class{i}",
                target_type="class",
                source_file="/test/project/src/main.py",
                source_language="python",
            )

        # Get statistics
        stats = resolver.get_resolution_stats()

        # Verify stats structure
        assert "total_attempts" in stats
        assert "resolved" in stats
        assert "unresolved" in stats
        assert "by_strategy" in stats
        assert "cache_hits" in stats
        assert "cache_misses" in stats

        # Verify counts
        assert stats["total_attempts"] == 5
        assert stats["resolved"] + stats["unresolved"] == 5

    @pytest.mark.asyncio
    async def test_tracks_strategy_breakdown(
        self, resolver: RelationshipResolver, mock_db_manager: AsyncMock
    ):
        """Test that strategy breakdown is tracked."""
        # Mock successful resolution
        mock_db_manager.query_entities.return_value = [
            {
                "id": "entity-strategy",
                "name": "StrategyClass",
                "file_path": "/test/project/src/strategy.py",
                "type": "class",
            }
        ]

        # Perform resolution
        await resolver.resolve_import(
            target_name="StrategyClass",
            target_type="class",
            source_file="/test/project/src/main.py",
            source_language="python",
        )

        stats = resolver.get_resolution_stats()

        # Verify strategy breakdown exists
        assert isinstance(stats["by_strategy"], dict)
        # At least one strategy should have been used
        assert sum(stats["by_strategy"].values()) > 0


class TestErrorMessageQuality:
    """Test that error messages are helpful and actionable."""

    @pytest.mark.asyncio
    async def test_error_message_includes_context(
        self, resolver: RelationshipResolver, log_capture: LogCapture
    ):
        """Test that error messages include enough context to debug."""
        # Attempt resolution that will fail
        await resolver.resolve_import(
            target_name="MysteryClass",
            target_type="class",
            source_file="/test/project/src/mystery.py",
            source_language="python",
            import_path="unknown.module",
        )

        # Get all warning messages (detailed diagnostic info is at WARNING level)
        messages = log_capture.get_messages("WARNING")

        # Find the failure message
        failure_msgs = [msg for msg in messages if "Failed to resolve" in msg]
        assert len(failure_msgs) > 0

        failure_msg = failure_msgs[0]

        # Verify message includes actionable information
        # Should include: symbol name, source file, import path, type, language
        assert "MysteryClass" in failure_msg
        assert "/test/project/src/mystery.py" in failure_msg
        assert "unknown.module" in failure_msg
        assert "class" in failure_msg
        assert "python" in failure_msg

    @pytest.mark.asyncio
    async def test_logs_intermediate_strategy_attempts(
        self, resolver: RelationshipResolver, log_capture: LogCapture
    ):
        """Test that intermediate strategy attempts are logged."""
        # Attempt resolution that will try multiple strategies
        await resolver.resolve_import(
            target_name="MultiStrategyClass",
            target_type="class",
            source_file="/test/project/src/main.py",
            source_language="python",
            import_path="some.module",
        )

        messages = log_capture.get_messages("DEBUG")

        # Should see attempts at different strategies
        # At minimum, should see "No entities found" from fuzzy match
        assert any("No entities found" in msg for msg in messages)


@pytest.mark.asyncio
async def test_performance_summary(
    resolver: RelationshipResolver, mock_db_manager: AsyncMock
):
    """Generate a performance summary for documentation."""
    # Mock entity lookup
    mock_db_manager.query_entities.return_value = [
        {
            "id": "entity-perf",
            "name": "PerfClass",
            "file_path": "/test/project/src/perf.py",
            "type": "class",
        }
    ]

    # Test various batch sizes
    batch_sizes = [1, 10, 50, 100]
    results = {}

    for batch_size in batch_sizes:
        start_time = time.perf_counter()

        tasks = [
            resolver.resolve_import(
                target_name=f"Class{i}",
                target_type="class",
                source_file="/test/project/src/main.py",
                source_language="python",
            )
            for i in range(batch_size)
        ]

        await asyncio.gather(*tasks)

        elapsed = time.perf_counter() - start_time
        avg_time = elapsed / batch_size

        results[batch_size] = {
            "total_time": elapsed,
            "avg_time": avg_time,
            "throughput": batch_size / elapsed,
        }

    # Print summary for documentation
    print("\n=== Resolution Performance Summary ===")
    for batch_size, metrics in results.items():
        print(f"\nBatch size: {batch_size}")
        print(f"  Total time: {metrics['total_time']:.3f}s")
        print(f"  Avg per resolution: {metrics['avg_time']:.4f}s")
        print(f"  Throughput: {metrics['throughput']:.1f} resolutions/sec")

    # Verify performance is acceptable
    # Average time should be under 100ms for all batch sizes
    for batch_size, metrics in results.items():
        assert metrics["avg_time"] < 0.1, (
            f"Batch size {batch_size}: avg time {metrics['avg_time']:.3f}s exceeds 0.1s"
        )
