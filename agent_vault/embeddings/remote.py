"""Base class for embedders that call out to a cloud API.

Captures the cross-cutting concerns shared by Bedrock, Vertex AI Generative,
Azure OpenAI, Cohere, etc.: per-request batch chunking against the
provider's input limit, optional parallel dispatch via an instance-scoped
thread pool, retry on subclass-declared throttle exceptions, and
output-dim validation against the configured ``ndims``.

Subclasses implement ``_invoke(texts)`` (one provider request, blocking
SDK call) and declare two class attributes:

- ``provider_name`` — used in logs / metrics.
- ``_max_inputs_per_request`` — the provider's hard cap on inputs per
  call (Titan v2: 1, Vertex: 250, OpenAI: 2048).

Optional class attribute:

- ``_throttle_exceptions`` — tuple of exception types that count as
  retryable throttling. Defaults to ``()`` (no automatic retry beyond
  what the SDK itself does).

The base class is sync-native: ``generate`` runs the blocking SDK in
the calling thread, ``generate_async`` inherits ``Embedder``'s
thread-pool offload. This matches every other ``Embedder`` subclass and
keeps ``embedder.generate(...)`` safe to call from inside a running
event loop (which the indexing pipeline does, via
``loop.run_in_executor(executor, embedder.generate, texts)``). Subclasses
that want a truly async transport (e.g. ``aioboto3``) override
``generate_async`` directly.
"""

from __future__ import annotations

import logging
import threading
import time
from abc import abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import ClassVar, List, Tuple, Type

from agent_vault.embeddings.base import Embedder
from agent_vault.metrics import get_metrics_tracker

logger = logging.getLogger(__name__)


class RemoteEmbedder(Embedder):
    """Base class for cloud-API embedders. Subclass and implement
    :meth:`_invoke`.
    """

    # Required class attributes — subclasses MUST set these.
    provider_name: ClassVar[str] = ""
    _max_inputs_per_request: ClassVar[int] = 1

    # Optional class attribute — exception types that should trigger
    # exponential-backoff retry. Subclasses override with their SDK's
    # throttle exception types.
    _throttle_exceptions: ClassVar[Tuple[Type[BaseException], ...]] = ()

    def __init__(
        self,
        *,
        model_id: str,
        ndims: int,
        batch_size: int = 16,
        max_retries: int = 3,
        timeout_seconds: float = 30.0,
        request_concurrency: int = 1,
    ) -> None:
        if not self.provider_name:
            raise ValueError(
                f"{type(self).__name__}.provider_name class attribute must "
                f"be set"
            )
        if ndims <= 0:
            raise ValueError(f"ndims must be positive, got {ndims}")
        if batch_size <= 0:
            raise ValueError(f"batch_size must be positive, got {batch_size}")
        if max_retries < 0:
            raise ValueError(
                f"max_retries must be >= 0, got {max_retries}"
            )
        if timeout_seconds <= 0:
            raise ValueError(
                f"timeout_seconds must be positive, got {timeout_seconds}"
            )
        if request_concurrency < 1:
            raise ValueError(
                f"request_concurrency must be >= 1, got {request_concurrency}"
            )
        self.model_id = model_id
        self._ndims = ndims
        self.batch_size = batch_size
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.request_concurrency = request_concurrency
        self._metrics = get_metrics_tracker()
        # Instance-scoped executor for parallel _invoke dispatch when
        # request_concurrency > 1. Lazily created (under
        # ``_executor_lock``) to keep request_concurrency=1 (the
        # default) zero-overhead. The lock matters in the unlikely but
        # real case where two threads enter ``generate`` concurrently
        # for the first time on the same embedder — without it, both
        # would create an executor and one would leak its workers.
        self._executor: ThreadPoolExecutor | None = None
        self._executor_lock = threading.Lock()

    @abstractmethod
    def _invoke(self, texts: List[str]) -> List[List[float]]:
        """Single provider request. Returns one vector per input text.

        Implementations use the provider's blocking SDK
        (e.g. ``boto3.client("bedrock-runtime").invoke_model``).
        Concurrency comes from the base class scheduling multiple
        ``_invoke`` calls in parallel — not from this method itself
        being async or threaded.

        Per the ``_max_inputs_per_request`` contract, ``len(texts)``
        will never exceed the subclass's declared limit.
        """

    def ndims(self) -> int:
        return self._ndims

    def generate(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a batch of texts.

        Splits ``texts`` into chunks of size
        ``min(batch_size, _max_inputs_per_request)`` and dispatches each
        chunk through ``_invoke``. When ``request_concurrency > 1`` the
        chunks fan out across an instance-scoped thread pool; otherwise
        they run serially in the calling thread.

        Each chunk is retried up to ``max_retries`` times on declared
        throttle exceptions with exponential backoff (``2**attempt``
        seconds, capped at 30s).
        """
        if not texts:
            return []

        with self._metrics.track_latency(
            f"embeddings.{self.provider_name}.generate"
        ):
            effective_chunk_size = min(
                self.batch_size, self._max_inputs_per_request
            )
            chunks = [
                texts[i : i + effective_chunk_size]
                for i in range(0, len(texts), effective_chunk_size)
            ]

            if self.request_concurrency == 1 or len(chunks) == 1:
                # Serial path — no thread pool overhead.
                vectors_by_chunk = [self._invoke_with_retry(c) for c in chunks]
            else:
                executor = self._get_executor()
                # Submit all chunks to the pool. Track futures by index
                # so we can both reorder results to match input order and
                # cancel pending work if any chunk fails — the latter
                # matters because every Bedrock call is billable, so
                # finishing 99 successful chunks just to discard them
                # because chunk 0 raised AccessDenied is wasted money.
                futures = [
                    executor.submit(self._invoke_with_retry, c) for c in chunks
                ]
                vectors_by_chunk = [None] * len(chunks)  # type: ignore[list-item]
                first_exc: Exception | None = None
                from concurrent.futures import as_completed

                pending = {f: i for i, f in enumerate(futures)}
                for f in as_completed(futures):
                    idx = pending.pop(f)
                    if first_exc is not None:
                        # Already failing — drop any results that
                        # arrived after we decided to abort.
                        continue
                    try:
                        vectors_by_chunk[idx] = f.result()
                    except Exception as exc:
                        # Catch Exception, not BaseException, so
                        # KeyboardInterrupt / SystemExit propagate
                        # immediately rather than being deferred to the
                        # end of the as_completed loop. Operational and
                        # API failures (botocore.ClientError, network
                        # errors, ValueError dim-mismatch) are all
                        # Exception subclasses, so the abort-on-first
                        # behaviour is preserved.
                        first_exc = exc
                        # Cancel everything not yet started. Already-
                        # running futures will run to completion (Python
                        # ThreadPoolExecutor can't preempt threads), but
                        # at least we stop submitting new requests.
                        for other in pending:
                            other.cancel()
                if first_exc is not None:
                    raise first_exc

            # Flatten + validate dim per vector. Belt-and-braces: fail
            # loudly if a subclass's _invoke returns the wrong dim, so
            # we surface the bug at the source rather than letting
            # mis-sized vectors leak into pgvector / LanceDB.
            result: List[List[float]] = []
            for chunk_vectors in vectors_by_chunk:
                for vec in chunk_vectors:
                    if len(vec) != self._ndims:
                        raise ValueError(
                            f"{self.provider_name} embedder returned a vector "
                            f"of length {len(vec)} but ndims={self._ndims}. "
                            f"Check the model_id / output_dim configuration."
                        )
                    result.append(vec)

            if len(result) != len(texts):
                raise RuntimeError(
                    f"{self.provider_name} embedder returned {len(result)} "
                    f"vectors for {len(texts)} inputs"
                )

            return result

    def _should_retry(self, exc: BaseException) -> bool:
        """Subclass hook: filter further among caught
        ``_throttle_exceptions``.

        Default returns ``True`` — every exception caught by the
        ``_throttle_exceptions`` tuple is treated as retryable. Subclasses
        with broader exception types (e.g. ``BedrockEmbedder`` catches
        ``botocore.exceptions.ClientError``, which covers auth +
        validation errors as well as throttling) override this to
        return ``True`` only on the actually-throttle-shaped errors.

        Returning ``False`` propagates the exception immediately
        without retry; auth / quota / validation errors should always
        return ``False``.
        """
        return True

    def _invoke_with_retry(self, texts: List[str]) -> List[List[float]]:
        """Call ``_invoke`` with exponential-backoff retry on declared
        throttle exceptions.

        Subclasses tune the retry filter via ``_should_retry``;
        non-retryable exceptions fall through immediately.
        """
        attempt = 0
        while True:
            try:
                return self._invoke(texts)
            except self._throttle_exceptions as exc:
                if not self._should_retry(exc):
                    raise
                if attempt >= self.max_retries:
                    logger.error(
                        "%s embedder throttled after %d retries: %s",
                        self.provider_name,
                        self.max_retries,
                        exc,
                    )
                    raise
                delay = min(2 ** attempt, 30)
                logger.warning(
                    "%s embedder throttled (attempt %d/%d), retrying in %ds: %s",
                    self.provider_name,
                    attempt + 1,
                    self.max_retries,
                    delay,
                    exc,
                )
                time.sleep(delay)
                attempt += 1

    def _get_executor(self) -> ThreadPoolExecutor:
        # Double-checked: read once outside the lock, recheck under it.
        # The fast path (executor already built) avoids the lock entirely
        # and matches the pattern in CPython's own lazy-init helpers.
        executor = self._executor
        if executor is not None:
            return executor
        with self._executor_lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=self.request_concurrency,
                    thread_name_prefix=f"{self.provider_name}-embedder",
                )
            return self._executor

    def close(self) -> None:
        """Shut down the thread pool used for parallel ``_invoke`` calls.

        Safe to call multiple times; idempotent. Long-running CLI /
        server processes that build short-lived embedder instances should
        prefer the context-manager form (``with embedder: ...``) so
        cleanup is deterministic. ``__del__`` calls this as a fallback
        for code paths that drop references without explicit shutdown.
        """
        with self._executor_lock:
            executor = self._executor
            if executor is None:
                return
            self._executor = None
        executor.shutdown(wait=False)

    def __enter__(self) -> RemoteEmbedder:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        # Finalizer fallback for callers that don't use the context
        # manager — keeps the worker pool from outliving the embedder
        # in long-running processes. ``close`` is idempotent.
        try:
            self.close()
        except Exception as exc:  # noqa: BLE001
            # ``__del__`` must never propagate; interpreter shutdown can
            # tear down logging or the executor module before this fires,
            # so we log at debug rather than warning to avoid noise on
            # normal process exit.
            logger.debug(
                "%s embedder finalizer failed (ignored): %s",
                self.provider_name,
                exc,
            )
