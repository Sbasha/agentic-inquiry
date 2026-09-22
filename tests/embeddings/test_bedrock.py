"""Unit tests for ``BedrockEmbedder``.

No live AWS credentials, no boto3 round-trips. The embedder accepts an
injected ``boto_client`` kwarg specifically so tests can drive a
hand-rolled fake; we use that to assert request/response shape, retry
behaviour against a synthetic ``ClientError``, and end-to-end
construction through the factory.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List

import pytest

from agent_vault.embeddings.bedrock import (
    DEFAULT_TITAN_V2_MODEL_ID,
    BedrockEmbedder,
)
from agent_vault.embeddings.remote import RemoteEmbedder

pytestmark = pytest.mark.unit

# Resolve the module object via ``sys.modules`` rather than a separate
# ``import ... as`` so the test file uses one import style for the
# ``agent_vault.embeddings.bedrock`` module (CodeQL py/import-and-import-from).
_BEDROCK_MODULE = sys.modules[BedrockEmbedder.__module__]
# The retry loop with the backoff sleep lives in ``RemoteEmbedder``
# now (after consolidating onto the ``_should_retry`` hook), so retry
# tests patch ``time.sleep`` on the remote module, not the bedrock one.
_REMOTE_MODULE = sys.modules[RemoteEmbedder.__module__]


# ---------- fake boto client + exceptions ----------


class _FakeStreamingBody:
    """Minimal stand-in for botocore's StreamingBody — just .read()."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


class _FakeClientError(Exception):
    """Mimics botocore.exceptions.ClientError shape closely enough for
    the throttle-detection logic.
    """

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(f"{code}: {message}")
        self.response: Dict[str, Any] = {
            "Error": {"Code": code, "Message": message}
        }


class FakeBedrockClient:
    """Records every ``invoke_model`` call, returns a deterministic
    Titan-shaped payload.

    Optional ``raise_first_n`` makes the first N calls raise
    ``_FakeClientError(code)`` so retry tests can simulate throttling
    without sleeping or hitting AWS.
    """

    def __init__(
        self,
        *,
        embedding: List[float] | None = None,
        raise_first_n: int = 0,
        raise_code: str = "ThrottlingException",
    ) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._embedding = embedding or [0.1] * 1024
        self._raise_first_n = raise_first_n
        self._raise_code = raise_code
        self._raised = 0

    def invoke_model(
        self,
        *,
        modelId: str,
        contentType: str,
        accept: str,
        body: str,
    ) -> Dict[str, Any]:
        if self._raised < self._raise_first_n:
            self._raised += 1
            raise _FakeClientError(self._raise_code)
        parsed_body = json.loads(body)
        self.calls.append(
            {
                "modelId": modelId,
                "contentType": contentType,
                "accept": accept,
                "body": parsed_body,
            }
        )
        return {
            "body": _FakeStreamingBody(
                json.dumps({"embedding": list(self._embedding),
                            "inputTextTokenCount": len(parsed_body["inputText"]) // 4}).encode("utf-8")
            )
        }


def _embedder_with_fake(**kwargs: Any) -> tuple[BedrockEmbedder, FakeBedrockClient]:
    """Build an embedder wired to a controllable fake client."""
    client_kwargs = {k: v for k, v in kwargs.items() if k in ("embedding", "raise_first_n", "raise_code")}
    embedder_kwargs = {k: v for k, v in kwargs.items() if k not in ("embedding", "raise_first_n", "raise_code")}
    fake = FakeBedrockClient(**client_kwargs)
    emb = BedrockEmbedder(
        region="us-east-1",
        ndims=embedder_kwargs.pop("ndims", 1024),
        boto_client=fake,
        **embedder_kwargs,
    )
    # Use the fake's exception type for throttle filtering — bypasses
    # botocore import for retry testing.
    emb._throttle_exceptions = (_FakeClientError,)  # type: ignore[misc]
    return emb, fake


# ---------- request / response shape ----------


class TestRequestShape:
    def test_invokes_titan_with_full_request_body(self):
        emb, fake = _embedder_with_fake()
        emb.generate(["hello world"])
        assert len(fake.calls) == 1
        call = fake.calls[0]
        assert call["modelId"] == DEFAULT_TITAN_V2_MODEL_ID
        assert call["contentType"] == "application/json"
        assert call["accept"] == "application/json"
        assert call["body"] == {
            "inputText": "hello world",
            "dimensions": 1024,
            "normalize": True,
        }

    def test_normalize_false_propagates(self):
        emb, fake = _embedder_with_fake(normalize=False)
        emb.generate(["hello"])
        assert fake.calls[0]["body"]["normalize"] is False

    def test_dimensions_512_propagates(self):
        emb, fake = _embedder_with_fake(
            embedding=[0.0] * 512,
            ndims=512,
        )
        emb.generate(["hello"])
        assert fake.calls[0]["body"]["dimensions"] == 512

    def test_titan_v2_rejects_invalid_dim(self):
        with pytest.raises(ValueError, match="Titan v2 supports"):
            BedrockEmbedder(region="us-east-1", ndims=999)

    def test_non_titan_model_skips_dim_enum_check(self):
        # Custom model id — dim isn't validated against Titan's enum,
        # operator takes responsibility.
        emb = BedrockEmbedder(
            region="us-east-1",
            model_id="some-other-model",
            ndims=999,
            boto_client=FakeBedrockClient(embedding=[0.0] * 999),
        )
        emb._throttle_exceptions = ()  # type: ignore[misc]
        out = emb.generate(["hello"])
        assert len(out[0]) == 999

    def test_one_input_per_call(self):
        # Three texts, _max_inputs_per_request=1, so three calls.
        emb, fake = _embedder_with_fake()
        emb.generate(["a", "b", "c"])
        assert len(fake.calls) == 3
        assert [c["body"]["inputText"] for c in fake.calls] == ["a", "b", "c"]


# ---------- retry behaviour ----------


class _SkipSleep:
    """Patch out the per-attempt backoff sleep in the retry loop."""

    def __enter__(self):
        self._orig = _REMOTE_MODULE.time.sleep
        _REMOTE_MODULE.time.sleep = lambda _s: None
        return self

    def __exit__(self, *a):
        _REMOTE_MODULE.time.sleep = self._orig


class TestRetry:
    def test_retries_throttling_exception(self):
        emb, fake = _embedder_with_fake(raise_first_n=2, max_retries=3)
        with _SkipSleep():
            out = emb.generate(["hi"])
        assert len(out) == 1
        # 2 throttles + 1 success
        assert fake._raised == 2
        assert len(fake.calls) == 1

    def test_does_not_retry_access_denied(self):
        emb, fake = _embedder_with_fake(
            raise_first_n=1,
            raise_code="AccessDeniedException",
            max_retries=5,
        )
        with pytest.raises(_FakeClientError):
            emb.generate(["hi"])
        # No retries — surfaces immediately.
        assert fake._raised == 1
        assert len(fake.calls) == 0

    def test_quota_exceeded_retries(self):
        emb, fake = _embedder_with_fake(
            raise_first_n=1,
            raise_code="ServiceQuotaExceededException",
            max_retries=3,
        )
        with _SkipSleep():
            out = emb.generate(["hi"])
        assert len(out) == 1


# ---------- region requirement ----------


class TestRegionRequirement:
    def test_empty_region_raises(self):
        with pytest.raises(ValueError, match="region"):
            BedrockEmbedder(region="")

    def test_none_region_raises(self):
        with pytest.raises(ValueError, match="region"):
            BedrockEmbedder(region=None)  # type: ignore[arg-type]


# ---------- malformed response ----------


class TestMalformedResponse:
    def test_missing_embedding_key_raises(self):
        class _BadClient:
            def invoke_model(self, **_kw):
                return {
                    "body": _FakeStreamingBody(json.dumps({"oops": "no embedding"}).encode())
                }

        emb = BedrockEmbedder(region="us-east-1", boto_client=_BadClient())
        emb._throttle_exceptions = ()  # type: ignore[misc]
        with pytest.raises(RuntimeError, match="no 'embedding'"):
            emb.generate(["hi"])

    def test_dim_mismatch_caught_by_base_validation(self):
        # Server returned 512-dim vector but embedder expects 1024 —
        # base class catches it.
        emb, fake = _embedder_with_fake(
            embedding=[0.0] * 512,
            ndims=1024,
        )
        with pytest.raises(ValueError, match="length 512 but ndims=1024"):
            emb.generate(["hi"])


# ---------- composition with CachingEmbedder ----------


class TestCachingComposition:
    def test_in_batch_dedup_through_cache(self):
        from agent_vault.embeddings.caching import CachingEmbedder

        emb, fake = _embedder_with_fake()
        cached = CachingEmbedder(emb, max_entries=10)
        out = cached.generate(["dup", "dup", "dup", "unique"])
        assert len(out) == 4
        # CachingEmbedder dedups within the batch — fake should see
        # only the 2 unique inputs once each.
        seen_inputs = [c["body"]["inputText"] for c in fake.calls]
        assert sorted(seen_inputs) == ["dup", "unique"]

    def test_cross_call_cache_hit(self):
        from agent_vault.embeddings.caching import CachingEmbedder

        emb, fake = _embedder_with_fake()
        cached = CachingEmbedder(emb, max_entries=10)
        cached.generate(["hello"])
        cached.generate(["hello", "world"])
        # 'hello' cached on second call, only 'world' goes to Bedrock
        seen = sorted(c["body"]["inputText"] for c in fake.calls)
        assert seen == ["hello", "world"]


# ---------- factory-driven construction ----------


class TestFactoryWiring:
    def test_factory_constructs_bedrock_with_region(self, monkeypatch):
        from agent_vault.config import (
            BedrockConfig,
            Config,
            EmbeddingsConfig,
        )
        from agent_vault.embeddings import factory as factory_mod
        from agent_vault.embeddings.registry import embedding_registry

        # Don't actually call boto3 — patch BedrockEmbedder to a
        # constructor-spy so the factory path is exercised end-to-end
        # but no AWS client is built.
        constructed: Dict[str, Any] = {}

        class _SpyBedrock:
            def __init__(self, **kwargs: Any) -> None:
                constructed.update(kwargs)
                self._n = kwargs["ndims"]

            def ndims(self) -> int:
                return self._n

            def generate(self, texts: List[str]) -> List[List[float]]:
                return [[0.0] * self._n for _ in texts]

        # Reuse the module-level ``_BEDROCK_MODULE`` resolved via
        # ``sys.modules`` rather than re-importing as ``bedrock_mod``,
        # to avoid the mixed-import pattern flagged by CodeQL.
        monkeypatch.setattr(_BEDROCK_MODULE, "BedrockEmbedder", _SpyBedrock)

        config = Config()
        config.embeddings = EmbeddingsConfig(
            default_provider="bedrock",
            bedrock=BedrockConfig(region="us-west-2", output_dim=512),
        )
        # Force a clean registry — the factory short-circuits if a
        # default is already configured.
        embedding_registry.reset()
        try:
            factory_mod.configure_embedder_for_backend(config, quiet=True)
        finally:
            embedding_registry.reset()

        assert constructed["region"] == "us-west-2"
        assert constructed["ndims"] == 512

    def test_factory_raises_on_missing_region(self):
        from agent_vault.config import (
            BedrockConfig,
            Config,
            EmbeddingsConfig,
        )
        from agent_vault.embeddings import factory as factory_mod
        from agent_vault.embeddings.registry import embedding_registry
        from agent_vault.exceptions import ConfigurationError

        config = Config()
        config.embeddings = EmbeddingsConfig(
            default_provider="bedrock",
            bedrock=BedrockConfig(region=None),
        )
        embedding_registry.reset()
        try:
            with pytest.raises(ConfigurationError, match="region is required"):
                factory_mod.configure_embedder_for_backend(config, quiet=True)
        finally:
            embedding_registry.reset()
