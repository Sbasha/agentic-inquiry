"""Tests that ``configure_embedder_for_backend`` wraps every local
embedder path with ``CachingEmbedder`` and skips the wrap for
server-side paths.

Per PR #135 reviewer concern — the wrapper is applied in the common
tail of ``factory.py``'s local branch, which means it covers
``sentence_transformer``, ``fastembed``, and ``local`` equally. Worth
pinning that with a test so a future refactor can't accidentally
wrap only one path. Uses ``patch`` on each provider constructor so
no models are actually downloaded / loaded.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agentic_inquiry.config import Config
from agentic_inquiry.embeddings.caching import CachingEmbedder
from agentic_inquiry.embeddings.factory import configure_embedder_for_backend
from agentic_inquiry.embeddings.noop import NoOpEmbedder

pytestmark = pytest.mark.unit


def _reset_registry():
    """Drop the default-embedder configured flag so the factory runs
    again in subsequent tests. ``embedding_registry`` is a module
    singleton — without this, the first configure_default_embedder call
    sticks for the rest of the test session.
    """
    from agentic_inquiry.embeddings.registry import embedding_registry

    embedding_registry._default_configured = False
    embedding_registry._default_embedder = None


def _base_config(provider: str = "sentence_transformer") -> Config:
    config = Config.load()
    config.embeddings.default_provider = provider
    # Ensure cache is enabled with a sane size for these tests.
    config.embeddings.cache.enabled = True
    config.embeddings.cache.max_entries = 100
    return config


class TestCacheWrappingCoversAllLocalProviders:
    """Each local-embedder path in ``factory.py`` must get the cache
    wrap. The wrap sits in the common tail of the local branch, so all
    three providers share it — but a future refactor could easily
    bypass it for one path without this guard.
    """

    def test_sentence_transformer_path_is_wrapped(self):
        _reset_registry()
        config = _base_config("sentence_transformer")

        mock_inner = MagicMock(name="SentenceTransformerEmbedder")
        mock_inner.ndims.return_value = 384

        with patch(
            "agentic_inquiry.embeddings.sentence_transformer.SentenceTransformerEmbedder",
            return_value=mock_inner,
        ):
            configure_embedder_for_backend(config, quiet=True)

        from agentic_inquiry.embeddings.registry import embedding_registry

        assert isinstance(embedding_registry._default_embedder, CachingEmbedder), (
            "sentence_transformer path should be wrapped in CachingEmbedder"
        )
        assert embedding_registry._default_embedder._wrapped is mock_inner

    def test_local_model_path_is_wrapped(self):
        _reset_registry()
        config = _base_config("local")

        mock_inner = MagicMock(name="LocalModelEmbedder")
        mock_inner.ndims.return_value = 384

        with patch(
            "agentic_inquiry.embeddings.local_model.LocalModelEmbedder",
            return_value=mock_inner,
        ):
            configure_embedder_for_backend(config, quiet=True)

        from agentic_inquiry.embeddings.registry import embedding_registry

        assert isinstance(embedding_registry._default_embedder, CachingEmbedder), (
            "local_model path should be wrapped in CachingEmbedder"
        )
        assert embedding_registry._default_embedder._wrapped is mock_inner

    def test_fastembed_path_is_wrapped(self):
        _reset_registry()
        config = _base_config("fastembed")

        mock_inner = MagicMock(name="FastEmbedEmbedder")
        mock_inner.ndims.return_value = 384

        with patch(
            "agentic_inquiry.embeddings.fastembed.FastEmbedEmbedder",
            return_value=mock_inner,
        ):
            configure_embedder_for_backend(config, quiet=True)

        from agentic_inquiry.embeddings.registry import embedding_registry

        assert isinstance(embedding_registry._default_embedder, CachingEmbedder), (
            "fastembed path should be wrapped in CachingEmbedder"
        )
        assert embedding_registry._default_embedder._wrapped is mock_inner


class TestCacheWrappingSkippedWhenAppropriate:
    """The wrap must NOT apply in two cases:

    1. Server-side embedding backends (NoOpEmbedder for AlloyDB / RDS) —
       no local forward pass to cache.
    2. ``embeddings.cache.enabled=false`` or ``max_entries=0`` — operator
       explicitly disabled caching (e.g. for micro-benchmarks).
    """

    def test_server_side_backend_uses_noop_embedder_not_wrapped(self):
        _reset_registry()
        config = _base_config("sentence_transformer")

        # Mock the capabilities lookup to return a SERVER_SIDE strategy.
        with patch(
            "agentic_inquiry.embeddings.factory.get_capabilities_for_backend"
        ) as caps_mock:
            from agentic_inquiry.embeddings.factory import EmbeddingStrategy

            caps_mock.return_value = MagicMock(
                embedding_strategy=EmbeddingStrategy.SERVER_SIDE,
                embedding_dimensions=768,
                embedding_model="text-embedding-005",
            )
            configure_embedder_for_backend(config, quiet=True)

        from agentic_inquiry.embeddings.registry import embedding_registry

        assert isinstance(embedding_registry._default_embedder, NoOpEmbedder), (
            "Server-side backends should use raw NoOpEmbedder, no cache wrap"
        )

    def test_cache_disabled_via_config_skips_wrap(self):
        _reset_registry()
        config = _base_config("sentence_transformer")
        config.embeddings.cache.enabled = False

        mock_inner = MagicMock(name="SentenceTransformerEmbedder")
        mock_inner.ndims.return_value = 384

        with patch(
            "agentic_inquiry.embeddings.sentence_transformer.SentenceTransformerEmbedder",
            return_value=mock_inner,
        ):
            configure_embedder_for_backend(config, quiet=True)

        from agentic_inquiry.embeddings.registry import embedding_registry

        assert embedding_registry._default_embedder is mock_inner, (
            "cache.enabled=false should skip the wrap — registry sees the raw embedder"
        )

    def test_zero_max_entries_skips_wrap(self):
        _reset_registry()
        config = _base_config("sentence_transformer")
        config.embeddings.cache.enabled = True
        config.embeddings.cache.max_entries = 0

        mock_inner = MagicMock(name="SentenceTransformerEmbedder")
        mock_inner.ndims.return_value = 384

        with patch(
            "agentic_inquiry.embeddings.sentence_transformer.SentenceTransformerEmbedder",
            return_value=mock_inner,
        ):
            configure_embedder_for_backend(config, quiet=True)

        from agentic_inquiry.embeddings.registry import embedding_registry

        assert embedding_registry._default_embedder is mock_inner, (
            "max_entries=0 should skip the wrap even with enabled=true"
        )
