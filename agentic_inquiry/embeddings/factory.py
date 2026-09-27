"""Embedder factory driven by storage provider capabilities.

Centralizes the embedder selection logic that was previously duplicated
across cli/index.py, cli/search.py (x2), and other entry points.

Example:
    >>> from agentic_inquiry.embeddings.factory import configure_embedder_for_backend
    >>> configure_embedder_for_backend(config)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agentic_inquiry.storage.capabilities import (
    EmbeddingStrategy,
    get_capabilities_for_backend,
)

if TYPE_CHECKING:
    from agentic_inquiry.config import Config
    from agentic_inquiry.embeddings.base import Embedder

logger = logging.getLogger(__name__)


def resolve_backend_type(config: "Config") -> str:
    """Resolve the effective backend type from configuration.

    Checks new-style backends config first, falls back to legacy backend field.

    Args:
        config: Application configuration

    Returns:
        Backend type string (e.g. "lancedb")
    """
    backend_type = getattr(config.storage, "backend", "lancedb")
    if hasattr(config.storage, "backends") and config.storage.backends:
        vector_backend_name = getattr(config.storage, "vector_backend", None)
        if vector_backend_name and vector_backend_name in config.storage.backends:
            backend_type = config.storage.backends[vector_backend_name].get(
                "type", backend_type
            )
    return backend_type


def _per_backend_setting(config: "Config", key: str):
    """Read a per-backend setting from the active vector backend's config.

    Returns ``None`` when no backends config exists, no ``vector_backend``
    is selected, or the key isn't set on the chosen backend. The factory
    uses this to honor ``BackendConfig.{embedding_strategy,
    embedding_model, embedding_dim}`` overrides ahead of the capability
    profile's defaults.
    """
    if not (
        hasattr(config.storage, "backends") and config.storage.backends
    ):
        return None
    vector_backend_name = getattr(config.storage, "vector_backend", None)
    if not (
        vector_backend_name and vector_backend_name in config.storage.backends
    ):
        return None
    return config.storage.backends[vector_backend_name].get(key)


def resolve_embedding_strategy(
    config: "Config", capability_default: EmbeddingStrategy
) -> EmbeddingStrategy:
    """Resolve the effective embedding strategy from configuration.

    Honors a per-backend ``embedding_strategy`` override from
    ``BackendConfig`` when set; otherwise falls back to the capability
    profile's default. This matters for backends like Azure where the
    capability default is SERVER_SIDE but operators may legitimately
    pick LOCAL (e.g. running on Azure Postgres without ``azure_ai``
    enabled because they prefer client-side embedding).

    Without this, ``type: azure`` + ``embedding_strategy: local`` would
    silently configure ``NoOpEmbedder`` (because the factory only
    looked at the capability default), and the indexer would write
    zero-vectors instead of real embeddings.

    Args:
        config: Application configuration
        capability_default: Strategy from ``get_capabilities_for_backend``

    Returns:
        ``EmbeddingStrategy.LOCAL`` or ``EmbeddingStrategy.SERVER_SIDE``
    """
    raw_strategy = _per_backend_setting(config, "embedding_strategy")
    if raw_strategy == "server_side":
        return EmbeddingStrategy.SERVER_SIDE
    if raw_strategy == "local":
        return EmbeddingStrategy.LOCAL
    return capability_default


def resolve_embedding_dimensions(
    config: "Config", capability_default: int
) -> int:
    """Resolve the effective embedding dim from configuration.

    Honors per-backend ``embedding_dim`` from ``BackendConfig`` when
    set; otherwise falls back to the capability profile's default.
    Matters when the operator overrides the AOAI deployment to
    ``text-embedding-3-large`` (3072d) — without this, the factory
    would still configure ``NoOpEmbedder(ndims=1536)`` and the
    schema-creation pass would size the vector column at the wrong
    width.
    """
    raw_dim = _per_backend_setting(config, "embedding_dim")
    # Accept ints and digit strings — the latter happens when the
    # value comes from a YAML overlay using ``${EMBEDDING_DIM}``-style
    # env-var interpolation (the wizard's ``render_template`` passes
    # ``str(self._embedding_dim)``) or when an operator hand-edits
    # YAML and the loader leaves it as a string. Anything else is
    # ignored — better to fall back to the capability default than to
    # crash the indexer at startup on a malformed config value.
    if isinstance(raw_dim, bool):
        # ``bool`` is an ``int`` subclass in Python, but treating
        # ``True``/``False`` as a dim is never what the caller meant.
        return capability_default
    if isinstance(raw_dim, int) and raw_dim > 0:
        return raw_dim
    if isinstance(raw_dim, str):
        stripped = raw_dim.strip()
        if stripped.isdigit():
            parsed = int(stripped)
            if parsed > 0:
                return parsed
    return capability_default


def resolve_embedding_model(
    config: "Config", capability_default: str | None
) -> str | None:
    """Resolve the effective embedding model name from configuration.

    Honors per-backend ``embedding_model`` from ``BackendConfig`` when
    set; otherwise falls back to the capability profile's default.
    Used purely for log messages today; the SQL adapter pulls its own
    model name from ``BackendConfig`` at runtime, so this affects
    diagnostic output, not embedding correctness.
    """
    raw_model = _per_backend_setting(config, "embedding_model")
    if isinstance(raw_model, str) and raw_model:
        return raw_model
    return capability_default


def configure_embedder_for_backend(config: "Config", quiet: bool = False) -> None:
    """Configure the global embedder based on storage backend capabilities.

    This replaces the duplicated logic in cli/index.py, cli/search.py that
    manually checks backend_type == "alloydb" to decide which embedder to use.

    For SERVER_SIDE backends: configures NoOpEmbedder (no local model needed).
    For LOCAL backends: configures SentenceTransformerEmbedder.

    Args:
        config: Application configuration
        quiet: If True, suppress print output
    """
    from agentic_inquiry.embeddings.registry import embedding_registry

    if embedding_registry._default_configured:
        return

    backend_type = resolve_backend_type(config)
    caps = get_capabilities_for_backend(backend_type)
    # Per-backend ``embedding_strategy`` override wins over the
    # capability default — see ``resolve_embedding_strategy``. Without
    # this, ``type: azure`` + ``embedding_strategy: local`` (and the
    # symmetric AlloyDB-with-LOCAL case) silently lands on
    # ``NoOpEmbedder``.
    effective_strategy = resolve_embedding_strategy(
        config, caps.embedding_strategy
    )

    if effective_strategy == EmbeddingStrategy.SERVER_SIDE:
        from agentic_inquiry.embeddings.noop import NoOpEmbedder

        # Per-backend ``embedding_dim`` and ``embedding_model``
        # overrides win over capability defaults — see
        # ``resolve_embedding_dimensions`` / ``resolve_embedding_model``.
        # Without this, ``type: azure`` + ``embedding_model:
        # text-embedding-3-large`` (3072d) would still configure
        # ``NoOpEmbedder(1536)`` and the schema-creation pass would
        # size the vector column at the wrong width.
        ndims = resolve_embedding_dimensions(config, caps.embedding_dimensions)
        model_name = resolve_embedding_model(config, caps.embedding_model) or "server-side"
        # Server-side embedding (AlloyDB ``embedding()``, RDS Bedrock,
        # Azure OpenAI) — model runs in-database, so there's no local
        # forward pass to cache. Skip the CachingEmbedder wrap here
        # regardless of ``embeddings.cache.enabled``; it wouldn't hurt
        # but the NoOpEmbedder's ``generate`` is a zero-cost stub.
        embedder: Embedder = NoOpEmbedder(ndims=ndims)
        embedding_registry.configure_default_embedder(embedder, ndims=ndims)
        if not quiet:
            logger.info(
                "Using server-side embeddings (%s, %d dimensions)",
                model_name,
                ndims,
            )
    else:
        # Local embedding strategy
        provider = config.embeddings.default_provider
        ndims = config.embeddings.default_dimensions

        if provider == "fastembed":
            from agentic_inquiry.embeddings.fastembed import FastEmbedEmbedder

            fe_config = config.embeddings.fastembed
            embedder = FastEmbedEmbedder(
                model_name=fe_config.model_name,
                cache_dir=fe_config.cache_dir,
                threads=fe_config.threads,
                batch_size=fe_config.batch_size,
                parallel=fe_config.parallel
            )
            model_display_name = fe_config.model_name
        elif provider in ("local", "local_model"):
            # Accept both literals so the factory and
            # ``EmbeddingService._create_embedder`` are consistent. The
            # JSON schema enum lists both for the same reason; long-
            # term cleanup is to collapse the dispatchers (cluster #168).
            from agentic_inquiry.embeddings.local_model import LocalModelEmbedder

            lm_config = config.embeddings.local_model
            embedder = LocalModelEmbedder(
                model_path=lm_config.model_path,
                normalize=lm_config.normalize,
                batch_size=lm_config.batch_size,
                ndims=lm_config.ndims or ndims,
                config=config
            )
            model_display_name = lm_config.model_path
        else:
            # Default to sentence_transformer
            from agentic_inquiry.embeddings.sentence_transformer import (
                SentenceTransformerEmbedder,
            )

            st_config = config.embeddings.sentence_transformer
            model_name = st_config.model_name
            embedder = SentenceTransformerEmbedder(
                model_name=model_name,
                ndims=st_config.ndims or ndims
            )
            model_display_name = model_name
            provider = "sentence_transformer"

        # Wrap the local embedder in a content-hash LRU if enabled.
        # This is the main win for monorepos / branch indexing where
        # the same chunk text (license headers, vendored deps, generated
        # files) reappears across documents. Skip the wrap entirely when
        # disabled or ``max_entries=0`` so the registry sees the raw
        # embedder — keeps tests and micro-benchmarks honest.
        cache_cfg = config.embeddings.cache
        cache_active = cache_cfg.enabled and cache_cfg.max_entries > 0
        if cache_active:
            from agentic_inquiry.embeddings.caching import CachingEmbedder

            embedder = CachingEmbedder(embedder, max_entries=cache_cfg.max_entries)

        embedding_registry.configure_default_embedder(embedder, ndims=ndims)
        if not quiet:
            cache_suffix = (
                f" with content-hash cache ({cache_cfg.max_entries} entries)"
                if cache_active
                else ""
            )
            logger.info(
                "Configured %s embedder: %s (%d dimensions)%s",
                provider,
                model_display_name,
                ndims,
                cache_suffix,
            )

