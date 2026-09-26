"""Unit tests for the per-backend resolver helpers in
``agentic_inquiry.embeddings.factory``.

The resolvers honor per-backend ``BackendConfig`` overrides ahead of
the capability-profile defaults. Tests pin the precedence rules so a
later refactor can't silently drop overrides — the bug that motivated
adding these helpers in PR #175 (``type: azure`` + ``embedding_model:
text-embedding-3-large`` was being ignored, sizing ``NoOpEmbedder``
at the capability default 1536 instead of 3072).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agentic_inquiry.embeddings.factory import (
    resolve_embedding_dimensions,
    resolve_embedding_model,
    resolve_embedding_strategy,
)
from agentic_inquiry.storage.capabilities import EmbeddingStrategy

pytestmark = pytest.mark.unit


def _make_config(
    backends: dict | None = None,
    vector_backend: str | None = None,
):
    """Build a minimal config-shaped object the resolvers can read.

    The resolvers only look at ``config.storage.backends`` (a dict of
    backend-name → backend-dict) and ``config.storage.vector_backend``,
    so the test config is just a ``SimpleNamespace`` with those two
    attributes.
    """
    storage = SimpleNamespace(backends=backends, vector_backend=vector_backend)
    return SimpleNamespace(storage=storage)


# ---------- resolve_embedding_strategy ----------


class TestResolveEmbeddingStrategy:
    def test_falls_back_to_capability_default_when_unset(self):
        config = _make_config(
            backends={"azure_db": {"type": "azure"}},
            vector_backend="azure_db",
        )
        assert (
            resolve_embedding_strategy(config, EmbeddingStrategy.SERVER_SIDE)
            == EmbeddingStrategy.SERVER_SIDE
        )

    def test_local_override_wins_over_server_side_default(self):
        # The motivating case: type: azure (SERVER_SIDE default) +
        # explicit embedding_strategy: local must yield LOCAL so the
        # factory configures a real client-side embedder rather than
        # NoOpEmbedder.
        config = _make_config(
            backends={
                "azure_db": {
                    "type": "azure",
                    "embedding_strategy": "local",
                }
            },
            vector_backend="azure_db",
        )
        assert (
            resolve_embedding_strategy(config, EmbeddingStrategy.SERVER_SIDE)
            == EmbeddingStrategy.LOCAL
        )

    def test_server_side_override_wins_over_local_default(self):
        # The symmetric case: type: rds (LOCAL default) + explicit
        # embedding_strategy: server_side (Aurora-only, but config-
        # level override valid).
        config = _make_config(
            backends={
                "rds": {
                    "type": "rds",
                    "embedding_strategy": "server_side",
                }
            },
            vector_backend="rds",
        )
        assert (
            resolve_embedding_strategy(config, EmbeddingStrategy.LOCAL)
            == EmbeddingStrategy.SERVER_SIDE
        )

    def test_no_backends_falls_back(self):
        config = _make_config(backends=None, vector_backend=None)
        assert (
            resolve_embedding_strategy(config, EmbeddingStrategy.LOCAL)
            == EmbeddingStrategy.LOCAL
        )

    def test_unknown_string_falls_back(self):
        config = _make_config(
            backends={"x": {"type": "rds", "embedding_strategy": "garbage"}},
            vector_backend="x",
        )
        assert (
            resolve_embedding_strategy(config, EmbeddingStrategy.LOCAL)
            == EmbeddingStrategy.LOCAL
        )


# ---------- resolve_embedding_dimensions ----------


class TestResolveEmbeddingDimensions:
    def test_int_override_wins(self):
        config = _make_config(
            backends={"azure_db": {"type": "azure", "embedding_dim": 3072}},
            vector_backend="azure_db",
        )
        assert resolve_embedding_dimensions(config, 1536) == 3072

    def test_digit_string_override_wins(self):
        # Motivating case (Copilot finding): YAML / env-template
        # rendering can leave embedding_dim as a string. Without the
        # string-coercion branch, the resolver would silently fall
        # back to the capability default and the NoOpEmbedder /
        # schema would be sized wrong.
        config = _make_config(
            backends={"azure_db": {"type": "azure", "embedding_dim": "3072"}},
            vector_backend="azure_db",
        )
        assert resolve_embedding_dimensions(config, 1536) == 3072

    def test_digit_string_with_whitespace(self):
        config = _make_config(
            backends={"azure_db": {"type": "azure", "embedding_dim": "  3072  "}},
            vector_backend="azure_db",
        )
        assert resolve_embedding_dimensions(config, 1536) == 3072

    def test_zero_falls_back(self):
        config = _make_config(
            backends={"x": {"type": "rds", "embedding_dim": 0}},
            vector_backend="x",
        )
        assert resolve_embedding_dimensions(config, 384) == 384

    def test_negative_falls_back(self):
        config = _make_config(
            backends={"x": {"type": "rds", "embedding_dim": -10}},
            vector_backend="x",
        )
        assert resolve_embedding_dimensions(config, 384) == 384

    def test_non_digit_string_falls_back(self):
        config = _make_config(
            backends={"x": {"type": "rds", "embedding_dim": "auto"}},
            vector_backend="x",
        )
        assert resolve_embedding_dimensions(config, 384) == 384

    def test_bool_falls_back(self):
        # Defensive: ``bool`` is an ``int`` subclass in Python, but
        # ``True`` / ``False`` is never a meaningful dim value.
        config = _make_config(
            backends={"x": {"type": "rds", "embedding_dim": True}},
            vector_backend="x",
        )
        assert resolve_embedding_dimensions(config, 384) == 384

    def test_none_falls_back(self):
        config = _make_config(backends={"x": {"type": "rds"}}, vector_backend="x")
        assert resolve_embedding_dimensions(config, 384) == 384

    def test_no_backends_falls_back(self):
        config = _make_config(backends=None, vector_backend=None)
        assert resolve_embedding_dimensions(config, 384) == 384


# ---------- resolve_embedding_model ----------


class TestResolveEmbeddingModel:
    def test_string_override_wins(self):
        config = _make_config(
            backends={
                "azure_db": {
                    "type": "azure",
                    "embedding_model": "text-embedding-3-large",
                }
            },
            vector_backend="azure_db",
        )
        assert (
            resolve_embedding_model(config, "text-embedding-3-small")
            == "text-embedding-3-large"
        )

    def test_empty_string_falls_back(self):
        config = _make_config(
            backends={"azure_db": {"type": "azure", "embedding_model": ""}},
            vector_backend="azure_db",
        )
        assert (
            resolve_embedding_model(config, "text-embedding-3-small")
            == "text-embedding-3-small"
        )

    def test_no_override_falls_back(self):
        config = _make_config(
            backends={"azure_db": {"type": "azure"}},
            vector_backend="azure_db",
        )
        assert (
            resolve_embedding_model(config, "text-embedding-3-small")
            == "text-embedding-3-small"
        )

    def test_capability_default_can_be_none(self):
        config = _make_config(backends={"x": {"type": "rds"}}, vector_backend="x")
        assert resolve_embedding_model(config, None) is None
