"""Cache module — pre-computed query results plus parsed-document caching.

Two unrelated caches share this namespace; their APIs are NOT interchangeable:

- ``DocumentCache`` (``document_cache.py``) — caches parsed documents keyed
  by file path, with mtime-based invalidation. Conforms to ``CacheProtocol``
  and is the default registered under ``register_cache(...)``. Used by
  ``IndexingPipeline``.
- ``PrecomputedCache`` (``precomputed.py``) — caches pre-computed query
  results keyed by ``(query_type, key)``. Has its own ``get / set`` API
  and does **not** implement ``CacheProtocol``; do not pass it to
  ``register_cache``.

Example:
    >>> from agent_vault.cache import get_cache
    >>> cache = get_cache()
    >>> doc = await cache.get("/path/to/file.py")
"""

from typing import Any, Protocol, runtime_checkable
import logging

from .precomputed import PrecomputedCache, CacheEntry

logger = logging.getLogger(__name__)


@runtime_checkable
class CacheProtocol(Protocol):
    """Protocol for parsed-document caches used by ``IndexingPipeline``.

    Implementations store and retrieve parsed documents keyed by file path,
    with automatic invalidation based on file modification tracking.
    """

    async def get(self, path: str) -> Any | None:
        """Return cached document for ``path`` if valid, else ``None``."""

    async def put(self, path: str, document: Any) -> None:
        """Store ``document`` in the cache under ``path``."""

    async def invalidate(self, path: str) -> None:
        """Remove the cached entry for ``path`` (if any)."""

    async def clear(self) -> None:
        """Clear the entire cache."""


class CacheRegistry:
    """Registry for ``CacheProtocol`` implementations.

    Allows multiple cache implementations to be registered and retrieved
    by name. Supports setting a default cache for convenience.
    """

    def __init__(self) -> None:
        self._caches: dict[str, CacheProtocol] = {}
        self._default: str | None = None

    def register(
        self,
        name: str,
        cache: CacheProtocol,
        *,
        set_default: bool = False,
    ) -> None:
        if name in self._caches:
            raise ValueError(f"Cache '{name}' already registered")

        self._caches[name] = cache

        if set_default or self._default is None:
            self._default = name

        logger.info("Registered cache: %s", name)

    def unregister(self, name: str) -> None:
        if name in self._caches:
            del self._caches[name]
            if self._default == name:
                self._default = None
            logger.info("Unregistered cache: %s", name)

    def get(self, name: str | None = None) -> CacheProtocol:
        cache_name = name or self._default

        if cache_name is None:
            raise ValueError("No default cache set")

        try:
            return self._caches[cache_name]
        except KeyError as exc:
            raise KeyError(f"Cache '{cache_name}' not registered") from exc

    def available(self) -> list[str]:
        return list(self._caches.keys())


# Global registry instance
_cache_registry = CacheRegistry()


# Late import — pulled at module top-level for the public re-export below,
# but the default ``DocumentCache`` instance itself is constructed lazily by
# ``_ensure_default_registered`` (see below). ``DocumentCache.__init__`` calls
# ``Config.load()`` and may touch disk for cache persistence, so doing it
# eagerly at import time would make ``import agent_vault.cache`` unexpectedly
# expensive and break in environments where config isn't available.
from agent_vault.cache.document_cache import DocumentCache  # noqa: E402


def _ensure_default_registered() -> None:
    """Lazily register the default ``DocumentCache`` on first use.

    Construction is deferred until the first ``get_cache()`` /
    ``available_caches()`` call so that simply importing this module has no
    side effects (no ``Config.load()``, no disk access).

    The registry itself is the source of truth: if ``"default"`` is already
    present (from a prior call, or from an explicit ``register_cache`` by
    the caller), this is a no-op. The explicit registration wins.
    """
    if "default" in _cache_registry.available():
        return
    _cache_registry.register("default", DocumentCache(), set_default=True)
    logger.info("Registered default DocumentCache")


def register_cache(
    name: str,
    cache: CacheProtocol,
    *,
    set_default: bool = False,
) -> None:
    """Register a ``CacheProtocol`` implementation globally."""
    _cache_registry.register(name, cache, set_default=set_default)


def get_cache(name: str | None = None) -> CacheProtocol:
    """Get a registered cache (default if name not specified)."""
    _ensure_default_registered()
    return _cache_registry.get(name)


def available_caches() -> list[str]:
    """List all registered cache names."""
    _ensure_default_registered()
    return _cache_registry.available()


__all__ = [
    # CacheProtocol family — parsed-document caching used by IndexingPipeline.
    "CacheProtocol",
    "CacheRegistry",
    "DocumentCache",
    "register_cache",
    "get_cache",
    "available_caches",
    # Independent — query-result cache. Not a CacheProtocol implementation.
    "PrecomputedCache",
    "CacheEntry",
]
