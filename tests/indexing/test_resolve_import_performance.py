"""Property-based tests for resolve_import cost and profiling data.

These tests validate the resolver's cache cost model and profiling data as
specified in the design document. Cost is measured in database queries and
symbol-registry lookups rather than wall-clock time, which varies with
machine load.

Property tests:
- Property 2: A cache hit does no backend work (Requirements 2.1)
- Property 3: An unresolved cache miss walks the strategy chain once, then hits (Requirements 2.2)
- Property 5: Profiling Data Completeness (Requirements 2.5)
"""

import pytest

pytestmark = pytest.mark.unit

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
    """Create a RelationshipResolver over a mock database and symbol registry.

    Every query and lookup returns an empty list, so nothing resolves and a
    cache miss walks the whole strategy chain.
    """
    mock_db = MagicMock()
    mock_db.query_raw = AsyncMock(return_value=[])
    mock_db.query_entities = AsyncMock(return_value=[])

    mock_registry = MagicMock()
    mock_registry.lookup_by_name = MagicMock(return_value=[])
    mock_registry.lookup_by_name_and_type = MagicMock(return_value=[])

    resolver = RelationshipResolver(
        symbol_registry=mock_registry,
        project_root="/tmp/test_project",
        db_manager=mock_db,
    )

    return resolver


def backend_calls(resolver: RelationshipResolver) -> list:
    """Return every method call made on the mock database and symbol registry so far.

    Dunder calls such as ``__bool__`` are truthiness checks, not backend work.
    """
    calls = resolver.db_manager.mock_calls + resolver.symbol_registry.mock_calls
    return [c for c in calls if not c[0].startswith("__")]


def calls_per_method(resolver: RelationshipResolver) -> dict[str, int]:
    """Count the backend calls issued so far, by method name."""
    counts: dict[str, int] = {}
    for name, _args, _kwargs in backend_calls(resolver):
        counts[name] = counts.get(name, 0) + 1
    return counts


# Pins the strategy chain for an unresolved miss without an import path: the
# database, symbol, exact-match and proximity strategies each issue one call,
# and the import-path and module-path strategies skip. A miss with an import
# path, or one the symbol strategy resolves, issues more.
UNRESOLVED_MISS_CALLS = {
    "query_raw": 1,
    "query_entities": 1,
    "lookup_by_name_and_type": 1,
    "lookup_by_name": 1,
}


# =============================================================================
# Property 2: A cache hit does no backend work
# Validates: Requirements 2.1
# =============================================================================


class TestCacheHitCost:
    """Tests for the cost of a cache hit."""

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
        resolved=st.booleans(),
    )
    @settings(max_examples=30, deadline=None)
    @pytest.mark.asyncio
    async def test_property_2_cache_hit_does_no_backend_work(
        self, target_name, target_type, source_file, resolved
    ):
        """Property 2: For any cache hit, resolution SHALL NOT query the database or registry.

        Holds for cached resolutions and for cached unresolved (None) results.
        """
        resolver = create_mock_resolver()
        source_file_with_ext = f"{source_file}.py"
        cached = (f"resolved_{source_file}.py", target_type, 0.95) if resolved else None

        resolver._cache.put(
            target_name=target_name,
            target_type=target_type,
            source_file=source_file_with_ext,
            result=cached,
        )

        result = await resolver.resolve_import(
            target_name=target_name,
            target_type=target_type,
            source_file=source_file_with_ext,
            source_language="python",
        )

        assert result == cached
        assert backend_calls(resolver) == []
        assert resolver.get_resolution_stats()["cache_hits"] == 1


# =============================================================================
# Property 3: An unresolved cache miss walks the strategy chain once, then hits
# Validates: Requirements 2.2
# =============================================================================


class TestCacheMissCost:
    """Tests for the cost of a cache miss."""

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
    @settings(max_examples=20, deadline=None)
    @pytest.mark.asyncio
    async def test_property_3_cache_miss_resolves_once_then_hits(
        self, target_name, source_file
    ):
        """Property 3: An unresolved miss without an import path SHALL walk the strategy chain once.

        Each backend lookup is issued once, and the unresolved result SHALL be
        cached, so repeating the call does no backend work.
        """
        resolver = create_mock_resolver()
        call = {
            "target_name": target_name,
            "target_type": "function",
            "source_file": f"{source_file}.py",
            "source_language": "python",
        }

        assert await resolver.resolve_import(**call) is None
        assert calls_per_method(resolver) == UNRESOLVED_MISS_CALLS
        calls_after_miss = len(backend_calls(resolver))

        assert await resolver.resolve_import(**call) is None
        assert len(backend_calls(resolver)) == calls_after_miss

        stats = resolver.get_resolution_stats()
        assert (stats["cache_misses"], stats["cache_hits"]) == (1, 1)


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
    @settings(max_examples=20, deadline=None)
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
# SimpleCache behavior
# =============================================================================


class TestSimpleCache:
    """Tests for SimpleCache lookups and eviction."""

    def test_get_returns_stored_results(self):
        """Lookups return the stored result, including a cached None, keyed per source file."""
        cache = SimpleCache(max_size=1000)
        cache.put("Found", "class", "a.py", ("target.py", "class", 1.0))
        cache.put("Unresolved", "class", "a.py", None)

        assert cache.get("Found", "class", "a.py") == (
            True,
            ("target.py", "class", 1.0),
        )
        assert cache.get("Unresolved", "class", "a.py") == (True, None)
        assert cache.get("Found", "class", "b.py") == (False, None)

    def test_eviction_drops_least_recently_used(self):
        """Past max_size, the least recently used entry is evicted first."""
        cache = SimpleCache(max_size=100)
        for i in range(100):
            cache.put(
                f"symbol_{i}",
                "function",
                f"file_{i}.py",
                (f"resolved_{i}.py", "function", 0.9),
            )

        # Reading symbol_0 makes symbol_1 the least recently used entry.
        assert cache.get("symbol_0", "function", "file_0.py")[0]
        cache.put(
            "symbol_100",
            "function",
            "file_100.py",
            ("resolved_100.py", "function", 0.9),
        )

        assert cache.get_statistics()["cache_size"] == 100
        assert cache.get("symbol_1", "function", "file_1.py") == (False, None)
        assert cache.get("symbol_0", "function", "file_0.py")[0]
        assert cache.get("symbol_100", "function", "file_100.py")[0]


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
