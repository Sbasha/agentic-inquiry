"""Property-based tests for resolve_import performance optimization.

These tests validate performance bounds and profiling data as specified
in the design document.

Property tests:
- Property 2: Cache Hit Performance Bound (Requirements 2.1)
- Property 3: Cache Miss Performance Bound (Requirements 2.2)
- Property 5: Profiling Data Completeness (Requirements 2.5)
"""

import pytest

pytestmark = pytest.mark.unit

import time
from hypothesis import given, strategies as st, settings
from unittest.mock import MagicMock, AsyncMock

from agentic_inquiry.indexing.relationship_resolver import (
    RelationshipResolver,
    SimpleCache,
)


# =============================================================================
# Helpers for creating test data
# =============================================================================


def create_mock_resolver() -> RelationshipResolver:
    """Create a mock RelationshipResolver for testing."""
    mock_db = MagicMock()
    mock_db.query_entities = AsyncMock(return_value=[])
    mock_db.get_relationships = AsyncMock(return_value=[])

    mock_registry = MagicMock()
    mock_registry.resolve_symbol = MagicMock(return_value=None)
    mock_registry.get_symbol = MagicMock(return_value=None)

    resolver = RelationshipResolver(
        symbol_registry=mock_registry,
        project_root="/tmp/test_project",
        db_manager=mock_db,
    )

    return resolver


def create_populated_cache(size: int = 100) -> SimpleCache:
    """Create a pre-populated cache for testing cache hits."""
    cache = SimpleCache(max_size=1000)

    for i in range(size):
        cache.put(
            target_name=f"symbol_{i}",
            target_type="function",
            source_file=f"file_{i % 10}.py",
            result=(f"resolved_file_{i}.py", "function", 0.9),
        )

    return cache


# =============================================================================
# Property 2: Cache Hit Performance Bound
# Validates: Requirements 2.1
# =============================================================================


class TestCacheHitPerformance:
    """Tests for cache hit resolution performance."""

    @pytest.mark.asyncio
    async def test_cache_hit_under_10ms(self):
        """Cache hit resolution SHALL complete in less than 10 milliseconds."""
        resolver = create_mock_resolver()

        # Pre-populate cache
        resolver._cache.put(
            target_name="CachedSymbol",
            target_type="class",
            source_file="source.py",
            result=("target.py", "class", 1.0),
        )

        start = time.perf_counter()
        result = await resolver.resolve_import(
            target_name="CachedSymbol",
            target_type="class",
            source_file="source.py",
            source_language="python",
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result is not None
        assert elapsed_ms < 10.0, f"Cache hit took {elapsed_ms:.2f}ms, should be < 10ms"

    @pytest.mark.asyncio
    async def test_multiple_cache_hits_performance(self):
        """Multiple cache hits should all be fast."""
        resolver = create_mock_resolver()

        # Pre-populate cache with multiple entries
        for i in range(10):
            resolver._cache.put(
                target_name=f"Symbol{i}",
                target_type="function",
                source_file=f"source_{i}.py",
                result=(f"target_{i}.py", "function", 0.9),
            )

        # Time multiple cache hits
        total_time_ms = 0.0
        for i in range(10):
            start = time.perf_counter()
            result = await resolver.resolve_import(
                target_name=f"Symbol{i}",
                target_type="function",
                source_file=f"source_{i}.py",
                source_language="python",
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            total_time_ms += elapsed_ms

            assert result is not None

        avg_time_ms = total_time_ms / 10
        assert avg_time_ms < 10.0, f"Average cache hit took {avg_time_ms:.2f}ms"

    def test_simple_cache_get_performance(self):
        """SimpleCache.get() should be O(1)."""
        cache = create_populated_cache(size=1000)

        # Warm up
        cache.get("symbol_0", "function", "file_0.py")

        # Time cache lookups
        timings = []
        for i in range(100):
            start = time.perf_counter()
            cache.get(f"symbol_{i}", "function", f"file_{i % 10}.py")
            elapsed_ns = (time.perf_counter() - start) * 1_000_000_000
            timings.append(elapsed_ns)

        avg_ns = sum(timings) / len(timings)
        # Cache lookup should be under 1ms (1,000,000 ns)
        assert avg_ns < 1_000_000, f"Average cache lookup took {avg_ns:.0f}ns"

    @given(
        target_name=st.text(
            min_size=1,
            max_size=30,
            alphabet=st.characters(whitelist_categories=("L", "N")),
        ),
        target_type=st.sampled_from(["function", "class", "module", "variable"]),
        source_file=st.text(
            min_size=1,
            max_size=30,
            alphabet=st.characters(whitelist_categories=("L", "N")),
        ),
    )
    @settings(max_examples=30)
    @pytest.mark.asyncio
    async def test_property_2_cache_hit_performance_bound(
        self, target_name, target_type, source_file
    ):
        """Property 2: For any cache hit, resolution SHALL complete in < 10ms."""
        if not target_name or not source_file:
            return  # Skip empty strings

        resolver = create_mock_resolver()
        source_file_with_ext = f"{source_file}.py"

        # Pre-populate cache
        resolver._cache.put(
            target_name=target_name,
            target_type=target_type,
            source_file=source_file_with_ext,
            result=(f"resolved_{source_file}.py", target_type, 0.95),
        )

        start = time.perf_counter()
        result = await resolver.resolve_import(
            target_name=target_name,
            target_type=target_type,
            source_file=source_file_with_ext,
            source_language="python",
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result is not None, "Cache should hit"
        assert elapsed_ms < 10.0, f"Cache hit took {elapsed_ms:.2f}ms, limit is 10ms"


# =============================================================================
# Property 3: Cache Miss Performance Bound
# Validates: Requirements 2.2
# =============================================================================


class TestCacheMissPerformance:
    """Tests for cache miss resolution performance."""

    @pytest.mark.asyncio
    async def test_cache_miss_under_100ms(self):
        """Cache miss resolution SHALL complete in less than 100 milliseconds."""
        resolver = create_mock_resolver()

        # Ensure cache miss by not populating cache
        start = time.perf_counter()
        await resolver.resolve_import(
            target_name="UnknownSymbol",
            target_type="class",
            source_file="source.py",
            source_language="python",
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Result may be None (unresolved) but timing should be bounded
        assert elapsed_ms < 100.0, (
            f"Cache miss took {elapsed_ms:.2f}ms, should be < 100ms"
        )

    @pytest.mark.asyncio
    async def test_cache_miss_with_db_query(self):
        """Cache miss with database query should still be bounded."""
        resolver = create_mock_resolver()

        # Mock database to return empty results (simulating cache miss path)
        resolver.db_manager.query_entities = AsyncMock(return_value=[])

        start = time.perf_counter()
        await resolver.resolve_import(
            target_name="MissedSymbol",
            target_type="function",
            source_file="module.py",
            source_language="python",
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 100.0, f"Cache miss with DB took {elapsed_ms:.2f}ms"

    @given(
        target_name=st.text(
            min_size=5,
            max_size=30,
            alphabet=st.characters(whitelist_categories=("L", "N")),
        ),
        source_file=st.text(
            min_size=5,
            max_size=30,
            alphabet=st.characters(whitelist_categories=("L", "N")),
        ),
    )
    @settings(max_examples=20)
    @pytest.mark.asyncio
    async def test_property_3_cache_miss_performance_bound(
        self, target_name, source_file
    ):
        """Property 3: For any cache miss, resolution SHALL complete in < 100ms."""
        if not target_name or not source_file:
            return

        resolver = create_mock_resolver()
        source_file_with_ext = f"{source_file}.py"

        # Ensure cache miss with unique symbol name
        unique_name = f"unique_{target_name}_{hash(source_file) % 10000}"

        start = time.perf_counter()
        await resolver.resolve_import(
            target_name=unique_name,
            target_type="function",
            source_file=source_file_with_ext,
            source_language="python",
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 100.0, f"Cache miss took {elapsed_ms:.2f}ms, limit is 100ms"


# =============================================================================
# Property 5: Profiling Data Completeness
# Validates: Requirements 2.5
# =============================================================================


class TestProfilingDataCompleteness:
    """Tests for profiling data tracking."""

    @pytest.mark.asyncio
    async def test_stats_track_resolution_strategies(self):
        """Statistics SHALL track time spent in each resolution strategy."""
        resolver = create_mock_resolver()

        # Perform some resolutions
        for i in range(5):
            await resolver.resolve_import(
                target_name=f"symbol_{i}",
                target_type="function",
                source_file=f"file_{i}.py",
                source_language="python",
            )

        stats = resolver.get_resolution_stats()

        # Verify strategy tracking exists
        assert "by_strategy" in stats
        assert isinstance(stats["by_strategy"], dict)

    @pytest.mark.asyncio
    async def test_stats_track_cache_metrics(self):
        """Statistics SHALL track cache hit/miss metrics."""
        resolver = create_mock_resolver()

        # Pre-populate cache for some symbols
        for i in range(3):
            resolver._cache.put(
                target_name=f"cached_{i}",
                target_type="function",
                source_file=f"source_{i}.py",
                result=(f"target_{i}.py", "function", 0.9),
            )

        # Resolve cached symbols (hits)
        for i in range(3):
            await resolver.resolve_import(
                target_name=f"cached_{i}",
                target_type="function",
                source_file=f"source_{i}.py",
                source_language="python",
            )

        # Resolve uncached symbols (misses)
        for i in range(2):
            await resolver.resolve_import(
                target_name=f"uncached_{i}",
                target_type="function",
                source_file=f"source_{i}.py",
                source_language="python",
            )

        stats = resolver.get_resolution_stats()

        assert "cache_hits" in stats
        assert "cache_misses" in stats
        assert stats["cache_hits"] == 3
        assert stats["cache_misses"] == 2

    @pytest.mark.asyncio
    async def test_stats_include_total_attempts(self):
        """Statistics SHALL include total resolution attempts."""
        resolver = create_mock_resolver()

        num_attempts = 7
        for i in range(num_attempts):
            await resolver.resolve_import(
                target_name=f"symbol_{i}",
                target_type="function",
                source_file=f"file_{i}.py",
                source_language="python",
            )

        stats = resolver.get_resolution_stats()

        assert "total_attempts" in stats
        assert stats["total_attempts"] == num_attempts

    @pytest.mark.asyncio
    async def test_stats_include_cache_hit_rate(self):
        """Statistics SHALL include cache hit rate percentage."""
        resolver = create_mock_resolver()

        # Pre-populate cache for some symbols
        for i in range(5):
            resolver._cache.put(
                target_name=f"cached_{i}",
                target_type="function",
                source_file=f"source_{i}.py",
                result=(f"target_{i}.py", "function", 0.9),
            )

        # Resolve: 5 hits + 5 misses = 50% hit rate
        for i in range(5):
            await resolver.resolve_import(
                target_name=f"cached_{i}",
                target_type="function",
                source_file=f"source_{i}.py",
                source_language="python",
            )

        for i in range(5):
            await resolver.resolve_import(
                target_name=f"uncached_{i}",
                target_type="function",
                source_file=f"source_{i}.py",
                source_language="python",
            )

        stats = resolver.get_resolution_stats()

        assert "cache_hit_rate" in stats
        assert 0 <= stats["cache_hit_rate"] <= 100  # Percentage
        assert abs(stats["cache_hit_rate"] - 50.0) < 1.0  # ~50%

    @given(
        num_cached=st.integers(min_value=0, max_value=50),
        num_uncached=st.integers(min_value=1, max_value=50),
    )
    @settings(max_examples=20)
    @pytest.mark.asyncio
    async def test_property_5_profiling_data_completeness(
        self, num_cached, num_uncached
    ):
        """Property 5: For any set of resolutions, profiling data SHALL be complete."""
        resolver = create_mock_resolver()

        # Pre-populate cache
        for i in range(num_cached):
            resolver._cache.put(
                target_name=f"cached_{i}",
                target_type="function",
                source_file=f"source_{i}.py",
                result=(f"target_{i}.py", "function", 0.9),
            )

        # Resolve cached symbols
        for i in range(num_cached):
            await resolver.resolve_import(
                target_name=f"cached_{i}",
                target_type="function",
                source_file=f"source_{i}.py",
                source_language="python",
            )

        # Resolve uncached symbols
        for i in range(num_uncached):
            await resolver.resolve_import(
                target_name=f"uncached_{i}",
                target_type="function",
                source_file=f"source_{i}.py",
                source_language="python",
            )

        stats = resolver.get_resolution_stats()

        # Verify all required fields are present
        required_fields = [
            "total_attempts",
            "cache_hits",
            "cache_misses",
            "resolved",
            "unresolved",
            "by_strategy",
            "cache_hit_rate",
        ]

        for field in required_fields:
            assert field in stats, f"Missing required field: {field}"

        # Verify counts are consistent
        assert stats["total_attempts"] == num_cached + num_uncached
        assert stats["cache_hits"] == num_cached
        assert stats["cache_misses"] == num_uncached

        # Verify hit rate calculation (cache_hit_rate is a percentage 0-100)
        if stats["total_attempts"] > 0:
            expected_rate_percent = (num_cached / (num_cached + num_uncached)) * 100
            assert abs(stats["cache_hit_rate"] - expected_rate_percent) < 1.0


# =============================================================================
# Additional Performance Tests
# =============================================================================


class TestSimpleCachePerformance:
    """Tests for SimpleCache performance characteristics."""

    def test_repeated_lookup_performance(self):
        """Repeated lookups for same target should be fast."""
        cache = SimpleCache(max_size=1000)

        # Add entries
        for i in range(10):
            cache.put(
                target_name="CommonImport",
                target_type="module",
                source_file=f"source_{i}.py",
                result=("common/module.py", "module", 1.0),
            )

        # Lookup performance
        timings = []
        for i in range(100):
            start = time.perf_counter()
            found, result = cache.get(
                target_name="CommonImport",
                target_type="module",
                source_file=f"source_{i % 10}.py",
            )
            elapsed_ns = (time.perf_counter() - start) * 1_000_000_000
            timings.append(elapsed_ns)

            # Should hit cache
            if found:
                assert result is not None

        avg_ns = sum(timings) / len(timings)
        assert avg_ns < 1_000_000, f"Cache lookup took {avg_ns:.0f}ns"

    def test_cache_eviction_performance(self):
        """Cache eviction should not degrade performance."""
        cache = SimpleCache(max_size=100)

        # Fill cache beyond capacity
        for i in range(200):
            cache.put(
                target_name=f"symbol_{i}",
                target_type="function",
                source_file=f"file_{i}.py",
                result=(f"resolved_{i}.py", "function", 0.9),
            )

        # Lookups should still be fast
        timings = []
        for i in range(100, 200):  # Recent items should be in cache
            start = time.perf_counter()
            cache.get(f"symbol_{i}", "function", f"file_{i}.py")
            elapsed_ns = (time.perf_counter() - start) * 1_000_000_000
            timings.append(elapsed_ns)

        avg_ns = sum(timings) / len(timings)
        assert avg_ns < 1_000_000, f"Post-eviction lookup took {avg_ns:.0f}ns"


class TestResolutionStatistics:
    """Tests for resolution statistics tracking."""

    @pytest.mark.asyncio
    async def test_resolved_vs_unresolved_tracking(self):
        """Statistics should track resolved vs unresolved counts."""
        resolver = create_mock_resolver()

        # Pre-populate cache with resolvable symbol
        resolver._cache.put(
            target_name="ResolvableSymbol",
            target_type="function",
            source_file="source.py",
            result=("target.py", "function", 0.9),
        )

        # Also add an unresolvable symbol (cached None)
        resolver._cache.put(
            target_name="UnresolvableSymbol",
            target_type="function",
            source_file="source.py",
            result=None,
        )

        # Resolve both
        await resolver.resolve_import(
            target_name="ResolvableSymbol",
            target_type="function",
            source_file="source.py",
            source_language="python",
        )

        await resolver.resolve_import(
            target_name="UnresolvableSymbol",
            target_type="function",
            source_file="source.py",
            source_language="python",
        )

        stats = resolver.get_resolution_stats()

        assert stats["resolved"] == 1
        assert stats["unresolved"] == 1
