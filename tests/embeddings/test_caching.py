"""Unit tests for ``CachingEmbedder``.

Covers cache-hit/miss mechanics, in-batch deduplication, LRU eviction,
thread safety under contention, and the ``max_entries=0`` pass-through.

No torch / sentence-transformers needed — uses a ``SpyEmbedder`` that
records calls and returns deterministic vectors.
"""
from __future__ import annotations

import threading
from typing import List

import pytest

from agentic_inquiry.embeddings.base import Embedder
from agentic_inquiry.embeddings.caching import CachingEmbedder

pytestmark = pytest.mark.unit


class SpyEmbedder(Embedder):
    """Records every ``generate`` call and returns deterministic vectors.

    Each unique text gets a unique 3-dim vector so tests can tell which
    call came from which text. ``generate`` returns the SAME vector for
    the same text across calls (mirrors real-model determinism).
    """

    def __init__(self, ndims: int = 3) -> None:
        self._ndims = ndims
        self.calls: List[List[str]] = []  # list of text batches
        self._vectors: dict[str, List[float]] = {}

    def generate(self, texts: List[str]) -> List[List[float]]:
        self.calls.append(list(texts))
        out = []
        for text in texts:
            if text not in self._vectors:
                # Unique per-text vector: [index, 0, 0]
                idx = float(len(self._vectors))
                self._vectors[text] = [idx, 0.0, 0.0]
            out.append(list(self._vectors[text]))
        return out

    def ndims(self) -> int:
        return self._ndims


class TestCacheHitMiss:
    """Basic cache-hit / cache-miss mechanics."""

    def test_first_call_is_all_misses(self):
        spy = SpyEmbedder()
        cached = CachingEmbedder(spy, max_entries=100)

        result = cached.generate(["a", "b", "c"])

        assert spy.calls == [["a", "b", "c"]], (
            "First call should pass all texts to the underlying embedder"
        )
        assert len(result) == 3
        assert cached.hits == 0
        assert cached.misses == 3

    def test_repeat_call_is_all_hits(self):
        spy = SpyEmbedder()
        cached = CachingEmbedder(spy, max_entries=100)

        first = cached.generate(["a", "b", "c"])
        second = cached.generate(["a", "b", "c"])

        assert spy.calls == [["a", "b", "c"]], (
            "Second call should not re-invoke the underlying embedder"
        )
        assert first == second, "Same input must return identical vectors"
        assert cached.hits == 3
        assert cached.misses == 3  # only from the first call

    def test_mixed_hit_and_miss_only_passes_misses(self):
        spy = SpyEmbedder()
        cached = CachingEmbedder(spy, max_entries=100)

        seed = cached.generate(["a", "b"])  # seed cache
        a_vec, b_vec = seed[0], seed[1]
        result = cached.generate(["a", "c", "b", "d"])

        # Second underlying call should contain only the uncached texts,
        # in the order they were first encountered.
        assert len(spy.calls) == 2
        assert spy.calls[1] == ["c", "d"]
        assert len(result) == 4
        # Cached texts return the identical vectors from the seed call
        # (same input → same SpyEmbedder output; same vector object content).
        assert result[0] == a_vec, "position 0 'a' should come from cache"
        assert result[2] == b_vec, "position 2 'b' should come from cache"
        # "c" (position 1) and "d" (position 3) are fresh, distinct from a/b.
        assert result[1] != a_vec and result[1] != b_vec
        assert result[3] != a_vec and result[3] != b_vec
        assert result[1] != result[3]
        assert cached.hits == 2
        assert cached.misses == 4

    def test_empty_input_returns_empty_without_touching_embedder(self):
        spy = SpyEmbedder()
        cached = CachingEmbedder(spy, max_entries=100)

        assert cached.generate([]) == []
        assert spy.calls == []


class TestInBatchDedup:
    """Duplicates within a single batch should hit the underlying
    embedder at most once per unique text."""

    def test_duplicate_text_in_single_batch_deduped(self):
        spy = SpyEmbedder()
        cached = CachingEmbedder(spy, max_entries=100)

        result = cached.generate(["header", "x", "header", "y", "header"])

        assert len(spy.calls) == 1
        # Underlying saw one "header", one "x", one "y" — three unique
        # texts total. Deduped from five input positions.
        assert spy.calls[0] == ["header", "x", "y"]
        # But the output still has 5 vectors, one per input position.
        assert len(result) == 5
        # All three "header" positions share the same vector.
        assert result[0] == result[2] == result[4]
        # "x" and "y" are distinct from "header".
        assert result[1] != result[0]
        assert result[3] != result[0]

    def test_all_duplicates_in_batch_still_one_underlying_call(self):
        spy = SpyEmbedder()
        cached = CachingEmbedder(spy, max_entries=100)

        result = cached.generate(["same"] * 10)

        assert len(spy.calls) == 1
        assert spy.calls[0] == ["same"]
        assert len(result) == 10
        # All ten output slots share the identical vector.
        first_vec = result[0]
        assert all(vec == first_vec for vec in result)


class TestLRUEviction:
    """Cache capacity is bounded. Oldest entries evict first."""

    def test_exceeds_max_entries_evicts_oldest(self):
        spy = SpyEmbedder()
        cached = CachingEmbedder(spy, max_entries=2)

        cached.generate(["a"])  # cache: [a]
        cached.generate(["b"])  # cache: [a, b]
        cached.generate(["c"])  # cache: [b, c] — "a" evicted

        assert cached.cache_stats()["size"] == 2
        assert "a" not in _cache_keys(cached)
        # Asking for "a" again should miss.
        cached.generate(["a"])
        assert cached.misses == 4  # a, b, c, a
        assert cached.hits == 0

    def test_lru_ordering_hit_moves_to_recent(self):
        """Accessing a cached entry should save it from eviction."""
        spy = SpyEmbedder()
        cached = CachingEmbedder(spy, max_entries=2)

        cached.generate(["a"])  # cache: [a]
        cached.generate(["b"])  # cache: [a, b]
        cached.generate(["a"])  # hit; cache: [b, a]
        cached.generate(["c"])  # cache: [a, c] — "b" evicted, not "a"

        # "a" should still be cached (moved to MRU by the hit), "b" is gone.
        keys = _cache_keys(cached)
        assert "a" in keys
        assert "b" not in keys
        assert "c" in keys


class TestDisabledCache:
    """``max_entries=0`` means pass-through — no cache, no dedup, no stats."""

    def test_max_entries_zero_passes_through(self):
        spy = SpyEmbedder()
        cached = CachingEmbedder(spy, max_entries=0)

        cached.generate(["a", "a", "b"])
        cached.generate(["a", "a", "b"])

        # Both calls forwarded verbatim — no dedup, no caching.
        assert spy.calls == [["a", "a", "b"], ["a", "a", "b"]]
        assert cached.hits == 0
        assert cached.misses == 0

    def test_negative_max_entries_rejected(self):
        spy = SpyEmbedder()
        with pytest.raises(ValueError, match="max_entries must be >= 0"):
            CachingEmbedder(spy, max_entries=-1)

    def test_negative_max_entries_rejected_at_config_load(self):
        """``EmbeddingsCacheConfig`` must reject negative ``max_entries``
        at construction time with a ``ConfigurationError`` — matches
        the pattern for other tuning knobs in ``config.py`` and means
        misconfigured YAML fails at ``Config.load()`` instead of deep
        inside the pipeline when the first chunk tries to embed.

        Schema validation enforces ``minimum: 0`` too, but the schema
        check can be skipped (jsonschema not installed or
        ``skip_schema_validation=True``), so dataclass ``__post_init__``
        is the load-time guarantee.
        """
        from agentic_inquiry.config import EmbeddingsCacheConfig
        from agentic_inquiry.exceptions import ConfigurationError

        with pytest.raises(ConfigurationError, match="max_entries must be >= 0"):
            EmbeddingsCacheConfig(max_entries=-1)


class TestNdims:
    def test_ndims_delegates_to_wrapped(self):
        spy = SpyEmbedder(ndims=768)
        cached = CachingEmbedder(spy, max_entries=10)
        assert cached.ndims() == 768


class TestThreadSafety:
    """Sanity check that concurrent callers don't corrupt the cache.

    Not a proof of correctness (Python's GIL hides a lot), but catches
    the common failure mode: two threads racing on the same miss.
    """

    def test_concurrent_generate_same_text_is_consistent(self):
        spy = SpyEmbedder()
        cached = CachingEmbedder(spy, max_entries=100)
        results: List[List[List[float]]] = []
        errors: List[Exception] = []
        results_lock = threading.Lock()

        def worker():
            try:
                r = cached.generate(["shared_text"])
                with results_lock:
                    results.append(r)
            except Exception as e:  # pragma: no cover
                # Bare ``Exception`` so KeyboardInterrupt / SystemExit
                # propagate to pytest's runner instead of being swallowed
                # and silently stashed as a "test error".
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Concurrent generate raised: {errors}"
        # All 20 threads got a valid vector.
        assert len(results) == 20
        first = results[0][0]
        assert all(r[0] == first for r in results), (
            "All threads must see the same vector for 'shared_text'"
        )


class TestCacheStats:
    def test_hit_rate_before_any_calls_is_none(self):
        cached = CachingEmbedder(SpyEmbedder(), max_entries=10)
        stats = cached.cache_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] is None

    def test_hit_rate_after_mixed_calls(self):
        spy = SpyEmbedder()
        cached = CachingEmbedder(spy, max_entries=10)
        cached.generate(["a", "b"])  # 2 misses
        cached.generate(["a", "a", "c"])  # 2 hits, 1 miss
        stats = cached.cache_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 3
        # 2 / (2 + 3) = 0.4
        assert stats["hit_rate"] == pytest.approx(0.4)


def _cache_keys(cached: CachingEmbedder) -> set[str]:
    """Reach into the cache for assertion convenience.

    Tests poke at the underlying keys to verify eviction ordering.
    Not a public API; only used here.
    """
    import hashlib

    with cached._lock:
        digests = set(cached._cache.keys())
    # Reverse-lookup by re-hashing common test inputs.
    reverse = {
        hashlib.sha256(s.encode("utf-8")).hexdigest(): s
        for s in ("a", "b", "c", "d", "header", "x", "y", "shared_text", "same")
    }
    return {reverse[d] for d in digests if d in reverse}
