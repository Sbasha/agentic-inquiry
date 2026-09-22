"""Amazon Bedrock embedder for the Titan v2 family.

Implements the :class:`RemoteEmbedder` base for
``amazon.titan-embed-text-v2:0`` (Titan Text Embeddings V2). The Bedrock
``InvokeModel`` API takes one input string per call for Titan, so
``_max_inputs_per_request = 1``; throughput on a multi-input batch comes
from the base class fanning chunks across an instance-scoped thread
pool (see ``request_concurrency`` on :class:`RemoteEmbedder`).

Output dim is configurable in the model's request body — Titan v2
supports 256 / 512 / 1024 dims. Default 1024. Lower dims trade recall
for storage and faster pgvector index builds.

AWS credentials are resolved through boto3's standard provider chain
(env vars, instance profile, ``~/.aws/credentials``, etc.) — this class
does not shadow that.

References:
- Titan v2 model card: https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html
- InvokeModel API: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InvokeModel.html
- Bedrock IAM (``bedrock:InvokeModel``): https://docs.aws.amazon.com/bedrock/latest/userguide/security-iam.html
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, List, Tuple, Type

from agent_vault.embeddings.remote import RemoteEmbedder

DEFAULT_TITAN_V2_MODEL_ID = "amazon.titan-embed-text-v2:0"
TITAN_V2_VALID_DIMS = (256, 512, 1024)


class BedrockEmbedder(RemoteEmbedder):
    """Bedrock-backed embedder for the Titan v2 model.

    Example:
        >>> embedder = BedrockEmbedder(region="us-east-1")
        >>> vectors = embedder.generate(["hello world"])
        >>> len(vectors[0])
        1024
    """

    provider_name: ClassVar[str] = "bedrock"
    # Titan ``InvokeModel`` accepts exactly one input per call.
    _max_inputs_per_request: ClassVar[int] = 1
    # Populated lazily after boto3 import — botocore's exception classes
    # are dynamic, so we can't import them at module load time without
    # forcing a hard boto3 dep.
    _throttle_exceptions: ClassVar[Tuple[Type[BaseException], ...]] = ()

    def __init__(
        self,
        *,
        region: str,
        model_id: str = DEFAULT_TITAN_V2_MODEL_ID,
        ndims: int = 1024,
        normalize: bool = True,
        batch_size: int = 16,
        max_retries: int = 3,
        timeout_seconds: float = 30.0,
        request_concurrency: int = 1,
        boto_client: Any = None,
    ) -> None:
        """Initialize the Bedrock embedder.

        Args:
            region: AWS region for the Bedrock endpoint
                (e.g. ``"us-east-1"``). Required — no default, since
                Titan v2 isn't available in every region.
            model_id: Bedrock model id. Defaults to Titan v2.
            ndims: Output dim. For Titan v2 must be one of
                ``{256, 512, 1024}``.
            normalize: Whether to request L2-normalized vectors. Default
                ``True`` (matches what pgvector cosine distance expects).
            batch_size: Forwarded to the base loop. With Titan's
                one-input-per-request limit, the effective per-call
                batch is always 1 — this knob shapes the fan-out granularity.
            max_retries: Retries on ``ThrottlingException`` and
                ``ServiceQuotaExceededException``. Auth and validation
                errors are not retried — they need operator attention.
            timeout_seconds: boto3 read/connect timeout.
            request_concurrency: Parallel ``InvokeModel`` calls when
                ``len(texts) > 1``. Bound by Bedrock RPM quota
                (Titan v2 default 2000 RPM in ``us-east-1``).
            boto_client: Pre-built ``bedrock-runtime`` client. Optional —
                used for testing with a mock; production callers leave
                this ``None`` and the embedder builds its own from
                ``region`` + the standard credential chain.
        """
        if not region:
            raise ValueError(
                "BedrockEmbedder requires a region (e.g. 'us-east-1'); "
                "Titan v2 is not available in every Bedrock region."
            )
        if model_id == DEFAULT_TITAN_V2_MODEL_ID and ndims not in TITAN_V2_VALID_DIMS:
            raise ValueError(
                f"Titan v2 supports only {TITAN_V2_VALID_DIMS} output "
                f"dimensions, got {ndims}."
            )
        super().__init__(
            model_id=model_id,
            ndims=ndims,
            batch_size=batch_size,
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
            request_concurrency=request_concurrency,
        )
        self.region = region
        self.normalize = normalize
        # Instance-level client so concurrent threads share one configured
        # connection. boto3 docs note that low-level clients are thread-safe.
        # Lazy build when ``boto_client`` is None so import-time of the
        # module doesn't require boto3 — only the first ``_invoke`` does.
        self._client = boto_client
        if boto_client is not None:
            self._populate_throttle_exceptions()

    def _build_client(self) -> Any:
        """Construct the bedrock-runtime client on first use."""
        try:
            import boto3
            from botocore.config import Config as BotoConfig
        except ImportError as exc:
            raise ImportError(
                "BedrockEmbedder requires boto3. Install with: "
                "pip install 'agent-vault[aws]'"
            ) from exc

        config = BotoConfig(
            read_timeout=self.timeout_seconds,
            connect_timeout=self.timeout_seconds,
            retries={"max_attempts": 1, "mode": "standard"},
        )
        return boto3.client(
            "bedrock-runtime", region_name=self.region, config=config
        )

    def _populate_throttle_exceptions(self) -> None:
        """Set ``_throttle_exceptions`` to ``(ClientError,)``.

        Botocore raises a single ``ClientError`` family for *every*
        Bedrock failure mode (auth, validation, throttling, quota,
        throttling-during-burst, etc.) — distinguished only by the
        ``Error.Code`` payload. So the base-class catch is intentionally
        broad; ``_should_retry`` does the real filtering against
        ``{"ThrottlingException", "ServiceQuotaExceededException"}``.

        Done after the client is built (which is also when ``botocore``
        is guaranteed importable). Assigned at the instance level (not
        the ``ClassVar``) so a fake client used in tests doesn't have
        to bring botocore in.
        """
        try:
            from botocore.exceptions import ClientError
        except ImportError:
            return
        self._throttle_exceptions = (ClientError,)  # type: ignore[misc]

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._build_client()
            self._populate_throttle_exceptions()
        return self._client

    def _should_retry(self, exc: BaseException) -> bool:
        """Filter the broad ``ClientError`` catch to only Bedrock
        throttle / quota codes.

        Auth failures (``AccessDeniedException``,
        ``UnrecognizedClientException``) and validation errors fall
        through to the caller — they need operator attention, not
        retries that will keep failing the same way.

        ``exc.response["Error"]["Code"]`` is the documented shape for
        botocore.ClientError. Defensive walk: the structure is always
        the same when the SDK builds it, but tests might raise a bare
        ClientError with no response payload, in which case ``False``
        is the safe answer (don't retry an exception we can't classify).
        """
        try:
            err_code = exc.response["Error"]["Code"]  # type: ignore[attr-defined]
        except (AttributeError, KeyError, TypeError):
            return False
        return err_code in {"ThrottlingException", "ServiceQuotaExceededException"}

    def _invoke(self, texts: List[str]) -> List[List[float]]:
        # ``_max_inputs_per_request = 1`` so the base loop always passes
        # a single-element list. The assertion guards against a future
        # subclass of BedrockEmbedder accidentally lifting that limit.
        if len(texts) != 1:
            raise RuntimeError(
                "BedrockEmbedder._invoke called with "
                f"{len(texts)} inputs but Titan v2 supports one per call. "
                "Did a subclass override _max_inputs_per_request?"
            )

        client = self._get_client()
        body = {
            "inputText": texts[0],
            "dimensions": self._ndims,
            "normalize": self.normalize,
        }
        response = client.invoke_model(
            modelId=self.model_id,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        # ``response["body"]`` is a streaming body; ``.read()`` returns
        # the full JSON payload. Titan v2's response shape is
        # ``{"embedding": [...], "inputTextTokenCount": N}``.
        payload = json.loads(response["body"].read())
        embedding = payload.get("embedding")
        if not isinstance(embedding, list):
            # Don't repr the full payload — Bedrock can return very
            # large bodies even on the unhappy path (e.g. a different
            # model's well-formed embedding under a key we don't
            # recognise), and putting that in the exception message
            # bloats every error log + stack-trace report. Surface only
            # the keys + a short type summary for diagnostic value.
            payload_keys = (
                sorted(payload.keys())
                if isinstance(payload, dict)
                else f"<{type(payload).__name__}>"
            )
            raise RuntimeError(
                "Bedrock returned unexpected payload (no 'embedding' "
                f"list); keys={payload_keys}, embedding_type="
                f"{type(embedding).__name__}"
            )
        return [embedding]
