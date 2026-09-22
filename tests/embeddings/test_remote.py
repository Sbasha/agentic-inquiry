"""Unit tests for ``RemoteEmbedder``.

The base class is exercised through a minimal ``FakeRemoteEmbedder``
subclass so the tests don't need boto3 / network — they validate the
shared behaviour (chunking, parallelism, retry, dim validation) that
every cloud-API embedder will inherit.
"""

from __future__ import annotations

import sys
import threading
from typing import ClassVar, List, Tuple, Type

import pytest

from agent_vault.embeddings.remote import RemoteEmbedder

pytestmark = pytest.mark.unit

# Resolve the module object via ``sys.modules`` rather than a separate
# ``import ... as`` so the test file uses one import style for the
# ``agent_vault.embeddings.remote`` module (CodeQL py/import-and-import-from).
_REMOTE_MODULE = sys.modules[RemoteEmbedder.__module__]


class _Throttled(Exception):
    """Stand-in throttle exception for retry tests."""


class _Fatal(Exception):
    """Stand-in non-retryable exception."""


class FakeRemoteEmbedder(RemoteEmbedder):
    """Records every ``_invoke`` call.

    Default behaviour: one float-3 vector per input, value derived from
    the input length so different texts get distinguishable vectors. The
    test fixture flips knobs (raise_count, _max_inputs_per_request,
    delay) per test.
    """

    provider_name: ClassVar[str] = "fake"
    _max_inputs_per_request: ClassVar[int] = 4
    _throttle_exceptions: ClassVar[Tuple[Type[BaseException], ...]] = (_Throttled,)

    def __init__(
        self,
        *,
        ndims: int = 3,
        wrong_dim: int | None = None,
        raise_count: int = 0,
        raise_exc: Type[BaseException] = _Throttled,
        wrong_count: bool = False,
        max_inputs: int | None = None,
        **kwargs,
    ) -> None:
        super().__init__(model_id="fake-model", ndims=ndims, **kwargs)
        # Test knobs.
        self.calls: List[List[str]] = []
        self.call_threads: List[str] = []
        self.lock = threading.Lock()
        self._wrong_dim = wrong_dim
        self._raise_count = raise_count
        self._raise_exc = raise_exc
        self._raises_remaining = raise_count
        self._wrong_count = wrong_count
        if max_inputs is not None:
            # Per-instance override of the class limit.
            self._max_inputs_per_request = max_inputs  # type: ignore[misc]

    def _invoke(self, texts: List[str]) -> List[List[float]]:
        with self.lock:
            self.calls.append(list(texts))
            self.call_threads.append(threading.current_thread().name)
        if self._raises_remaining > 0:
            self._raises_remaining -= 1
            raise self._raise_exc("simulated failure")
        # By default, return one float-3 vector per input, value =
        # len(text). When wrong_dim is set, return the wrong size to
        # exercise validation.
        out_dim = self._wrong_dim if self._wrong_dim is not None else self._ndims
        vectors = [[float(len(t))] * out_dim for t in texts]
        if self._wrong_count:
            vectors = vectors[:-1]  # short-count return
        return vectors


class TestBatchChunking:
    def test_single_chunk_under_limit(self):
        emb = FakeRemoteEmbedder(max_inputs=4, batch_size=4)
        out = emb.generate(["a", "bb", "ccc"])
        assert len(out) == 3
        assert emb.calls == [["a", "bb", "ccc"]]

    def test_chunks_to_max_inputs_per_request(self):
        # Limit is 2 inputs per request; user-facing batch_size higher
        # is capped by the provider limit.
        emb = FakeRemoteEmbedder(max_inputs=2, batch_size=10)
        out = emb.generate(["a", "b", "c", "d", "e"])
        assert len(out) == 5
        assert emb.calls == [["a", "b"], ["c", "d"], ["e"]]

    def test_chunks_to_user_batch_size(self):
        # User caps batch_size below the provider limit; user wins.
        emb = FakeRemoteEmbedder(max_inputs=10, batch_size=2)
        out = emb.generate(["a", "b", "c", "d", "e"])
        assert len(out) == 5
        assert emb.calls == [["a", "b"], ["c", "d"], ["e"]]

    def test_empty_input_skips_invoke(self):
        emb = FakeRemoteEmbedder()
        assert emb.generate([]) == []
        assert emb.calls == []


class TestDimValidation:
    def test_wrong_dim_raises(self):
        emb = FakeRemoteEmbedder(ndims=3, wrong_dim=5)
        with pytest.raises(ValueError, match="length 5 but ndims=3"):
            emb.generate(["text"])

    def test_short_count_raises(self):
        emb = FakeRemoteEmbedder(ndims=3, wrong_count=True, max_inputs=2)
        with pytest.raises(RuntimeError, match="returned"):
            emb.generate(["a", "b"])


class TestRetry:
    def test_retries_throttle_exception(self):
        # Three throttles, then succeed; max_retries=3 must cover.
        emb = FakeRemoteEmbedder(raise_count=3, max_retries=3)
        # Skip the sleep — patch in the same module that imports time.
        with _no_sleep():
            out = emb.generate(["only"])
        assert len(out) == 1
        # 3 raised invocations + 1 successful
        assert len(emb.calls) == 4

    def test_gives_up_after_max_retries(self):
        emb = FakeRemoteEmbedder(raise_count=5, max_retries=2)
        with _no_sleep(), pytest.raises(_Throttled):
            emb.generate(["x"])
        # Initial attempt + 2 retries = 3 invocations
        assert len(emb.calls) == 3

    def test_does_not_retry_non_throttle(self):
        emb = FakeRemoteEmbedder(
            raise_count=10, raise_exc=_Fatal, max_retries=5
        )
        with pytest.raises(_Fatal):
            emb.generate(["x"])
        assert len(emb.calls) == 1


class TestParallelism:
    """Parallelism is asserted via ``threading.Barrier`` rather than
    timing bounds — a structural check that doesn't flake under CI
    load. With concurrency=N and N input chunks each blocking on a
    Barrier(N), all workers must arrive simultaneously for the test
    to pass; serial execution times out at the barrier.
    """

    def test_request_concurrency_one_is_serial(self):
        # concurrency=1 should never spawn a worker pool. With
        # max_inputs=1 and 4 chunks, all four _invoke calls execute
        # in the calling thread.
        emb = FakeRemoteEmbedder(max_inputs=1, request_concurrency=1)
        out = emb.generate(["a", "b", "c", "d"])
        assert len(out) == 4
        worker_threads = {n for n in emb.call_threads if "fake-embedder" in n}
        assert worker_threads == set(), (
            f"concurrency=1 should not spawn worker threads, got {worker_threads}"
        )

    def test_request_concurrency_parallel(self):
        # 4 chunks × concurrency=4: every worker must arrive at the
        # barrier within 2s, otherwise BrokenBarrierError fires.
        # Serial execution (or stuck-thread dispatch) trips the timeout.
        barrier = threading.Barrier(4, timeout=2.0)

        class _BarrierEmbedder(FakeRemoteEmbedder):
            def _invoke(self, texts: List[str]) -> List[List[float]]:
                barrier.wait()
                return super()._invoke(texts)

        emb = _BarrierEmbedder(max_inputs=1, request_concurrency=4)
        out = emb.generate(["a", "b", "c", "d"])
        assert len(out) == 4
        # Sanity: all four chunks ran in distinct worker threads from
        # the embedder's pool.
        worker_threads = {n for n in emb.call_threads if "fake-embedder" in n}
        assert len(worker_threads) == 4

    def test_request_concurrency_below_chunks_caps_at_pool_size(self):
        # 8 chunks with concurrency=2: workers run in waves of 2.
        # Barrier(2) lets exactly two workers proceed at a time;
        # subsequent waves arrive after the first releases.
        barrier = threading.Barrier(2, timeout=2.0)

        class _BarrierEmbedder(FakeRemoteEmbedder):
            def _invoke(self, texts: List[str]) -> List[List[float]]:
                barrier.wait()
                return super()._invoke(texts)

        emb = _BarrierEmbedder(max_inputs=1, request_concurrency=2)
        out = emb.generate(["a", "b", "c", "d", "e", "f", "g", "h"])
        assert len(out) == 8
        worker_threads = {n for n in emb.call_threads if "fake-embedder" in n}
        # At most two distinct worker threads (pool size = 2). Could be
        # 1 or 2 depending on whether the OS reuses the same thread
        # across waves.
        assert 1 <= len(worker_threads) <= 2

    def test_results_preserve_input_order(self):
        # With parallel dispatch, futures complete out-of-order; the
        # base class must reorder to match input.
        emb = FakeRemoteEmbedder(max_inputs=1, request_concurrency=4)
        out = emb.generate(["a", "bb", "ccc", "dddd"])
        # Each vector's first element = len(text)
        first_elems = [v[0] for v in out]
        assert first_elems == [1.0, 2.0, 3.0, 4.0]


class TestConstructorValidation:
    def test_missing_provider_name_raises(self):
        class NoName(RemoteEmbedder):
            provider_name = ""  # default; tests the explicit "must set" guard

            def _invoke(self, texts):
                return []

        with pytest.raises(ValueError, match="provider_name"):
            NoName(model_id="x", ndims=3)

    def test_zero_ndims_raises(self):
        with pytest.raises(ValueError, match="ndims must be positive"):
            FakeRemoteEmbedder(ndims=0)

    def test_zero_concurrency_raises(self):
        with pytest.raises(ValueError, match="request_concurrency"):
            FakeRemoteEmbedder(request_concurrency=0)


# --- helpers ---


class _no_sleep:
    """Context manager that no-ops ``time.sleep`` inside ``RemoteEmbedder``.

    The retry-loop sleeps for backoff delays we don't want to wait
    through in tests. Patching at module scope rather than via
    ``unittest.mock.patch`` to keep the dependency surface narrow.
    """

    def __enter__(self):
        self._orig = _REMOTE_MODULE.time.sleep
        _REMOTE_MODULE.time.sleep = lambda _s: None
        return self

    def __exit__(self, *a):
        _REMOTE_MODULE.time.sleep = self._orig
